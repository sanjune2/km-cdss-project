"""Persist v1.3 AI search snapshots in the existing PostgreSQL schema."""
import json
import logging
from datetime import datetime, timezone
from threading import Lock
from time import monotonic
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import text

from database import engine
from catalog import corporate_data
from prescription_ingredients import validate_ingredient_copy
from .explanations import explain, state
from .evidence_checks import check_record, verify_candidate
from .symptom_context import analyze_symptoms

logger = logging.getLogger(__name__)
model_process_lock = Lock()
DEPENDENCY_FAILURE = "기업 검색 자료 또는 임베딩 실행을 확인할 수 없습니다."


class DiseaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    caseId: Annotated[int, Field(strict=True, gt=0, le=2**63 - 1)]
    symptoms: Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1)]


SearchId = Annotated[str, StringConstraints(strict=True, pattern=r"^[1-9][0-9]{0,9}$")]


class PrescriptionRequest(DiseaseRequest):
    diseaseSearchId: SearchId
    selectedDiseases: list[Annotated[int, Field(strict=True, gt=0, le=2**31 - 1)]]


class ExplanationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidateIds: Annotated[list[Annotated[int, Field(strict=True, gt=0, le=2**31 - 1)]],
                            Field(min_length=1, max_length=60)]


def eligible(row):
    return bool(row["_sources"]) and row.get("evaluationStatus", "SCORED") == "SCORED"


def queued_job():
    return {"result": state("QUEUED", "관련 이유 생성 대기 중"),
            "queuedAt": datetime.now(timezone.utc).isoformat()}


def initial_explanations(rows, symptoms, data, assessment=None):
    assessment = assessment if assessment is not None else analyze_symptoms(symptoms, data or {})
    # Send only verified registered expressions, never free-form patient input.
    terms = assessment['affirmedTerms']
    jobs = {str(row['id']):queued_job() for row in rows[:3] if eligible(row)} if terms else {}
    return {"explanations": jobs, "explanationTerms": terms, "inputAssessment": assessment,
            "versions": dict(data.get("versions", {})) if data else {}}


def presentation(row, search_id, jobs):
    candidate = public_candidate(row, search_id)
    job = jobs.get(str(row["id"]))
    if job:
        candidate["explanation"] = job["result"]
    return candidate


def pending(jobs):
    return any(job["result"]["status"] in ("QUEUED", "RUNNING") for job in jobs.values())


def public_candidate(row, search_id):
    candidate = {key: value for key, value in row.items() if not key.startswith("_")}
    trace = row.get("_trace", {})
    if "keywordRank" in trace and "semantic" in trace:
        candidate["rankingBasis"] = {
            "keywordRank": trace["keywordRank"],
            "semanticRank": (trace["semantic"] or {}).get("rank"),
        }
    candidate["evidence"] = [
        {**source, "sourceUrl": f"{source['sourceUrl']}?searchId={search_id}"}
        for source in row["evidence"]
    ]
    return candidate


def validate_prescription_source(connection, request, author_id):
    """Verify AI provenance and copied ingredients against the saved snapshot."""
    source_id = request.prescriptionId
    search_id = request.prescriptionSearchId
    originals = {}
    catalog_tables = None
    if search_id is not None:
        if (source_id is None or not search_id.isascii() or not search_id.isdecimal()
                or len(search_id) > 10 or not 0 < int(search_id) <= 2**31 - 1):
            raise HTTPException(400, "처방 원본과 검색 번호를 확인해주세요.")
        search = connection.execute(text("""
            SELECT "INPUT_CONTEXT", "SEARCH_CONFIG" FROM "SEARCH_LOG"
            WHERE "SEARCH_UNIQN" = :id AND "CASE_UNIQN" = :case_id
              AND "SEARCH_METHOD" = 'PRESCRIPTION_COSINE' AND "SEARCH_STATUS" = 'COMPLETED'
        """), {"id": int(search_id), "case_id": request.caseId}).mappings().first()
        if not search or search["INPUT_CONTEXT"].get("authorId") != author_id:
            raise HTTPException(409, "해당 상담의 처방 검색을 확인할 수 없습니다.")
        snapshot = search["SEARCH_CONFIG"]
        candidate = next((row for row in snapshot["candidates"] + snapshot["unscoredCandidates"]
                          if row["id"] == source_id), None)
        if candidate is None:
            raise HTTPException(400, "해당 처방 검색에서 반환된 후보를 선택해주세요.")
        originals = {item["compositionId"]: item for item in candidate["ingredients"]}
    elif source_id is not None:
        catalog_tables, _, catalog_ingredients = corporate_data()
        if source_id not in catalog_tables["prescription"]:
            raise HTTPException(400, "기업 처방 원본을 찾을 수 없습니다.")
        originals = {row["compositionId"]: row for row in catalog_ingredients.get(source_id, ())}

    ingredients = []
    seen = set()
    for ingredient in request.ingredients:
        item = validate_ingredient_copy(ingredient, originals, seen)
        if item["compositionId"] is None and item["id"] is not None:
            if catalog_tables is None:
                catalog_tables, _, _ = corporate_data()
            herb = catalog_tables["herb"].get(item["id"])
            if herb is None or item["name"] != herb["MED_NM"].strip():
                raise HTTPException(400, "선택 약재의 식별자와 원본 이름을 확인해주세요.")
        ingredients.append(item)
    return ingredients


def mark_prescription_selected(connection, request):
    if request.prescriptionSearchId is not None:
        connection.execute(text("""
            UPDATE "PRESP_SEARCH_RESULT"
            SET "IS_SELECTED" = TRUE, "SELECTED_AT" = COALESCE("SELECTED_AT", CURRENT_TIMESTAMP)
            WHERE "PRESP_UNIQN" = :id AND "EVIDENCE_JSON" ->> 'prescriptionSearchId' = :search_id
        """), {"id": request.prescriptionId, "search_id": str(int(request.prescriptionSearchId))})


def create_ai_router(require_clinical_user, get_editable_consultation, validate_state):
    router = APIRouter()

    @router.post("/api/ai/symptoms")
    def search_symptoms(request: DiseaseRequest, background: BackgroundTasks, account=Depends(require_clinical_user)):
        with engine.begin() as connection:
            record = get_editable_consultation(connection, request.caseId, account)
            validate_state(record, account)

        started = monotonic()
        failure = None
        data = None
        assessment = None
        rows = []
        try:
            from .runtime import diseases_for, get_runtime

            data = get_runtime()
            assessment = analyze_symptoms(request.symptoms, data)
            rows = diseases_for(request.symptoms, data, assessment)
        except (ImportError, OSError, ValueError, KeyError, RuntimeError):
            logger.exception("Company disease search dependency failed")
            failure = (503, DEPENDENCY_FAILURE)
        except Exception:
            logger.exception("Unexpected disease search failure")
            failure = (500, "병증 검색 중 오류가 발생했습니다.")

        explanation_context = initial_explanations(rows, request.symptoms, data, assessment) if not failure else {}
        if not failure:
            explanation_context["versions"]["rankingPolicy"] = "rrf-k60-v1.3"
        jobs = explanation_context.get("explanations", {})
        with engine.begin() as connection:
            record = get_editable_consultation(connection, request.caseId, account)
            validate_state(record, account)
            # The deployed search keys have no database defaults. Serialize
            # allocation with other inserts until the schema assigns IDs itself.
            connection.execute(text('LOCK TABLE "SEARCH_LOG" IN SHARE ROW EXCLUSIVE MODE'))
            search_id = connection.execute(text("""
                INSERT INTO "SEARCH_LOG" (
                    "SEARCH_UNIQN", "CASE_UNIQN", "INPUT_TEXT", "INPUT_CONTEXT",
                    "SEARCH_METHOD", "SEARCH_VERSION", "DATA_VERSION", "MODEL_INFO",
                    "SEARCH_STATUS", "FAILURE_REASON", "ELAPSED_MS"
                )
                SELECT COALESCE(MAX("SEARCH_UNIQN"), 0) + 1, :case_id, :symptoms,
                       CAST(:context AS jsonb), 'DISEASE_RRF', '1.3', :version,
                       'intfloat/multilingual-e5-small', :status, :failure, :elapsed
                FROM "SEARCH_LOG"
                RETURNING "SEARCH_UNIQN"
            """), {
                "case_id": request.caseId, "symptoms": request.symptoms,
                "context": json.dumps({"kind": "DISEASE", "authorId": account["ACCOUNT_UNIQN"],
                                       "visitId": record["VISIT_UNIQN"],
                                       **explanation_context,
                                       "failureHttpStatus": failure[0] if failure else None}),
                "version": data["version"] if data else None,
                "status": "FAILED" if failure else "COMPLETED",
                "failure": failure[1] if failure else None,
                "elapsed": round((monotonic() - started) * 1000),
            }).scalar_one()
            if rows:
                connection.execute(text('LOCK TABLE "SEARCH_RESULT" IN SHARE ROW EXCLUSIVE MODE'))
                first_id = connection.execute(text(
                    'SELECT COALESCE(MAX("RESULT_UNIQN"), 0) + 1 FROM "SEARCH_RESULT"'
                )).scalar_one()
                connection.execute(text("""
                    INSERT INTO "SEARCH_RESULT" (
                        "RESULT_UNIQN", "SEARCH_UNIQN", "DIS_UNIQN", "RESULT_RANK",
                        "MATCH_SCORE", "EVIDENCE_JSON", "SEARCH_TRACE"
                    ) VALUES (
                        :id, :search_id, :disease_id, :rank, :score,
                        CAST(:evidence AS jsonb), CAST(:trace AS jsonb)
                    )
                """), [
                    {"id": first_id + index, "search_id": search_id, "disease_id": row["id"],
                     "rank": row["rank"], "score": row["score"],
                     "evidence": json.dumps(row["_sources"], ensure_ascii=False),
                     "trace": json.dumps(row["_trace"], ensure_ascii=False)}
                    for index, row in enumerate(rows)
                ])

        if failure:
            raise HTTPException(status_code=failure[0], detail=failure[1])
        if jobs:
            schedule(background, str(search_id), account)
        return {
            "kind": "DISEASE", "caseId": request.caseId, "searchId": str(search_id),
            "symptoms": request.symptoms,
            "candidates": [presentation(row, search_id, jobs) for row in rows],
            "total": len(rows), "hasPendingExplanations": bool(jobs), "cancelRequested": False,
            "inputAssessment": assessment,
            "message": (assessment or {}).get('message'),
        }

    @router.post("/api/ai/prescriptions")
    def search_prescriptions(request: PrescriptionRequest, background: BackgroundTasks,
                             account=Depends(require_clinical_user)):
        if len(request.selectedDiseases) != 1:
            return JSONResponse(status_code=400, content={
                "error": {"code": "INVALID_SELECTED_DISEASE", "message": "병증은 한 개만 선택해주세요.",
                          "field": "selectedDiseases"}
            })
        disease_id = request.selectedDiseases[0]
        author_id = account["ACCOUNT_UNIQN"]
        parent_id = int(request.diseaseSearchId)
        if parent_id > 2**31 - 1:
            raise HTTPException(404, "병증 검색 이력을 찾을 수 없습니다.")

        with engine.begin() as connection:
            record = get_editable_consultation(connection, request.caseId, account)
            validate_state(record, account)
            parent = connection.execute(text("""
                SELECT "CASE_UNIQN", "INPUT_TEXT", "INPUT_CONTEXT", "SEARCH_STATUS", "DATA_VERSION", "SEARCH_METHOD"
                FROM "SEARCH_LOG"
                WHERE "SEARCH_UNIQN" = :id
            """), {"id": parent_id}).mappings().first()
            if not parent:
                raise HTTPException(404, "병증 검색 이력을 찾을 수 없습니다.")
            if parent["INPUT_CONTEXT"].get("authorId") != author_id:
                raise HTTPException(403, "본인의 병증 검색만 처방에 연결할 수 있습니다.")
            if (parent["CASE_UNIQN"] != request.caseId or parent["INPUT_TEXT"] != request.symptoms
                    or parent["SEARCH_STATUS"] != "COMPLETED" or parent["SEARCH_METHOD"] != "DISEASE_RRF"):
                raise HTTPException(409, "상담과 병증 검색 조건이 일치하지 않습니다.")
            result_id = connection.execute(text("""
                SELECT "RESULT_UNIQN" FROM "SEARCH_RESULT"
                WHERE "SEARCH_UNIQN" = :search_id AND "DIS_UNIQN" = :disease_id
            """), {"search_id": parent_id, "disease_id": disease_id}).scalar_one_or_none()
            if result_id is None:
                return JSONResponse(status_code=400, content={
                    "error": {"code": "INVALID_SELECTED_DISEASE",
                              "message": "병증 검색 결과에서 병증을 선택해주세요.", "field": "selectedDiseases"}
                })

        started = monotonic()
        failure = None
        result = None
        try:
            from .runtime import get_runtime, prescriptions_for

            data = get_runtime()
            if data["version"] != parent["DATA_VERSION"]:
                raise ValueError("병증 검색 당시와 현재 검색 자료 버전이 다릅니다.")
            assessment = parent["INPUT_CONTEXT"].get('inputAssessment')
            assessment = assessment if assessment is not None else analyze_symptoms(request.symptoms, data)
            if not assessment.get('searchTerms',assessment['affirmedTerms']):
                return JSONResponse(status_code=409, content={'error':{'code':'STATE_CONFLICT',
                    'message':'현재 환자의 긍정 증상을 확인한 뒤 병증을 다시 검색해주세요.','field':'symptoms'}})
            result = prescriptions_for(request.symptoms, disease_id, data, assessment)
        except (ImportError, OSError, ValueError, KeyError, RuntimeError):
            logger.exception("Company prescription search dependency failed")
            failure = (503, DEPENDENCY_FAILURE)
        except Exception:
            logger.exception("Unexpected prescription search failure")
            failure = (500, "처방 검색 중 오류가 발생했습니다.")

        explanation_context = initial_explanations(result["candidates"], request.symptoms, data, assessment) if not failure else {}
        if not failure:
            explanation_context["versions"]["evaluationPolicy"] = result.get("_evaluationPolicy")
        jobs = explanation_context.get("explanations", {})
        with engine.begin() as connection:
            record = get_editable_consultation(connection, request.caseId, account)
            validate_state(record, account)
            connection.execute(text('LOCK TABLE "SEARCH_LOG" IN SHARE ROW EXCLUSIVE MODE'))
            search_id = connection.execute(text("""
                INSERT INTO "SEARCH_LOG" (
                    "SEARCH_UNIQN", "CASE_UNIQN", "INPUT_TEXT", "INPUT_CONTEXT",
                    "SEARCH_METHOD", "SEARCH_VERSION", "DATA_VERSION", "MODEL_INFO",
                    "SEARCH_CONFIG", "SEARCH_STATUS", "FAILURE_REASON", "ELAPSED_MS"
                )
                SELECT COALESCE(MAX("SEARCH_UNIQN"), 0) + 1, :case_id, :symptoms,
                       CAST(:context AS jsonb), 'PRESCRIPTION_COSINE', '1.3', :version,
                       'intfloat/multilingual-e5-small', CAST(:snapshot AS jsonb),
                       :status, :failure, :elapsed
                FROM "SEARCH_LOG"
                RETURNING "SEARCH_UNIQN"
            """), {
                "case_id": request.caseId, "symptoms": request.symptoms,
                "context": json.dumps({"kind": "PRESCRIPTION", "authorId": author_id,
                                       "visitId": record["VISIT_UNIQN"], "diseaseSearchId": parent_id,
                                       "selectedDiseaseId": disease_id,
                                       **explanation_context,
                                       "failureHttpStatus": failure[0] if failure else None}),
                "version": parent["DATA_VERSION"], "status": "FAILED" if failure else "COMPLETED",
                "failure": failure[1] if failure else None,
                "elapsed": round((monotonic() - started) * 1000),
                "snapshot": json.dumps(result, ensure_ascii=False),
            }).scalar_one()
            if not failure:
                # Finish the user's selected prescription search before the
                # unselected disease explanations that remain in its parent.
                connection.execute(text('''
                    UPDATE "SEARCH_LOG" SET "INPUT_CONTEXT" = "INPUT_CONTEXT" ||
                        jsonb_build_object('prioritizedPrescriptionSearchId', CAST(:child AS text))
                    WHERE "SEARCH_UNIQN" = :parent
                '''), {'child':str(search_id),'parent':parent_id})
                connection.execute(text("""
                    UPDATE "SEARCH_RESULT"
                    SET "IS_SELECTED" = TRUE, "SELECTED_AT" = COALESCE("SELECTED_AT", CURRENT_TIMESTAMP)
                    WHERE "RESULT_UNIQN" = :result_id
                """), {"result_id": result_id})
                candidates = result["candidates"] + result["unscoredCandidates"]
                if candidates:
                    connection.execute(text('LOCK TABLE "PRESP_SEARCH_RESULT" IN SHARE ROW EXCLUSIVE MODE'))
                    first_id = connection.execute(text(
                        'SELECT COALESCE(MAX("PRESP_RESULT_UNIQN"), 0) + 1 FROM "PRESP_SEARCH_RESULT"'
                    )).scalar_one()
                    connection.execute(text("""
                        INSERT INTO "PRESP_SEARCH_RESULT" (
                            "PRESP_RESULT_UNIQN", "RESULT_UNIQN", "PRESP_UNIQN", "RESULT_RANK",
                            "RELEVANCE_SCORE", "SCORE_STATUS", "EVIDENCE_JSON", "CAUTION_INFO"
                        ) VALUES (
                            :id, :result_id, :prescription_id, :rank, :score, :status,
                            CAST(:evidence AS jsonb), CAST(:caution AS jsonb)
                        )
                    """), [
                        {"id": first_id + index, "result_id": result_id, "prescription_id": row["id"],
                         "rank": row["rank"], "score": row["score"], "status": row["evaluationStatus"],
                         "evidence": json.dumps({"prescriptionSearchId": str(search_id),
                                                 "sources": row["_sources"]}, ensure_ascii=False),
                         "caution": json.dumps({"caution": row["caution"],
                                                "sources": row["_cautionSources"]}, ensure_ascii=False)}
                        for index, row in enumerate(candidates)
                    ])

        if failure:
            raise HTTPException(status_code=failure[0], detail=failure[1])
        if jobs:
            schedule(background, str(search_id), account)
        return {
            "kind": "PRESCRIPTION", "caseId": request.caseId, "searchId": str(search_id),
            "inputAssessment": assessment,
            "diseaseSearchId": request.diseaseSearchId, "selectedDiseaseId": disease_id,
            "symptoms": request.symptoms, "summary": result["summary"], "message": result["message"],
            "hasPendingExplanations": bool(jobs), "cancelRequested": False,
            "candidates": [presentation(row, search_id, jobs) for row in result["candidates"]],
            "unscoredCandidates": [public_candidate(row, search_id) for row in result["unscoredCandidates"]],
        }

    def get_search(connection, search_id, account, *, lock=False):
        row = connection.execute(text("""
            SELECT s.*, p."CLINIC_UNIQN" FROM "SEARCH_LOG" s
            JOIN "CASE_RECORD" c ON c."CASE_UNIQN" = s."CASE_UNIQN"
            JOIN "VISIT" v ON v."VISIT_UNIQN" = c."VISIT_UNIQN"
            JOIN "PATIENT" p ON p."PATIENT_UNIQN" = v."PATIENT_UNIQN"
            WHERE s."SEARCH_UNIQN" = :id
              AND s."SEARCH_METHOD" IN ('DISEASE_RRF', 'PRESCRIPTION_COSINE')
        """ + (' FOR UPDATE OF s' if lock else '')),
            {"id": int(search_id)}).mappings().first() if int(search_id) <= 2**31 - 1 else None
        if row is None:
            raise HTTPException(404, "검색 이력을 찾을 수 없습니다.")
        if row["CLINIC_UNIQN"] != account["CLINIC_UNIQN"]:
            raise HTTPException(403, "다른 한의원의 검색 이력에 접근할 수 없습니다.")
        return row

    def load_candidates(connection, search):
        from .runtime import evidence_response, explanation

        return [
            {"id": row["DIS_UNIQN"], "name": row["SEARCH_TRACE"]["name"],
             "score": row["MATCH_SCORE"], "rank": row["RESULT_RANK"],
             "evidence": [evidence_response(source) for source in row["EVIDENCE_JSON"]],
             "explanation": explanation(row["EVIDENCE_JSON"]), "_sources": row["EVIDENCE_JSON"],
             "_trace": row["SEARCH_TRACE"]}
            for row in connection.execute(text("""
                SELECT r.* FROM "SEARCH_RESULT" r
                WHERE r."SEARCH_UNIQN" = :id ORDER BY r."RESULT_RANK"
            """), {"id": search["SEARCH_UNIQN"]}).mappings()
        ]

    def scored_candidates(connection, search):
        if search["INPUT_CONTEXT"]["kind"] == "DISEASE":
            return load_candidates(connection, search)
        return search["SEARCH_CONFIG"]["candidates"]

    def save_context(connection, search_id, context):
        connection.execute(text("""
            UPDATE "SEARCH_LOG" SET "INPUT_CONTEXT" = CAST(:context AS jsonb)
            WHERE "SEARCH_UNIQN" = :id
        """), {"id": int(search_id), "context": json.dumps(context, ensure_ascii=False)})

    scheduled = set()
    schedule_lock = Lock()

    def schedule(background, search_id, account):
        with schedule_lock:
            if search_id in scheduled:
                return
            scheduled.add(search_id)
        background.add_task(run_explanations, search_id, account)

    def run_explanations(search_id, account):
        try:
            # Model calls are serialized between application processes as well.
            while True:
                # Release the model slot between candidates so another search can run.
                with model_process_lock, engine.begin() as model_slot:
                    model_slot.execute(text("SELECT pg_advisory_xact_lock(61231841)"))
                    with engine.begin() as connection:
                        search = get_search(connection, search_id, account, lock=True)
                        context = search["INPUT_CONTEXT"]
                        jobs = context.get("explanations", {})
                        priority_child = context.get('prioritizedPrescriptionSearchId')
                        if priority_child:
                            child = get_search(connection, priority_child, account)
                            if pending(child['INPUT_CONTEXT'].get('explanations', {})):
                                return
                        for interrupted in jobs.values():
                            if interrupted["result"]["status"] == "RUNNING":
                                interrupted.update(
                                    result=state("INCOMPLETE", "이전 설명 실행이 종료되어 결과를 확인할 수 없습니다."),
                                    finishedAt=datetime.now(timezone.utc).isoformat(),
                                )
                                save_context(connection, search_id, context)
                        if context.get("cancelRequested"):
                            return
                        candidate = next((row for row in scored_candidates(connection, search)
                                          if jobs.get(str(row["id"]), {}).get("result", {}).get("status") == "QUEUED"), None)
                        if candidate is None:
                            return
                        key = str(candidate["id"])
                        job = jobs[key]
                        started_at = datetime.now(timezone.utc)
                        job["startedAt"] = started_at.isoformat()
                        job["queueMs"] = round((started_at - datetime.fromisoformat(job["queuedAt"])).total_seconds() * 1000)
                        job["result"] = state("RUNNING", "관련 이유를 생성·확인 중")
                        save_context(connection, search_id, context)

                    def cancelled():
                        with engine.connect() as connection:
                            return bool(get_search(connection, search_id, account)["INPUT_CONTEXT"].get("cancelRequested"))

                    terms = context.get("explanationTerms", [])
                    try:
                        if terms:
                            from .runtime import get_runtime

                            checks = verify_candidate(search, candidate, get_runtime(), corporate_data())
                            result, trace = explain(candidate, terms, cancelled, checks=checks)
                        else:
                            result = state("INCOMPLETE", "설명에 사용할 수 있는 등록 증상 표현을 확인하지 못했습니다.")
                            trace = {}
                    except Exception:
                        logger.exception("Explanation processing failed")
                        result = state("INCOMPLETE", "설명 생성 또는 검토를 완료하지 못했습니다.")
                        trace = {"checks": [check_record("SERVER_CHECKS", {"id": candidate["id"]}, True,
                                                         "ERROR", "필수 서버 검사 실행 실패")]}

                    with engine.begin() as connection:
                        context = get_search(connection, search_id, account, lock=True)["INPUT_CONTEXT"]
                        if context.get("cancelRequested"):
                            result = state("INCOMPLETE", "중단 요청으로 설명 처리를 종료했습니다.")
                        context["explanations"][key].update(
                            result=result, trace=trace, finishedAt=datetime.now(timezone.utc).isoformat(),
                        )
                        save_context(connection, search_id, context)
        except Exception:
            logger.exception("Explanation job persistence failed")
        finally:
            with schedule_lock:
                scheduled.discard(search_id)

    @router.post("/api/ai/searches/{search_id}/explanations", status_code=202)
    def request_explanations(search_id: SearchId, request: ExplanationRequest,
                             background: BackgroundTasks, account=Depends(require_clinical_user)):
        accepted = []
        existing = []
        if len(set(request.candidateIds)) != len(request.candidateIds):
            raise HTTPException(400, "설명 대상 병증 또는 처방이 중복되었습니다.")
        with engine.begin() as connection:
            search = get_search(connection, search_id, account, lock=True)
            context = search["INPUT_CONTEXT"]
            if context["authorId"] != account["ACCOUNT_UNIQN"]:
                raise HTTPException(403, "작성자만 설명을 요청할 수 있습니다.")
            if context.get("cancelRequested") or search["SEARCH_STATUS"] != "COMPLETED":
                raise HTTPException(409, "이 검색에는 설명을 추가할 수 없습니다.")
            candidates = {row["id"]: row for row in scored_candidates(connection, search)}
            jobs = context.setdefault("explanations", {})
            for item_id in request.candidateIds:
                if item_id not in candidates:
                    raise HTTPException(400, "설명 대상은 해당 검색의 평가 후보여야 합니다.")
                if not eligible(candidates[item_id]):
                    continue
                key = str(item_id)
                if key in jobs:
                    existing.append(item_id)
                else:
                    jobs[key] = queued_job()
                    accepted.append(item_id)
            if accepted:
                save_context(connection, search_id, context)
        if accepted:
            schedule(background, search_id, account)
        return {"searchId": search_id, "acceptedCandidateIds": accepted, "existingCandidateIds": existing}

    @router.get("/api/ai/searches/{search_id}")
    def search_detail(search_id: SearchId, background: BackgroundTasks,
                      account=Depends(require_clinical_user)):
        with engine.connect() as connection:
            search = get_search(connection, search_id, account)
            context = search["INPUT_CONTEXT"]
            jobs = context.get("explanations", {})
            if pending(jobs):
                schedule(background, search_id, account)
            if search["SEARCH_STATUS"] == "FAILED":
                raise HTTPException(context["failureHttpStatus"], search["FAILURE_REASON"])
            base = {"kind": context["kind"], "caseId": search["CASE_UNIQN"], "searchId": search_id,
                    "symptoms": search["INPUT_TEXT"], "hasPendingExplanations": pending(jobs),
                    "inputAssessment": context.get('inputAssessment'),
                    "cancelRequested": bool(context.get("cancelRequested"))}
            if context["kind"] == "DISEASE":
                candidates = load_candidates(connection, search)
                return {**base, "total": len(candidates),
                        "candidates": [presentation(row, search_id, jobs) for row in candidates],
                        "message": context.get('inputAssessment', {}).get('message') if candidates else context.get('inputAssessment', {}).get('message', '현재 검색 범위에서 관련 병증을 찾지 못했습니다')}
            snapshot = search["SEARCH_CONFIG"]
            return {**base, "selectedDiseaseId": context["selectedDiseaseId"],
                    "diseaseSearchId": str(context["diseaseSearchId"]), "summary": snapshot["summary"],
                    "message": snapshot["message"],
                    "candidates": [presentation(row, search_id, jobs) for row in snapshot["candidates"]],
                    "unscoredCandidates": [public_candidate(row, search_id) for row in snapshot["unscoredCandidates"]]}

    @router.get("/api/ai/sources/{source_id}")
    def source_detail(source_id: str, searchId: SearchId, account=Depends(require_clinical_user)):
        from .runtime import evidence_response

        with engine.connect() as connection:
            search = get_search(connection, searchId, account)
            if search["SEARCH_STATUS"] == "COMPLETED":
                if search["INPUT_CONTEXT"]["kind"] == "DISEASE":
                    candidates = load_candidates(connection, search)
                else:
                    snapshot = search["SEARCH_CONFIG"]
                    candidates = snapshot["candidates"] + snapshot["unscoredCandidates"]
                for candidate in candidates:
                    for source in candidate["_sources"]:
                        if source["sourceId"] == source_id:
                            detail = evidence_response(source)
                            detail["sourceUrl"] += f"?searchId={searchId}"
                            return {"record": {**detail, "originalText": source["originalText"]}}
        raise HTTPException(404, "저장된 원문을 찾을 수 없습니다.")

    @router.post("/api/ai/searches/{search_id}/cancel")
    def cancel_search(search_id: SearchId, account=Depends(require_clinical_user)):
        with engine.begin() as connection:
            search = get_search(connection, search_id, account, lock=True)
            if search["INPUT_CONTEXT"]["authorId"] != account["ACCOUNT_UNIQN"]:
                raise HTTPException(403, "작성자만 검색 작업을 중단할 수 있습니다.")
            context = search["INPUT_CONTEXT"]
            if not context.get("cancelRequested"):
                context["cancelRequested"] = True
                requested_at = datetime.now(timezone.utc).isoformat()
                context["cancelRequestedAt"] = requested_at
                for job in context.get("explanations", {}).values():
                    if job["result"]["status"] == "QUEUED":
                        job.update(result=state("INCOMPLETE", "중단 요청으로 대기 중인 설명을 종료했습니다."),
                                   finishedAt=requested_at)
                save_context(connection, search_id, context)
        return {"searchId": search_id, "cancelRequested": True}

    @router.get("/api/consultations/{case_id}/searches")
    def consultation_searches(
        case_id: Annotated[int, Field(gt=0, le=2**63 - 1)],
        account=Depends(require_clinical_user),
    ):
        with engine.connect() as connection:
            clinic = connection.execute(text("""
                SELECT p."CLINIC_UNIQN" FROM "CASE_RECORD" c
                JOIN "VISIT" v ON v."VISIT_UNIQN" = c."VISIT_UNIQN"
                JOIN "PATIENT" p ON p."PATIENT_UNIQN" = v."PATIENT_UNIQN"
                WHERE c."CASE_UNIQN" = :id
            """), {"id": case_id}).first()
            if clinic is None:
                raise HTTPException(404, "상담기록을 찾을 수 없습니다.")
            if clinic[0] != account["CLINIC_UNIQN"]:
                raise HTTPException(403, "다른 한의원의 검색 이력에 접근할 수 없습니다.")
            rows = connection.execute(text("""
                SELECT * FROM "SEARCH_LOG" WHERE "CASE_UNIQN" = :id
                  AND "SEARCH_METHOD" IN ('DISEASE_RRF', 'PRESCRIPTION_COSINE')
                ORDER BY "CREATED_AT", "SEARCH_UNIQN"
            """), {"id": case_id}).mappings().all()
        records = []
        for row in rows:
            context = row["INPUT_CONTEXT"]
            parent_id = context.get("diseaseSearchId")
            records.append({
                "searchId": str(row["SEARCH_UNIQN"]), "kind": context["kind"],
                "caseId": case_id, "symptoms": row["INPUT_TEXT"],
                "diseaseSearchId": str(parent_id) if parent_id else None,
                "selectedDiseaseId": context.get("selectedDiseaseId"),
                "status": row["SEARCH_STATUS"], "cancelRequested": bool(context.get("cancelRequested")),
                "createdAt": row["CREATED_AT"].isoformat(), "elapsedMs": row["ELAPSED_MS"],
                "failureReason": row["FAILURE_REASON"],
            })
        return {"records": records, "total": len(records)}

    return router

