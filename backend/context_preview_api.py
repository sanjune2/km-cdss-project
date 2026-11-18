"""로컬 전용 AI 통합 검증 API. 기존 서비스 앱·DB·검색 이력에는 연결하지 않는다."""
from contextlib import asynccontextmanager
import ipaddress
import logging
import os
from pathlib import Path
from threading import Lock
from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.scripts.run_context_search_preview import load_data, run_preview

logger = logging.getLogger(__name__)


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    symptoms: str = Field(min_length=1, description="통합 실험에 사용할 증상 문장")

    @field_validator("symptoms")
    @classmethod
    def clean_symptoms(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("증상을 입력해주세요.")
        return value


class PreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    previewId: str
    symptoms: str
    route: Literal["CANDIDATE_REVIEW", "CONFIRM_INTERPRETATION", "REVIEW_INPUT"]
    message: str
    total: int = Field(ge=0)
    candidates: list[dict[str, Any]]
    reviewMentions: list[dict[str, Any]]
    explanationStatus: Literal["NOT_REQUESTED"] = "NOT_REQUESTED"
    historySaved: Literal[False] = False


def create_app(data_loader=load_data, preview_runner=run_preview):
    @asynccontextmanager
    async def lifespan(app):
        root = Path(os.environ.get("KM_CDSS_DATA_ROOT", r"C:\km-cdss-data"))
        app.state.data = data_loader(root)
        app.state.inference_lock = Lock()
        yield
        app.state.data = None

    app = FastAPI(
        title="한의결 AI 로컬 통합 검증 API",
        description="로컬 실험용 API. 기존 상담·검색 식별번호와 저장 이력을 생성하지 않습니다.",
        version="0.1.0-preview", lifespan=lifespan,
    )

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        try:
            allowed = request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
        except ValueError:
            allowed = False
        if not allowed:
            return JSONResponse(status_code=403, content={"detail": "로컬 통합 검증 API입니다."})
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc):
        return JSONResponse(status_code=422, content={
            "detail": "요청 형식을 확인해주세요. symptoms에 비어 있지 않은 문자열을 입력해주세요."
        }, headers={"Cache-Control": "no-store"})

    @app.get("/api/health")
    def health():
        return {"status": "ok", "scope": "LOCAL_PREVIEW", "historySaved": False}

    @app.post("/api/ai/diagnosis/preview", response_model=PreviewResponse)
    def diagnosis_preview(payload: PreviewRequest):
        lock = app.state.inference_lock
        if not lock.acquire(blocking=False):
            raise HTTPException(status_code=429, detail="다른 분석이 진행 중입니다. 완료 후 다시 시도해주세요.", headers={"Retry-After": "1"})
        try:
            preview_id = "preview-" + uuid4().hex
            report = {
                "case_id": preview_id, "symptoms": payload.symptoms,
                "status": "NOT_RUN", "stage": "DATA_VALIDATED",
                "generation_calls": 0, "query_embedding_calls": 0,
                "context_run_status": "NOT_RUN", "search_run_status": "NOT_RUN",
                "candidates": [], "top3": [], "keywordIds": [], "semanticCandidates": [],
                "used_in_search": False, "actual_api_modified": False,
            }
            preview_runner(report, app.state.data, "http://127.0.0.1:11434", lambda _: None)
            if report["status"] != "COMPLETED":
                raise RuntimeError("통합 분석이 완료되지 않았습니다.")
            # 실험 추적·모델 원문 응답·설정은 API 응답에서 제외한다.
            # 후보 전체 목록과 RRF 점수·순위는 통합 실행 결과 그대로 반환한다.
            if report["route"] != "CANDIDATE_REVIEW" and report["candidates"]:
                raise RuntimeError("확인 경로에 검색 후보가 포함됐습니다.")
            return PreviewResponse(
                previewId=preview_id, symptoms=payload.symptoms,
                route=report["route"], message=report["message"],
                total=len(report["candidates"]), candidates=report["candidates"],
                reviewMentions=report["reviewMentions"],
            )
        except HTTPException:
            raise
        except Exception:
            logger.exception("AI preview failed")
            raise HTTPException(status_code=503, detail="AI 통합 분석을 완료하지 못했습니다. 서버 상태를 확인해주세요.") from None
        finally:
            lock.release()

    return app


app = create_app()
