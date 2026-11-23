import json
import math
import secrets
import hashlib
from fastapi import Query
from datetime import datetime, timedelta, timezone
from staff import create_staff_router
from fastapi import Depends
from fastapi import Request
from itsdangerous import BadSignature, SignatureExpired
import os
from itsdangerous import URLSafeTimedSerializer
from fastapi import Response
from auth import verify_password, hash_password
from models import Patient
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError
from prescription_ingredients import Ingredient

from sqlalchemy import text
from database import engine
from catalog import create_catalog_router
from ai.service import create_ai_router, mark_prescription_selected, validate_prescription_source


app = FastAPI(title="한의결 API")
SESSION_TTL_SECONDS = int(os.environ["SESSION_TTL_SECONDS"])

if SESSION_TTL_SECONDS <= 0:
    raise RuntimeError("SESSION_TTL_SECONDS는 0보다 커야 합니다.")


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_login_session(account_id: int):
    token = secrets.token_urlsafe(32)
    token_hash = hash_session_token(token)

    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=SESSION_TTL_SECONDS
    )

    with engine.begin() as connection:
        connection.execute(
            text("""
                INSERT INTO "LOGIN_SESSION" (
                    "ACCOUNT_UNIQN",
                    "TOKEN_HASH",
                    "CREATED_AT",
                    "EXPIRES_AT",
                    "REVOKED_AT"
                )
                VALUES (
                    :account_id,
                    :token_hash,
                    CURRENT_TIMESTAMP,
                    :expires_at,
                    NULL
                )
            """),
            {
                "account_id": account_id,
                "token_hash": token_hash,
                "expires_at": expires_at
            }
        )

    return token, expires_at


def require_authenticated_user(request: Request):
    token = request.cookies.get("session")

    if not token:
        raise HTTPException(
            status_code=401,
            detail="로그인이 필요합니다."
        )

    token_hash = hash_session_token(token)

    with engine.connect() as connection:
        account = connection.execute(
            text("""
                SELECT
                    a."ACCOUNT_UNIQN",
                    a."CLINIC_UNIQN",
                    a."EMAIL",
                    a."NAME",
                    a."ROLE_CD",
                    a."IS_OWNER",
                    a."STATUS_CD",
                    s."EXPIRES_AT",
                    c."STATUS_CD" AS "CLINIC_STATUS"
                FROM "LOGIN_SESSION" s
                JOIN "ACCOUNT" a
                    ON a."ACCOUNT_UNIQN" = s."ACCOUNT_UNIQN"
                LEFT JOIN "CLINIC" c
                    ON c."CLINIC_UNIQN" = a."CLINIC_UNIQN"
                WHERE s."TOKEN_HASH" = :token_hash
                  AND s."REVOKED_AT" IS NULL
                  AND s."EXPIRES_AT" > CURRENT_TIMESTAMP
            """),
            {"token_hash": token_hash}
        ).mappings().first()

    if account is None:
        raise HTTPException(
            status_code=401,
            detail="로그인 세션이 유효하지 않거나 만료되었습니다."
        )

    if account["STATUS_CD"] != "ACTIVE":
        raise HTTPException(
            status_code=403,
            detail="사용할 수 없는 계정입니다."
        )

    if account["ROLE_CD"] == "SERVICE_ADMIN":
        if account["CLINIC_UNIQN"] is not None:
            raise HTTPException(
                status_code=403,
                detail="서비스 운영 관리자 계정 정보가 올바르지 않습니다."
            )
        return account

    if account["CLINIC_UNIQN"] is None:
        raise HTTPException(
            status_code=403,
            detail="소속 한의원 정보가 없습니다."
        )

    if account["CLINIC_STATUS"] != "ACTIVE":
        raise HTTPException(
            status_code=403,
            detail="이용할 수 없는 한의원입니다."
        )

    if account["ROLE_CD"] not in ("DOCTOR", "DESK"):
        raise HTTPException(
            status_code=403,
            detail="접근 권한이 없습니다."
        )

    return account

app.include_router(
    create_staff_router(require_authenticated_user)
)

# API 설계서 v1.3 - 공통 오류 응답

_ERROR_CODES = {
    400: "INVALID_INPUT",
    401: "AUTH_REQUIRED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "STATE_CONFLICT",
    500: "INTERNAL_ERROR",
    503: "SERVICE_UNAVAILABLE",
}


def api_error(status_code: int, message: str, field: str | None = None, code: str | None = None):
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code or _ERROR_CODES.get(status_code, "INTERNAL_ERROR"),
                "message": message,
                "field": field,
            }
        },
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if (exc.status_code == 400 and isinstance(exc.detail, dict)
            and exc.detail.get("code") == "INVALID_SELECTED_DISEASE"):
        return api_error(400, exc.detail["message"], exc.detail["field"], "INVALID_SELECTED_DISEASE")
    message = (
        exc.detail
        if isinstance(exc.detail, str)
        else "요청을 처리할 수 없습니다."
    )
    return api_error(exc.status_code, message)


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
):
    first = exc.errors()[0] if exc.errors() else {}
    loc = first.get("loc", ())

    field = ".".join(
        str(part)
        for part in loc
        if part not in ("body", "query", "path")
    ) or None

    return api_error(
        400,
        "요청 필드 또는 자료형이 올바르지 않습니다.",
        field,
    )


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
    print("DATABASE ERROR:", repr(exc), flush=True)

    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "code": "SERVICE_UNAVAILABLE",
                "message": "데이터베이스 처리 중 오류가 발생했습니다.",
                "field": None
            }
        }
    )



@app.exception_handler(Exception)
async def internal_exception_handler(
    request: Request,
    exc: Exception,
):
    return api_error(
        500,
        "서버 내부 오류가 발생했습니다.",
    )

allowed_origins = {
    origin.strip() for origin in os.getenv(
        "HANUI_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",") if origin.strip()
}


@app.middleware("http")
async def validate_write_origin(request: Request, call_next):
    origin = request.headers.get("origin")
    if (request.url.path.startswith("/api/") and request.method in {"POST", "PATCH", "PUT", "DELETE"}
            and (origin is not None and origin not in allowed_origins
                 or origin is None and request.headers.get("sec-fetch-site") == "cross-site")):
        return api_error(403, "허용된 서비스 주소에서 요청해주세요.")
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(allowed_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



@app.get("/")
def root():
    return {"message": "한의결 백엔드 서버 실행 성공"}


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/db-health")
def db_health():
    try:
        with engine.connect() as connection:
            result = connection.execute(text("SELECT 1"))

            return {
                "status": "ok",
                "database": "connected",
                "result": result.scalar_one(),
                "patient_table": Patient.name
            }
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="데이터베이스 연결에 실패했습니다."
        )



class SymptomRequest(BaseModel):
    symptoms: str


@app.post("/api/diagnosis/recommend")
def recommend_diagnosis(request: SymptomRequest):
    if not request.symptoms.strip():
        return {
            "candidates": [],
            "message": "증상을 입력해 주세요."
        }

    return {
        "candidates": [],
        "message": "AI 병증 추천 기능은 아직 연결되지 않았습니다."
    }

from fastapi import HTTPException

class PatientCreate(BaseModel):
    name: str
    birthDate: str
    phone: str
    address: str
    guardianName: str = ""
    guardianRelation: str = ""
    guardianPhone: str = ""


@app.post("/api/patients", status_code=201)
def create_patient(
    patient: PatientCreate,
    account=Depends(require_authenticated_user)
):
    if not all([
        patient.name.strip(),
        patient.birthDate.strip(),
        patient.phone.strip(),
        patient.address.strip()
    ]):
        raise HTTPException(
            status_code=400,
            detail="필수 환자 정보를 모두 입력해 주세요."
        )

    try:
        birth_date = datetime.strptime(
            patient.birthDate, "%Y-%m-%d"
        ).date()
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="생년월일 형식이 올바르지 않습니다."
        )

    with engine.begin() as connection:
        patient_id = connection.execute(
            text("""
                INSERT INTO "PATIENT" (
                    "CLINIC_UNIQN",
                    "NAME",
                    "BIRTH_DATE",
                    "PHONE",
                    "ADDRESS",
                    "GUARDIAN_NAME",
                    "GUARDIAN_RELATION",
                    "GUARDIAN_PHONE"
                )
                VALUES (
                    :clinic_id,
                    :name,
                    :birth_date,
                    :phone,
                    :address,
                    :guardian_name,
                    :guardian_relation,
                    :guardian_phone
                )
                RETURNING "PATIENT_UNIQN"
            """),
            {
                "clinic_id": account["CLINIC_UNIQN"],
                "name": patient.name.strip(),
                "birth_date": birth_date,
                "phone": patient.phone.strip(),
                "address": patient.address.strip(),
                "guardian_name": patient.guardianName.strip() or None,
                "guardian_relation": patient.guardianRelation.strip() or None,
                "guardian_phone": patient.guardianPhone.strip() or None
            }
        ).scalar_one()

    return {
        "message": "환자 등록이 완료되었습니다.",
        "patient": {
            "id": patient_id,
            **patient.model_dump()
        }
    }

@app.get("/api/patients")
def get_patients(
    account=Depends(require_authenticated_user)
):
    with engine.connect() as connection:
        rows = connection.execute(
            text("""
                SELECT
                    "PATIENT_UNIQN",
                    "NAME",
                    "BIRTH_DATE",
                    "PHONE",
                    "ADDRESS",
                    "GUARDIAN_NAME",
                    "GUARDIAN_RELATION",
                    "GUARDIAN_PHONE"
                FROM "PATIENT"
                WHERE "CLINIC_UNIQN" = :clinic_id
                ORDER BY "PATIENT_UNIQN"
                """),
                {"clinic_id": account["CLINIC_UNIQN"]}
                ).mappings().all()

    patients = [
        {
            "id": row["PATIENT_UNIQN"],
            "name": row["NAME"],
            "birthDate": row["BIRTH_DATE"].isoformat(),
            "phone": row["PHONE"],
            "address": row["ADDRESS"],
            "guardianName": row["GUARDIAN_NAME"] or "",
            "guardianRelation": row["GUARDIAN_RELATION"] or "",
            "guardianPhone": row["GUARDIAN_PHONE"] or ""
        }
        for row in rows
    ]

    return {"patients": patients}

@app.patch("/api/patients/{patient_id}")
def update_patient(
    patient_id: int,
    patient: PatientCreate,
    account=Depends(require_authenticated_user)
):
    if not all([
        patient.name.strip(),
        patient.birthDate.strip(),
        patient.phone.strip(),
        patient.address.strip()
    ]):
        raise HTTPException(
            status_code=400,
            detail="필수 환자 정보를 모두 입력해 주세요."
        )

    try:
        birth_date = datetime.strptime(
            patient.birthDate, "%Y-%m-%d"
        ).date()
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="생년월일 형식이 올바르지 않습니다."
        )

    with engine.begin() as connection:
        updated = connection.execute(
            text("""
                UPDATE "PATIENT"
                SET
                    "NAME" = :name,
                    "BIRTH_DATE" = :birth_date,
                    "PHONE" = :phone,
                    "ADDRESS" = :address,
                    "GUARDIAN_NAME" = :guardian_name,
                    "GUARDIAN_RELATION" = :guardian_relation,
                    "GUARDIAN_PHONE" = :guardian_phone
                WHERE "PATIENT_UNIQN" = :patient_id
                    AND "CLINIC_UNIQN" = :clinic_id
                RETURNING "PATIENT_UNIQN"
            """),
            {
                "patient_id": patient_id,
                "clinic_id": account["CLINIC_UNIQN"],
                "name": patient.name.strip(),
                "birth_date": birth_date,
                "phone": patient.phone.strip(),
                "address": patient.address.strip(),
                "guardian_name": patient.guardianName.strip() or None,
                "guardian_relation": patient.guardianRelation.strip() or None,
                "guardian_phone": patient.guardianPhone.strip() or None
            }
        ).scalar_one_or_none()

    if updated is None:
        raise HTTPException(
            status_code=404,
            detail="수정할 환자를 찾을 수 없습니다."
        )

    return {
        "message": "환자 정보가 수정되었습니다.",
        "patient": {
            "id": patient_id,
            **patient.model_dump()
        }
    }

class VisitCreate(BaseModel):
    patientId: int = Field(gt=0, le=2**63 - 1)

    model_config = {"extra": "forbid", "strict": True}


@app.post("/api/visits", status_code=201)
def create_visit(
    request: VisitCreate,
    account=Depends(require_authenticated_user)
):
    if account["ROLE_CD"] != "DESK":
        raise HTTPException(403, "안내데스크 권한이 필요합니다.")

    with engine.begin() as connection:
        require_clinic_references(connection, account, patient=request.patientId)
        patient = connection.execute(
            text("""
                SELECT "PATIENT_UNIQN", "NAME", "BIRTH_DATE"
                FROM "PATIENT"
                WHERE "PATIENT_UNIQN" = :patient_id
                  AND "CLINIC_UNIQN" = :clinic_id
                FOR UPDATE
            """),
            {
                "patient_id": request.patientId,
                "clinic_id": account["CLINIC_UNIQN"]
            }
        ).mappings().first()

        if patient is None:
            raise HTTPException(
                status_code=404,
                detail="등록되지 않은 환자입니다."
            )

        existing_visit = connection.execute(
            text("""
                SELECT "VISIT_UNIQN"
                FROM "VISIT"
                WHERE "PATIENT_UNIQN" = :patient_id
                  AND "STATUS_CD" IN (
                      'REGISTERED', 'WAITING', 'IN_PROGRESS'
                  )
                LIMIT 1
            """),
            {"patient_id": request.patientId}
        ).scalar_one_or_none()

        if existing_visit is not None:
            raise HTTPException(
                status_code=409,
                detail="이미 접수되었거나 진료 중인 환자입니다."
            )

        visit = connection.execute(
            text("""
                INSERT INTO "VISIT" (
                    "PATIENT_UNIQN",
                    "REGISTERED_BY",
                    "STATUS_CD"
                )
                VALUES (
                    :patient_id,
                    :registered_by,
                    'REGISTERED'
                )
                RETURNING "VISIT_UNIQN", "REGISTERED_AT"
            """),
            {
                "patient_id": request.patientId,
                "registered_by": account["ACCOUNT_UNIQN"]
            }
        ).mappings().one()
        visit_id = visit["VISIT_UNIQN"]
        connection.execute(
            text("""
                INSERT INTO "VISIT_STATUS_HISTORY" (
                    "VISIT_UNIQN",
                    "BEFORE_STATUS",
                    "AFTER_STATUS",
                    "CHANGED_BY",
                    "REASON"
                )
                VALUES (
                    :visit_id,
                    NULL,
                    'REGISTERED',
                    :account_id,
                    NULL
                )
            """),
            {
                "visit_id": visit_id,
                "account_id": account["ACCOUNT_UNIQN"]
            }
        )

    return {
        "record": {
            "id": visit_id, "patientId": patient["PATIENT_UNIQN"], "patientName": patient["NAME"],
            "birthDate": patient["BIRTH_DATE"].isoformat() if patient["BIRTH_DATE"] else "",
            "status": "REGISTERED", "registeredAt": visit["REGISTERED_AT"].isoformat(),
            "waitingAt": None, "startedAt": None, "completedAt": None,
            "doctorId": None, "doctorName": None, "caseId": None,
        },
        "message": "환자 접수가 완료되었습니다.",
        "visitId": visit_id,
        "patientId": request.patientId,
        "status": "REGISTERED"
    }

class WaitingPatient(BaseModel):
    id: int
    name: str
    birthDate: str
    phone: str
    address: str


from datetime import date


@app.get("/api/visits")
def get_visits(
    scope: str = "all",
    account=Depends(require_authenticated_user)
):
    if account["ROLE_CD"] not in ("DOCTOR", "DESK"):
        raise HTTPException(403, "접수 현황을 조회할 권한이 없습니다.")

    if scope not in ("all", "waiting"):
        raise HTTPException(
            status_code=400,
            detail="scope는 all 또는 waiting이어야 합니다."
        )

    with engine.connect() as connection:
        rows = connection.execute(
            text("""
                SELECT
                    v."VISIT_UNIQN",
                    v."PATIENT_UNIQN",
                    v."DOCTOR_UNIQN",
                    v."STATUS_CD",
                    v."REGISTERED_AT",
                    v."WAITING_AT",
                    v."STARTED_AT",
                    v."COMPLETED_AT",
                    p."NAME", p."BIRTH_DATE", p."PHONE", p."ADDRESS", a."NAME" AS doctor_name,
                    c."CASE_UNIQN" AS case_id
                FROM "VISIT" v
                JOIN "PATIENT" p
                    ON v."PATIENT_UNIQN" = p."PATIENT_UNIQN"
                LEFT JOIN "ACCOUNT" a ON a."ACCOUNT_UNIQN" = v."DOCTOR_UNIQN"
                LEFT JOIN LATERAL (
                    SELECT "CASE_UNIQN" FROM "CASE_RECORD"
                    WHERE "VISIT_UNIQN" = v."VISIT_UNIQN"
                      AND "AUTHOR_UNIQN" = v."DOCTOR_UNIQN"
                    ORDER BY "CASE_UNIQN" DESC LIMIT 1
                ) c ON TRUE
                WHERE p."CLINIC_UNIQN" = :clinic_id
                  AND (v."REGISTERED_AT" AT TIME ZONE 'Asia/Seoul')::date =
                      (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Seoul')::date
                  AND (
                      :scope = 'all'
                      OR v."STATUS_CD" = 'WAITING'
                  )
                ORDER BY
                    CASE WHEN :scope = 'waiting'
                        THEN v."WAITING_AT"
                    END,
                    v."REGISTERED_AT",
                    v."VISIT_UNIQN"
            """),
            {
                "clinic_id": account["CLINIC_UNIQN"],
                "scope": scope
            }
        ).mappings().all()

    records = [
        {
            "id": row["VISIT_UNIQN"],
            "visitId": row["VISIT_UNIQN"],
            "patientId": row["PATIENT_UNIQN"],
            "patientName": row["NAME"],
            "birthDate": row["BIRTH_DATE"].isoformat() if row["BIRTH_DATE"] else "",
            "phone": row["PHONE"] or "",
            "address": row["ADDRESS"] or "",
            "doctorName": row["doctor_name"],
            "caseId": row["case_id"],
            "doctorId": row["DOCTOR_UNIQN"],
            "status": row["STATUS_CD"],
            "registeredAt": row["REGISTERED_AT"].isoformat(),
            "waitingAt": (
                row["WAITING_AT"].isoformat()
                if row["WAITING_AT"] else None
            ),
            "startedAt": (
                row["STARTED_AT"].isoformat()
                if row["STARTED_AT"] else None
            ),
            "completedAt": (
                row["COMPLETED_AT"].isoformat()
                if row["COMPLETED_AT"] else None
            )
        }
        for row in rows
    ]

    return {
        "records": records,
        "total": len(records),
        "message": (
            "당일 접수 내역이 없습니다"
            if not records else None
        )
    }

@app.get("/api/waiting")
def get_waiting_patients(
    account=Depends(require_authenticated_user)
):
    with engine.connect() as connection:
        rows = connection.execute(
            text("""
                SELECT
                    v."VISIT_UNIQN",
                    v."PATIENT_UNIQN",
                    v."STATUS_CD",
                    p."NAME",
                    p."BIRTH_DATE",
                    p."PHONE",
                    p."ADDRESS"
                FROM "VISIT" v
                JOIN "PATIENT" p
                    ON v."PATIENT_UNIQN" = p."PATIENT_UNIQN"
                WHERE p."CLINIC_UNIQN" = :clinic_id
                  AND v."STATUS_CD" IN (
                      'WAITING',
                      'IN_PROGRESS',
                      'COMPLETED'
                  )
                ORDER BY v."REGISTERED_AT", v."VISIT_UNIQN"
                """),
                {"clinic_id": account["CLINIC_UNIQN"]}
                ).mappings().all()

    status_map = {
        "WAITING": "대기",
        "IN_PROGRESS": "진료 중",
        "COMPLETED": "완료"
    }

    patients = [
        {
            "id": row["PATIENT_UNIQN"],
            "visitId": row["VISIT_UNIQN"],
            "name": row["NAME"],
            "birthDate": row["BIRTH_DATE"].isoformat(),
            "phone": row["PHONE"],
            "address": row["ADDRESS"],
            "status": status_map[row["STATUS_CD"]]
        }
        for row in rows
    ]

    return {"patients": patients}



def require_clinical_user(request: Request):
    account = require_authenticated_user(request)

    if account["ROLE_CD"] != "DOCTOR":
        raise HTTPException(
            status_code=403,
            detail="진료·상담 권한이 없습니다."
        )

    return account


@app.post("/api/waiting")
def register_waiting_patient(
    patient: WaitingPatient,
    account=Depends(require_authenticated_user)
):
    with engine.begin() as connection:
        existing_patient = connection.execute(
            text("""
                SELECT "PATIENT_UNIQN"
                FROM "PATIENT"
                WHERE "PATIENT_UNIQN" = :patient_id
                  AND "CLINIC_UNIQN" = :clinic_id
            """),
            {
                "patient_id": patient.id,
                "clinic_id": account["CLINIC_UNIQN"]
            }
        ).scalar_one_or_none()

        if existing_patient is None:
            raise HTTPException(
                status_code=404,
                detail="등록되지 않은 환자입니다."
            )

        existing_visit = connection.execute(
            text("""
                SELECT "VISIT_UNIQN"
                FROM "VISIT"
                WHERE "PATIENT_UNIQN" = :patient_id
                  AND "STATUS_CD" IN ('REGISTERED', 'WAITING', 'IN_PROGRESS')
                LIMIT 1
            """),
            {"patient_id": patient.id}
        ).scalar_one_or_none()

        if existing_visit is not None:
            raise HTTPException(
                status_code=409,
                detail="이미 상담 대기 또는 진료 중인 환자입니다."
            )

        visit_id = connection.execute(
            text("""
                INSERT INTO "VISIT" (
                    "PATIENT_UNIQN",
                    "REGISTERED_BY",
                    "STATUS_CD",
                    "WAITING_AT"
                )
                VALUES (
                    :patient_id,
                    :registered_by,
                    'WAITING',
                    CURRENT_TIMESTAMP
                )
                RETURNING "VISIT_UNIQN"
            """),
            {
                "patient_id": patient.id,
                "registered_by": account["ACCOUNT_UNIQN"]
            }
        ).scalar_one()

    new_patient = {
        **patient.model_dump(),
        "visitId": visit_id,
        "status": "대기"
    }


    return {
        "message": "상담 대기 등록이 완료되었습니다.",
        "patient": new_patient
    }



class WaitingStatusUpdate(BaseModel):
    status: str
    doctor: str | None = None

class VisitStatusUpdate(BaseModel):
    model_config = {"extra": "forbid", "strict": True}

    action: str
    reason: str | None
    consultation: dict | None


@app.patch("/api/visits/{visit_id}/status")
def update_visit_status(
    visit_id: int,
    request: VisitStatusUpdate,
    account=Depends(require_authenticated_user)
):
    action = request.action
    account_id = account["ACCOUNT_UNIQN"]
    role = account["ROLE_CD"]

    if action not in (
            "REGISTER_WAITING",
            "START",
            "CANCEL",
            "PAUSE",
            "RESUME",
            "CORRECT_START"
    ):
        raise HTTPException(
            status_code=400,
            detail="아직 구현되지 않은 상태 변경 동작입니다."
        )

    if action != "PAUSE" and request.consultation is not None:
        raise HTTPException(
            status_code=400,
            detail="이 동작에서는 consultation이 null이어야 합니다."
        )

    if action in ("REGISTER_WAITING", "CANCEL") and role != "DESK":
        raise HTTPException(
            status_code=403,
            detail="안내데스크 권한이 필요합니다."
        )

    if action in ("START", "PAUSE", "RESUME", "CORRECT_START") and role != "DOCTOR":
        raise HTTPException(
            status_code=403,
            detail="한의사 권한이 필요합니다."
        )

    if action == "CANCEL" and not (request.reason or "").strip():
        raise HTTPException(
            status_code=400,
            detail="접수 취소 사유를 입력해야 합니다."
        )

    with engine.begin() as connection:
        require_clinic_references(connection, account, visit=visit_id)
        visit = connection.execute(
            text("""
                SELECT v.*
                FROM "VISIT" v
                JOIN "PATIENT" p
                  ON p."PATIENT_UNIQN" = v."PATIENT_UNIQN"
                WHERE v."VISIT_UNIQN" = :visit_id
                  AND p."CLINIC_UNIQN" = :clinic_id
                FOR UPDATE OF v
            """),
            {
                "visit_id": visit_id,
                "clinic_id": account["CLINIC_UNIQN"]
            }
        ).mappings().first()

        if visit is None:
            raise HTTPException(
                status_code=404,
                detail="방문 기록을 찾을 수 없습니다."
            )

        before_status = visit["STATUS_CD"]

        if action in ("PAUSE", "RESUME", "CORRECT_START"):
            if visit["DOCTOR_UNIQN"] != account_id:
                raise HTTPException(
                    status_code=403,
                    detail="해당 상담의 담당 한의사만 처리할 수 있습니다."
                )

        if action == "REGISTER_WAITING":
            if before_status == "WAITING":
                pass
            elif before_status == "REGISTERED":
                connection.execute(
                    text("""
                        UPDATE "VISIT"
                        SET "STATUS_CD" = 'WAITING',
                            "WAITING_AT" = CURRENT_TIMESTAMP
                        WHERE "VISIT_UNIQN" = :visit_id
                    """),
                    {"visit_id": visit_id}
                )
            else:
                raise HTTPException(
                    status_code=409,
                    detail="대기 등록이 가능한 상태가 아닙니다."
                )

        elif action == "START":
            if before_status != "WAITING":
                raise HTTPException(
                    status_code=409,
                    detail="대기 상태에서만 상담을 시작할 수 있습니다."
                )

            connection.execute(
                text("""
                    UPDATE "VISIT"
                    SET "STATUS_CD" = 'IN_PROGRESS',
                        "DOCTOR_UNIQN" = :account_id,
                        "STARTED_AT" = CURRENT_TIMESTAMP
                    WHERE "VISIT_UNIQN" = :visit_id
                """),
                {
                    "visit_id": visit_id,
                    "account_id": account_id
                }
            )

            existing_case = connection.execute(
                text("""
                    SELECT "CASE_UNIQN"
                    FROM "CASE_RECORD"
                    WHERE "VISIT_UNIQN" = :visit_id
                      AND "AUTHOR_UNIQN" = :account_id
                      AND NULLIF(BTRIM(COALESCE("SYMPTOM_TEXT", '')), '') IS NULL
                      AND NULLIF(BTRIM(COALESCE("CONSULTATION_TEXT", '')), '') IS NULL
                      AND NULLIF(BTRIM(COALESCE("SPECIAL_NOTE", '')), '') IS NULL
                      AND NULLIF(BTRIM(COALESCE("MANUAL_DISEASE_TEXT", '')), '') IS NULL
                      AND "DISEASE_SEARCH_UNIQN" IS NULL
                      AND "SELECTED_DIS_UNIQN" IS NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM "SEARCH_LOG" sl
                          WHERE sl."CASE_UNIQN" = "CASE_RECORD"."CASE_UNIQN"
                      )
                      AND NOT EXISTS (
                          SELECT 1 FROM "PATIENT_PRESP" rx
                          WHERE rx."CASE_UNIQN" = "CASE_RECORD"."CASE_UNIQN"
                      )
                    ORDER BY "CASE_UNIQN" DESC
                    LIMIT 1
                """),
                {
                    "visit_id": visit_id,
                    "account_id": account_id
                }
            ).scalar_one_or_none()

            if existing_case is None:
                existing_case = connection.execute(
                    text("""
                        INSERT INTO "CASE_RECORD" (
                            "VISIT_UNIQN",
                            "AUTHOR_UNIQN"
                        )
                        VALUES (
                            :visit_id,
                            :account_id
                        )
                        RETURNING "CASE_UNIQN"
                    """),
                    {
                        "visit_id": visit_id,
                        "account_id": account_id
                    }
                ).scalar_one()

            # START 응답은 이번 트랜잭션에서 재사용/생성한 정확한 상담 ID를 반환한다.
            # 이전에 작성된 다른 상담기록의 최신 ID를 임의로 선택하지 않는다.
            started_case_id = existing_case

        elif action == "CANCEL":
            if before_status not in ("REGISTERED", "WAITING"):
                raise HTTPException(
                    status_code=409,
                    detail="접수를 취소할 수 없는 상태입니다."
                )

            connection.execute(
                text("""
                    UPDATE "VISIT"
                    SET "STATUS_CD" = 'CANCELLED'
                    WHERE "VISIT_UNIQN" = :visit_id
                """),
                {"visit_id": visit_id}
            )
        elif action == "PAUSE":
            if before_status != "IN_PROGRESS":
                raise HTTPException(status_code=409, detail="진료 중인 상담만 중단할 수 있습니다.")
            if not (request.reason or "").strip():
                raise HTTPException(status_code=400, detail="중단 사유가 필요합니다.")
            if request.consultation is None:
                raise HTTPException(400, "중단할 상담 내용을 함께 보내주세요.")
            try:
                draft = ConsultationWrite.model_validate(request.consultation)
            except ValidationError as error:
                raise HTTPException(400, "중단 상담 내용의 형식이 올바르지 않습니다.") from error
            validate_consultation_write(draft)
            if draft.operation != "SAVE":
                raise HTTPException(400, "진료 중단 시 상담 동작은 SAVE여야 합니다.")
            case_id = connection.execute(text("""
                SELECT "CASE_UNIQN" FROM "CASE_RECORD"
                WHERE "VISIT_UNIQN" = :visit_id AND "AUTHOR_UNIQN" = :account_id
                ORDER BY "CASE_UNIQN" DESC LIMIT 1 FOR UPDATE
            """), {"visit_id": visit_id, "account_id": account_id}).scalar_one_or_none()
            if case_id is None:
                raise HTTPException(409, "중단할 상담기록을 찾을 수 없습니다.")
            search_id = validate_disease_search(
                connection, case_id, draft.symptoms.strip(), draft.diseaseSearchId, draft.selectedDiseaseId,
            )
            connection.execute(text("""
                UPDATE "CASE_RECORD"
                SET "SYMPTOM_TEXT" = :symptoms, "CONSULTATION_TEXT" = :consultation,
                    "SPECIAL_NOTE" = :notes, "MANUAL_DISEASE_TEXT" = :manual,
                    "DISEASE_SEARCH_UNIQN" = :search_id, "SELECTED_DIS_UNIQN" = :disease_id,
                    "UPDATED_AT" = CURRENT_TIMESTAMP
                WHERE "CASE_UNIQN" = :case_id
            """), {"case_id": case_id, "symptoms": draft.symptoms, "consultation": draft.consultationText,
                   "notes": draft.additionalNotes, "manual": draft.manualDiseaseText,
                   "search_id": search_id, "disease_id": draft.selectedDiseaseId})
            connection.execute(
                text("""UPDATE "VISIT" SET "STATUS_CD" = 'INTERRUPTED' WHERE "VISIT_UNIQN" = :visit_id"""),
                {"visit_id": visit_id}
            )

        elif action == "RESUME":
            if before_status != "INTERRUPTED":
                raise HTTPException(
                    status_code=409,
                    detail="중단된 상담만 재개할 수 있습니다."
                )

            if not (request.reason or "").strip():
                raise HTTPException(
                    status_code=400,
                    detail="재개 사유가 필요합니다."
                )

            if visit["STARTED_AT"] is None:
                raise HTTPException(
                    status_code=409,
                    detail="상담 시작 기록이 없습니다."
                )

            same_day = connection.execute(
                text("""
                        SELECT (
                            CAST(:started_at AS timestamptz)
                            AT TIME ZONE 'Asia/Seoul'
                        )::date = (
                            CURRENT_TIMESTAMP
                            AT TIME ZONE 'Asia/Seoul'
                        )::date
                    """),
                {"started_at": visit["STARTED_AT"]}
            ).scalar_one()

            if not same_day:
                raise HTTPException(
                    status_code=409,
                    detail="당일 중단된 상담만 재개할 수 있습니다."
                )

            connection.execute(
                text("""
                        UPDATE "VISIT"
                        SET "STATUS_CD" = 'IN_PROGRESS'
                        WHERE "VISIT_UNIQN" = :visit_id
                    """),
                {"visit_id": visit_id}
            )

        elif action == "CORRECT_START":
            if before_status != "IN_PROGRESS":
                raise HTTPException(
                    status_code=409,
                    detail="진료 중인 방문만 시작 정정이 가능합니다."
                )

            if not (request.reason or "").strip():
                raise HTTPException(
                    status_code=400,
                    detail="오시작 정정 사유가 필요합니다."
                )

            cases = connection.execute(
                text("""
                        SELECT
                            "CASE_UNIQN",
                            "SYMPTOM_TEXT",
                            "CONSULTATION_TEXT",
                            "SPECIAL_NOTE",
                            "MANUAL_DISEASE_TEXT",
                            "DISEASE_SEARCH_UNIQN",
                            "SELECTED_DIS_UNIQN"
                        FROM "CASE_RECORD"
                        WHERE "VISIT_UNIQN" = :visit_id
                    """),
                {"visit_id": visit_id}
            ).mappings().all()

            for case in cases:
                if any(
                        (case[field] or "").strip()
                        for field in (
                                "SYMPTOM_TEXT",
                                "CONSULTATION_TEXT",
                                "SPECIAL_NOTE",
                                "MANUAL_DISEASE_TEXT"
                        )
                ) or case["DISEASE_SEARCH_UNIQN"] is not None or case["SELECTED_DIS_UNIQN"] is not None:
                    raise HTTPException(
                        status_code=409,
                        detail="상담 내용이 저장되어 시작을 정정할 수 없습니다."
                    )

            search_count = connection.execute(
                text("""
                    SELECT COUNT(*)
                    FROM "SEARCH_LOG" sl
                    JOIN "CASE_RECORD" c ON c."CASE_UNIQN" = sl."CASE_UNIQN"
                    WHERE c."VISIT_UNIQN" = :visit_id
                """),
                {"visit_id": visit_id}
            ).scalar_one()
            if search_count > 0:
                raise HTTPException(
                    status_code=409,
                    detail="AI 검색 기록이 있어 시작을 정정할 수 없습니다."
                )

            prescription_count = connection.execute(
                text("""
                        SELECT COUNT(*)
                        FROM "PATIENT_PRESP" rx
                        JOIN "CASE_RECORD" c
                          ON c."CASE_UNIQN" = rx."CASE_UNIQN"
                        WHERE c."VISIT_UNIQN" = :visit_id
                    """),
                {"visit_id": visit_id}
            ).scalar_one()

            if prescription_count > 0:
                raise HTTPException(
                    status_code=409,
                    detail="처방 기록이 있어 시작을 정정할 수 없습니다."
                )

            connection.execute(
                text("""
                        UPDATE "VISIT"
                        SET "STATUS_CD" = 'WAITING',
                            "DOCTOR_UNIQN" = NULL,
                            "STARTED_AT" = NULL
                        WHERE "VISIT_UNIQN" = :visit_id
                    """),
                {"visit_id": visit_id}
            )

        if not (action == "REGISTER_WAITING" and before_status == "WAITING"):
            after_status = {
                "REGISTER_WAITING": "WAITING",
                "START": "IN_PROGRESS",
                "CANCEL": "CANCELLED",
                "PAUSE": "INTERRUPTED",
                "RESUME": "IN_PROGRESS",
                "CORRECT_START": "WAITING"
            }[action]

            connection.execute(
                text("""
                    INSERT INTO "VISIT_STATUS_HISTORY" (
                        "VISIT_UNIQN",
                        "BEFORE_STATUS",
                        "AFTER_STATUS",
                        "CHANGED_BY",
                        "REASON"
                    )
                    VALUES (
                        :visit_id,
                        :before_status,
                        :after_status,
                        :account_id,
                        :reason
                    )
                """),
                {
                    "visit_id": visit_id,
                    "before_status": before_status,
                    "after_status": after_status,
                    "account_id": account_id,
                    "reason": (
                        request.reason.strip()
                        if action in (
                            "CANCEL",
                            "PAUSE",
                            "RESUME",
                            "CORRECT_START"
                        ) else None
                    )
                    }
            )

        row = connection.execute(
            text("""
                SELECT
                    v."VISIT_UNIQN",
                    v."PATIENT_UNIQN",
                    v."STATUS_CD",
                    v."REGISTERED_AT",
                    v."WAITING_AT",
                    v."STARTED_AT",
                    v."COMPLETED_AT",
                    v."DOCTOR_UNIQN",
                    p."NAME" AS patient_name,
                    p."BIRTH_DATE" AS birth_date,
                    a."NAME" AS doctor_name,
                    c."CASE_UNIQN" AS case_id
                FROM "VISIT" v
                JOIN "PATIENT" p
                  ON p."PATIENT_UNIQN" = v."PATIENT_UNIQN"
                LEFT JOIN "ACCOUNT" a
                  ON a."ACCOUNT_UNIQN" = v."DOCTOR_UNIQN"
                LEFT JOIN LATERAL (
                    SELECT "CASE_UNIQN"
                    FROM "CASE_RECORD"
                    WHERE "VISIT_UNIQN" = v."VISIT_UNIQN"
                      AND "AUTHOR_UNIQN" = v."DOCTOR_UNIQN"
                    ORDER BY "CASE_UNIQN" DESC
                    LIMIT 1
                ) c ON TRUE
                WHERE v."VISIT_UNIQN" = :visit_id
            """),
            {"visit_id": visit_id}
        ).mappings().one()

    def format_time(value):
        return value.isoformat() if value is not None else None

    return {
        "record": {
            "id": row["VISIT_UNIQN"],
            "patientId": row["PATIENT_UNIQN"],
            "patientName": row["patient_name"],
            "birthDate": row["birth_date"].isoformat(),
            "status": row["STATUS_CD"],
            "registeredAt": format_time(row["REGISTERED_AT"]),
            "waitingAt": format_time(row["WAITING_AT"]),
            "startedAt": format_time(row["STARTED_AT"]),
            "completedAt": format_time(row["COMPLETED_AT"]),
            "doctorId": row["DOCTOR_UNIQN"],
            "doctorName": row["doctor_name"],
            "caseId": started_case_id if action == "START" else row["case_id"]
        }
    }

@app.patch("/api/waiting/{patient_id}")
def update_waiting_status(patient_id: int, request: WaitingStatusUpdate,
                          account=Depends(require_clinical_user)):
    if request.status not in ("진료 중", "대기"):
        raise HTTPException(status_code=400, detail="올바르지 않은 상태입니다.")
    # Older clients must not bypass saved consultation/search/prescription guards.
    # Reverting a start requires the explicit, reasoned CORRECT_START workflow.
    if request.status == "대기":
        raise HTTPException(409, "상담 중단 또는 시작 정정은 방문 상태 변경 기능에서 사유와 함께 처리해주세요.")
    with engine.connect() as connection:
        visit = connection.execute(text('''
            SELECT v."VISIT_UNIQN" FROM "VISIT" v
            JOIN "PATIENT" p ON p."PATIENT_UNIQN" = v."PATIENT_UNIQN"
            WHERE v."PATIENT_UNIQN" = :patient_id
              AND p."CLINIC_UNIQN" = :clinic_id AND v."STATUS_CD" = 'WAITING'
            ORDER BY v."VISIT_UNIQN" DESC LIMIT 1
        '''), {"patient_id": patient_id, "clinic_id": account["CLINIC_UNIQN"],
                }).mappings().first()
        if visit is None:
            raise HTTPException(status_code=409, detail="현재 상태에서는 변경할 수 없습니다.")
    result = update_visit_status(visit["VISIT_UNIQN"],
                                VisitStatusUpdate(action="START", reason=None, consultation=None), account)
    return {"message": "환자 상태가 변경되었습니다.", "patient": {
        "id": patient_id, "visitId": visit["VISIT_UNIQN"], "status": request.status,
        "doctor": result["record"]["doctorName"], "caseId": result["record"]["caseId"]}}


@app.delete("/api/waiting/{patient_id}")
def cancel_waiting_reception(
    patient_id: int,
    account=Depends(require_authenticated_user)
):
    if account["ROLE_CD"] != "DESK":
        raise HTTPException(
            status_code=403,
            detail="안내데스크만 접수를 취소할 수 있습니다."
        )

    with engine.begin() as connection:
        visit_id = connection.execute(
            text("""
                UPDATE "VISIT"
                SET "STATUS_CD" = 'CANCELLED'
                WHERE "VISIT_UNIQN" = (
                    SELECT v."VISIT_UNIQN"
                    FROM "VISIT" v
                    JOIN "PATIENT" p
                        ON v."PATIENT_UNIQN" = p."PATIENT_UNIQN"
                    WHERE v."PATIENT_UNIQN" = :patient_id
                      AND p."CLINIC_UNIQN" = :clinic_id
                      AND v."STATUS_CD" = 'WAITING'
                    ORDER BY v."VISIT_UNIQN" DESC
                    LIMIT 1
                )
                  AND "STATUS_CD" = 'WAITING'
                RETURNING "VISIT_UNIQN"
            """),
            {
                "patient_id": patient_id,
                "clinic_id": account["CLINIC_UNIQN"]
            }
        ).scalar_one_or_none()

    if visit_id is None:
        raise HTTPException(
            status_code=409,
            detail="대기 중인 환자만 접수를 취소할 수 있습니다."
        )

    return {
        "message": "접수가 취소되었습니다."
    }


from datetime import datetime
from uuid import uuid4


class ConsultationRecord(BaseModel):
    patientId: int
    symptoms: str
    selectedCandidates: list[str]
    additionalNotes: str = ""

from typing import Literal


class ConsultationWrite(BaseModel):
    model_config = {"extra": "forbid", "strict": True}

    operation: Literal["SAVE", "CORRECT"]
    symptoms: str
    consultationText: str
    additionalNotes: str | None
    diseaseSearchId: str | None
    selectedDiseaseId: int | None
    manualDiseaseText: str | None
    reason: str | None

def validate_consultation_write(data: ConsultationWrite):
    if (
        data.selectedDiseaseId is not None
        and data.manualDiseaseText is not None
    ):
        raise HTTPException(
            status_code=400,
            detail="기업 병증 선택과 직접 병명 입력은 동시에 사용할 수 없습니다."
        )

    if (
        (data.diseaseSearchId is None)
        != (data.selectedDiseaseId is None)
    ):
        raise HTTPException(
            status_code=400,
            detail="병증 검색 ID와 선택 병증 ID를 함께 입력해야 합니다."
        )

    if data.operation == "CORRECT" and not (data.reason or "").strip():
        raise HTTPException(
            status_code=400,
            detail="상담기록 정정 사유를 입력해야 합니다."
        )

def get_editable_consultation(connection, case_id: int, account: dict):
    record = connection.execute(
        text("""
            SELECT
                c."CASE_UNIQN",
                c."VISIT_UNIQN",
                c."AUTHOR_UNIQN",
                c."SYMPTOM_TEXT",
                c."CONSULTATION_TEXT",
                c."SPECIAL_NOTE",
                c."DISEASE_SEARCH_UNIQN",
                c."SELECTED_DIS_UNIQN",
                c."MANUAL_DISEASE_TEXT",
                v."PATIENT_UNIQN",
                v."DOCTOR_UNIQN",
                v."STATUS_CD",
                p."CLINIC_UNIQN"
            FROM "CASE_RECORD" c
            JOIN "VISIT" v
                ON v."VISIT_UNIQN" = c."VISIT_UNIQN"
            JOIN "PATIENT" p
                ON p."PATIENT_UNIQN" = v."PATIENT_UNIQN"
            WHERE c."CASE_UNIQN" = :case_id
            FOR UPDATE OF c, v
        """),
        {
            "case_id": case_id,
        }
    ).mappings().first()

    if record is None:
        raise HTTPException(
            status_code=404,
            detail="상담기록을 찾을 수 없습니다."
        )

    if record["CLINIC_UNIQN"] != account["CLINIC_UNIQN"]:
        raise HTTPException(403, "다른 한의원의 상담기록에 접근할 수 없습니다.")

    if record["AUTHOR_UNIQN"] != account["ACCOUNT_UNIQN"]:
        raise HTTPException(
            status_code=403,
            detail="본인이 작성한 상담기록만 수정할 수 있습니다."
        )

    return record

def validate_consultation_save_state(record, account):
    if record["STATUS_CD"] != "IN_PROGRESS":
        raise HTTPException(
            status_code=409,
            detail="진료 중인 상담기록만 저장할 수 있습니다."
        )

    if record["DOCTOR_UNIQN"] != account["ACCOUNT_UNIQN"]:
        raise HTTPException(
            status_code=403,
            detail="담당 한의사만 상담기록을 저장할 수 있습니다."
        )

app.include_router(create_ai_router(
    require_clinical_user, get_editable_consultation, validate_consultation_save_state,
))
app.include_router(create_catalog_router(require_clinical_user))


def validate_disease_search(
    connection,
    case_id: int,
    symptoms: str,
    disease_search_id: str | None,
    selected_disease_id: int | None
):
    if disease_search_id is None:
        return None

    if (not disease_search_id.isascii() or not disease_search_id.isdecimal()
            or len(disease_search_id) > 10 or not 0 < int(disease_search_id) <= 2**31 - 1):
        raise HTTPException(
            status_code=400,
            detail="병증 검색 ID 형식이 올바르지 않습니다."
        )
    search_id = int(disease_search_id)

    search = connection.execute(
        text("""
            SELECT
                "SEARCH_UNIQN",
                "CASE_UNIQN",
                "INPUT_TEXT",
                "SEARCH_STATUS",
                "SEARCH_METHOD"
            FROM "SEARCH_LOG"
            WHERE "SEARCH_UNIQN" = :search_id
        """),
        {
            "search_id": search_id,
        }
    ).mappings().first()

    if search is None:
        raise HTTPException(
            status_code=404,
            detail="해당 상담기록의 병증 검색 이력을 찾을 수 없습니다."
        )

    if (search["CASE_UNIQN"] != case_id or search["INPUT_TEXT"] != symptoms
            or search["SEARCH_STATUS"] != "COMPLETED" or search["SEARCH_METHOD"] == "PRESCRIPTION_COSINE"):
        raise HTTPException(
            status_code=409,
            detail="검색 당시 증상과 현재 증상이 일치하지 않습니다."
        )

    if selected_disease_id is not None:
        candidate = connection.execute(
            text("""
                SELECT r."RESULT_UNIQN"
                FROM "SEARCH_RESULT" r
                JOIN "ATT_DIS" d
                  ON d."DIS_UNIQN" = r."DIS_UNIQN"
                WHERE r."SEARCH_UNIQN" = :search_id
                  AND r."DIS_UNIQN" = :disease_id
            """),
            {
                "search_id": search_id,
                "disease_id": selected_disease_id
            }
        ).first()

        if candidate is None:
            raise HTTPException(
                status_code=400,
                detail={"code": "INVALID_SELECTED_DISEASE", "field": "selectedDiseaseId",
                        "message": "해당 검색 결과에 포함되지 않은 병증입니다."},
            )

    return search_id

@app.patch("/api/consultations/{case_id}")
def update_consultation(
    case_id: int,
    request: ConsultationWrite,
    account=Depends(require_clinical_user)
):
    validate_consultation_write(request)

    if request.operation == "SAVE":
        with engine.begin() as connection:
            record = get_editable_consultation(connection, case_id, account)
            validate_consultation_save_state(record, account)
            search_id = validate_disease_search(
                connection, case_id, request.symptoms.strip(),
                request.diseaseSearchId, request.selectedDiseaseId
            )
            connection.execute(
                text('''
                    UPDATE "CASE_RECORD"
                    SET "SYMPTOM_TEXT" = :symptoms,
                        "CONSULTATION_TEXT" = :consultation_text,
                        "SPECIAL_NOTE" = :additional_notes,
                        "MANUAL_DISEASE_TEXT" = :manual_disease,
                        "DISEASE_SEARCH_UNIQN" = :search_id,
                        "SELECTED_DIS_UNIQN" = :disease_id,
                        "UPDATED_AT" = CURRENT_TIMESTAMP
                    WHERE "CASE_UNIQN" = :case_id
                '''), {
                    "case_id": case_id,
                    "symptoms": request.symptoms,
                    "consultation_text": request.consultationText,
                    "additional_notes": request.additionalNotes,
                    "manual_disease": request.manualDiseaseText,
                    "search_id": search_id,
                    "disease_id": request.selectedDiseaseId
                }
            )
            return {"record": read_consultation_detail(connection, case_id, account)}

    if request.operation == "CORRECT":
        import json

        with engine.begin() as connection:
            record = get_editable_consultation(
                connection,
                case_id,
                account
            )

            # v1.3: 정정 시에도 원래 검색 실행과 후보의 연결을 검증한다.
            # 가장 최근 검색 ID만 허용하는 제한은 두지 않는다.
            search_id = validate_disease_search(
                connection, case_id, request.symptoms.strip(),
                request.diseaseSearchId, request.selectedDiseaseId
            )

            field_map = {
                "diseaseSearchId": ("DISEASE_SEARCH_UNIQN", search_id),
                "selectedDiseaseId": ("SELECTED_DIS_UNIQN", request.selectedDiseaseId),
                "symptoms": ("SYMPTOM_TEXT", request.symptoms),
                "consultationText": (
                    "CONSULTATION_TEXT",
                    request.consultationText
                ),
                "additionalNotes": (
                    "SPECIAL_NOTE",
                    request.additionalNotes
                ),
                "manualDiseaseText": (
                    "MANUAL_DISEASE_TEXT",
                    request.manualDiseaseText
                )
            }

            before_values = {}
            after_values = {}

            for field, (column, new_value) in field_map.items():
                old_value = record[column]

                if old_value != new_value:
                    before_values[field] = old_value
                    after_values[field] = new_value

            if not after_values:
                raise HTTPException(
                    status_code=409,
                    detail="변경된 상담 내용이 없습니다."
                )

            connection.execute(
                text("""
                    UPDATE "CASE_RECORD"
                    SET
                        "SYMPTOM_TEXT" = :symptoms,
                        "CONSULTATION_TEXT" = :consultation_text,
                        "SPECIAL_NOTE" = :additional_notes,
                        "MANUAL_DISEASE_TEXT" = :manual_disease,
                        "DISEASE_SEARCH_UNIQN" = :search_id,
                        "SELECTED_DIS_UNIQN" = :disease_id,
                        "UPDATED_AT" = CURRENT_TIMESTAMP
                    WHERE "CASE_UNIQN" = :case_id
                """),
                {
                    "case_id": case_id,
                    "symptoms": request.symptoms,
                    "consultation_text": request.consultationText,
                    "additional_notes": request.additionalNotes,
                    "manual_disease": request.manualDiseaseText,
                    "search_id": search_id,
                    "disease_id": request.selectedDiseaseId
                }
            )

            connection.execute(
                text("""
                    INSERT INTO "CASE_REVISION" (
                        "CASE_UNIQN",
                        "CHANGED_FIELDS",
                        "BEFORE_VALUES",
                        "AFTER_VALUES",
                        "CHANGED_BY",
                        "REASON"
                    )
                    VALUES (
                        :case_id,
                        CAST(:changed_fields AS jsonb),
                        CAST(:before_values AS jsonb),
                        CAST(:after_values AS jsonb),
                        :account_id,
                        :reason
                    )
                """),
                {
                    "case_id": case_id,
                    "changed_fields": json.dumps(
                        list(after_values.keys()),
                        ensure_ascii=False
                    ),
                    "before_values": json.dumps(
                        before_values,
                        ensure_ascii=False
                    ),
                    "after_values": json.dumps(
                        after_values,
                        ensure_ascii=False
                    ),
                    "account_id": account["ACCOUNT_UNIQN"],
                    "reason": request.reason.strip()
                }
            )

            return {"record": read_consultation_detail(connection, case_id, account)}

@app.post("/api/consultations/{case_id}/complete")
def complete_consultation(
    case_id: int,
    request: ConsultationWrite,
    account=Depends(require_clinical_user)
):
    validate_consultation_write(request)

    if request.operation != "SAVE":
        raise HTTPException(
            status_code=400,
            detail="상담 완료 시 operation은 SAVE여야 합니다."
        )

    if not request.symptoms.strip():
        raise HTTPException(
            status_code=400,
            detail="증상을 입력해야 상담을 완료할 수 있습니다."
        )

    if not request.consultationText.strip():
        raise HTTPException(
            status_code=400,
            detail="상담 내용을 입력해야 상담을 완료할 수 있습니다."
        )

    with engine.begin() as connection:
        record = get_editable_consultation(
            connection,
            case_id,
            account
        )

        validate_consultation_save_state(record, account)

        search_id = validate_disease_search(
            connection, case_id, request.symptoms.strip(),
            request.diseaseSearchId, request.selectedDiseaseId,
        )
        connection.execute(
            text("""
                UPDATE "CASE_RECORD"
                SET
                    "SYMPTOM_TEXT" = :symptoms,
                    "CONSULTATION_TEXT" = :consultation_text,
                    "SPECIAL_NOTE" = :additional_notes,
                    "MANUAL_DISEASE_TEXT" = :manual_disease,
                    "DISEASE_SEARCH_UNIQN" = :search_id,
                    "SELECTED_DIS_UNIQN" = :disease_id,
                    "UPDATED_AT" = CURRENT_TIMESTAMP
                WHERE "CASE_UNIQN" = :case_id
            """),
            {
                "case_id": case_id,
                "symptoms": request.symptoms,
                "consultation_text": request.consultationText,
                "additional_notes": request.additionalNotes,
                "manual_disease": request.manualDiseaseText,
                "search_id": search_id,
                "disease_id": request.selectedDiseaseId,
            }
        )

        connection.execute(
            text("""
                UPDATE "VISIT"
                SET
                    "STATUS_CD" = 'COMPLETED',
                    "COMPLETED_AT" = CURRENT_TIMESTAMP
                WHERE "VISIT_UNIQN" = :visit_id
                  AND "STATUS_CD" = 'IN_PROGRESS'
                  AND "DOCTOR_UNIQN" = :account_id
            """),
            {
                "visit_id": record["VISIT_UNIQN"],
                "account_id": account["ACCOUNT_UNIQN"]
            }
        )

        connection.execute(
            text("""
                INSERT INTO "VISIT_STATUS_HISTORY" (
                    "VISIT_UNIQN",
                    "BEFORE_STATUS",
                    "AFTER_STATUS",
                    "CHANGED_BY",
                    "REASON"
                )
                VALUES (
                    :visit_id,
                    'IN_PROGRESS',
                    'COMPLETED',
                    :account_id,
                    NULL
                )
            """),
            {
                "visit_id": record["VISIT_UNIQN"],
                "account_id": account["ACCOUNT_UNIQN"]
            }
        )

        return {"record": read_consultation_detail(connection, case_id, account)}

# v1.3: 상담 초안은 방문 START에서 생성하며 별도 POST 생성 API를 두지 않는다.

@app.get("/api/consultations/{case_id}/revisions")
def get_consultation_revisions(
    case_id: int,
    account=Depends(require_clinical_user)
):
    with engine.connect() as connection:
        require_clinic_references(connection, account, case=case_id)
        consultation = connection.execute(
            text("""
                SELECT c."CASE_UNIQN"
                FROM "CASE_RECORD" c
                JOIN "VISIT" v
                  ON v."VISIT_UNIQN" = c."VISIT_UNIQN"
                JOIN "PATIENT" p
                  ON p."PATIENT_UNIQN" = v."PATIENT_UNIQN"
                WHERE c."CASE_UNIQN" = :case_id
                  AND p."CLINIC_UNIQN" = :clinic_id
            """),
            {
                "case_id": case_id,
                "clinic_id": account["CLINIC_UNIQN"]
            }
        ).first()

        if consultation is None:
            raise HTTPException(
                status_code=404,
                detail="상담기록을 찾을 수 없습니다."
            )

        rows = connection.execute(
            text("""
                SELECT
                    r."REVISION_UNIQN",
                    r."CHANGED_FIELDS",
                    r."BEFORE_VALUES",
                    r."AFTER_VALUES",
                    r."CHANGED_BY",
                    r."CHANGED_AT",
                    r."REASON",
                    a."NAME" AS changed_by_name
                FROM "CASE_REVISION" r
                JOIN "ACCOUNT" a
                  ON a."ACCOUNT_UNIQN" = r."CHANGED_BY"
                WHERE r."CASE_UNIQN" = :case_id
                ORDER BY
                    r."CHANGED_AT" ASC,
                    r."REVISION_UNIQN" ASC
            """),
            {"case_id": case_id}
        ).mappings().all()

    records = [
        {
            "id": row["REVISION_UNIQN"],
            "changedBy": row["CHANGED_BY"],
            "changedByName": row["changed_by_name"],
            "changedAt": row["CHANGED_AT"].isoformat(),
            "changedFields": row["CHANGED_FIELDS"],
            "beforeValues": row["BEFORE_VALUES"],
            "afterValues": row["AFTER_VALUES"],
            "reason": row["REASON"]
        }
        for row in rows
    ]

    return {
        "records": records,
        "total": len(records)
    }


def consultation_time(value):
    return value.isoformat() if value is not None else None


def build_consultation_record(row, detail=False):
    record = {
        "id": row["CASE_UNIQN"],
        "visitId": row["VISIT_UNIQN"],
        "patientId": row["PATIENT_UNIQN"],
        "authorId": row["AUTHOR_UNIQN"],
        "patientName": row["patient_name"],
        "birthDate": str(row["birth_date"]),
        "authorName": row["author_name"],
        "registeredAt": consultation_time(row["REGISTERED_AT"]),
        "startedAt": consultation_time(row["STARTED_AT"]),
        "completedAt": consultation_time(row["COMPLETED_AT"]),
        "createdAt": consultation_time(row["CREATED_AT"]),
        "updatedAt": consultation_time(row["UPDATED_AT"]),
        "status": row["STATUS_CD"],
        "diagnosis": {
            "diseaseSearchId": (
                str(row["DISEASE_SEARCH_UNIQN"])
                if row["DISEASE_SEARCH_UNIQN"] is not None
                else None
            ),
            "selectedDiseaseId": row["SELECTED_DIS_UNIQN"],
            "selectedDiseaseName": row["selected_disease_name"],
            "manualDiseaseText": row["MANUAL_DISEASE_TEXT"]
        },
        "prescriptionNames": row["prescription_names"] or []
    }

    if detail:
        record.update({
            "symptoms": row["SYMPTOM_TEXT"] or "",
            "consultationText": row["CONSULTATION_TEXT"] or "",
            "additionalNotes": row["SPECIAL_NOTE"],
            "searchIds": [
                str(search_id)
                for search_id in (row["search_ids"] or [])
            ],
            "prescriptionIds": row["prescription_ids"] or []
        })

    return record


CONSULTATION_SELECT_SQL = """
    SELECT
        c.*,
        v."PATIENT_UNIQN",
        v."STATUS_CD",
        v."REGISTERED_AT",
        v."STARTED_AT",
        v."COMPLETED_AT",
        p."NAME" AS patient_name,
        p."BIRTH_DATE" AS birth_date,
        a."NAME" AS author_name,
        d."ATT_DIS_NM" AS selected_disease_name,

        COALESCE(rx_data.prescription_ids, ARRAY[]::bigint[])
            AS prescription_ids,
        COALESCE(rx_data.prescription_names, ARRAY[]::text[])
            AS prescription_names,
        COALESCE(search_data.search_ids, ARRAY[]::integer[])
            AS search_ids

    FROM "CASE_RECORD" c
    JOIN "VISIT" v
      ON v."VISIT_UNIQN" = c."VISIT_UNIQN"
    JOIN "PATIENT" p
      ON p."PATIENT_UNIQN" = v."PATIENT_UNIQN"
    JOIN "ACCOUNT" a
      ON a."ACCOUNT_UNIQN" = c."AUTHOR_UNIQN"
    LEFT JOIN "ATT_DIS" d
      ON d."DIS_UNIQN" = c."SELECTED_DIS_UNIQN"

    LEFT JOIN LATERAL (
        SELECT
            array_agg(rx."RX_UNIQN" ORDER BY rx."RX_UNIQN")
                AS prescription_ids,
            array_agg(
                latest."PRESP_NM"
                ORDER BY rx."RX_UNIQN"
            ) AS prescription_names
        FROM "PATIENT_PRESP" rx
        LEFT JOIN LATERAL (
            SELECT pv."PRESP_NM"
            FROM "PATIENT_PRESP_VERSION" pv
            WHERE pv."RX_UNIQN" = rx."RX_UNIQN"
            ORDER BY pv."VERSION_NO" DESC,
                     pv."RX_VERSION_UNIQN" DESC
            LIMIT 1
        ) latest ON TRUE
        WHERE rx."CASE_UNIQN" = c."CASE_UNIQN"
          AND rx."IS_DELETED" = FALSE
    ) rx_data ON TRUE

    LEFT JOIN LATERAL (
        SELECT array_agg(
            s."SEARCH_UNIQN"
            ORDER BY s."SEARCH_UNIQN"
        ) AS search_ids
        FROM "SEARCH_LOG" s
        WHERE s."CASE_UNIQN" = c."CASE_UNIQN"
    ) search_data ON TRUE

    WHERE p."CLINIC_UNIQN" = :clinic_id
"""


def read_consultation_detail(connection, case_id, account):
    row = connection.execute(
        text(CONSULTATION_SELECT_SQL + ' AND c."CASE_UNIQN" = :case_id'),
        {"case_id": case_id, "clinic_id": account["CLINIC_UNIQN"]},
    ).mappings().first()
    if row is None:
        if connection.execute(text("""
            SELECT 1 FROM "CASE_RECORD" WHERE "CASE_UNIQN" = :id
        """), {"id": case_id}).scalar_one_or_none() is not None:
            raise HTTPException(403, "다른 한의원의 상담기록에 접근할 수 없습니다.")
        raise HTTPException(404, "상담기록을 찾을 수 없습니다.")
    return build_consultation_record(row, detail=True)


CLINIC_REFERENCE_QUERIES = {
    "patient": 'SELECT "CLINIC_UNIQN" FROM "PATIENT" WHERE "PATIENT_UNIQN" = :id',
    "visit": """SELECT p."CLINIC_UNIQN" FROM "VISIT" v
        JOIN "PATIENT" p ON p."PATIENT_UNIQN" = v."PATIENT_UNIQN" WHERE v."VISIT_UNIQN" = :id""",
    "case": """SELECT p."CLINIC_UNIQN" FROM "CASE_RECORD" c
        JOIN "VISIT" v ON v."VISIT_UNIQN" = c."VISIT_UNIQN"
        JOIN "PATIENT" p ON p."PATIENT_UNIQN" = v."PATIENT_UNIQN" WHERE c."CASE_UNIQN" = :id""",
    "prescription": """SELECT p."CLINIC_UNIQN" FROM "PATIENT_PRESP" rx
        JOIN "CASE_RECORD" c ON c."CASE_UNIQN" = rx."CASE_UNIQN"
        JOIN "VISIT" v ON v."VISIT_UNIQN" = c."VISIT_UNIQN"
        JOIN "PATIENT" p ON p."PATIENT_UNIQN" = v."PATIENT_UNIQN"
        WHERE rx."RX_UNIQN" = :id AND rx."IS_DELETED" = FALSE""",
    "delivery": """SELECT p."CLINIC_UNIQN" FROM "PRESP_DELIVERY" d
        JOIN "PATIENT_PRESP_VERSION" vr ON vr."RX_VERSION_UNIQN" = d."RX_VERSION_UNIQN"
        JOIN "PATIENT_PRESP" rx ON rx."RX_UNIQN" = vr."RX_UNIQN"
        JOIN "CASE_RECORD" c ON c."CASE_UNIQN" = rx."CASE_UNIQN"
        JOIN "VISIT" v ON v."VISIT_UNIQN" = c."VISIT_UNIQN"
        JOIN "PATIENT" p ON p."PATIENT_UNIQN" = v."PATIENT_UNIQN"
        WHERE d."DELIVERY_UNIQN" = :id AND rx."IS_DELETED" = FALSE""",
}


def require_clinic_references(connection, account, **references):
    for kind, item_id in references.items():
        if item_id is None:
            continue
        if not 0 < item_id <= 2**63 - 1:
            raise HTTPException(400, "조회 또는 연결 식별번호가 올바르지 않습니다.")
        row = connection.execute(text(CLINIC_REFERENCE_QUERIES[kind]), {"id": item_id}).first()
        if row is not None and row[0] != account["CLINIC_UNIQN"]:
            raise HTTPException(403, "다른 한의원의 자료에 접근할 수 없습니다.")


@app.get("/api/consultations")
def get_consultations(
    patientId: int | None = Query(default=None),
    visitId: int | None = Query(default=None),
    account=Depends(require_clinical_user)
):
    sql = CONSULTATION_SELECT_SQL

    params = {
        "clinic_id": account["CLINIC_UNIQN"]
    }

    if patientId is not None:
        sql += ' AND v."PATIENT_UNIQN" = :patient_id'
        params["patient_id"] = patientId

    if visitId is not None:
        sql += ' AND v."VISIT_UNIQN" = :visit_id'
        params["visit_id"] = visitId

    sql += """
        ORDER BY
            v."REGISTERED_AT" DESC,
            c."CASE_UNIQN" DESC
    """

    with engine.connect() as connection:
        require_clinic_references(connection, account, patient=patientId, visit=visitId)
        rows = connection.execute(
            text(sql),
            params
        ).mappings().all()

    records = [
        build_consultation_record(row)
        for row in rows
    ]

    return {
        "records": records,
        "total": len(records)
    }


@app.get("/api/consultations/{case_id}")
def get_consultation_detail(
    case_id: int,
    account=Depends(require_clinical_user)
):
    with engine.connect() as connection:
        return {"record": read_consultation_detail(connection, case_id, account)}



class HerbItem(BaseModel):
    name: str
    amount: float


class PrescriptionRecord(BaseModel):
    patientId: int
    consultationId: str
    prescriptionName: str
    herbs: list[HerbItem]

class PrescriptionWrite(BaseModel):
    model_config = {"extra": "forbid", "strict": True}
    caseId: int
    diagnosisText: str | None
    prescriptionId: int | None
    prescriptionSearchId: str | None
    prescriptionName: str
    prescriptionText: str | None
    ingredients: list[Ingredient]

class PrescriptionCorrection(PrescriptionWrite):
    versionId: int
    reason: str

class PrescriptionSendRequest(BaseModel):
    model_config = {"extra": "forbid", "strict": True}
    versionId: int


@app.post("/api/prescriptions", status_code=201)
def save_prescription(
    request: PrescriptionWrite,
    account=Depends(require_clinical_user)
):
    prescription_name = request.prescriptionName.strip()

    if not prescription_name:
        raise HTTPException(
            status_code=400,
            detail="처방명을 입력해야 합니다."
        )

    if request.caseId <= 0:
        raise HTTPException(
            status_code=400,
            detail="상담기록 ID가 올바르지 않습니다."
        )

    with engine.begin() as connection:
        require_clinic_references(connection, account, case=request.caseId)
        consultation = connection.execute(
            text("""
                SELECT
                    c."CASE_UNIQN",
                    c."AUTHOR_UNIQN",
                    v."VISIT_UNIQN",
                    v."PATIENT_UNIQN",
                    v."REGISTERED_AT",
                    p."NAME" AS patient_name,
                    p."BIRTH_DATE" AS birth_date,
                    a."NAME" AS author_name
                FROM "CASE_RECORD" c
                JOIN "VISIT" v
                  ON v."VISIT_UNIQN" = c."VISIT_UNIQN"
                JOIN "PATIENT" p
                  ON p."PATIENT_UNIQN" = v."PATIENT_UNIQN"
                JOIN "ACCOUNT" a
                  ON a."ACCOUNT_UNIQN" = :author_id
                WHERE c."CASE_UNIQN" = :case_id
                  AND p."CLINIC_UNIQN" = :clinic_id
            """),
            {
                "case_id": request.caseId,
                "clinic_id": account["CLINIC_UNIQN"],
                "author_id": account["ACCOUNT_UNIQN"]
            }
        ).mappings().first()

        if consultation is None:
            raise HTTPException(
                status_code=404,
                detail="연결된 상담기록을 찾을 수 없습니다."
            )

        if consultation["AUTHOR_UNIQN"] != account["ACCOUNT_UNIQN"]:
            raise HTTPException(403, "본인이 작성한 상담의 처방만 저장할 수 있습니다.")
        ingredients = validate_prescription_source(connection, request, account["ACCOUNT_UNIQN"])

        rx_id = connection.execute(
            text("""
                INSERT INTO "PATIENT_PRESP" (
                    "CASE_UNIQN",
                    "AUTHOR_UNIQN"
                )
                VALUES (
                    :case_id,
                    :author_id
                )
                RETURNING "RX_UNIQN"
            """),
            {
                "case_id": request.caseId,
                "author_id": account["ACCOUNT_UNIQN"]
            }
        ).scalar_one()

        version = connection.execute(
            text("""
                INSERT INTO "PATIENT_PRESP_VERSION" (
                    "RX_UNIQN",
                    "VERSION_NO",
                    "DIAGNOSIS_TEXT",
                    "PRESP_NM",
                    "PRESP_CONT",
                    "SOURCE_PRESP_UNIQN",
                    "PRESCRIPTION_SEARCH_UNIQN",
                    "INGREDIENTS_JSON",
                    "SAVED_BY"
                )
                VALUES (
                    :rx_id,
                    1,
                    :diagnosis_text,
                    :prescription_name,
                    :prescription_text,
                    :source_id,
                    :search_id,
                    CAST(:ingredients AS jsonb),
                    :saved_by
                )
                RETURNING
                    "RX_VERSION_UNIQN",
                    "CREATED_AT"
            """),
            {
                "rx_id": rx_id,
                "diagnosis_text": request.diagnosisText,
                "prescription_name": prescription_name,
                "prescription_text": request.prescriptionText,
                "source_id": request.prescriptionId,
                "search_id": int(request.prescriptionSearchId) if request.prescriptionSearchId else None,
                "ingredients": json.dumps(
                    ingredients,
                    ensure_ascii=False
                ),
                "saved_by": account["ACCOUNT_UNIQN"]
            }
        ).mappings().one()

        mark_prescription_selected(connection, request)

    return {
        "record": {
            "rxId": rx_id,
            "versionId": version["RX_VERSION_UNIQN"],
            "versionNo": 1,
            "caseId": request.caseId,
            "visitId": consultation["VISIT_UNIQN"],
            "patientId": consultation["PATIENT_UNIQN"],
            "authorId": account["ACCOUNT_UNIQN"],
            "patientName": consultation["patient_name"],
            "birthDate": str(consultation["birth_date"]),
            "authorName": consultation["author_name"],
            "registeredAt": consultation["REGISTERED_AT"].isoformat(),
            "diagnosisText": request.diagnosisText,
            "prescriptionName": prescription_name,
            "prescriptionText": request.prescriptionText,
            "prescriptionId": request.prescriptionId,
            "prescriptionSearchId": request.prescriptionSearchId,
            "ingredients": ingredients,
            "savedBy": account["ACCOUNT_UNIQN"],
            "savedByName": consultation["author_name"],
            "savedAt": version["CREATED_AT"].isoformat(),
            "change": None
        }
    }




@app.get("/api/prescriptions")
def get_prescriptions(
    caseId: int | None = Query(default=None, gt=0),
    patientId: int | None = Query(default=None, gt=0),
    account=Depends(require_clinical_user)
):
    with engine.connect() as connection:
        require_clinic_references(connection, account, patient=patientId, case=caseId)
        rows = connection.execute(
            text("""
                SELECT
                    p."RX_UNIQN" AS rx_id,
                    p."CASE_UNIQN" AS case_id,
                    p."AUTHOR_UNIQN" AS author_id,
                    p."CREATED_AT" AS created_at,
                    visit."VISIT_UNIQN" AS visit_id,
                    visit."PATIENT_UNIQN" AS patient_id,
                    visit."REGISTERED_AT" AS registered_at,
                    patient."NAME" AS patient_name,
                    patient."BIRTH_DATE" AS birth_date,
                    author."NAME" AS author_name,
                    latest."RX_VERSION_UNIQN" AS version_id,
                    latest."VERSION_NO" AS version_no,
                    latest."DIAGNOSIS_TEXT" AS diagnosis_text,
                    latest."PRESP_NM" AS prescription_name,
                    latest."CREATED_AT" AS updated_at,
                    delivered."RX_VERSION_UNIQN" AS delivered_version_id,
                    delivered."SENT_AT" AS delivered_at
                FROM "PATIENT_PRESP" p
                JOIN "CASE_RECORD" c
                  ON c."CASE_UNIQN" = p."CASE_UNIQN"
                JOIN "VISIT" visit
                  ON visit."VISIT_UNIQN" = c."VISIT_UNIQN"
                JOIN "PATIENT" patient
                  ON patient."PATIENT_UNIQN" = visit."PATIENT_UNIQN"
                JOIN "ACCOUNT" author
                  ON author."ACCOUNT_UNIQN" = p."AUTHOR_UNIQN"
                JOIN LATERAL (
                    SELECT
                        rv."RX_VERSION_UNIQN",
                        rv."VERSION_NO",
                        rv."DIAGNOSIS_TEXT",
                        rv."PRESP_NM",
                        rv."CREATED_AT"
                    FROM "PATIENT_PRESP_VERSION" rv
                    WHERE rv."RX_UNIQN" = p."RX_UNIQN"
                    ORDER BY rv."VERSION_NO" DESC,
                             rv."RX_VERSION_UNIQN" DESC
                    LIMIT 1
                ) latest ON TRUE
                LEFT JOIN LATERAL (
                    SELECT
                        rv."RX_VERSION_UNIQN",
                        d."SENT_AT"
                    FROM "PRESP_DELIVERY" d
                    JOIN "PATIENT_PRESP_VERSION" rv
                      ON rv."RX_VERSION_UNIQN" = d."RX_VERSION_UNIQN"
                    WHERE rv."RX_UNIQN" = p."RX_UNIQN"
                    ORDER BY d."SENT_AT" DESC,
                             d."DELIVERY_UNIQN" DESC
                    LIMIT 1
                ) delivered ON TRUE
                WHERE patient."CLINIC_UNIQN" = :clinic_id
                  AND p."IS_DELETED" = FALSE
                  AND (
                      CAST(:case_id AS bigint) IS NULL
                      OR p."CASE_UNIQN" = :case_id
                  )
                  AND (
                      CAST(:patient_id AS bigint) IS NULL
                      OR visit."PATIENT_UNIQN" = :patient_id
                  )
                ORDER BY latest."CREATED_AT" DESC,
                         p."RX_UNIQN" DESC
            """),
            {
                "clinic_id": account["CLINIC_UNIQN"],
                "case_id": caseId,
                "patient_id": patientId
            }
        ).mappings().all()

    records = []

    for row in rows:
        records.append({
            "id": row["rx_id"],
            "caseId": row["case_id"],
            "visitId": row["visit_id"],
            "patientId": row["patient_id"],
            "authorId": row["author_id"],
            "patientName": row["patient_name"],
            "birthDate": str(row["birth_date"]),
            "authorName": row["author_name"],
            "registeredAt": row["registered_at"].isoformat(),
            "createdAt": row["created_at"].isoformat(),
            "updatedAt": row["updated_at"].isoformat(),
            "diagnosisText": row["diagnosis_text"],
            "prescriptionName": row["prescription_name"],
            "currentVersionId": row["version_id"],
            "currentVersionNo": row["version_no"],
            "lastDeliveredVersionId": row["delivered_version_id"],
            "lastDeliveredAt": (
                row["delivered_at"].isoformat()
                if row["delivered_at"] is not None
                else None
            )
        })

    return {
        "records": records,
        "total": len(records)
    }



# 기업 원본 처방명 검색
@app.get("/api/prescription-catalog/search")
def search_prescription_catalog(
    q: str = "",
    account=Depends(require_authenticated_user)
):
    keyword = q.strip()

    if not keyword:
        return {"results": []}

    with engine.connect() as connection:
        rows = connection.execute(
            text("""
                SELECT
                    "PRESP_UNIQN",
                    "PRESP_NM"
                FROM "PRESP"
                WHERE "PRESP_NM" ILIKE :keyword
                ORDER BY
                    CASE
                        WHEN "PRESP_NM" ILIKE :prefix THEN 0
                        ELSE 1
                    END,
                    "PRESP_NM",
                    "PRESP_UNIQN"
                LIMIT 50
            """),
            {
                "keyword": f"%{keyword}%",
                "prefix": f"{keyword}%"
            }
        ).mappings().all()

    return {
        "results": [
            {
                "id": row["PRESP_UNIQN"],
                "name": row["PRESP_NM"]
            }
            for row in rows
        ]
    }


# 기업 원본 처방 상세 조회

@app.get("/api/prescription-catalog/{presp_id}")
def get_prescription_catalog_detail(
    presp_id: int,
    account=Depends(require_authenticated_user)
):
    with engine.connect() as connection:
        row = connection.execute(
            text("""
                SELECT
                    "PRESP_UNIQN",
                    "ORIG_CD_NM",
                    "PRESP_NM",
                    "PRESP_CONT",
                    "DISP_USG_CONT",
                    "TABO_CONT"
                FROM "PRESP"
                WHERE "PRESP_UNIQN" = :presp_id
            """),
            {"presp_id": presp_id}
        ).mappings().first()

        if row is None:
            raise HTTPException(
                status_code=404,
                detail="처방 정보를 찾을 수 없습니다."
            )

        herb_rows = connection.execute(
            text("""
                SELECT
                    r."MED_UNIQN",
                    m."MED_NM",
                    r."MED_SPEC_REP",
                    r."UNT",
                    r."UNT_COEFF"
                FROM "PRESP_MED_RSHIP" AS r
                JOIN "MED" AS m
                    ON r."MED_UNIQN" = m."MED_UNIQN"
                WHERE r."PRESP_UNIQN" = :presp_id
                ORDER BY r."RSHIP_UNIQN"
            """),
            {"presp_id": presp_id}
        ).mappings().all()

    herbs = [
        {
            "id": herb["MED_UNIQN"],
            "name": herb["MED_NM"],
            "specification": herb["MED_SPEC_REP"] or "",
            "amount": (
                float(herb["UNT_COEFF"])
                if herb["UNT_COEFF"] is not None
                else None
            ),
            "unit": herb["UNT"] or ""
        }
        for herb in herb_rows
    ]

    return {
        "id": row["PRESP_UNIQN"],
        "originalCode": row["ORIG_CD_NM"],
        "name": row["PRESP_NM"],
        "description": row["PRESP_CONT"] or "",
        "usage": row["DISP_USG_CONT"] or "",
        "cautions": row["TABO_CONT"] or "",
        "herbs": herbs
    }




@app.patch("/api/prescriptions/{prescription_id}/send")
def send_prescription(
    prescription_id: int,
    request: PrescriptionSendRequest,
    account=Depends(require_clinical_user)
):
    account_id = account["ACCOUNT_UNIQN"]

    if prescription_id <= 0 or request.versionId <= 0:
        raise HTTPException(
            status_code=400,
            detail="처방전 또는 버전 ID가 올바르지 않습니다."
        )

    with engine.begin() as connection:
        require_clinic_references(connection, account, prescription=prescription_id)
        prescription = connection.execute(
            text("""
                SELECT
                    p."RX_UNIQN",
                    p."AUTHOR_UNIQN",
                    p."CASE_UNIQN",
                    c."VISIT_UNIQN",
                    visit."PATIENT_UNIQN",
                    visit."REGISTERED_AT",
                    patient."NAME" AS patient_name,
                    patient."BIRTH_DATE" AS birth_date,
                    author."NAME" AS author_name
                FROM "PATIENT_PRESP" p
                JOIN "CASE_RECORD" c
                  ON c."CASE_UNIQN" = p."CASE_UNIQN"
                JOIN "VISIT" visit
                  ON visit."VISIT_UNIQN" = c."VISIT_UNIQN"
                JOIN "PATIENT" patient
                  ON patient."PATIENT_UNIQN" = visit."PATIENT_UNIQN"
                JOIN "ACCOUNT" author
                  ON author."ACCOUNT_UNIQN" = p."AUTHOR_UNIQN"
                WHERE p."RX_UNIQN" = :rx_id
                  AND patient."CLINIC_UNIQN" = :clinic_id
                  AND p."IS_DELETED" = FALSE
                FOR UPDATE OF p
            """),
            {
                "rx_id": prescription_id,
                "clinic_id": account["CLINIC_UNIQN"]
            }
        ).mappings().first()

        if prescription is None:
            raise HTTPException(
                status_code=404,
                detail="처방전을 찾을 수 없습니다."
            )

        if prescription["AUTHOR_UNIQN"] != account_id:
            raise HTTPException(
                status_code=403,
                detail="처방전 작성자만 전달할 수 있습니다."
            )

        version = connection.execute(
            text("""
                SELECT
                    "RX_VERSION_UNIQN",
                    "RX_UNIQN",
                    "VERSION_NO",
                    "DIAGNOSIS_TEXT",
                    "PRESP_NM",
                    "CREATED_AT"
                FROM "PATIENT_PRESP_VERSION"
                WHERE "RX_VERSION_UNIQN" = :version_id
                  AND "RX_UNIQN" = :rx_id
            """),
            {
                "version_id": request.versionId,
                "rx_id": prescription_id
            }
        ).mappings().first()

        if version is None:
            raise HTTPException(
                status_code=404,
                detail="해당 처방전의 저장 버전을 찾을 수 없습니다."
            )

        # 동일 버전 재전송 시 기존 전달 기록 반환
        delivery = connection.execute(
            text("""
                SELECT
                    d."DELIVERY_UNIQN",
                    d."RX_VERSION_UNIQN",
                    d."SENT_BY",
                    d."SENT_AT",
                    sender."NAME" AS sent_by_name
                FROM "PRESP_DELIVERY" d
                JOIN "ACCOUNT" sender
                  ON sender."ACCOUNT_UNIQN" = d."SENT_BY"
                WHERE d."RX_VERSION_UNIQN" = :version_id
                ORDER BY d."DELIVERY_UNIQN"
                LIMIT 1
            """),
            {"version_id": request.versionId}
        ).mappings().first()

        if delivery is None:
            delivery = connection.execute(
                text("""
                    WITH inserted AS (
                        INSERT INTO "PRESP_DELIVERY" (
                            "RX_VERSION_UNIQN",
                            "SENT_BY",
                            "STATUS_CD"
                        )
                        VALUES (
                            :version_id,
                            :sent_by,
                            'SENT'
                        )
                        RETURNING
                            "DELIVERY_UNIQN",
                            "RX_VERSION_UNIQN",
                            "SENT_BY",
                            "SENT_AT"
                    )
                    SELECT
                        inserted.*,
                        sender."NAME" AS sent_by_name
                    FROM inserted
                    JOIN "ACCOUNT" sender
                      ON sender."ACCOUNT_UNIQN" = inserted."SENT_BY"
                """),
                {
                    "version_id": request.versionId,
                    "sent_by": account_id
                }
            ).mappings().one()

    return {
        "record": {
            "id": delivery["DELIVERY_UNIQN"],
            "rxId": prescription_id,
            "versionId": version["RX_VERSION_UNIQN"],
            "versionNo": version["VERSION_NO"],
            "caseId": prescription["CASE_UNIQN"],
            "visitId": prescription["VISIT_UNIQN"],
            "patientId": prescription["PATIENT_UNIQN"],
            "authorId": prescription["AUTHOR_UNIQN"],
            "patientName": prescription["patient_name"],
            "birthDate": str(prescription["birth_date"]),
            "authorName": prescription["author_name"],
            "diagnosisText": version["DIAGNOSIS_TEXT"],
            "prescriptionName": version["PRESP_NM"],
            "registeredAt": prescription["REGISTERED_AT"].isoformat(),
            "savedAt": version["CREATED_AT"].isoformat(),
            "sentAt": delivery["SENT_AT"].isoformat(),
            "sentBy": delivery["SENT_BY"],
            "sentByName": delivery["sent_by_name"]
        }
    }


@app.post("/api/prescriptions/{prescription_id}/print", status_code=201)
def record_prescription_print(
    prescription_id: int,
    versionId: int | None = Query(default=None, gt=0),
    account=Depends(require_authenticated_user)
):
    # 안내데스크만 인쇄 가능
    if account["IS_OWNER"] or account["ROLE_CD"] != "DESK":
        raise HTTPException(
            status_code=403,
            detail="안내데스크 직원만 처방전을 인쇄할 수 있습니다."
        )

    with engine.begin() as connection:
        # 같은 한의원에서 수신한 처방전인지 확인
        prescription = connection.execute(
            text("""
                SELECT v."RX_VERSION_UNIQN"
                FROM "PATIENT_PRESP" p
                JOIN "CASE_RECORD" c
                    ON p."CASE_UNIQN" = c."CASE_UNIQN"
                JOIN "VISIT" visit
                    ON c."VISIT_UNIQN" = visit."VISIT_UNIQN"
                JOIN "PATIENT" patient
                    ON visit."PATIENT_UNIQN" = patient."PATIENT_UNIQN"
                JOIN LATERAL (
                    SELECT "RX_VERSION_UNIQN"
                    FROM "PATIENT_PRESP_VERSION"
                    WHERE "RX_UNIQN" = p."RX_UNIQN"
                      AND (CAST(:version_id AS bigint) IS NULL OR "RX_VERSION_UNIQN" = :version_id)
                    ORDER BY "VERSION_NO" DESC,
                             "RX_VERSION_UNIQN" DESC
                    LIMIT 1
                ) v ON TRUE
                JOIN "PRESP_DELIVERY" d
                    ON d."RX_VERSION_UNIQN" = v."RX_VERSION_UNIQN"
                WHERE p."RX_UNIQN" = :prescription_id
                  AND patient."CLINIC_UNIQN" = :clinic_id
                  AND p."IS_DELETED" = FALSE
                LIMIT 1
            """),
            {
                "prescription_id": prescription_id,
                "version_id": versionId,
                "clinic_id": account["CLINIC_UNIQN"]
            }
        ).scalar_one_or_none()

        if prescription is None:
            raise HTTPException(
                status_code=404,
                detail="수신한 처방전을 찾을 수 없습니다."
            )

        # 인쇄 요청 이력 저장
        print_id = connection.execute(
            text("""
                INSERT INTO "PRESP_PRINT_HISTORY" (
                    "RX_VERSION_UNIQN",
                    "PRINTED_BY"
                )
                VALUES (
                    :rx_version_id,
                    :printed_by
                )
                RETURNING "PRINT_UNIQN"
            """),
            {
                "rx_version_id": prescription,
                "printed_by": account["ACCOUNT_UNIQN"]
            }
        ).scalar_one()

    return {
        "message": "처방전 인쇄 요청이 기록되었습니다.",
        "printId": print_id,
        "prescriptionId": prescription_id,
        "rxVersionId": prescription
    }

@app.get("/api/prescriptions/{prescription_id}/print-history")
def get_prescription_print_history(
    prescription_id: int,
    versionId: int | None = Query(default=None, gt=0),
    account=Depends(require_authenticated_user)
):
    if account["IS_OWNER"] or account["ROLE_CD"] != "DESK":
        raise HTTPException(
            status_code=403,
            detail="안내데스크 직원만 인쇄 이력을 조회할 수 있습니다."
        )

    with engine.connect() as connection:
        result = connection.execute(
            text("""
                SELECT
                    v."RX_VERSION_UNIQN",
                    COUNT(h."PRINT_UNIQN") AS print_count
                FROM "PATIENT_PRESP" p
                JOIN "CASE_RECORD" c
                    ON p."CASE_UNIQN" = c."CASE_UNIQN"
                JOIN "VISIT" visit
                    ON c."VISIT_UNIQN" = visit."VISIT_UNIQN"
                JOIN "PATIENT" patient
                    ON visit."PATIENT_UNIQN" = patient."PATIENT_UNIQN"
                JOIN LATERAL (
                    SELECT "RX_VERSION_UNIQN"
                    FROM "PATIENT_PRESP_VERSION"
                    WHERE "RX_UNIQN" = p."RX_UNIQN"
                      AND (CAST(:version_id AS bigint) IS NULL OR "RX_VERSION_UNIQN" = :version_id)
                    ORDER BY "VERSION_NO" DESC,
                             "RX_VERSION_UNIQN" DESC
                    LIMIT 1
                ) v ON TRUE
                JOIN "PRESP_DELIVERY" d
                    ON d."RX_VERSION_UNIQN" = v."RX_VERSION_UNIQN"
                LEFT JOIN "PRESP_PRINT_HISTORY" h
                    ON h."RX_VERSION_UNIQN" = v."RX_VERSION_UNIQN"
                WHERE p."RX_UNIQN" = :prescription_id
                  AND patient."CLINIC_UNIQN" = :clinic_id
                  AND p."IS_DELETED" = FALSE
                GROUP BY v."RX_VERSION_UNIQN"
            """),
            {
                "prescription_id": prescription_id,
                "version_id": versionId,
                "clinic_id": account["CLINIC_UNIQN"]
            }
        ).mappings().first()

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="수신한 처방전을 찾을 수 없습니다."
        )

    return {
        "prescriptionId": prescription_id,
        "rxVersionId": result["RX_VERSION_UNIQN"],
        "printCount": result["print_count"],
        "hasPrinted": result["print_count"] > 0
    }


@app.patch("/api/prescriptions/{prescription_id}")
def update_prescription(
    prescription_id: int,
    request: PrescriptionCorrection,
    account=Depends(require_clinical_user)
):
    account_id = account["ACCOUNT_UNIQN"]

    if request.caseId <= 0 or prescription_id <= 0:
        raise HTTPException(
            status_code=400,
            detail="처방전 또는 상담기록 ID가 올바르지 않습니다."
        )

    if request.versionId <= 0:
        raise HTTPException(
            status_code=400,
            detail="버전 ID가 올바르지 않습니다."
        )

    reason = request.reason.strip()
    prescription_name = request.prescriptionName.strip()

    if not reason:
        raise HTTPException(
            status_code=400,
            detail="정정 사유를 입력해야 합니다."
        )

    if not prescription_name:
        raise HTTPException(
            status_code=400,
            detail="처방명을 입력해야 합니다."
        )

    with engine.begin() as connection:
        require_clinic_references(connection, account, prescription=prescription_id)
        prescription = connection.execute(
            text("""
                SELECT
                    p."RX_UNIQN",
                    p."CASE_UNIQN",
                    p."AUTHOR_UNIQN",
                    v."VISIT_UNIQN",
                    v."PATIENT_UNIQN",
                    v."REGISTERED_AT",
                    patient."NAME" AS patient_name,
                    patient."BIRTH_DATE" AS birth_date,
                    author."NAME" AS author_name
                FROM "PATIENT_PRESP" p
                JOIN "CASE_RECORD" c
                  ON c."CASE_UNIQN" = p."CASE_UNIQN"
                JOIN "VISIT" v
                  ON v."VISIT_UNIQN" = c."VISIT_UNIQN"
                JOIN "PATIENT" patient
                  ON patient."PATIENT_UNIQN" = v."PATIENT_UNIQN"
                JOIN "ACCOUNT" author
                  ON author."ACCOUNT_UNIQN" = p."AUTHOR_UNIQN"
                WHERE p."RX_UNIQN" = :rx_id
                  AND patient."CLINIC_UNIQN" = :clinic_id
                  AND p."IS_DELETED" = FALSE
                FOR UPDATE OF p
            """),
            {
                "rx_id": prescription_id,
                "clinic_id": account["CLINIC_UNIQN"]
            }
        ).mappings().first()

        if prescription is None:
            raise HTTPException(
                status_code=404,
                detail="처방전을 찾을 수 없습니다."
            )

        if prescription["AUTHOR_UNIQN"] != account_id:
            raise HTTPException(
                status_code=403,
                detail="처방전 작성자만 정정할 수 있습니다."
            )

        if prescription["CASE_UNIQN"] != request.caseId:
            raise HTTPException(
                status_code=400,
                detail="처방전의 상담기록을 변경할 수 없습니다."
            )

        latest = connection.execute(
            text("""
                SELECT *
                FROM "PATIENT_PRESP_VERSION"
                WHERE "RX_UNIQN" = :rx_id
                ORDER BY "VERSION_NO" DESC,
                         "RX_VERSION_UNIQN" DESC
                LIMIT 1
            """),
            {"rx_id": prescription_id}
        ).mappings().first()

        if latest is None:
            raise HTTPException(
                status_code=404,
                detail="처방전 버전을 찾을 수 없습니다."
            )

        if latest["RX_VERSION_UNIQN"] != request.versionId:
            raise HTTPException(
                status_code=409,
                detail="현재 처방전 버전과 요청 버전이 일치하지 않습니다."
            )

        ingredients = validate_prescription_source(connection, request, account["ACCOUNT_UNIQN"])

        before = {
            "diagnosisText": latest["DIAGNOSIS_TEXT"],
            "prescriptionName": latest["PRESP_NM"],
            "prescriptionText": latest["PRESP_CONT"],
            "prescriptionId": latest["SOURCE_PRESP_UNIQN"],
            "prescriptionSearchId": (
                str(latest["PRESCRIPTION_SEARCH_UNIQN"])
                if latest["PRESCRIPTION_SEARCH_UNIQN"] is not None
                else None
            ),
            "ingredients": latest["INGREDIENTS_JSON"] or []
        }

        after = {
            "diagnosisText": request.diagnosisText,
            "prescriptionName": prescription_name,
            "prescriptionText": request.prescriptionText,
            "prescriptionId": request.prescriptionId,
            "prescriptionSearchId": request.prescriptionSearchId,
            "ingredients": ingredients
        }

        changed_fields = [
            key
            for key in after
            if before[key] != after[key]
        ]

        if not changed_fields:
            raise HTTPException(
                status_code=409,
                detail="변경된 처방전 내용이 없습니다."
            )

        change_data = {
            "changedFields": changed_fields,
            "beforeValues": {
                key: before[key] for key in changed_fields
            },
            "afterValues": {
                key: after[key] for key in changed_fields
            },
            "changedBy": account_id,
            "reason": reason
        }

        new_version = connection.execute(
            text("""
                INSERT INTO "PATIENT_PRESP_VERSION" (
                    "RX_UNIQN",
                    "VERSION_NO",
                    "DIAGNOSIS_TEXT",
                    "PRESP_NM",
                    "PRESP_CONT",
                    "SOURCE_PRESP_UNIQN",
                    "PRESCRIPTION_SEARCH_UNIQN",
                    "INGREDIENTS_JSON",
                    "SAVED_BY",
                    "CHANGED_FIELDS",
                    "REASON"
                )
                VALUES (
                    :rx_id,
                    :version_no,
                    :diagnosis_text,
                    :prescription_name,
                    :prescription_text,
                    :source_id,
                    :search_id,
                    CAST(:ingredients AS jsonb),
                    :saved_by,
                    CAST(:changed_fields AS jsonb),
                    :reason
                )
                RETURNING
                    "RX_VERSION_UNIQN",
                    "VERSION_NO",
                    "CREATED_AT"
            """),
            {
                "rx_id": prescription_id,
                "version_no": latest["VERSION_NO"] + 1,
                "diagnosis_text": request.diagnosisText,
                "prescription_name": prescription_name,
                "prescription_text": request.prescriptionText,
                "source_id": request.prescriptionId,
                "search_id": int(request.prescriptionSearchId) if request.prescriptionSearchId else None,
                "ingredients": json.dumps(
                    ingredients,
                    ensure_ascii=False
                ),
                "saved_by": account_id,
                "changed_fields": json.dumps(
                    change_data,
                    ensure_ascii=False
                ),
                "reason": reason
            }
        ).mappings().one()

        mark_prescription_selected(connection, request)

    saved_at = new_version["CREATED_AT"].isoformat()

    change_record = {
        "id": new_version["RX_VERSION_UNIQN"],
        "changedBy": account_id,
        "changedByName": prescription["author_name"],
        "changedAt": saved_at,
        **change_data
    }

    return {
        "record": {
            "rxId": prescription_id,
            "versionId": new_version["RX_VERSION_UNIQN"],
            "versionNo": new_version["VERSION_NO"],
            "caseId": request.caseId,
            "visitId": prescription["VISIT_UNIQN"],
            "patientId": prescription["PATIENT_UNIQN"],
            "authorId": prescription["AUTHOR_UNIQN"],
            "patientName": prescription["patient_name"],
            "birthDate": str(prescription["birth_date"]),
            "authorName": prescription["author_name"],
            "registeredAt": prescription["REGISTERED_AT"].isoformat(),
            "diagnosisText": request.diagnosisText,
            "prescriptionName": prescription_name,
            "prescriptionText": request.prescriptionText,
            "prescriptionId": request.prescriptionId,
            "prescriptionSearchId": request.prescriptionSearchId,
            "ingredients": ingredients,
            "savedBy": account_id,
            "savedByName": prescription["author_name"],
            "savedAt": saved_at,
            "change": change_record
        }
    }

class LoginRequest(BaseModel):
    email: str
    password: str

    model_config = {"extra": "forbid"}


def use_secure_session_cookie(request: Request):
    return request.url.scheme == "https" or os.getenv("HANUI_SESSION_COOKIE_SECURE") == "1"


@app.post("/api/auth/login")
def login(request: LoginRequest, response: Response, http_request: Request):
    with engine.connect() as connection:
        account = connection.execute(
            text("""
                SELECT
                    a."ACCOUNT_UNIQN",
                    a."CLINIC_UNIQN",
                    a."EMAIL",
                    a."NAME",
                    a."PASSWORD_HASH",
                    a."ROLE_CD",
                    a."IS_OWNER",
                    a."STATUS_CD",
                    c."STATUS_CD" AS "CLINIC_STATUS"
                FROM "ACCOUNT" a
                LEFT JOIN "CLINIC" c
                    ON c."CLINIC_UNIQN" = a."CLINIC_UNIQN"
                WHERE LOWER(a."EMAIL") = LOWER(:email)
            """),
            {"email": request.email.strip()}
        ).mappings().first()

    if account is None or not verify_password(
        request.password,
        account["PASSWORD_HASH"]
    ):
        raise HTTPException(
            status_code=401,
            detail="이메일 또는 비밀번호가 올바르지 않습니다."
        )

    if account["STATUS_CD"] != "ACTIVE":
        raise HTTPException(
            status_code=403,
            detail="사용할 수 없는 계정입니다."
        )

    if account["ROLE_CD"] == "SERVICE_ADMIN":
        if account["CLINIC_UNIQN"] is not None:
            raise HTTPException(
                status_code=403,
                detail="서비스 운영 관리자 계정 정보가 올바르지 않습니다."
            )
    elif (
        account["CLINIC_UNIQN"] is None
        or account["CLINIC_STATUS"] != "ACTIVE"
    ):
        raise HTTPException(
            status_code=403,
            detail="이용할 수 없는 한의원입니다."
        )

    token, expires_at = create_login_session(
        account["ACCOUNT_UNIQN"]
    )

    response.set_cookie(
        key="session",
        value=token,
        httponly=True,
        secure=use_secure_session_cookie(http_request),
        samesite="lax",
        max_age=SESSION_TTL_SECONDS,
        path="/"
    )

    return {
        "account": {
            "id": account["ACCOUNT_UNIQN"],
            "name": account["NAME"],
            "email": account["EMAIL"],
            "role": account["ROLE_CD"],
            "isOwner": bool(account["IS_OWNER"]),
            "clinicId": account["CLINIC_UNIQN"]
        },
        "expiresAt": expires_at.isoformat()
    }


@app.get("/api/auth/me")
def get_current_user(
    account=Depends(require_authenticated_user)
):
    return {
        "account": {
            "id": account["ACCOUNT_UNIQN"],
            "name": account["NAME"],
            "email": account["EMAIL"],
            "role": account["ROLE_CD"],
            "isOwner": bool(account["IS_OWNER"]),
            "clinicId": account["CLINIC_UNIQN"]
        },
        "expiresAt": account["EXPIRES_AT"].isoformat()
    }


@app.get("/api/profile")
def get_my_profile(
    account=Depends(require_authenticated_user)
):
    with engine.connect() as connection:
        profile = connection.execute(
            text("""
                SELECT
                    "ACCOUNT_UNIQN",
                    "EMAIL",
                    "NAME",
                    "PHONE",
                    "ROLE_CD",
                    "IS_OWNER"
                FROM "ACCOUNT"
                WHERE "ACCOUNT_UNIQN" = :account_id
                  AND "CLINIC_UNIQN" = :clinic_id
                  AND "STATUS_CD" = 'ACTIVE'
            """),
            {
                "account_id": account["ACCOUNT_UNIQN"],
                "clinic_id": account["CLINIC_UNIQN"]
            }
        ).mappings().first()

    if profile is None:
        raise HTTPException(
            status_code=404,
            detail="프로필 정보를 찾을 수 없습니다."
        )

    return {
        "id": profile["ACCOUNT_UNIQN"],
        "email": profile["EMAIL"],
        "name": profile["NAME"],
        "phone": profile["PHONE"] or "",
        "role": (
            "원장"
            if profile["IS_OWNER"]
            else "한의사"
            if profile["ROLE_CD"] == "DOCTOR"
            else "안내데스크"
        )
    }


class ProfileUpdateRequest(BaseModel):
    name: str
    phone: str | None = None


@app.patch("/api/profile")
def update_my_profile(
    request: ProfileUpdateRequest,
    account=Depends(require_authenticated_user)
):
    name = request.name.strip()
    phone = (request.phone or "").strip()

    if not name:
        raise HTTPException(
            status_code=400,
            detail="이름을 입력해 주세요."
        )

    with engine.begin() as connection:
        profile = connection.execute(
            text("""
                UPDATE "ACCOUNT"
                SET
                    "NAME" = :name,
                    "PHONE" = :phone
                WHERE "ACCOUNT_UNIQN" = :account_id
                  AND "CLINIC_UNIQN" = :clinic_id
                  AND "STATUS_CD" = 'ACTIVE'
                RETURNING
                    "ACCOUNT_UNIQN",
                    "EMAIL",
                    "NAME",
                    "PHONE",
                    "ROLE_CD",
                    "IS_OWNER"
            """),
            {
                "name": name,
                "phone": phone or None,
                "account_id": account["ACCOUNT_UNIQN"],
                "clinic_id": account["CLINIC_UNIQN"]
            }
        ).mappings().first()

    if profile is None:
        raise HTTPException(
            status_code=404,
            detail="프로필 정보를 찾을 수 없습니다."
        )

    return {
        "message": "계정 정보가 수정되었습니다.",
        "profile": {
            "id": profile["ACCOUNT_UNIQN"],
            "email": profile["EMAIL"],
            "name": profile["NAME"],
            "phone": profile["PHONE"] or "",
            "role": (
                "원장"
                if profile["IS_OWNER"]
                else "한의사"
                if profile["ROLE_CD"] == "DOCTOR"
                else "안내데스크"
            )
        }
    }

class PasswordChangeRequest(BaseModel):
    currentPassword: str
    newPassword: str
    confirmPassword: str


@app.patch("/api/profile/password")
def change_my_password(
    request: PasswordChangeRequest,
    http_request: Request,
    account=Depends(require_authenticated_user)
):
    # 1. 새 비밀번호 유효성 검사
    if len(request.newPassword) < 8:
        raise HTTPException(
            status_code=400,
            detail="새 비밀번호는 8자 이상이어야 합니다."
        )

    # 2. 새 비밀번호 확인
    if request.newPassword != request.confirmPassword:
        raise HTTPException(
            status_code=400,
            detail="새 비밀번호가 일치하지 않습니다."
        )

    # 3. 현재 비밀번호 조회
    with engine.begin() as connection:
        current_account = connection.execute(
            text("""
                SELECT "PASSWORD_HASH"
                FROM "ACCOUNT"
                WHERE "ACCOUNT_UNIQN" = :account_id
                  AND "CLINIC_UNIQN" = :clinic_id
                  AND "STATUS_CD" = 'ACTIVE'
                FOR UPDATE
            """),
            {
                "account_id": account["ACCOUNT_UNIQN"],
                "clinic_id": account["CLINIC_UNIQN"]
            }
        ).mappings().first()

        if current_account is None:
            raise HTTPException(
                status_code=404,
                detail="계정 정보를 찾을 수 없습니다."
            )

        # 4. 현재 비밀번호 검증
        if not verify_password(
            request.currentPassword,
            current_account["PASSWORD_HASH"]
        ):
            raise HTTPException(
                status_code=400,
                detail="현재 비밀번호가 올바르지 않습니다."
            )

        # 5. 기존 비밀번호와 동일한지 확인
        if verify_password(
            request.newPassword,
            current_account["PASSWORD_HASH"]
        ):
            raise HTTPException(
                status_code=400,
                detail="기존 비밀번호와 다른 비밀번호를 입력해 주세요."
            )

        # 6. 새 비밀번호 암호화 및 저장
        new_password_hash = hash_password(request.newPassword)

        connection.execute(
            text("""
                UPDATE "ACCOUNT"
                SET "PASSWORD_HASH" = :password_hash
                WHERE "ACCOUNT_UNIQN" = :account_id
                  AND "CLINIC_UNIQN" = :clinic_id
                  AND "STATUS_CD" = 'ACTIVE'
            """),
            {
                "password_hash": new_password_hash,
                "account_id": account["ACCOUNT_UNIQN"],
                "clinic_id": account["CLINIC_UNIQN"]
            }
        )

        connection.execute(text('''
            UPDATE "LOGIN_SESSION" SET "REVOKED_AT" = CURRENT_TIMESTAMP
            WHERE "ACCOUNT_UNIQN" = :account_id AND "REVOKED_AT" IS NULL
              AND "TOKEN_HASH" <> :current_token
        '''), {"account_id": account["ACCOUNT_UNIQN"],
               "current_token": hash_session_token(http_request.cookies.get("session", ""))})

    return {"message": "비밀번호가 변경되었습니다. 다른 기기의 로그인은 종료되었습니다."}

@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get("session")

    if token:
        token_hash = hash_session_token(token)

        with engine.begin() as connection:
            connection.execute(
                text("""
                    UPDATE "LOGIN_SESSION"
                    SET "REVOKED_AT" = CURRENT_TIMESTAMP
                    WHERE "TOKEN_HASH" = :token_hash
                      AND "REVOKED_AT" IS NULL
                """),
                {"token_hash": token_hash}
            )

    response.delete_cookie(
        key="session",
        path="/",
        samesite="lax",
        secure=use_secure_session_cookie(request),
    )

    return {"loggedOut": True}

@app.get("/api/chat/messages")
def get_chat_messages(
    account=Depends(require_authenticated_user)
):
    with engine.connect() as connection:
        rows = connection.execute(
            text("""
                SELECT
                    "MESSAGE_UNIQN",
                    "SENDER_UNIQN",
                    "SENDER_NAME_SNAPSHOT",
                    "SENDER_ROLE_SNAPSHOT",
                    "MESSAGE_TEXT",
                    "SENT_AT"
                FROM "CHAT_MESSAGE"
                WHERE "CLINIC_UNIQN" = :clinic_id
                ORDER BY "SENT_AT" DESC, "MESSAGE_UNIQN" DESC
                LIMIT 100
            """),
            {
                "clinic_id": account["CLINIC_UNIQN"]
            }
        ).mappings().all()

    return {
        "messages": [
            {
                "id": row["MESSAGE_UNIQN"],
                "senderId": row["SENDER_UNIQN"],
                "senderName": row["SENDER_NAME_SNAPSHOT"],
                "senderRole": row["SENDER_ROLE_SNAPSHOT"],
                "message": row["MESSAGE_TEXT"],
                "sentAt": row["SENT_AT"].isoformat()
            }
            for row in reversed(rows)
        ]
    }

class ChatMessageCreateRequest(BaseModel):
    message: str


@app.post("/api/chat/messages", status_code=201)
def create_chat_message(
    request: ChatMessageCreateRequest,
    account=Depends(require_authenticated_user)
):
    message = request.message.strip()

    if not message:
        raise HTTPException(
            status_code=400,
            detail="메시지를 입력해 주세요."
        )

    if len(message) > 2000:
        raise HTTPException(
            status_code=400,
            detail="메시지는 2000자 이하로 입력해 주세요."
        )

    with engine.begin() as connection:
        sender = connection.execute(
            text("""
                SELECT
                    "NAME",
                    "ROLE_CD",
                    "IS_OWNER"
                FROM "ACCOUNT"
                WHERE "ACCOUNT_UNIQN" = :account_id
                  AND "CLINIC_UNIQN" = :clinic_id
                  AND "STATUS_CD" = 'ACTIVE'
            """),
            {
                "account_id": account["ACCOUNT_UNIQN"],
                "clinic_id": account["CLINIC_UNIQN"]
            }
        ).mappings().first()

        if sender is None:
            raise HTTPException(
                status_code=403,
                detail="채팅을 이용할 수 없는 계정입니다."
            )

        sender_role = (
            "원장" if sender["IS_OWNER"]
            else "한의사" if sender["ROLE_CD"] == "DOCTOR"
            else "안내데스크"
        )

        row = connection.execute(
            text("""
                INSERT INTO "CHAT_MESSAGE" (
                    "CLINIC_UNIQN",
                    "SENDER_UNIQN",
                    "SENDER_NAME_SNAPSHOT",
                    "SENDER_ROLE_SNAPSHOT",
                    "MESSAGE_TEXT",
                    "SENT_AT"
                )
                VALUES (
                    :clinic_id,
                    :sender_id,
                    :sender_name,
                    :sender_role,
                    :message,
                    NOW()
                )
                RETURNING
                    "MESSAGE_UNIQN",
                    "SENDER_UNIQN",
                    "SENDER_NAME_SNAPSHOT",
                    "SENDER_ROLE_SNAPSHOT",
                    "MESSAGE_TEXT",
                    "SENT_AT"
            """),
            {
                "clinic_id": account["CLINIC_UNIQN"],
                "sender_id": account["ACCOUNT_UNIQN"],
                "sender_name": sender["NAME"],
                "sender_role": sender_role,
                "message": message
            }
        ).mappings().first()

    return {
        "message": "메시지가 전송되었습니다.",
        "chatMessage": {
            "id": row["MESSAGE_UNIQN"],
            "senderId": row["SENDER_UNIQN"],
            "senderName": row["SENDER_NAME_SNAPSHOT"],
            "senderRole": row["SENDER_ROLE_SNAPSHOT"],
            "message": row["MESSAGE_TEXT"],
            "sentAt": row["SENT_AT"].isoformat()
        }
    }


@app.get("/api/prescription-deliveries")
def get_prescription_deliveries(
    patientId: int | None = Query(default=None, gt=0),
    caseId: int | None = Query(default=None, gt=0),
    account=Depends(require_authenticated_user)
):
    if account["ROLE_CD"] not in ("DOCTOR", "DESK"):
        raise HTTPException(403, "처방전 전달본을 조회할 권한이 없습니다.")

    params = {
        "clinic_id": account["CLINIC_UNIQN"],
        "patient_id": patientId,
        "case_id": caseId
    }

    with engine.connect() as connection:
        require_clinic_references(connection, account, patient=patientId, case=caseId)
        rows = connection.execute(
            text("""
                SELECT
                    d."DELIVERY_UNIQN" AS id,
                    p."RX_UNIQN" AS rx_id,
                    rv."RX_VERSION_UNIQN" AS version_id,
                    rv."VERSION_NO" AS version_no,
                    c."CASE_UNIQN" AS case_id,
                    visit."VISIT_UNIQN" AS visit_id,
                    patient."PATIENT_UNIQN" AS patient_id,
                    p."AUTHOR_UNIQN" AS author_id,
                    patient."NAME" AS patient_name,
                    patient."BIRTH_DATE" AS birth_date,
                    author."NAME" AS author_name,
                    rv."DIAGNOSIS_TEXT" AS diagnosis_text,
                    rv."PRESP_NM" AS prescription_name,
                    visit."REGISTERED_AT" AS registered_at,
                    rv."CREATED_AT" AS saved_at,
                    d."SENT_AT" AS sent_at,
                    d."SENT_BY" AS sent_by,
                    sender."NAME" AS sent_by_name
                FROM "PRESP_DELIVERY" d
                JOIN "PATIENT_PRESP_VERSION" rv
                  ON rv."RX_VERSION_UNIQN" = d."RX_VERSION_UNIQN"
                JOIN "PATIENT_PRESP" p
                  ON p."RX_UNIQN" = rv."RX_UNIQN"
                JOIN "CASE_RECORD" c
                  ON c."CASE_UNIQN" = p."CASE_UNIQN"
                JOIN "VISIT" visit
                  ON visit."VISIT_UNIQN" = c."VISIT_UNIQN"
                JOIN "PATIENT" patient
                  ON patient."PATIENT_UNIQN" = visit."PATIENT_UNIQN"
                JOIN "ACCOUNT" author
                  ON author."ACCOUNT_UNIQN" = p."AUTHOR_UNIQN"
                JOIN "ACCOUNT" sender
                  ON sender."ACCOUNT_UNIQN" = d."SENT_BY"
                WHERE patient."CLINIC_UNIQN" = :clinic_id
                  AND (
                      CAST(:patient_id AS bigint) IS NULL
                      OR patient."PATIENT_UNIQN" = :patient_id
                  )
                  AND (
                      CAST(:case_id AS bigint) IS NULL
                      OR c."CASE_UNIQN" = :case_id
                  )
                ORDER BY d."SENT_AT" DESC,
                         d."DELIVERY_UNIQN" DESC
            """),
            params
        ).mappings().all()

    records = []

    for row in rows:
        records.append({
            "id": row["id"],
            "rxId": row["rx_id"],
            "versionId": row["version_id"],
            "versionNo": row["version_no"],
            "caseId": row["case_id"],
            "visitId": row["visit_id"],
            "patientId": row["patient_id"],
            "authorId": row["author_id"],
            "patientName": row["patient_name"],
            "birthDate": str(row["birth_date"]),
            "authorName": row["author_name"],
            "diagnosisText": row["diagnosis_text"],
            "prescriptionName": row["prescription_name"],
            "registeredAt": row["registered_at"].isoformat(),
            "savedAt": row["saved_at"].isoformat(),
            "sentAt": row["sent_at"].isoformat(),
            "sentBy": row["sent_by"],
            "sentByName": row["sent_by_name"]
        })

    return {
        "records": records,
        "total": len(records)
    }


@app.get("/api/prescription-deliveries/{delivery_id}")
def get_prescription_delivery_detail(
    delivery_id: int,
    account=Depends(require_authenticated_user)
):
    if account["ROLE_CD"] not in ("DOCTOR", "DESK"):
        raise HTTPException(403, "처방전 전달본을 조회할 권한이 없습니다.")

    with engine.connect() as connection:
        require_clinic_references(connection, account, delivery=delivery_id)
        row = connection.execute(
            text("""
                SELECT
                    d."DELIVERY_UNIQN",
                    d."SENT_BY",
                    d."SENT_AT",
                    rv.*,
                    p."AUTHOR_UNIQN",
                    c."CASE_UNIQN",
                    visit."VISIT_UNIQN",
                    visit."PATIENT_UNIQN",
                    visit."REGISTERED_AT",
                    patient."NAME" AS patient_name,
                    patient."BIRTH_DATE" AS birth_date,
                    author."NAME" AS author_name,
                    saver."NAME" AS saved_by_name,
                    sender."NAME" AS sent_by_name
                FROM "PRESP_DELIVERY" d
                JOIN "PATIENT_PRESP_VERSION" rv
                  ON rv."RX_VERSION_UNIQN" = d."RX_VERSION_UNIQN"
                JOIN "PATIENT_PRESP" p
                  ON p."RX_UNIQN" = rv."RX_UNIQN"
                JOIN "CASE_RECORD" c
                  ON c."CASE_UNIQN" = p."CASE_UNIQN"
                JOIN "VISIT" visit
                  ON visit."VISIT_UNIQN" = c."VISIT_UNIQN"
                JOIN "PATIENT" patient
                  ON patient."PATIENT_UNIQN" = visit."PATIENT_UNIQN"
                JOIN "ACCOUNT" author
                  ON author."ACCOUNT_UNIQN" = p."AUTHOR_UNIQN"
                JOIN "ACCOUNT" saver
                  ON saver."ACCOUNT_UNIQN" = rv."SAVED_BY"
                JOIN "ACCOUNT" sender
                  ON sender."ACCOUNT_UNIQN" = d."SENT_BY"
                WHERE d."DELIVERY_UNIQN" = :delivery_id
                  AND patient."CLINIC_UNIQN" = :clinic_id
            """),
            {
                "delivery_id": delivery_id,
                "clinic_id": account["CLINIC_UNIQN"]
            }
        ).mappings().first()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="전달된 처방전을 찾을 수 없습니다."
        )

    common = {
        "rxId": row["RX_UNIQN"],
        "versionId": row["RX_VERSION_UNIQN"],
        "versionNo": row["VERSION_NO"],
        "caseId": row["CASE_UNIQN"],
        "visitId": row["VISIT_UNIQN"],
        "patientId": row["PATIENT_UNIQN"],
        "authorId": row["AUTHOR_UNIQN"],
        "patientName": row["patient_name"],
        "birthDate": str(row["birth_date"]),
        "authorName": row["author_name"],
        "registeredAt": row["REGISTERED_AT"].isoformat(),
        "diagnosisText": row["DIAGNOSIS_TEXT"],
        "prescriptionName": row["PRESP_NM"]
    }

    change = None
    if row["CHANGED_FIELDS"] is not None:
        change_data = row["CHANGED_FIELDS"]

        if isinstance(change_data, str):
            change_data = json.loads(change_data)

        if isinstance(change_data, dict):
            change = {
                "id": row["RX_VERSION_UNIQN"],
                "changedBy": change_data.get("changedBy"),
                "changedByName": row["saved_by_name"],
                "changedAt": row["CREATED_AT"].isoformat(),
                "changedFields": change_data.get("changedFields", []),
                "beforeValues": change_data.get("beforeValues", {}),
                "afterValues": change_data.get("afterValues", {}),
                "reason": row["REASON"]
            }

    version = {
        **common,
        "prescriptionText": row["PRESP_CONT"],
        "prescriptionId": row["SOURCE_PRESP_UNIQN"],
        "prescriptionSearchId": (
            str(row["PRESCRIPTION_SEARCH_UNIQN"])
            if row["PRESCRIPTION_SEARCH_UNIQN"] is not None
            else None
        ),
        "ingredients": row["INGREDIENTS_JSON"] or [],
        "savedBy": row["SAVED_BY"],
        "savedByName": row["saved_by_name"],
        "savedAt": row["CREATED_AT"].isoformat(),
        "change": change
    }

    delivery = {
        "id": row["DELIVERY_UNIQN"],
        **common,
        "savedAt": row["CREATED_AT"].isoformat(),
        "sentAt": row["SENT_AT"].isoformat(),
        "sentBy": row["SENT_BY"],
        "sentByName": row["sent_by_name"],
        "version": version
    }

    return {"record": delivery}


@app.get("/api/prescriptions/{rx_id}/versions")
def get_prescription_versions(
    rx_id: int,
    account=Depends(require_clinical_user)
):
    with engine.connect() as connection:
        require_clinic_references(connection, account, prescription=rx_id)
        rows = connection.execute(
            text("""
                SELECT
                    rv.*,
                    p."AUTHOR_UNIQN",
                    c."CASE_UNIQN",
                    visit."VISIT_UNIQN",
                    visit."PATIENT_UNIQN",
                    visit."REGISTERED_AT",
                    patient."NAME" AS patient_name,
                    patient."BIRTH_DATE" AS birth_date,
                    author."NAME" AS author_name,
                    saver."NAME" AS saved_by_name
                FROM "PATIENT_PRESP" p
                JOIN "PATIENT_PRESP_VERSION" rv
                  ON rv."RX_UNIQN" = p."RX_UNIQN"
                JOIN "CASE_RECORD" c
                  ON c."CASE_UNIQN" = p."CASE_UNIQN"
                JOIN "VISIT" visit
                  ON visit."VISIT_UNIQN" = c."VISIT_UNIQN"
                JOIN "PATIENT" patient
                  ON patient."PATIENT_UNIQN" = visit."PATIENT_UNIQN"
                JOIN "ACCOUNT" author
                  ON author."ACCOUNT_UNIQN" = p."AUTHOR_UNIQN"
                JOIN "ACCOUNT" saver
                  ON saver."ACCOUNT_UNIQN" = rv."SAVED_BY"
                WHERE p."RX_UNIQN" = :rx_id
                  AND patient."CLINIC_UNIQN" = :clinic_id
                ORDER BY rv."VERSION_NO" ASC,
                         rv."RX_VERSION_UNIQN" ASC
            """),
            {
                "rx_id": rx_id,
                "clinic_id": account["CLINIC_UNIQN"]
            }
        ).mappings().all()

    records = []

    for row in rows:
        change = None

        if row["CHANGED_FIELDS"] is not None:
            change_data = row["CHANGED_FIELDS"]

            if isinstance(change_data, str):
                change_data = json.loads(change_data)

            if isinstance(change_data, dict):
                change = {
                    "id": row["RX_VERSION_UNIQN"],
                    "changedBy": change_data.get("changedBy"),
                    "changedByName": row["saved_by_name"],
                    "changedAt": row["CREATED_AT"].isoformat(),
                    "changedFields": change_data.get("changedFields", []),
                    "beforeValues": change_data.get("beforeValues", {}),
                    "afterValues": change_data.get("afterValues", {}),
                    "reason": row["REASON"]
                }

        records.append({
            "rxId": row["RX_UNIQN"],
            "versionId": row["RX_VERSION_UNIQN"],
            "versionNo": row["VERSION_NO"],
            "caseId": row["CASE_UNIQN"],
            "visitId": row["VISIT_UNIQN"],
            "patientId": row["PATIENT_UNIQN"],
            "authorId": row["AUTHOR_UNIQN"],
            "patientName": row["patient_name"],
            "birthDate": str(row["birth_date"]),
            "authorName": row["author_name"],
            "registeredAt": row["REGISTERED_AT"].isoformat(),
            "diagnosisText": row["DIAGNOSIS_TEXT"],
            "prescriptionName": row["PRESP_NM"],
            "prescriptionText": row["PRESP_CONT"],
            "prescriptionId": row["SOURCE_PRESP_UNIQN"],
            "prescriptionSearchId": (
                str(row["PRESCRIPTION_SEARCH_UNIQN"])
                if row["PRESCRIPTION_SEARCH_UNIQN"] is not None
                else None
            ),
            "ingredients": row["INGREDIENTS_JSON"] or [],
            "savedBy": row["SAVED_BY"],
            "savedByName": row["saved_by_name"],
            "savedAt": row["CREATED_AT"].isoformat(),
            "change": change
        })

    if not records:
        raise HTTPException(
            status_code=404,
            detail="처방전을 찾을 수 없습니다."
        )

    return {
        "records": records,
        "total": len(records)
    }

@app.get("/api/prescriptions/{rx_id}/versions/{version_id}")
def get_prescription_version_detail(
    rx_id: int,
    version_id: int,
    account=Depends(require_clinical_user)
):
    result = get_prescription_versions(
        rx_id=rx_id,
        account=account
    )

    for record in result["records"]:
        if record["versionId"] == version_id:
            return {"record": record}

    raise HTTPException(
        status_code=404,
        detail="해당 처방전 버전을 찾을 수 없습니다."
    )

