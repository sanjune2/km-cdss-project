"""기존 인증과 상담 접근 검사를 적용하는 AI 미리보기 라우터. DB에는 쓰지 않는다."""
import logging
import os
from pathlib import Path
from threading import Lock
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.ai.schemas import SymptomSearchRequest
from backend.context_preview_api import PreviewResponse
from backend.scripts.run_context_search_preview import load_data, run_preview

logger = logging.getLogger(__name__)


class ConsultationPreviewResponse(PreviewResponse):
    caseId: int


CASE_QUERY = '''SELECT c."CASE_UNIQN", c."AUTHOR_UNIQN", v."VISIT_UNIQN",
    v."STATUS_CD", v."DOCTOR_UNIQN", p."CLINIC_UNIQN"
    FROM "CASE_RECORD" c
    JOIN "VISIT" v ON v."VISIT_UNIQN"=c."VISIT_UNIQN"
    JOIN "PATIENT" p ON p."PATIENT_UNIQN"=v."PATIENT_UNIQN"
    WHERE c."CASE_UNIQN"=:case_id AND p."CLINIC_UNIQN"=:clinic_id'''


def check_clinical_account(account):
    for key in ["ACCOUNT_UNIQN", "CLINIC_UNIQN"]:
        if type(account.get(key)) is not int or account[key] <= 0:
            raise HTTPException(403, detail="계정 또는 소속 한의원 정보를 확인해주세요.")
    if account.get("STATUS_CD") != "ACTIVE":
        raise HTTPException(401, detail="사용할 수 없는 계정입니다.")
    if account.get("IS_OWNER") is not True and account.get("ROLE_CD") != "DOCTOR":
        raise HTTPException(403, detail="AI 검색을 사용할 진료 권한이 없습니다.")


def authorized_case(engine, sql_text, case_id, account):
    check_clinical_account(account)
    # 추론 전에 연결을 반환한다. 긴 모델 호출 중 행 잠금·DB 연결을 유지하지 않는다.
    with engine.connect() as connection:
        row = connection.execute(sql_text(CASE_QUERY), {
            "case_id": case_id, "clinic_id": account["CLINIC_UNIQN"],
        }).mappings().first()
        case = dict(row) if row is not None else None
    if case is None:
        raise HTTPException(404, detail="상담기록이 없습니다.")
    if case["CLINIC_UNIQN"] != account["CLINIC_UNIQN"]:
        raise HTTPException(404, detail="상담기록이 없습니다.")
    if case["AUTHOR_UNIQN"] != account["ACCOUNT_UNIQN"] or case["DOCTOR_UNIQN"] != account["ACCOUNT_UNIQN"]:
        raise HTTPException(403, detail="담당 한의사만 이 상담의 AI 검색을 사용할 수 있습니다.")
    if case["STATUS_CD"] != "IN_PROGRESS":
        raise HTTPException(409, detail="진료 중인 상담에서 AI 검색을 사용할 수 있습니다.")
    return case


def create_context_preview_router(*, clinical_dependency, engine, sql_text,
                                  data_root=None, data_loader=load_data, preview_runner=run_preview):
    router = APIRouter(tags=["상담 AI 통합 미리보기"])
    inference_lock = Lock()
    cached_data = None
    root = Path(data_root or os.environ.get("KM_CDSS_DATA_ROOT", r"C:\km-cdss-data"))

    @router.post("/api/ai/diagnosis/preview", response_model=ConsultationPreviewResponse)
    def consultation_preview(payload: SymptomSearchRequest, request: Request,
                             account=Depends(clinical_dependency)):
        nonlocal cached_data
        authorized_case(engine, sql_text, payload.caseId, account)
        if not inference_lock.acquire(blocking=False):
            raise HTTPException(429, detail="다른 AI 분석이 진행 중입니다. 완료 후 다시 시도해주세요.", headers={"Retry-After": "1"})
        try:
            if cached_data is None:
                cached_data = data_loader(root)
            preview_id = "preview-" + uuid4().hex
            report = {
                "case_id": str(payload.caseId), "symptoms": payload.symptoms,
                "status": "NOT_RUN", "stage": "DATA_VALIDATED",
                "generation_calls": 0, "query_embedding_calls": 0,
                "context_run_status": "NOT_RUN", "search_run_status": "NOT_RUN",
                "candidates": [], "top3": [], "keywordIds": [], "semanticCandidates": [],
                "used_in_search": False, "actual_api_modified": False,
            }
            preview_runner(report, cached_data, "http://127.0.0.1:11434", lambda _: None)
            if report["status"] != "COMPLETED":
                raise RuntimeError("AI 분석이 완료되지 않았습니다.")
            if report["route"] != "CANDIDATE_REVIEW" and report["candidates"]:
                raise RuntimeError("확인 경로에 후보가 포함됐습니다.")
            # 분석 중 로그아웃·권한 변경·담당자 변경·진료 완료가 발생한 경우 결과를 반환하지 않는다.
            fresh_account = clinical_dependency(request)
            if fresh_account["ACCOUNT_UNIQN"] != account["ACCOUNT_UNIQN"]:
                raise HTTPException(401, detail="로그인 정보가 변경됐습니다. 다시 요청해주세요.")
            authorized_case(engine, sql_text, payload.caseId, fresh_account)
            return ConsultationPreviewResponse(
                caseId=payload.caseId, previewId=preview_id, symptoms=payload.symptoms,
                route=report["route"], message=report["message"],
                total=len(report["candidates"]), candidates=report["candidates"],
                reviewMentions=report["reviewMentions"],
            )
        except HTTPException:
            raise
        except Exception:
            logger.exception("Authenticated AI preview failed")
            raise HTTPException(503, detail="AI 분석을 완료하지 못했습니다. 서버 상태를 확인해주세요.") from None
        finally:
            inference_lock.release()

    return router
