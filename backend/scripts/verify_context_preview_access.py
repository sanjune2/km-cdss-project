"""가상 계정·가상 DB로 인증 연결을 검사한다. 실제 로그인·DB·모델은 호출하지 않는다."""
import asyncio
import copy
import json
import logging
from pathlib import Path
from threading import Event

from fastapi import FastAPI, HTTPException, Request
from backend.ai.context_preview_routes import create_context_preview_router


class FakeEngine:
    def __init__(self):
        self.open_connections = 0
        self.queries = []
        self.cases = {
            21: dict(CASE_UNIQN=21, AUTHOR_UNIQN=101, DOCTOR_UNIQN=101, CLINIC_UNIQN=1, VISIT_UNIQN=31, STATUS_CD="IN_PROGRESS"),
            22: dict(CASE_UNIQN=22, AUTHOR_UNIQN=102, DOCTOR_UNIQN=102, CLINIC_UNIQN=1, VISIT_UNIQN=32, STATUS_CD="IN_PROGRESS"),
            23: dict(CASE_UNIQN=23, AUTHOR_UNIQN=201, DOCTOR_UNIQN=201, CLINIC_UNIQN=2, VISIT_UNIQN=33, STATUS_CD="IN_PROGRESS"),
            25: dict(CASE_UNIQN=25, AUTHOR_UNIQN=101, DOCTOR_UNIQN=101, CLINIC_UNIQN=1, VISIT_UNIQN=35, STATUS_CD="COMPLETED"),
        }

    def connect(self):
        engine = self
        class Connection:
            def __enter__(self):
                engine.open_connections += 1
                return self
            def __exit__(self, *args):
                engine.open_connections -= 1
            def execute(self, statement, parameters):
                assert statement.lstrip().startswith("SELECT ")
                assert "FOR UPDATE" not in statement
                assert set(parameters) == {"case_id", "clinic_id"}
                engine.queries.append((statement, dict(parameters)))
                found = engine.cases.get(parameters["case_id"])
                self.row = copy.deepcopy(found) if found and found["CLINIC_UNIQN"] == parameters["clinic_id"] else None
                return self
            def mappings(self):
                return self
            def first(self):
                return self.row
        return Connection()


async def post(app, body, token=None):
    content = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(content)).encode())]
    if token:
        headers.append((b"cookie", ("hanui_session=" + token).encode()))
    sent = False
    messages = []
    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": content, "more_body": False}
        await asyncio.Event().wait()
    async def send(message):
        messages.append(message)
    await app({
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "POST", "scheme": "http", "path": "/api/ai/diagnosis/preview",
        "raw_path": b"/api/ai/diagnosis/preview", "query_string": b"", "root_path": "",
        "headers": headers, "client": ("127.0.0.1", 12345), "server": ("127.0.0.1", 8000),
    }, receive, send)
    start = next(m for m in messages if m["type"] == "http.response.start")
    raw = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return start["status"], json.loads(raw)


async def verify():
    logging.getLogger("backend.ai.context_preview_routes").disabled = True
    engine = FakeEngine()
    accounts = {
        "TEST-DOCTOR": dict(ACCOUNT_UNIQN=101, CLINIC_UNIQN=1, ROLE_CD="DOCTOR", IS_OWNER=False, STATUS_CD="ACTIVE"),
        "TEST-OWNER": dict(ACCOUNT_UNIQN=102, CLINIC_UNIQN=1, ROLE_CD="OWNER", IS_OWNER=True, STATUS_CD="ACTIVE"),
        "TEST-DESK": dict(ACCOUNT_UNIQN=301, CLINIC_UNIQN=1, ROLE_CD="DESK", IS_OWNER=False, STATUS_CD="ACTIVE"),
        "TEST-OTHER-CLINIC": dict(ACCOUNT_UNIQN=201, CLINIC_UNIQN=2, ROLE_CD="DOCTOR", IS_OWNER=False, STATUS_CD="ACTIVE"),
        "TEST-OTHER-DOCTOR": dict(ACCOUNT_UNIQN=103, CLINIC_UNIQN=1, ROLE_CD="DOCTOR", IS_OWNER=False, STATUS_CD="ACTIVE"),
    }
    state = {"loads": 0, "calls": 0, "revoked": False}
    started, release = Event(), Event()
    def auth(request: Request):
        account = accounts.get(request.cookies.get("hanui_session"))
        if account is None or state["revoked"]:
            raise HTTPException(401, detail="검사용 로그인 필요")
        return copy.deepcopy(account)
    def loader(root):
        state["loads"] += 1
        return {"fixture": True}
    def runner(report, data, url, progress):
        assert engine.open_connections == 0
        assert data == {"fixture": True}
        state["calls"] += 1
        text = report["symptoms"]
        if text == "FAIL":
            raise RuntimeError("PRIVATE_TEST_ERROR")
        if text == "FINISH":
            engine.cases[int(report["case_id"])]["STATUS_CD"] = "COMPLETED"
        if text == "REASSIGN":
            engine.cases[int(report["case_id"])]["DOCTOR_UNIQN"] = 103
        if text == "REVOKE":
            state["revoked"] = True
        if text == "BLOCK":
            started.set()
            assert release.wait(5), "동시 요청 검사 제한시간 초과"
        route = "CONFIRM_INTERPRETATION" if text == "UNCERTAIN" else "REVIEW_INPUT" if text == "NEGATED" else "CANDIDATE_REVIEW"
        candidates = [{"id": i, "name": str(i), "score": 1/(60+i), "rank": i} for i in range(1,32)] if route == "CANDIDATE_REVIEW" else []
        report.update(status="COMPLETED", route=route, message="검사용 안내", candidates=candidates, reviewMentions=[])
        progress(report)
    app = FastAPI()
    app.include_router(create_context_preview_router(clinical_dependency=auth, engine=engine, sql_text=lambda q:q,
        data_loader=loader, preview_runner=runner))
    checks = []
    def record(label, status):
        checks.append({"check": label, "status": status})
        print(label, status, "통과", flush=True)
    denied = [
        ("로그인 없음", None, 21, "POSITIVE", 401),
        ("접수 직원", "TEST-DESK", 21, "POSITIVE", 403),
        ("다른 한의원 상담", "TEST-DOCTOR", 23, "POSITIVE", 404),
        ("다른 담당자", "TEST-OTHER-DOCTOR", 21, "POSITIVE", 403),
        ("완료된 상담", "TEST-DOCTOR", 25, "POSITIVE", 409),
        ("없는 상담", "TEST-DOCTOR", 999, "POSITIVE", 404),
        ("잘못된 상담 ID", "TEST-DOCTOR", True, "POSITIVE", 422),
        ("빈 증상", "TEST-DOCTOR", 21, "   ", 422),
    ]
    for label, token, case_id, text, expected in denied:
        status, body = await post(app, {"caseId":case_id,"symptoms":text}, token)
        assert status == expected and "candidates" not in body
        assert state["calls"] == state["loads"] == 0
        record(label, status)
    for text, expected_route in [("POSITIVE","CANDIDATE_REVIEW"),("NEGATED","REVIEW_INPUT"),("UNCERTAIN","CONFIRM_INTERPRETATION")]:
        status, body = await post(app, {"caseId":21,"symptoms":text}, "TEST-DOCTOR")
        assert status==200 and body["caseId"]==21 and body["route"]==expected_route
        assert body["historySaved"] is False and "searchId" not in body
        assert body["total"] == (31 if text=="POSITIVE" else 0)
        assert len(body["candidates"])==body["total"]
        record(text, status)
    status, body = await post(app, {"caseId":22,"symptoms":"POSITIVE"}, "TEST-OWNER")
    assert status==200 and body["caseId"]==22
    record("담당 원장", status)
    for text, expected in [("FINISH",409),("REASSIGN",403),("REVOKE",401)]:
        status,body=await post(app,{"caseId":21,"symptoms":text},"TEST-DOCTOR")
        assert status==expected and "candidates" not in body
        engine.cases[21]["STATUS_CD"]="IN_PROGRESS"
        engine.cases[21]["DOCTOR_UNIQN"]=101
        state["revoked"]=False
        record(text,status)
    first=asyncio.create_task(post(app,{"caseId":21,"symptoms":"BLOCK"},"TEST-DOCTOR"))
    for _ in range(200):
        if started.is_set(): break
        await asyncio.sleep(0.01)
    assert started.is_set()
    calls=state["calls"]
    try:
        status,body=await post(app,{"caseId":21,"symptoms":"POSITIVE"},"TEST-DOCTOR")
        assert status==429 and state["calls"]==calls
        record("동시 분석",status)
    finally:
        release.set()
    assert (await first)[0]==200
    status,body=await post(app,{"caseId":21,"symptoms":"FAIL"},"TEST-DOCTOR")
    assert status==503 and "PRIVATE_TEST_ERROR" not in json.dumps(body)
    assert "candidates" not in body
    record("모델 실패",status)
    assert (await post(app,{"caseId":21,"symptoms":"POSITIVE"},"TEST-DOCTOR"))[0]==200
    assert state["loads"]==1 and engine.open_connections==0
    assert all(q.lstrip().startswith("SELECT ") for q,_ in engine.queries)
    result={"checks":checks,"passed":len(checks),"real_db_calls":0,"real_model_calls":0,
            "data_loaded_once":True,"db_connection_released_during_inference":True,
            "sql_writes_executed":False,"history_saved":False}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return result


if __name__ == "__main__":
    asyncio.run(verify())
