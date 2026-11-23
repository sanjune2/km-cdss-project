"""Staff invitation lifecycle against PostgreSQL temporary tables only."""
from contextlib import ExitStack, contextmanager
import os
import unittest
from unittest.mock import patch


@unittest.skipUnless(os.getenv("HANUI_RUN_POSTGRES_TESTS") == "1", "requires local PostgreSQL")
class StaffInvitationLifecycleTests(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from sqlalchemy import text
        import staff
        from database import engine

        self.staff, self.text = staff, text
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.connection = stack.enter_context(engine.connect())
        transaction = stack.enter_context(self.connection.begin())
        stack.callback(transaction.rollback)
        for table, column in (("ACCOUNT", "ACCOUNT_UNIQN"), ("INVITATION", "INVITE_UNIQN")):
            self.sql(f'CREATE TEMP TABLE "{table}" (LIKE public."{table}" INCLUDING DEFAULTS) ON COMMIT DROP')
            sequence = "staff_test_" + table.lower()
            self.sql(f'CREATE TEMP SEQUENCE "{sequence}" START WITH 100')
            self.sql(f'''ALTER TABLE "{table}" ALTER COLUMN "{column}" SET DEFAULT nextval('pg_temp.{sequence}')''')
        isolated = stack.enter_context(patch.object(staff, "engine"))
        isolated.begin.side_effect = self.begin
        isolated.connect.side_effect = self.connect
        self.owner = {"ACCOUNT_UNIQN": 1, "CLINIC_UNIQN": 1, "IS_OWNER": True}
        app = FastAPI()
        app.include_router(staff.create_staff_router(lambda: self.owner))
        self.client = stack.enter_context(TestClient(app))
        stack.enter_context(patch.dict(os.environ, {"HANUI_PUBLIC_URL": "http://localhost:5173"}))
        self.mail = stack.enter_context(patch.object(staff, "send_staff_invitation", return_value="sent"))

    def sql(self, query, **values):
        return self.connection.execute(self.text(query), values)

    @contextmanager
    def begin(self):
        with self.connection.begin_nested():
            yield self.connection

    @contextmanager
    def connect(self):
        yield self.connection

    def invite(self):
        return self.client.post("/api/staff/invitations", json={"email": "staff@example.com", "role": "DESK"})

    def test_delivery_registration_and_owner_approval(self):
        response = self.invite()
        self.assertEqual(response.status_code, 201)
        result = response.json()
        self.assertEqual(result["emailDelivery"], "sent")
        self.assertIn("/staff/register?token=", result["registrationUrl"])
        self.mail.assert_called_once_with("staff@example.com", result["registrationUrl"])
        self.assertEqual(self.invite().status_code, 409)
        self.mail.assert_called_once()
        token = result["token"]
        verified = self.client.get("/api/staff/invitations/verify", params={"token": token})
        self.assertEqual(verified.status_code, 200)
        self.assertEqual(verified.json()["role"], "DESK")
        registered = self.client.post("/api/staff/register", json={
            "token": token, "name": "Contract staff", "password": "Contract-test-only-92!",
        })
        self.assertEqual(registered.status_code, 201)
        account = self.sql('SELECT "ACCOUNT_UNIQN", "STATUS_CD", "ROLE_CD" FROM "ACCOUNT"').mappings().one()
        self.assertEqual((account["STATUS_CD"], account["ROLE_CD"]), ("PENDING", "DESK"))
        self.assertEqual(self.client.get("/api/staff/invitations/verify", params={"token": token}).status_code, 400)
        self.assertEqual(self.client.patch(f'/api/staff/{account["ACCOUNT_UNIQN"]}/approve').status_code, 200)
        self.assertEqual(self.sql('SELECT "STATUS_CD" FROM "ACCOUNT"').scalar_one(), "ACTIVE")

    def test_mail_failure_retains_usable_invitation_link(self):
        self.mail.return_value = "failed"
        response = self.invite()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["emailDelivery"], "failed")
        self.assertTrue(response.json()["registrationUrl"])
        self.assertEqual(self.client.get("/api/staff/invitations/verify", params={"token": response.json()["token"]}).status_code, 200)

    def test_non_owner_cannot_create_invitation_or_send_email(self):
        self.owner["IS_OWNER"] = False
        self.assertEqual(self.invite().status_code, 403)
        self.mail.assert_not_called()
        self.assertEqual(self.sql('SELECT COUNT(*) FROM "INVITATION"').scalar_one(), 0)
