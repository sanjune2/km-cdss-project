import json
import math
from fastapi import Depends
from fastapi import Request
from itsdangerous import BadSignature, SignatureExpired
import os
from itsdangerous import URLSafeTimedSerializer
from fastapi import Response
from auth import verify_password
from models import Patient
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from sqlalchemy import text
from database import engine


app = FastAPI(title="한의결 API")
SESSION_SECRET = os.environ.get("SESSION_SECRET_KEY")

if not SESSION_SECRET:
    raise RuntimeError("SESSION_SECRET_KEY 환경변수가 설정되지 않았습니다.")

session_signer = URLSafeTimedSerializer(SESSION_SECRET)

def require_authenticated_user(request: Request):
    token = request.cookies.get("hanui_session")

    if not token:
        raise HTTPException(
            status_code=401,
            detail="로그인이 필요합니다."
        )

    try:
        session_data = session_signer.loads(
            token,
            max_age=60 * 60 * 8
        )
    except (BadSignature, SignatureExpired):
        raise HTTPException(
            status_code=401,
            detail="로그인 세션이 유효하지 않습니다."
        )

    account_id = session_data.get("accountId")

    if not isinstance(account_id, int) or isinstance(account_id, bool):
        raise HTTPException(
            status_code=401,
            detail="로그인 세션 정보가 올바르지 않습니다."
        )

    with engine.connect() as connection:
        account = connection.execute(
            text("""
                SELECT
                    "ACCOUNT_UNIQN",
                    "CLINIC_UNIQN",
                    "ROLE_CD",
                    "IS_OWNER",
                    "STATUS_CD"
                FROM "ACCOUNT"
                WHERE "ACCOUNT_UNIQN" = :account_id
            """),
            {"account_id": account_id}
        ).mappings().first()

    if account is None or account["STATUS_CD"] != "ACTIVE":
        raise HTTPException(
            status_code=401,
            detail="사용할 수 없는 계정입니다."
        )

    if account["CLINIC_UNIQN"] is None:
        raise HTTPException(
            status_code=403,
            detail="소속 한의원 정보가 없습니다."
        )

    if not account["IS_OWNER"] and account["ROLE_CD"] not in ("DOCTOR", "DESK"):
        raise HTTPException(
            status_code=403,
            detail="접근 권한이 없습니다."
        )

    return account

@app.exception_handler(SQLAlchemyError)
async def database_exception_handler(request, exc):
    print("DB ERROR:", repr(exc))

    return JSONResponse(
        status_code=503,
        content={
            "detail": "데이터베이스 처리 중 오류가 발생했습니다."
        }
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
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

def require_authenticated_user(request: Request):
    token = request.cookies.get("hanui_session")

    if not token:
        raise HTTPException(
            status_code=401,
            detail="로그인이 필요합니다."
        )

    try:
        session_data = session_signer.loads(
            token,
            max_age=60 * 60 * 8
        )
    except (BadSignature, SignatureExpired):
        raise HTTPException(
            status_code=401,
            detail="로그인 세션이 유효하지 않습니다."
        )

    account_id = session_data.get("accountId")

    if not isinstance(account_id, int) or isinstance(account_id, bool):
        raise HTTPException(
            status_code=401,
            detail="로그인 세션 정보가 올바르지 않습니다."
        )

    with engine.connect() as connection:
        account = connection.execute(
            text("""
                SELECT
                    "ACCOUNT_UNIQN",
                    "CLINIC_UNIQN",
                    "ROLE_CD",
                    "IS_OWNER",
                    "STATUS_CD"
                FROM "ACCOUNT"
                WHERE "ACCOUNT_UNIQN" = :account_id
            """),
            {"account_id": account_id}
        ).mappings().first()

    if account is None or account["STATUS_CD"] != "ACTIVE":
        raise HTTPException(
            status_code=401,
            detail="사용할 수 없는 계정입니다."
        )

    if account["CLINIC_UNIQN"] is None:
        raise HTTPException(
            status_code=403,
            detail="소속 한의원 정보가 없습니다."
        )

    if not account["IS_OWNER"] and account["ROLE_CD"] not in ("DOCTOR", "DESK"):
        raise HTTPException(
            status_code=403,
            detail="접근 권한이 없습니다."
        )

    return account

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
    patientId: int


@app.post("/api/visits", status_code=201)
def create_visit(
    request: VisitCreate,
    account=Depends(require_authenticated_user)
):
    with engine.begin() as connection:
        patient = connection.execute(
            text("""
                SELECT "PATIENT_UNIQN"
                FROM "PATIENT"
                WHERE "PATIENT_UNIQN" = :patient_id
                  AND "CLINIC_UNIQN" = :clinic_id
            """),
            {
                "patient_id": request.patientId,
                "clinic_id": account["CLINIC_UNIQN"]
            }
        ).scalar_one_or_none()

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

        visit_id = connection.execute(
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
                RETURNING "VISIT_UNIQN"
            """),
            {
                "patient_id": request.patientId,
                "registered_by": account["ACCOUNT_UNIQN"]
            }
        ).scalar_one()
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

# 임시 대기 목록 (서버 재시작 시 초기화)
waiting_patients = []

from datetime import date


@app.get("/api/visits")
def get_visits(
    scope: str = "all",
    account=Depends(require_authenticated_user)
):
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
                    p."NAME",
                    (SELECT c."CASE_UNIQN" FROM "CASE_RECORD" c
                     WHERE c."VISIT_UNIQN"=v."VISIT_UNIQN"
                     ORDER BY c."CASE_UNIQN" DESC LIMIT 1) AS "CASE_UNIQN"
                FROM "VISIT" v
                JOIN "PATIENT" p
                    ON v."PATIENT_UNIQN" = p."PATIENT_UNIQN"
                WHERE p."CLINIC_UNIQN" = :clinic_id
                  AND v."REGISTERED_AT" >= CURRENT_DATE
                  AND v."REGISTERED_AT" < CURRENT_DATE + INTERVAL '1 day'
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
            "visitId": row["VISIT_UNIQN"],
            "caseId": row["CASE_UNIQN"],
            "patientId": row["PATIENT_UNIQN"],
            "patientName": row["NAME"],
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
    token = request.cookies.get("hanui_session")

    if not token:
        raise HTTPException(
            status_code=401,
            detail="로그인이 필요합니다."
        )

    try:
        session_data = session_signer.loads(
            token,
            max_age=60 * 60 * 8
        )
    except (BadSignature, SignatureExpired):
        raise HTTPException(
            status_code=401,
            detail="로그인 세션이 유효하지 않습니다."
        )

    account_id = session_data.get("accountId")

    if not isinstance(account_id, int):
        raise HTTPException(
            status_code=401,
            detail="로그인 세션 정보가 올바르지 않습니다."
        )

    with engine.connect() as connection:
        account = connection.execute(
            text("""
                SELECT
                    "ACCOUNT_UNIQN",
                    "CLINIC_UNIQN",
                    "ROLE_CD",
                    "IS_OWNER",
                    "STATUS_CD"
                FROM "ACCOUNT"
                WHERE "ACCOUNT_UNIQN" = :account_id
            """),
            {"account_id": account_id}
        ).mappings().first()

    if account is None or account["STATUS_CD"] != "ACTIVE":
        raise HTTPException(
            status_code=401,
            detail="사용할 수 없는 계정입니다."
        )

    if not account["IS_OWNER"] and account["ROLE_CD"] != "DOCTOR":
        raise HTTPException(
            status_code=403,
            detail="상담일지 조회 권한이 없습니다."
        )

    if account["CLINIC_UNIQN"] is None:
        raise HTTPException(
            status_code=403,
            detail="소속 한의원 정보가 없습니다."
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
                  AND "STATUS_CD" IN ('WAITING', 'IN_PROGRESS')
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

    waiting_patients.append(new_patient)

    return {
        "message": "상담 대기 등록이 완료되었습니다.",
        "patient": new_patient
    }



class WaitingStatusUpdate(BaseModel):
    status: str
    doctor: str | None = None

from typing import Literal


class ConsultationWrite(BaseModel):
    operation: Literal["SAVE", "CORRECT"]
    symptoms: str
    consultationText: str
    additionalNotes: str | None
    diseaseSearchId: str | None
    selectedDiseaseId: int | None
    manualDiseaseText: str | None
    reason: str | None


class VisitStatusUpdate(BaseModel):
    action: Literal[
        "REGISTER_WAITING",
        "START",
        "CANCEL",
        "PAUSE",
        "RESUME",
        "CORRECT_START"
    ]
    reason: str | None = None
    consultation: ConsultationWrite | None = None


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
    if action == "PAUSE":
        if not (request.reason or "").strip():
            raise HTTPException(
                status_code=400,
                detail="상담 중단 사유를 입력해야 합니다."
            )

        if request.consultation is None:
            raise HTTPException(
                status_code=400,
                detail="상담 중단 시 상담 내용이 필요합니다."
            )

        consultation = request.consultation

        if (
            consultation.selectedDiseaseId is not None
            and consultation.manualDiseaseText is not None
        ):
            raise HTTPException(
                status_code=400,
                detail="기업 병증 선택과 직접 입력을 동시에 사용할 수 없습니다."
            )

        if consultation.operation == "CORRECT":
            if not (consultation.reason or "").strip():
                raise HTTPException(
                    status_code=400,
                    detail="상담기록 정정 사유가 필요합니다."
                )

    with engine.begin() as connection:
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
                    ORDER BY "CASE_UNIQN"
                    LIMIT 1
                """),
                {
                    "visit_id": visit_id,
                    "account_id": account_id
                }
            ).scalar_one_or_none()

            if existing_case is None:
                connection.execute(
                    text("""
                        INSERT INTO "CASE_RECORD" (
                            "VISIT_UNIQN",
                            "AUTHOR_UNIQN"
                        )
                        VALUES (
                            :visit_id,
                            :account_id
                        )
                    """),
                    {
                        "visit_id": visit_id,
                        "account_id": account_id
                    }
                )


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
                    raise HTTPException(
                        status_code=409,
                        detail="진료 중인 상담만 중단할 수 있습니다."
                    )

                consultation = request.consultation

                if consultation is None:
                    raise HTTPException(
                        status_code=400,
                        detail="상담 내용이 필요합니다."
                    )
                disease_search_id = consultation.diseaseSearchId
                selected_disease_id = consultation.selectedDiseaseId
                manual_disease_text = consultation.manualDiseaseText

                has_search = disease_search_id is not None
                has_selected = selected_disease_id is not None
                has_manual = bool(
                    manual_disease_text and manual_disease_text.strip()
                )

                if has_search != has_selected:
                    raise HTTPException(
                        status_code=400,
                        detail="병증 후보를 선택하려면 검색 ID와 병증 ID가 모두 필요합니다."
                    )

                if has_selected and has_manual:
                    raise HTTPException(
                        status_code=400,
                        detail="기업 병증 후보와 직접 입력 병증을 동시에 선택할 수 없습니다."
                    )

                if consultation.operation == "CORRECT":
                    if not (consultation.reason or "").strip():
                        raise HTTPException(
                            status_code=400,
                            detail="상담기록 정정 사유가 필요합니다."
                        )

                case = connection.execute(
                    text("""
                            SELECT
                                "CASE_UNIQN",
                                "AUTHOR_UNIQN",
                                "SYMPTOM_TEXT",
                                "CONSULTATION_TEXT",
                                "SPECIAL_NOTE"
                            FROM "CASE_RECORD"
                            WHERE "VISIT_UNIQN" = :visit_id
                            ORDER BY "CASE_UNIQN" DESC
                            LIMIT 1
                            FOR UPDATE
                        """),
                    {"visit_id": visit_id}
                ).mappings().first()

                if case is None:
                    raise HTTPException(
                        status_code=409,
                        detail="연결된 상담기록이 없습니다."
                    )

                if case["AUTHOR_UNIQN"] != account_id:
                    raise HTTPException(
                        status_code=403,
                        detail="담당 한의사의 상담기록이 아닙니다."
                    )
                full_case = connection.execute(text('SELECT * FROM "CASE_RECORD" WHERE "CASE_UNIQN"=:id FOR UPDATE'),
                    {'id':case['CASE_UNIQN']}).mappings().one()
                _write_case(connection, full_case, consultation, account_id)
                connection.execute(text('''UPDATE "VISIT" SET "STATUS_CD"='INTERRUPTED' WHERE "VISIT_UNIQN"=:id'''),
                    {'id':visit_id})

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
                            "SPECIAL_NOTE", "DISEASE_SEARCH_UNIQN", "SELECTED_DIS_UNIQN", "MANUAL_DISEASE_TEXT"
                        FROM "CASE_RECORD"
                        WHERE "VISIT_UNIQN" = :visit_id
                    """),
                {"visit_id": visit_id}
            ).mappings().all()

            for case in cases:
                if any(
                        str(case[field] or "").strip()
                        for field in (
                                "SYMPTOM_TEXT",
                                "CONSULTATION_TEXT",
                                "SPECIAL_NOTE", "DISEASE_SEARCH_UNIQN", "SELECTED_DIS_UNIQN", "MANUAL_DISEASE_TEXT"
                        )
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="상담 내용이 저장되어 시작을 정정할 수 없습니다."
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
            "caseId": row["case_id"]
        }
    }

@app.patch("/api/waiting/{patient_id}")
def update_waiting_status(
    patient_id: int,
    request: WaitingStatusUpdate,
    account=Depends(require_clinical_user)
):
    if request.status == "진료 중":
        before_status = "WAITING"
        after_status = "IN_PROGRESS"
        error_message = "대기 중인 환자만 상담을 시작할 수 있습니다."

    elif request.status == "대기":
        before_status = "IN_PROGRESS"
        after_status = "WAITING"
        error_message = "진료 중인 환자만 상담을 취소할 수 있습니다."

    else:
        raise HTTPException(
            status_code=400,
            detail="올바르지 않은 상태입니다."
        )

    with engine.begin() as connection:
        row = connection.execute(
            text("""
                UPDATE "VISIT"
                SET
                    "STATUS_CD" = CAST(:after_status AS VARCHAR),
                    "STARTED_AT" = CASE
                        WHEN CAST(:after_status AS VARCHAR) = 'IN_PROGRESS'
                        THEN CURRENT_TIMESTAMP
                        ELSE NULL
                    END,
                    "WAITING_AT" = CASE
                        WHEN CAST(:after_status AS VARCHAR) = 'WAITING'
                        THEN CURRENT_TIMESTAMP
                        ELSE "WAITING_AT"
                    END
                WHERE "VISIT_UNIQN" = (
                    SELECT "VISIT_UNIQN"
                    FROM "VISIT"
                    WHERE "PATIENT_UNIQN" = :patient_id
                      AND "STATUS_CD" = :before_status
                      AND "PATIENT_UNIQN" IN (
                          SELECT "PATIENT_UNIQN"
                          FROM "PATIENT"
                          WHERE "CLINIC_UNIQN" = :clinic_id
                      )
                    ORDER BY "VISIT_UNIQN" DESC
                    LIMIT 1
                )
                  AND "STATUS_CD" = :before_status
                RETURNING "VISIT_UNIQN"
            """),
            {
                "patient_id": patient_id,
                "before_status": before_status,
                "after_status": after_status,
                "clinic_id": account["CLINIC_UNIQN"]
            }
        ).scalar_one_or_none()

    if row is None:
        raise HTTPException(
            status_code=409,
            detail=error_message
        )

    return {
        "message": "환자 상태가 변경되었습니다.",
        "patient": {
            "id": patient_id,
            "visitId": row,
            "status": request.status,
            "doctor": request.doctor if request.status == "진료 중" else None
        }
    }




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



# Consultation persistence shared by SAVE/CORRECT/PAUSE/COMPLETE.
def _write_case(connection, case, payload, account_id):
    from sqlalchemy import bindparam
    from sqlalchemy.dialects.postgresql import JSONB
    search_id = payload.diseaseSearchId
    selected_id = payload.selectedDiseaseId
    manual = (payload.manualDiseaseText or '').strip() or None
    if (search_id is None) != (selected_id is None) or (selected_id is not None and manual):
        raise HTTPException(400, detail="병증 검색/선택 ID가 일치해야 하며 직접 입력과 동시에 선택할 수 없습니다.")
    search_int = None
    if search_id is not None:
        try:
            search_int = int(search_id)
            if str(search_int) != str(search_id):
                raise ValueError()
        except (TypeError, ValueError):
            raise HTTPException(400, detail="올바르지 않은 병증 검색 ID입니다.")
        found = connection.execute(text('''SELECT 1 FROM "SEARCH_LOG" l JOIN "SEARCH_RESULT" r
            ON r."SEARCH_UNIQN"=l."SEARCH_UNIQN"
            WHERE l."SEARCH_UNIQN"=:search AND l."CASE_UNIQN"=:case
              AND r."DIS_UNIQN"=:disease LIMIT 1'''),
            {"search":search_int,"case":case["CASE_UNIQN"],"disease":selected_id}).scalar_one_or_none()
        if found is None:
            raise HTTPException(400, detail="이 상담에서 검색한 병증 후보가 아닙니다.")
    if payload.operation == 'CORRECT' and not (payload.reason or '').strip():
        raise HTTPException(400, detail="정정 사유가 필요합니다.")
    columns = {"SYMPTOM_TEXT":payload.symptoms, "CONSULTATION_TEXT":payload.consultationText,
               "SPECIAL_NOTE":payload.additionalNotes,"DISEASE_SEARCH_UNIQN":search_int,
               "SELECTED_DIS_UNIQN":selected_id,"MANUAL_DISEASE_TEXT":manual}
    before = {key:case[key] for key in columns}
    changed = {key:val for key,val in columns.items() if before[key]!=val}
    if payload.operation == 'CORRECT' and changed:
        statement = text('''INSERT INTO "CASE_REVISION" ("CASE_UNIQN","CHANGED_FIELDS","BEFORE_VALUES",
            "AFTER_VALUES","CHANGED_BY","REASON") VALUES (:case,:fields,:before,:after,:by,:reason)''').bindparams(
                bindparam('fields',type_=JSONB),bindparam('before',type_=JSONB),bindparam('after',type_=JSONB))
        connection.execute(statement,{"case":case["CASE_UNIQN"],"fields":list(changed),
            "before":{k:before[k] for k in changed},"after":changed,"by":account_id,
            "reason":payload.reason.strip()})
    connection.execute(text('''UPDATE "CASE_RECORD" SET "SYMPTOM_TEXT"=:symptoms,
        "CONSULTATION_TEXT"=:consultation,"SPECIAL_NOTE"=:notes,
        "DISEASE_SEARCH_UNIQN"=:search,"SELECTED_DIS_UNIQN"=:disease,
        "MANUAL_DISEASE_TEXT"=:manual,"UPDATED_AT"=CURRENT_TIMESTAMP
        WHERE "CASE_UNIQN"=:case'''),{"symptoms":payload.symptoms,"consultation":payload.consultationText,
        "notes":payload.additionalNotes,"search":search_int,"disease":selected_id,
        "manual":manual,"case":case["CASE_UNIQN"]})


def _load_case_for_write(connection, case_id, account, *, allow_completed=False):
    row = connection.execute(text('''SELECT c.*, v."STATUS_CD", v."DOCTOR_UNIQN"
        FROM "CASE_RECORD" c JOIN "VISIT" v ON v."VISIT_UNIQN"=c."VISIT_UNIQN"
        JOIN "PATIENT" p ON p."PATIENT_UNIQN"=v."PATIENT_UNIQN"
        WHERE c."CASE_UNIQN"=:case AND p."CLINIC_UNIQN"=:clinic
        FOR UPDATE OF c, v'''),{"case":case_id,"clinic":account["CLINIC_UNIQN"]}).mappings().first()
    if row is None:
        raise HTTPException(404, detail="상담기록이 없습니다.")
    if row["AUTHOR_UNIQN"]!=account["ACCOUNT_UNIQN"] or row["DOCTOR_UNIQN"]!=account["ACCOUNT_UNIQN"]:
        raise HTTPException(403, detail="담당 한의사만 상담기록을 변경할 수 있습니다.")
    if row["STATUS_CD"]!='IN_PROGRESS' and not (allow_completed and row["STATUS_CD"]=='COMPLETED'):
        raise HTTPException(409, detail="현재 상태에서 상담기록을 변경할 수 없습니다.")
    return row

@app.patch('/api/consultations/{case_id}')
def patch_consultation(case_id:int, request:ConsultationWrite, account=Depends(require_authenticated_user)):
    if account['ROLE_CD']!='DOCTOR':
        raise HTTPException(403,detail='한의사 권한이 필요합니다.')
    with engine.begin() as connection:
        case=_load_case_for_write(connection,case_id,account,allow_completed=request.operation=='CORRECT')
        _write_case(connection,case,request,account['ACCOUNT_UNIQN'])
    return {'message':'상담일지가 저장되었습니다.','record':{'id':str(case_id),'caseId':case_id,
        'visitId':case['VISIT_UNIQN'],'symptoms':request.symptoms,'consultationText':request.consultationText,
        'additionalNotes':request.additionalNotes}}

@app.post('/api/consultations/{case_id}/complete')
def complete_consultation(case_id:int, request:ConsultationWrite, account=Depends(require_authenticated_user)):
    if account['ROLE_CD']!='DOCTOR':
        raise HTTPException(403,detail='한의사 권한이 필요합니다.')
    if not request.symptoms.strip() or not request.consultationText.strip():
        raise HTTPException(400,detail='진료 완료 시 증상과 상담 내용이 필요합니다.')
    with engine.begin() as connection:
        case=_load_case_for_write(connection,case_id,account)
        _write_case(connection,case,request,account['ACCOUNT_UNIQN'])
        connection.execute(text('''UPDATE "VISIT" SET "STATUS_CD"='COMPLETED',
          "COMPLETED_AT"=CURRENT_TIMESTAMP WHERE "VISIT_UNIQN"=:visit'''),{'visit':case['VISIT_UNIQN']})
        connection.execute(text('''INSERT INTO "VISIT_STATUS_HISTORY"
          ("VISIT_UNIQN","BEFORE_STATUS","AFTER_STATUS","CHANGED_BY","REASON")
          VALUES (:visit,'IN_PROGRESS','COMPLETED',:by,NULL)'''),
          {'visit':case['VISIT_UNIQN'],'by':account['ACCOUNT_UNIQN']})
    return {'message':'진료가 완료되었습니다.','record':{'caseId':case_id,'visitId':case['VISIT_UNIQN'],'status':'COMPLETED'}}

@app.get('/api/consultations/{case_id}')
def get_consultation_detail(case_id:int,account=Depends(require_authenticated_user)):
    with engine.connect() as connection:
        row=connection.execute(text('''SELECT c.*,v."PATIENT_UNIQN",p."NAME" AS "PATIENT_NAME"
          FROM "CASE_RECORD" c JOIN "VISIT" v ON v."VISIT_UNIQN"=c."VISIT_UNIQN"
          JOIN "PATIENT" p ON p."PATIENT_UNIQN"=v."PATIENT_UNIQN"
          WHERE c."CASE_UNIQN"=:case AND p."CLINIC_UNIQN"=:clinic'''),
          {'case':case_id,'clinic':account['CLINIC_UNIQN']}).mappings().first()
    if row is None: raise HTTPException(404,detail='상담기록이 없습니다.')
    return {'record':{'id':str(row['CASE_UNIQN']),'caseId':row['CASE_UNIQN'],
      'visitId':row['VISIT_UNIQN'],'patientId':row['PATIENT_UNIQN'],
      'patientName':row['PATIENT_NAME'],'symptoms':row['SYMPTOM_TEXT'] or '',
      'consultationText':row['CONSULTATION_TEXT'] or '',
      'additionalNotes':row['SPECIAL_NOTE'],
      'diseaseSearchId':str(row['DISEASE_SEARCH_UNIQN']) if row['DISEASE_SEARCH_UNIQN'] is not None else None,
      'selectedDiseaseId':row['SELECTED_DIS_UNIQN'],
      'manualDiseaseText':row['MANUAL_DISEASE_TEXT']}}

@app.get('/api/consultations/{case_id}/revisions')
def get_consultation_revisions(case_id:int,account=Depends(require_authenticated_user)):
    with engine.connect() as connection:
        exists=connection.execute(text('''SELECT 1 FROM "CASE_RECORD" c JOIN "VISIT" v ON v."VISIT_UNIQN"=c."VISIT_UNIQN"
          JOIN "PATIENT" p ON p."PATIENT_UNIQN"=v."PATIENT_UNIQN"
          WHERE c."CASE_UNIQN"=:case AND p."CLINIC_UNIQN"=:clinic'''),
          {'case':case_id,'clinic':account['CLINIC_UNIQN']}).scalar_one_or_none()
        if not exists: raise HTTPException(404,detail='상담기록이 없습니다.')
        rows=connection.execute(text('''SELECT * FROM "CASE_REVISION" WHERE "CASE_UNIQN"=:case
          ORDER BY "CHANGED_AT" DESC,"REVISION_UNIQN" DESC'''),{'case':case_id}).mappings().all()
    return {'records':[{'id':r['REVISION_UNIQN'],'changedFields':r['CHANGED_FIELDS'],
       'beforeValues':r['BEFORE_VALUES'],'afterValues':r['AFTER_VALUES'],
       'changedBy':r['CHANGED_BY'],'changedAt':r['CHANGED_AT'].isoformat(),
       'reason':r['REASON']} for r in rows]}

class ConsultationRecord(BaseModel):
    patientId: int
    symptoms: str
    selectedCandidates: list[str]
    additionalNotes: str = ""


consultation_records = []



@app.post("/api/consultations", status_code=410)
def deprecated_save_consultation():
    raise HTTPException(410,detail="기존 저장 API는 사용하지 않습니다. PATCH /api/consultations/{caseId}를 사용하세요.")


@app.get("/api/consultations")
def get_consultations(account=Depends(require_authenticated_user)):
    with engine.connect() as connection:
        rows = connection.execute(
            text("""
                SELECT
                    c."CASE_UNIQN",
                    c."VISIT_UNIQN",
                    c."SYMPTOM_TEXT",
                    c."CONSULTATION_TEXT",
                    c."SPECIAL_NOTE",
                    c."CREATED_AT",
                    v."PATIENT_UNIQN",
                    p."NAME"
                FROM "CASE_RECORD" c
                JOIN "VISIT" v
                    ON c."VISIT_UNIQN" = v."VISIT_UNIQN"
                JOIN "PATIENT" p
                    ON v."PATIENT_UNIQN" = p."PATIENT_UNIQN"
                WHERE p."CLINIC_UNIQN" = :clinic_id
                ORDER BY c."CREATED_AT" DESC, c."CASE_UNIQN" DESC
            """),
            {"clinic_id": account["CLINIC_UNIQN"]}
        ).mappings().all()

    records = [
        {
            "id": str(row["CASE_UNIQN"]),
            "patientId": row["PATIENT_UNIQN"],
            "patientName": row["NAME"],
            "symptoms": row["SYMPTOM_TEXT"] or "",
            "selectedCandidates": [
                candidate.strip()
                for candidate in (row["CONSULTATION_TEXT"] or "").split(",")
                if candidate.strip()
            ],
            "additionalNotes": row["SPECIAL_NOTE"] or "",
            "createdAt": row["CREATED_AT"].isoformat()
        }
        for row in rows
    ]

    return {"records": records}



class HerbItem(BaseModel):
    name: str
    amount: float


class PrescriptionRecord(BaseModel):
    patientId: int
    consultationId: str
    prescriptionName: str
    herbs: list[HerbItem]


# 임시 처방전 목록 (서버 재시작 시 초기화)
prescription_records = []


@app.post("/api/prescriptions", status_code=201)
def save_prescription(
    request: PrescriptionRecord,
    account=Depends(require_clinical_user)
):
    # 1. 상담일지 ID 검사
    try:
        case_id = int(request.consultationId)
        if case_id <= 0:
            raise ValueError
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=400,
            detail="상담일지 ID가 올바르지 않습니다."
        )

    # 2. 처방명 검사
    prescription_name = request.prescriptionName.strip()

    if not prescription_name:
        raise HTTPException(
            status_code=400,
            detail="처방명을 입력해 주세요."
        )

    # 3. 약재 검사
    if not request.herbs:
        raise HTTPException(
            status_code=400,
            detail="약재를 하나 이상 입력해 주세요."
        )

    herbs = []

    for herb in request.herbs:
        if (
            not herb.name.strip()
            or not math.isfinite(herb.amount)
            or herb.amount <= 0
        ):
            raise HTTPException(
                status_code=400,
                detail="약재명과 올바른 용량을 입력해 주세요."
            )

        herbs.append({
            "name": herb.name.strip(),
            "amount": herb.amount
        })

    # 4. 상담일지 확인 및 처방전 저장
    with engine.begin() as connection:
        consultation = connection.execute(
            text("""
                SELECT
                    c."CASE_UNIQN",
                    v."PATIENT_UNIQN",
                    p."NAME"
                FROM "CASE_RECORD" c
                JOIN "VISIT" v
                    ON c."VISIT_UNIQN" = v."VISIT_UNIQN"
                JOIN "PATIENT" p
                    ON v."PATIENT_UNIQN" = p."PATIENT_UNIQN"
                WHERE c."CASE_UNIQN" = :case_id
                  AND p."CLINIC_UNIQN" = :clinic_id
            """),
            {
                "case_id": case_id,
                "clinic_id": account["CLINIC_UNIQN"]
            }
        ).mappings().first()

        if consultation is None:
            raise HTTPException(
                status_code=404,
                detail="연결된 상담일지를 찾을 수 없습니다."
            )

        if consultation["PATIENT_UNIQN"] != request.patientId:
            raise HTTPException(
                status_code=400,
                detail="상담일지의 환자 정보가 일치하지 않습니다."
            )

        # 5. 처방전 기본 정보 저장
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
                "case_id": case_id,
                "author_id": account["ACCOUNT_UNIQN"]
            }
        ).scalar_one()

        # 6. 처방전 첫 번째 버전 저장
        rx_version_id = connection.execute(
            text("""
                INSERT INTO "PATIENT_PRESP_VERSION" (
                    "RX_UNIQN",
                    "VERSION_NO",
                    "PRESP_NM",
                    "PRESP_CONT",
                    "SAVED_BY"
                )
                VALUES (
                    :rx_id,
                    1,
                    :prescription_name,
                    :prescription_content,
                    :saved_by
                )
                RETURNING "RX_VERSION_UNIQN"
            """),
            {
                "rx_id": rx_id,
                "prescription_name": prescription_name,
                "prescription_content": json.dumps(
                    herbs,
                    ensure_ascii=False
                ),
                "saved_by": account["ACCOUNT_UNIQN"]
            }
        ).scalar_one()

    # 7. 기존 응답 형식 유지
    record = {
        "id": str(rx_id),
        "rxVersionId": rx_version_id,
        "patientId": request.patientId,
        "consultationId": request.consultationId,
        "prescriptionName": prescription_name,
        "herbs": herbs,
        "patientName": consultation["NAME"],
        "status": "미전송",
        "createdAt": datetime.now().astimezone().isoformat()
    }

    return {
        "message": "처방전이 저장되었습니다.",
        "record": record
    }


@app.get("/api/prescriptions")
def get_prescriptions(
    account=Depends(require_authenticated_user)
):
    is_desk = (
        not account["IS_OWNER"]
        and account["ROLE_CD"] == "DESK"
    )

    with engine.connect() as connection:
        rows = connection.execute(
            text("""
                SELECT
                    p."RX_UNIQN",
                    p."CASE_UNIQN",
                    p."CREATED_AT",
                    v."RX_VERSION_UNIQN",
                    v."PRESP_NM",
                    v."PRESP_CONT",
                    patient."PATIENT_UNIQN",
                    patient."NAME",
                    d."DELIVERY_UNIQN"
                FROM "PATIENT_PRESP" p
                JOIN "CASE_RECORD" c
                    ON p."CASE_UNIQN" = c."CASE_UNIQN"
                JOIN "VISIT" visit
                    ON c."VISIT_UNIQN" = visit."VISIT_UNIQN"
                JOIN "PATIENT" patient
                    ON visit."PATIENT_UNIQN" = patient."PATIENT_UNIQN"
                JOIN LATERAL (
                    SELECT
                        pv."RX_VERSION_UNIQN",
                        pv."PRESP_NM",
                        pv."PRESP_CONT"
                    FROM "PATIENT_PRESP_VERSION" pv
                    WHERE pv."RX_UNIQN" = p."RX_UNIQN"
                    ORDER BY pv."VERSION_NO" DESC,
                             pv."RX_VERSION_UNIQN" DESC
                    LIMIT 1
                ) v ON TRUE
                LEFT JOIN "PRESP_DELIVERY" d
                    ON d."RX_VERSION_UNIQN" = v."RX_VERSION_UNIQN"
                WHERE patient."CLINIC_UNIQN" = :clinic_id
                  AND p."IS_DELETED" = FALSE
                  AND (
                      :is_desk = FALSE
                      OR d."DELIVERY_UNIQN" IS NOT NULL
                  )
                ORDER BY p."CREATED_AT" DESC, p."RX_UNIQN" DESC
            """),
            {
                "clinic_id": account["CLINIC_UNIQN"],
                "is_desk": is_desk
            }
        ).mappings().all()

    records = []

    for row in rows:
        try:
            herbs = json.loads(row["PRESP_CONT"] or "[]")
        except (json.JSONDecodeError, TypeError):
            herbs = []

        records.append({
            "id": str(row["RX_UNIQN"]),
            "rxVersionId": row["RX_VERSION_UNIQN"],
            "patientId": row["PATIENT_UNIQN"],
            "consultationId": str(row["CASE_UNIQN"]),
            "patientName": row["NAME"],
            "prescriptionName": row["PRESP_NM"] or "",
            "herbs": herbs,
            "status": (
                "전송완료"
                if row["DELIVERY_UNIQN"] is not None
                else "미전송"
            ),
            "createdAt": row["CREATED_AT"].isoformat()
        })

    return {"records": records}

@app.post("/api/prescriptions/{prescription_id}/send")
def send_prescription(
    prescription_id: int,
    account=Depends(require_clinical_user)
):
    with engine.begin() as connection:
        # 동일 처방전의 동시 전송 요청 방지
        prescription = connection.execute(
            text("""
                SELECT
                    p."RX_UNIQN",
                    v."RX_VERSION_UNIQN"
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
                    ORDER BY "VERSION_NO" DESC,
                             "RX_VERSION_UNIQN" DESC
                    LIMIT 1
                ) v ON TRUE
                WHERE p."RX_UNIQN" = :prescription_id
                  AND patient."CLINIC_UNIQN" = :clinic_id
                  AND p."IS_DELETED" = FALSE
                FOR UPDATE OF p
            """),
            {
                "prescription_id": prescription_id,
                "clinic_id": account["CLINIC_UNIQN"]
            }
        ).mappings().first()

        if prescription is None:
            raise HTTPException(
                status_code=404,
                detail="전송할 처방전을 찾을 수 없습니다."
            )

        rx_version_id = prescription["RX_VERSION_UNIQN"]

        # 이미 전송된 버전인지 확인
        existing_delivery = connection.execute(
            text("""
                SELECT "DELIVERY_UNIQN"
                FROM "PRESP_DELIVERY"
                WHERE "RX_VERSION_UNIQN" = :rx_version_id
                LIMIT 1
            """),
            {"rx_version_id": rx_version_id}
        ).scalar_one_or_none()

        if existing_delivery is not None:
            raise HTTPException(
                status_code=409,
                detail="이미 전송된 처방전입니다."
            )

        # 전송 기록 저장
        delivery_id = connection.execute(
            text("""
                INSERT INTO "PRESP_DELIVERY" (
                    "RX_VERSION_UNIQN",
                    "SENT_BY",
                    "STATUS_CD"
                )
                VALUES (
                    :rx_version_id,
                    :sent_by,
                    'SENT'
                )
                RETURNING "DELIVERY_UNIQN"
            """),
            {
                "rx_version_id": rx_version_id,
                "sent_by": account["ACCOUNT_UNIQN"]
            }
        ).scalar_one()

    return {
        "message": "처방전이 안내데스크로 전송되었습니다.",
        "deliveryId": delivery_id,
        "prescriptionId": prescription_id,
        "rxVersionId": rx_version_id,
        "status": "전송완료"
    }


@app.patch("/api/prescriptions/{prescription_id}")
def update_prescription(
    prescription_id: int,
    request: PrescriptionRecord,
    account=Depends(require_clinical_user)
):
    try:
        case_id = int(request.consultationId)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=400,
            detail="상담일지 ID가 올바르지 않습니다."
        )

    prescription_name = request.prescriptionName.strip()

    if not prescription_name:
        raise HTTPException(
            status_code=400,
            detail="처방명을 입력해 주세요."
        )

    if not request.herbs:
        raise HTTPException(
            status_code=400,
            detail="약재를 하나 이상 입력해 주세요."
        )

    herbs = []

    for herb in request.herbs:
        if (
            not herb.name.strip()
            or not math.isfinite(herb.amount)
            or herb.amount <= 0
        ):
            raise HTTPException(
                status_code=400,
                detail="약재명과 올바른 용량을 입력해 주세요."
            )

        herbs.append({
            "name": herb.name.strip(),
            "amount": herb.amount
        })

    with engine.begin() as connection:
        prescription = connection.execute(
            text("""
                SELECT
                    p."RX_UNIQN",
                    p."CASE_UNIQN",
                    p."CREATED_AT",
                    patient."PATIENT_UNIQN",
                    patient."NAME"
                FROM "PATIENT_PRESP" p
                JOIN "CASE_RECORD" c
                    ON p."CASE_UNIQN" = c."CASE_UNIQN"
                JOIN "VISIT" visit
                    ON c."VISIT_UNIQN" = visit."VISIT_UNIQN"
                JOIN "PATIENT" patient
                    ON visit."PATIENT_UNIQN" = patient."PATIENT_UNIQN"
                WHERE p."RX_UNIQN" = :prescription_id
                  AND patient."CLINIC_UNIQN" = :clinic_id
                  AND p."IS_DELETED" = FALSE
                FOR UPDATE OF p
            """),
            {
                "prescription_id": prescription_id,
                "clinic_id": account["CLINIC_UNIQN"]
            }
        ).mappings().first()

        if prescription is None:
            raise HTTPException(
                status_code=404,
                detail="처방전을 찾을 수 없습니다."
            )

        if (
            prescription["PATIENT_UNIQN"] != request.patientId
            or prescription["CASE_UNIQN"] != case_id
        ):
            raise HTTPException(
                status_code=400,
                detail="처방전의 환자 또는 상담 기록을 변경할 수 없습니다."
            )

        latest_version = connection.execute(
            text("""
                SELECT
                    "RX_VERSION_UNIQN",
                    "VERSION_NO"
                FROM "PATIENT_PRESP_VERSION"
                WHERE "RX_UNIQN" = :prescription_id
                ORDER BY "VERSION_NO" DESC,
                         "RX_VERSION_UNIQN" DESC
                LIMIT 1
            """),
            {"prescription_id": prescription_id}
        ).mappings().first()

        if latest_version is None:
            raise HTTPException(
                status_code=404,
                detail="처방전 버전을 찾을 수 없습니다."
            )

        existing_delivery = connection.execute(
            text("""
                SELECT 1
                FROM "PRESP_DELIVERY" d
                JOIN "PATIENT_PRESP_VERSION" v
                    ON d."RX_VERSION_UNIQN" = v."RX_VERSION_UNIQN"
                WHERE v."RX_UNIQN" = :prescription_id
                LIMIT 1
            """),
            {"prescription_id": prescription_id}
        ).scalar_one_or_none()

        if existing_delivery is not None:
            raise HTTPException(
                status_code=409,
                detail="전송된 처방전은 수정할 수 없습니다."
            )

        new_version_id = connection.execute(
            text("""
                INSERT INTO "PATIENT_PRESP_VERSION" (
                    "RX_UNIQN",
                    "VERSION_NO",
                    "PRESP_NM",
                    "PRESP_CONT",
                    "SAVED_BY"
                )
                VALUES (
                    :prescription_id,
                    :version_no,
                    :prescription_name,
                    :prescription_content,
                    :saved_by
                )
                RETURNING "RX_VERSION_UNIQN"
            """),
            {
                "prescription_id": prescription_id,
                "version_no": latest_version["VERSION_NO"] + 1,
                "prescription_name": prescription_name,
                "prescription_content": json.dumps(
                    herbs,
                    ensure_ascii=False
                ),
                "saved_by": account["ACCOUNT_UNIQN"]
            }
        ).scalar_one()

    return {
        "message": "처방전이 수정되었습니다.",
        "record": {
            "id": str(prescription_id),
            "rxVersionId": new_version_id,
            "patientId": request.patientId,
            "consultationId": str(case_id),
            "patientName": prescription["NAME"],
            "prescriptionName": prescription_name,
            "herbs": herbs,
            "status": "미전송",
            "createdAt": prescription["CREATED_AT"].isoformat()
        }
    }



@app.delete("/api/prescriptions/{prescription_id}")
def delete_prescription(
    prescription_id: int,
    account=Depends(require_clinical_user)
):
    with engine.begin() as connection:
        prescription = connection.execute(
            text("""
                SELECT p."RX_UNIQN"
                FROM "PATIENT_PRESP" p
                JOIN "CASE_RECORD" c
                    ON p."CASE_UNIQN" = c."CASE_UNIQN"
                JOIN "VISIT" v
                    ON c."VISIT_UNIQN" = v."VISIT_UNIQN"
                JOIN "PATIENT" patient
                    ON v."PATIENT_UNIQN" = patient."PATIENT_UNIQN"
                WHERE p."RX_UNIQN" = :prescription_id
                  AND patient."CLINIC_UNIQN" = :clinic_id
                  AND p."IS_DELETED" = FALSE
                FOR UPDATE OF p
            """),
            {
                "prescription_id": prescription_id,
                "clinic_id": account["CLINIC_UNIQN"]
            }
        ).scalar_one_or_none()

        if prescription is None:
            raise HTTPException(
                status_code=404,
                detail="삭제할 처방전을 찾을 수 없습니다."
            )

        existing_delivery = connection.execute(
            text("""
                SELECT 1
                FROM "PRESP_DELIVERY" d
                JOIN "PATIENT_PRESP_VERSION" pv
                    ON d."RX_VERSION_UNIQN" = pv."RX_VERSION_UNIQN"
                WHERE pv."RX_UNIQN" = :prescription_id
                LIMIT 1
            """),
            {"prescription_id": prescription_id}
        ).scalar_one_or_none()

        if existing_delivery is not None:
            raise HTTPException(
                status_code=409,
                detail="전송된 처방전은 삭제할 수 없습니다."
            )

        connection.execute(
            text("""
                UPDATE "PATIENT_PRESP"
                SET
                    "IS_DELETED" = TRUE,
                    "DELETED_AT" = CURRENT_TIMESTAMP,
                    "DELETED_BY" = :account_id
                WHERE "RX_UNIQN" = :prescription_id
                  AND "IS_DELETED" = FALSE
            """),
            {
                "prescription_id": prescription_id,
                "account_id": account["ACCOUNT_UNIQN"]
            }
        )

    return {
        "message": "처방전이 삭제되었습니다."
    }

class LoginRequest(BaseModel):
    email: str
    password: str


@app.post("/api/auth/login")
def login(request: LoginRequest, response: Response):
    with engine.connect() as connection:
        account = connection.execute(
            text("""
                SELECT
                    "ACCOUNT_UNIQN",
                    "CLINIC_UNIQN",
                    "EMAIL",
                    "PASSWORD_HASH",
                    "ROLE_CD",
                    "IS_OWNER",
                    "STATUS_CD"
                FROM "ACCOUNT"
                WHERE LOWER("EMAIL") = LOWER(:email)
            """),
            {"email": request.email.strip()}
        ).mappings().first()

    if (
        account is None
        or account["STATUS_CD"] != "ACTIVE"
        or not verify_password(
            request.password,
            account["PASSWORD_HASH"]
        )
    ):
        raise HTTPException(
            status_code=401,
            detail="이메일 또는 비밀번호가 올바르지 않습니다."
        )

    session_token = session_signer.dumps({
        "accountId": account["ACCOUNT_UNIQN"]
    })

    response.set_cookie(
        key="hanui_session",
        value=session_token,
        httponly=True,
        secure=False,  # 로컬 HTTP 개발 환경에서만 사용
        samesite="lax",
        max_age=60 * 60 * 8,
        path="/"
    )

    return {
        "message": "계정 정보가 확인되었습니다.",
        "account": {
            "id": account["ACCOUNT_UNIQN"],
            "clinicId": account["CLINIC_UNIQN"],
            "email": account["EMAIL"],
            "role": "DIRECTOR" if account["IS_OWNER"] else account["ROLE_CD"]
        }
    }

@app.get("/api/auth/me")
def get_current_user(request: Request):
    token = request.cookies.get("hanui_session")

    if not token:
        raise HTTPException(
            status_code=401,
            detail="로그인이 필요합니다."
        )

    try:
        session_data = session_signer.loads(
            token,
            max_age=60 * 60 * 8
        )
    except (BadSignature, SignatureExpired):
        raise HTTPException(
            status_code=401,
            detail="로그인 세션이 유효하지 않습니다."
        )

    with engine.connect() as connection:
        account = connection.execute(
            text("""
                SELECT
                    "ACCOUNT_UNIQN",
                    "CLINIC_UNIQN",
                    "EMAIL",
                    "ROLE_CD",
                    "IS_OWNER",
                    "STATUS_CD"
                FROM "ACCOUNT"
                WHERE "ACCOUNT_UNIQN" = :account_id
            """),
            {"account_id": session_data["accountId"]}
        ).mappings().first()

    if account is None or account["STATUS_CD"] != "ACTIVE":
        raise HTTPException(
            status_code=401,
            detail="사용할 수 없는 계정입니다."
        )

    return {
        "id": account["ACCOUNT_UNIQN"],
        "clinicId": account["CLINIC_UNIQN"],
        "email": account["EMAIL"],
        "role": "DIRECTOR" if account["IS_OWNER"] else account["ROLE_CD"]
    }

@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(
        key="hanui_session",
        path="/",
        samesite="lax",
        secure=False
    )

    return {
        "message": "로그아웃되었습니다."
    }