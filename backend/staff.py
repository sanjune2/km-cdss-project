
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from auth import hash_password
from database import engine
from invitation_email import invitation_link, send_staff_invitation


class InviteRequest(BaseModel):
    email: EmailStr
    role: str


class RegisterRequest(BaseModel):
    token: str
    name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=128)
    phone: str | None = None


class RoleRequest(BaseModel):
    role: str


def create_staff_router(auth_dependency: Callable):
    router = APIRouter(prefix="/api/staff", tags=["직원 관리"])

    def require_owner(account=Depends(auth_dependency)):
        if not account["IS_OWNER"]:
            raise HTTPException(
                status_code=403,
                detail="원장만 직원 관리 기능을 사용할 수 있습니다."
            )
        return account

    def validate_role(role):
        if role not in ("DOCTOR", "DESK"):
            raise HTTPException(
                status_code=400,
                detail="직책은 DOCTOR 또는 DESK여야 합니다."
            )

    def find_staff(connection, staff_id, clinic_id):
        staff = connection.execute(
            text("""
                SELECT "ACCOUNT_UNIQN", "IS_OWNER", "STATUS_CD"
                FROM "ACCOUNT"
                WHERE "ACCOUNT_UNIQN" = :staff_id
                  AND "CLINIC_UNIQN" = :clinic_id
                FOR UPDATE
            """),
            {"staff_id": staff_id, "clinic_id": clinic_id}
        ).mappings().first()

        if not staff:
            raise HTTPException(404, "직원을 찾을 수 없습니다.")

        if staff["IS_OWNER"]:
            raise HTTPException(403, "원장 계정은 변경할 수 없습니다.")

        if staff["STATUS_CD"] == "DELETED":
            raise HTTPException(409, "삭제된 계정입니다.")

        return staff

    @router.get("")
    def list_staff(account=Depends(require_owner)):
        clinic_id = account["CLINIC_UNIQN"]

        with engine.connect() as connection:
            staff = connection.execute(
                text("""
                    SELECT "ACCOUNT_UNIQN", "EMAIL", "NAME",
                           "PHONE", "ROLE_CD", "IS_OWNER",
                           "STATUS_CD", "CREATED_AT"
                    FROM "ACCOUNT"
                    WHERE "CLINIC_UNIQN" = :clinic_id
                      AND "STATUS_CD" <> 'DELETED'
                    ORDER BY "CREATED_AT" DESC
                """),
                {"clinic_id": clinic_id}
            ).mappings().all()

            invitations = connection.execute(
                text("""
                    SELECT "INVITE_UNIQN", "EMAIL", "ROLE_CD",
                           "STATUS_CD", "CREATED_AT", "EXPIRES_AT"
                    FROM "INVITATION"
                    WHERE "CLINIC_UNIQN" = :clinic_id
                      AND "STATUS_CD" = 'PENDING'
                    ORDER BY "CREATED_AT" DESC
                """),
                {"clinic_id": clinic_id}
            ).mappings().all()

        return {
            "staff": [
                {
                    "id": s["ACCOUNT_UNIQN"],
                    "email": s["EMAIL"],
                    "name": s["NAME"],
                    "phone": s["PHONE"],
                    "role": s["ROLE_CD"],
                    "isOwner": s["IS_OWNER"],
                    "status": s["STATUS_CD"],
                }
                for s in staff
            ],
            "invitations": [
                {
                    "id": i["INVITE_UNIQN"],
                    "email": i["EMAIL"],
                    "role": i["ROLE_CD"],
                    "status": (
                        "EXPIRED"
                        if i["EXPIRES_AT"] <= datetime.now(timezone.utc)
                        else "PENDING"
                    ),
                }
                for i in invitations
            ]
        }

    @router.post("/invitations", status_code=201)
    def invite_staff(
        payload: InviteRequest,
        account=Depends(require_owner)
    ):
        validate_role(payload.role)
        email = payload.email.strip().lower()
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)

        with engine.begin() as connection:
            existing = connection.execute(
                text("""
                    SELECT 1 FROM "ACCOUNT"
                    WHERE LOWER("EMAIL") = :email
                """),
                {"email": email}
            ).first()

            if existing:
                raise HTTPException(409, "이미 등록된 이메일입니다.")

            pending = connection.execute(
                text("""
                    SELECT 1 FROM "INVITATION"
                    WHERE "CLINIC_UNIQN" = :clinic_id
                      AND LOWER("EMAIL") = :email
                      AND "STATUS_CD" = 'PENDING'
                      AND "EXPIRES_AT" > CURRENT_TIMESTAMP
                """),
                {
                    "clinic_id": account["CLINIC_UNIQN"],
                    "email": email
                }
            ).first()

            if pending:
                raise HTTPException(409, "유효한 초대가 이미 존재합니다.")

            invite_id = connection.execute(
                text("""
                    INSERT INTO "INVITATION" (
                        "CLINIC_UNIQN", "EMAIL", "ROLE_CD",
                        "TOKEN_HASH", "STATUS_CD",
                        "INVITED_BY", "EXPIRES_AT"
                    )
                    VALUES (
                        :clinic_id, :email, :role,
                        :token_hash, 'PENDING',
                        :invited_by, :expires_at
                    )
                    RETURNING "INVITE_UNIQN"
                """),
                {
                    "clinic_id": account["CLINIC_UNIQN"],
                    "email": email,
                    "role": payload.role,
                    "token_hash": token_hash,
                    "invited_by": account["ACCOUNT_UNIQN"],
                    "expires_at": expires_at
                }
            ).scalar_one()

        link = invitation_link(token)
        delivery = send_staff_invitation(email, link)
        return {
            "message": "초대 링크가 생성되었습니다.",
            "invitationId": invite_id,
            "token": token,
            "registrationUrl": link,
            "emailDelivery": delivery,
            "expiresAt": expires_at.isoformat()
        }

    @router.get("/invitations/verify")
    def verify_invitation(token: str):
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        with engine.connect() as connection:
            invitation = connection.execute(
                text("""
                    SELECT "EMAIL", "ROLE_CD"
                    FROM "INVITATION"
                    WHERE "TOKEN_HASH" = :token_hash
                      AND "STATUS_CD" = 'PENDING'
                      AND "EXPIRES_AT" > CURRENT_TIMESTAMP
                """),
                {"token_hash": token_hash}
            ).mappings().first()

        if not invitation:
            raise HTTPException(400, "유효하지 않거나 만료된 초대입니다.")

        return {
            "email": invitation["EMAIL"],
            "role": invitation["ROLE_CD"]
        }

    @router.post("/register", status_code=201)
    def register_staff(payload: RegisterRequest):
        token_hash = hashlib.sha256(
            payload.token.encode()
        ).hexdigest()

        try:
            with engine.begin() as connection:
                invitation = connection.execute(
                    text("""
                        SELECT "INVITE_UNIQN", "CLINIC_UNIQN",
                               "EMAIL", "ROLE_CD"
                        FROM "INVITATION"
                        WHERE "TOKEN_HASH" = :token_hash
                          AND "STATUS_CD" = 'PENDING'
                          AND "EXPIRES_AT" > CURRENT_TIMESTAMP
                        FOR UPDATE
                    """),
                    {"token_hash": token_hash}
                ).mappings().first()

                if not invitation:
                    raise HTTPException(
                        400, "유효하지 않거나 만료된 초대입니다."
                    )

                account_id = connection.execute(
                    text("""
                        INSERT INTO "ACCOUNT" (
                            "CLINIC_UNIQN", "EMAIL",
                            "PASSWORD_HASH", "NAME", "PHONE",
                            "ROLE_CD", "IS_OWNER", "STATUS_CD"
                        )
                        VALUES (
                            :clinic_id, :email,
                            :password_hash, :name, :phone,
                            :role, FALSE, 'PENDING'
                        )
                        RETURNING "ACCOUNT_UNIQN"
                    """),
                    {
                        "clinic_id": invitation["CLINIC_UNIQN"],
                        "email": invitation["EMAIL"],
                        "password_hash": hash_password(payload.password),
                        "name": payload.name.strip(),
                        "phone": payload.phone,
                        "role": invitation["ROLE_CD"]
                    }
                ).scalar_one()

                connection.execute(
                    text("""
                        UPDATE "INVITATION"
                        SET "STATUS_CD" = 'USED',
                            "USED_BY" = :account_id
                        WHERE "INVITE_UNIQN" = :invite_id
                    """),
                    {
                        "account_id": account_id,
                        "invite_id": invitation["INVITE_UNIQN"]
                    }
                )
        except IntegrityError:
            raise HTTPException(
                409, "이미 등록된 계정이거나 DB 제약조건에 맞지 않습니다."
            )

        return {"message": "가입되었습니다. 원장 승인을 기다려 주세요."}

    @router.patch("/{staff_id}/approve")
    def approve_staff(
        staff_id: int,
        account=Depends(require_owner)
    ):
        with engine.begin() as connection:
            staff = find_staff(
                connection, staff_id, account["CLINIC_UNIQN"]
            )

            if staff["STATUS_CD"] != "PENDING":
                raise HTTPException(409, "승인대기 계정이 아닙니다.")

            connection.execute(
                text("""
                    UPDATE "ACCOUNT"
                    SET "STATUS_CD" = 'ACTIVE'
                    WHERE "ACCOUNT_UNIQN" = :staff_id
                """),
                {"staff_id": staff_id}
            )

        return {"message": "직원 승인이 완료되었습니다."}

    @router.patch("/{staff_id}/role")
    def change_staff_role(
        staff_id: int,
        payload: RoleRequest,
        account=Depends(require_owner)
    ):
        validate_role(payload.role)

        with engine.begin() as connection:
            find_staff(connection, staff_id, account["CLINIC_UNIQN"])

            connection.execute(
                text("""
                    UPDATE "ACCOUNT"
                    SET "ROLE_CD" = :role
                    WHERE "ACCOUNT_UNIQN" = :staff_id
                """),
                {"role": payload.role, "staff_id": staff_id}
            )

        return {"message": "직무가 변경되었습니다."}

    @router.patch("/{staff_id}/suspend")
    def suspend_staff(
        staff_id: int,
        account=Depends(require_owner)
    ):
        with engine.begin() as connection:
            staff = find_staff(
                connection, staff_id, account["CLINIC_UNIQN"]
            )

            if staff["STATUS_CD"] != "ACTIVE":
                raise HTTPException(409, "활성 직원만 이용중지할 수 있습니다.")

            connection.execute(
                text("""
                    UPDATE "ACCOUNT"
                    SET "STATUS_CD" = 'SUSPENDED'
                    WHERE "ACCOUNT_UNIQN" = :staff_id
                """),
                {"staff_id": staff_id}
            )

        return {"message": "직원 이용이 중지되었습니다."}

    @router.patch("/{staff_id}/resume")
    def resume_staff(
            staff_id: int,
            account=Depends(require_owner)
    ):
        with engine.begin() as connection:
            staff = find_staff(
                connection, staff_id, account["CLINIC_UNIQN"]
            )

            if staff["STATUS_CD"] != "SUSPENDED":
                raise HTTPException(
                    409,
                    "이용중지된 직원만 이용재개할 수 있습니다."
                )

            connection.execute(
                text("""
                    UPDATE "ACCOUNT"
                    SET "STATUS_CD" = 'ACTIVE'
                    WHERE "ACCOUNT_UNIQN" = :staff_id
                """),
                {"staff_id": staff_id}
            )

        return {"message": "직원 이용이 재개되었습니다."}

    @router.delete("/{staff_id}")
    def delete_staff(
        staff_id: int,
        account=Depends(require_owner)
    ):
        with engine.begin() as connection:
            find_staff(connection, staff_id, account["CLINIC_UNIQN"])

            connection.execute(
                text("""
                    UPDATE "ACCOUNT"
                    SET "STATUS_CD" = 'DELETED'
                    WHERE "ACCOUNT_UNIQN" = :staff_id
                """),
                {"staff_id": staff_id}
            )

        return {"message": "직원이 삭제 처리되었습니다."}

    return router
