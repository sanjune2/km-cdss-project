import json
import math
from staff import create_staff_router
from fastapi import Depends
from fastapi import Request
from itsdangerous import BadSignature, SignatureExpired
import os
from pathlib import Path
from dotenv import load_dotenv
from itsdangerous import URLSafeTimedSerializer
from fastapi import Response
from auth import verify_password, hash_password
from models import Patient
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from sqlalchemy import text
from database import engine


load_dotenv(Path(__file__).resolve().parent / ".env")

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

app.include_router(
    create_staff_router(require_authenticated_user)
)

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
                    p."NAME"
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
    account = require_authenticated_user(request)

    if not account["IS_OWNER"] and account["ROLE_CD"] != "DOCTOR":
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
    action: str
    reason: str | None = None
    consultation: dict | None = None


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
                raise HTTPException(status_code=409, detail="진료 중인 상담만 중단할 수 있습니다.")
            if not (request.reason or "").strip():
                raise HTTPException(status_code=400, detail="중단 사유가 필요합니다.")
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
                            "SPECIAL_NOTE"
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
                                "SPECIAL_NOTE"
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
def update_waiting_status(patient_id: int, request: WaitingStatusUpdate,
                          account=Depends(require_clinical_user)):
    if request.status not in ("진료 중", "대기"):
        raise HTTPException(status_code=400, detail="올바르지 않은 상태입니다.")
    starting = request.status == "진료 중"
    before = "WAITING" if starting else "IN_PROGRESS"
    after = "IN_PROGRESS" if starting else "WAITING"
    with engine.begin() as connection:
        visit = connection.execute(text('''
            SELECT v."VISIT_UNIQN", v."DOCTOR_UNIQN" FROM "VISIT" v
            JOIN "PATIENT" p ON p."PATIENT_UNIQN" = v."PATIENT_UNIQN"
            WHERE v."PATIENT_UNIQN" = :patient_id
              AND p."CLINIC_UNIQN" = :clinic_id AND v."STATUS_CD" = :before
            ORDER BY v."VISIT_UNIQN" DESC LIMIT 1 FOR UPDATE OF v
        '''), {"patient_id": patient_id, "clinic_id": account["CLINIC_UNIQN"],
                "before": before}).mappings().first()
        if visit is None:
            raise HTTPException(status_code=409, detail="현재 상태에서는 변경할 수 없습니다.")
        if not starting and visit["DOCTOR_UNIQN"] != account["ACCOUNT_UNIQN"]:
            raise HTTPException(status_code=403, detail="담당 한의사만 상담을 취소할 수 있습니다.")
        connection.execute(text('''
            UPDATE "VISIT" SET "STATUS_CD" = :after,
                "DOCTOR_UNIQN" = :doctor_id,
                "STARTED_AT" = CASE WHEN :starting THEN CURRENT_TIMESTAMP ELSE NULL END,
                "WAITING_AT" = CASE WHEN :starting THEN "WAITING_AT" ELSE CURRENT_TIMESTAMP END
            WHERE "VISIT_UNIQN" = :visit_id
        '''), {"after": after, "doctor_id": account["ACCOUNT_UNIQN"] if starting else None,
                "starting": starting, "visit_id": visit["VISIT_UNIQN"]})
        connection.execute(text('''
            INSERT INTO "VISIT_STATUS_HISTORY"
                ("VISIT_UNIQN", "BEFORE_STATUS", "AFTER_STATUS", "CHANGED_BY", "REASON")
            VALUES (:visit_id, :before, :after, :changed_by, NULL)
        '''), {"visit_id": visit["VISIT_UNIQN"], "before": before,
                "after": after, "changed_by": account["ACCOUNT_UNIQN"]})
    return {"message": "환자 상태가 변경되었습니다.", "patient": {
        "id": patient_id, "visitId": visit["VISIT_UNIQN"], "status": request.status,
        "doctor": request.doctor if starting else None}}


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





@app.post("/api/consultations", status_code=201)
def save_consultation(
    request: ConsultationRecord,
    account=Depends(require_clinical_user)
):
    if not request.symptoms.strip():
        raise HTTPException(
            status_code=400,
            detail="증상을 입력해 주세요."
        )

    with engine.begin() as connection:
        patient = connection.execute(
            text("""
                SELECT
                    p."NAME",
                    v."VISIT_UNIQN"
                FROM "VISIT" v
                JOIN "PATIENT" p
                    ON v."PATIENT_UNIQN" = p."PATIENT_UNIQN"
                WHERE v."PATIENT_UNIQN" = :patient_id
                  AND p."CLINIC_UNIQN" = :clinic_id
                  AND v."STATUS_CD" = 'IN_PROGRESS'
                  AND v."DOCTOR_UNIQN" = :doctor_id
                ORDER BY v."VISIT_UNIQN" DESC
                LIMIT 1
                FOR UPDATE OF v
            """),
            {
                "patient_id": request.patientId,
                "clinic_id": account["CLINIC_UNIQN"],
                "doctor_id": account["ACCOUNT_UNIQN"]
            }
        ).mappings().first()

        if patient is None:
            raise HTTPException(
                status_code=409,
                detail="진료 중인 환자만 상담일지를 저장할 수 있습니다."
            )

        existing_case_id = connection.execute(
            text('''SELECT "CASE_UNIQN" FROM "CASE_RECORD"
                    WHERE "VISIT_UNIQN" = :visit_id AND "AUTHOR_UNIQN" = :author_id
                    ORDER BY "CASE_UNIQN" DESC LIMIT 1'''),
            {"visit_id": patient["VISIT_UNIQN"], "author_id": account["ACCOUNT_UNIQN"]}
        ).scalar_one_or_none()
        values = {
            "visit_id": patient["VISIT_UNIQN"],
            "author_id": account["ACCOUNT_UNIQN"],
            "symptoms": request.symptoms.strip(),
            "consultation_text": ", ".join(request.selectedCandidates),
            "special_note": request.additionalNotes.strip()
        }
        if existing_case_id is None:
            case_id = connection.execute(text('''
                INSERT INTO "CASE_RECORD" ("VISIT_UNIQN", "AUTHOR_UNIQN", "SYMPTOM_TEXT", "CONSULTATION_TEXT", "SPECIAL_NOTE")
                VALUES (:visit_id, :author_id, :symptoms, :consultation_text, :special_note)
                RETURNING "CASE_UNIQN"
            '''), values).scalar_one()
        else:
            case_id = existing_case_id
            connection.execute(text('''
                UPDATE "CASE_RECORD" SET "SYMPTOM_TEXT" = :symptoms,
                    "CONSULTATION_TEXT" = :consultation_text, "SPECIAL_NOTE" = :special_note
                WHERE "CASE_UNIQN" = :case_id
            '''), {**values, "case_id": case_id})

        connection.execute(
            text("""
                UPDATE "VISIT"
                SET
                    "STATUS_CD" = 'COMPLETED',
                    "COMPLETED_AT" = CURRENT_TIMESTAMP
                WHERE "VISIT_UNIQN" = :visit_id
            """),
            {"visit_id": patient["VISIT_UNIQN"]}
        )

    record = {
        "id": str(case_id),
        **request.model_dump(),
        "patientName": patient["NAME"],
        "createdAt": datetime.now().astimezone().isoformat()
    }


    return {
        "message": "상담일지가 저장되었습니다.",
        "record": record
    }



@app.get("/api/consultations")
def get_consultations(account=Depends(require_clinical_user)):
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

@app.post("/api/prescriptions/{prescription_id}/print", status_code=201)
def record_prescription_print(
    prescription_id: int,
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

    if account["CLINIC_UNIQN"] is None:
        raise HTTPException(status_code=403, detail="소속 한의원 정보가 없습니다.")

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
            "role": account["ROLE_CD"],
            "isOwner": bool(account["IS_OWNER"])
        }
    }

@app.get("/api/auth/me")
def get_current_user(account=Depends(require_authenticated_user)):
    return {
        "id": account["ACCOUNT_UNIQN"],
        "clinicId": account["CLINIC_UNIQN"],
        "role": account["ROLE_CD"],
        "isOwner": bool(account["IS_OWNER"])
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

    return {
        "message": "비밀번호가 변경되었습니다."
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