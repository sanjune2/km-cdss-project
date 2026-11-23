"""Opt-in v1.3 contract checks using PostgreSQL temporary tables.

Run from backend with HANUI_RUN_POSTGRES_TESTS=1 and the normal database configuration.
"""
import json
import os
import sys
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PASSWORD = "Contract-test-only-92!"
ERROR_CODES = {
    400: "INVALID_INPUT", 401: "AUTH_REQUIRED", 403: "FORBIDDEN",
    404: "NOT_FOUND", 409: "STATE_CONFLICT", 500: "INTERNAL_ERROR", 503: "SERVICE_UNAVAILABLE",
}


@unittest.skipUnless(os.getenv("HANUI_RUN_POSTGRES_TESTS") == "1", "requires local PostgreSQL")
class ApiV13Postgres(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from sqlalchemy import inspect, text

        import main
        from ai import runtime, service
        from database import engine

        cls.main, cls.service, cls.runtime = main, service, runtime
        cls.engine, cls.inspect, cls.text = engine, staticmethod(inspect), staticmethod(text)
        cls.test_client = TestClient

    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.connection = stack.enter_context(self.engine.connect())
        transaction = stack.enter_context(self.connection.begin())
        stack.callback(transaction.rollback)
        inspector = self.inspect(self.connection)
        simple = ("ACCOUNT", "CLINIC", "PATIENT", "VISIT", "ATT_DIS")
        for name in simple:
            self.sql(f'CREATE TEMP TABLE "{name}" ON COMMIT DROP AS SELECT * FROM public."{name}" WITH NO DATA')
        persistent = (
            "LOGIN_SESSION", "CASE_RECORD", "CASE_REVISION", "VISIT_STATUS_HISTORY",
            "SEARCH_LOG", "SEARCH_RESULT", "PRESP_SEARCH_RESULT", "PATIENT_PRESP",
            "PATIENT_PRESP_VERSION", "PRESP_DELIVERY",
        )
        ids = {"VISIT": "VISIT_UNIQN"}
        for name in persistent:
            self.sql(f'CREATE TEMP TABLE "{name}" (LIKE public."{name}" INCLUDING DEFAULTS) ON COMMIT DROP')
            for column in inspector.get_columns(name, schema="public"):
                if "nextval(" in (column["default"] or "") or column.get("identity"):
                    ids[name] = column["name"]
        for table, column in ids.items():
            seq = f"v13_test_{table.lower()}"
            self.sql(f'CREATE TEMP SEQUENCE "{seq}" START WITH 100')
            self.sql(f"""ALTER TABLE "{table}" ALTER COLUMN "{column}" SET DEFAULT nextval('pg_temp.{seq}')""")
        self.sql('ALTER TABLE "VISIT" ALTER COLUMN "REGISTERED_AT" SET DEFAULT CURRENT_TIMESTAMP')
        self.seed()
        isolated = stack.enter_context(patch.object(self.main, "engine"))
        stack.enter_context(patch.object(self.service, "engine", isolated))
        isolated.begin.side_effect = self.begin
        isolated.connect.side_effect = self.connect
        self.client = stack.enter_context(self.test_client(self.main.app, raise_server_exceptions=False))

    @contextmanager
    def begin(self):
        with self.connection.begin_nested():
            yield self.connection

    @contextmanager
    def connect(self):
        yield self.connection

    def sql(self, query, **values):
        return self.connection.execute(self.text(query), values)

    def seed(self):
        self.sql("""INSERT INTO "CLINIC" ("CLINIC_UNIQN","STATUS_CD")
                    VALUES (1,'ACTIVE'),(2,'ACTIVE'),(3,'SUSPENDED')""")
        password_hash = self.main.hash_password(PASSWORD)
        for aid, clinic, role, status, name in (
            (1, 1, "DOCTOR", "ACTIVE", "author"), (2, 1, "DESK", "ACTIVE", "desk"),
            (3, 1, "DOCTOR", "ACTIVE", "peer"), (4, 2, "DOCTOR", "ACTIVE", "outsider"),
            (5, 1, "DOCTOR", "SUSPENDED", "suspended"), (6, 3, "DOCTOR", "ACTIVE", "closed"),
            (7, None, "SERVICE_ADMIN", "ACTIVE", "admin"),
        ):
            self.sql("""INSERT INTO "ACCOUNT"
                        ("ACCOUNT_UNIQN","CLINIC_UNIQN","EMAIL","NAME","ROLE_CD","IS_OWNER","STATUS_CD","PASSWORD_HASH")
                        VALUES (:id,:clinic,:email,:name,:role,FALSE,:status,:hash)""",
                     id=aid, clinic=clinic, email=f"{name}@example.invalid", name=name,
                     role=role, status=status, hash=password_hash)
            self.sql("""INSERT INTO "LOGIN_SESSION" ("ACCOUNT_UNIQN","TOKEN_HASH","CREATED_AT","EXPIRES_AT")
                        VALUES (:id,:token,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP + interval '1 hour')""",
                     id=aid, token=self.main.hash_session_token(name))
        self.sql("""INSERT INTO "LOGIN_SESSION" ("ACCOUNT_UNIQN","TOKEN_HASH","CREATED_AT","EXPIRES_AT")
                    VALUES (1,:expired,CURRENT_TIMESTAMP - interval '2 hours',CURRENT_TIMESTAMP - interval '1 hour')""",
                 expired=self.main.hash_session_token("expired"))
        self.sql("""INSERT INTO "PATIENT" ("PATIENT_UNIQN","CLINIC_UNIQN","NAME","BIRTH_DATE")
                    VALUES (1,1,'a','2000-01-01'),(2,2,'b','2000-01-01'),(3,1,'c','2000-01-01')""")
        for vid, patient, doctor, status in (
            (1, 1, 1, "IN_PROGRESS"), (2, 2, 4, "IN_PROGRESS"),
            (3, 1, 1, "COMPLETED"), (4, 3, None, "WAITING"),
        ):
            self.sql("""INSERT INTO "VISIT" ("VISIT_UNIQN","PATIENT_UNIQN","DOCTOR_UNIQN","STATUS_CD",
                         "REGISTERED_AT","WAITING_AT","STARTED_AT")
                         VALUES (:id,:patient,:doctor,:status,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)""",
                     id=vid, patient=patient, doctor=doctor, status=status)
        self.sql("""INSERT INTO "CASE_RECORD" ("CASE_UNIQN","VISIT_UNIQN","AUTHOR_UNIQN")
                    VALUES (1,1,1),(2,2,4),(3,3,1)""")
        self.sql("""INSERT INTO "ATT_DIS" ("DIS_UNIQN","ATT_DIS_NM") VALUES (5062,'test disease')""")
        for sid, cid, author, kind, status, symptoms in (
            (1, 1, 1, "DISEASE_RRF", "COMPLETED", "test"),
            (2, 1, 1, "DISEASE_RRF", "COMPLETED", "newer"),
            (3, 2, 4, "DISEASE_RRF", "COMPLETED", "test"),
            (4, 1, 1, "PRESCRIPTION_COSINE", "COMPLETED", "test"),
            (5, 1, 1, "DISEASE_RRF", "FAILED", "test"),
        ):
            self.sql("""INSERT INTO "SEARCH_LOG" ("SEARCH_UNIQN","CASE_UNIQN","INPUT_TEXT","INPUT_CONTEXT",
                         "SEARCH_METHOD","SEARCH_VERSION","DATA_VERSION","SEARCH_STATUS","FAILURE_REASON")
                         VALUES (:id,:case_id,:symptoms,CAST(:context AS jsonb),:kind,'1.3','fixture',:status,:failure)""",
                     id=sid, case_id=cid, symptoms=symptoms, kind=kind, status=status,
                     context=json.dumps({"authorId": author, "kind": "DISEASE",
                                         "failureHttpStatus": 503 if status == "FAILED" else None}),
                     failure="fixture dependency failure" if status == "FAILED" else None)
        self.sql("""INSERT INTO "SEARCH_RESULT" ("RESULT_UNIQN","SEARCH_UNIQN","DIS_UNIQN","RESULT_RANK",
                    "MATCH_SCORE","EVIDENCE_JSON","SEARCH_TRACE") VALUES
                    (1,1,5062,1,0.01,'[]'::jsonb,'{"name":"test disease"}'::jsonb)""")

    def call(self, method, path, status, *, user="author", body=None, code=None, origin=None):
        headers = {}
        if user:
            headers["Cookie"] = f"session={user}"
        if origin:
            headers["Origin"] = origin
        response = self.client.request(method, path, headers=headers, json=body)
        self.assertEqual(response.status_code, status, f"{method} {path}: {response.text}")
        result = response.json()
        if status in ERROR_CODES:
            self.assertEqual(set(result), {"error"})
            self.assertEqual(set(result["error"]), {"code", "message", "field"})
            self.assertEqual(result["error"]["code"], code or ERROR_CODES[status])
            self.assertTrue(result["error"]["message"])
        return result

    @staticmethod
    def visit(action, reason=None, consultation=None):
        return {"action": action, "reason": reason, "consultation": consultation}

    @staticmethod
    def draft(**overrides):
        return {"operation": "SAVE", "symptoms": "test", "consultationText": "note", "additionalNotes": None,
                "diseaseSearchId": None, "selectedDiseaseId": None, "manualDiseaseText": None,
                "reason": None, **overrides}

    @staticmethod
    def prescription(**overrides):
        return {"caseId": 1, "diagnosisText": None, "prescriptionId": None, "prescriptionSearchId": None,
                "prescriptionName": "fixture", "prescriptionText": None, "ingredients": [], **overrides}

    def test_authentication_origin_and_desk_read_scope(self):
        for user, status in ((None, 401), ("missing", 401), ("expired", 401),
                             ("suspended", 403), ("closed", 403), ("author", 200), ("admin", 200)):
            with self.subTest(user=user):
                self.call("GET", "/api/auth/me", status, user=user)
        self.call("POST", "/api/auth/login", 401, user=None,
                  body={"email": "author@example.invalid", "password": "wrong"})
        self.call("POST", "/api/auth/login", 403, user=None,
                  body={"email": "suspended@example.invalid", "password": PASSWORD})
        self.call("POST", "/api/auth/login", 403, user=None, origin="https://blocked.invalid",
                  body={"email": "author@example.invalid", "password": PASSWORD})
        self.call("GET", "/api/visits", 403, user="admin")
        for path in ("/api/consultations", "/api/prescriptions", "/api/ai/searches/1",
                     "/api/catalog/search?type=herb&query=x"):
            self.call("GET", path, 403, user="desk")
        self.call("GET", "/api/prescription-deliveries", 200, user="desk")
        self.call("POST", "/api/auth/logout", 200)
        self.call("GET", "/api/auth/me", 401)

    def test_visit_roles_validation_and_state_conflicts(self):
        for body in ({}, {"patientId": "1"}, {"patientId": True}, {"patientId": 0},
                     {"patientId": 1, "clinicId": 2}):
            self.call("POST", "/api/visits", 400, user="desk", body=body)
        self.call("POST", "/api/visits", 403, body={"patientId": 1})
        self.call("POST", "/api/visits", 404, user="desk", body={"patientId": 999})
        self.call("POST", "/api/visits", 409, user="desk", body={"patientId": 1})
        self.call("GET", "/api/visits?scope=no", 400)
        for body in ({"action": "START"}, self.visit("INVALID"),
                     self.visit("START", consultation={}), {**self.visit("START"), "authorId": 3}):
            self.call("PATCH", "/api/visits/4/status", 400, body=body)
        self.call("PATCH", "/api/visits/4/status", 403, user="desk", body=self.visit("START"))
        self.call("PATCH", "/api/visits/4/status", 400, user="desk", body=self.visit("CANCEL"))
        first = self.call("PATCH", "/api/visits/4/status", 200,
                          user="desk", body=self.visit("REGISTER_WAITING"))["record"]
        repeated = self.call("PATCH", "/api/visits/4/status", 200,
                             user="desk", body=self.visit("REGISTER_WAITING"))["record"]
        self.assertEqual(first["waitingAt"], repeated["waitingAt"])
        self.call("PATCH", "/api/visits/4/status", 200, body=self.visit("START"))
        self.call("PATCH", "/api/visits/4/status", 409, body=self.visit("START"))
        self.call("PATCH", "/api/visits/1/status", 403, user="peer", body=self.visit("PAUSE", "reason", self.draft()))
        self.call("PATCH", "/api/visits/1/status", 400, body=self.visit("PAUSE", "reason"))
        self.call("PATCH", "/api/visits/1/status", 409, body=self.visit("RESUME", "reason"))
        paused = self.call("PATCH", "/api/visits/1/status", 200,
                           body=self.visit("PAUSE", "reason", self.draft()))["record"]
        self.call("PATCH", "/api/visits/1/status", 400, body=self.visit("RESUME"))
        resumed = self.call("PATCH", "/api/visits/1/status", 200, body=self.visit("RESUME", "reason"))["record"]
        self.assertEqual((resumed["caseId"], resumed["startedAt"]), (paused["caseId"], paused["startedAt"]))
        self.call("PATCH", "/api/visits/1/status", 409, body=self.visit("CORRECT_START", "reason"))
        self.call("PATCH", "/api/visits/3/status", 409, body=self.visit("RESUME", "reason"))

    def test_consultation_reference_conflicts_and_correction(self):
        path = "/api/consultations/1"
        self.call("GET", path, 200, user="peer")
        self.call("GET", path, 403, user="outsider")
        self.call("PATCH", path, 403, user="peer", body=self.draft())
        self.call("PATCH", path, 403, user="outsider", body=self.draft())
        self.call("PATCH", "/api/consultations/999", 404, body=self.draft())
        for fields, status, code in (
            ({"diseaseSearchId": "1"}, 400, None),
            ({"diseaseSearchId": "1", "selectedDiseaseId": True}, 400, None),
            ({"diseaseSearchId": "999", "selectedDiseaseId": 5062}, 404, None),
            ({"diseaseSearchId": "4", "selectedDiseaseId": 5062}, 409, None),
            ({"diseaseSearchId": "5", "selectedDiseaseId": 5062}, 409, None),
            ({"diseaseSearchId": "1", "selectedDiseaseId": 1}, 400, "INVALID_SELECTED_DISEASE"),
            ({"diseaseSearchId": "1", "selectedDiseaseId": 5062, "symptoms": "changed"}, 409, None),
            ({"diseaseSearchId": "1", "selectedDiseaseId": 5062, "manualDiseaseText": "manual"}, 400, None),
        ):
            with self.subTest(fields=fields):
                self.call("PATCH", path, status, body=self.draft(**fields), code=code)
        selected = self.draft(diseaseSearchId="1", selectedDiseaseId=5062)
        saved = self.call("PATCH", path, 200, body=selected)["record"]
        self.assertEqual(saved, self.call("GET", path, 200)["record"])
        self.assertEqual(saved["diagnosis"]["selectedDiseaseName"], "test disease")
        self.call("POST", f"{path}/complete", 400, body={**selected, "consultationText": " "})
        self.call("POST", f"{path}/complete", 200, body=selected)
        self.call("POST", f"{path}/complete", 409, body=selected)
        self.call("PATCH", path, 409, body=selected)
        self.call("PATCH", path, 400, body={**selected, "operation": "CORRECT"})
        self.call("PATCH", path, 200, body={**selected, "operation": "CORRECT",
                                            "reason": "correct note", "consultationText": "new"})
        self.assertEqual(self.call("GET", f"{path}/revisions", 200)["total"], 1)
        self.assertEqual(self.call("GET", path, 200)["record"]["status"], "COMPLETED")

    def test_search_dependency_failure_zero_results_and_selection_errors(self):
        disease = "/api/ai/symptoms"
        prescription = "/api/ai/prescriptions"
        for body in ({"caseId": 1, "symptoms": " "}, {"caseId": "1", "symptoms": "test"},
                     {"caseId": True, "symptoms": "test"}, {"caseId": 1, "symptoms": "test", "actor": 1}):
            self.call("POST", disease, 400, body=body)
        self.call("POST", disease, 403, user="peer", body={"caseId": 1, "symptoms": "test"})
        self.call("POST", disease, 409, body={"caseId": 3, "symptoms": "test"})
        for exception, status in ((FileNotFoundError("internal-path"), 503), (AssertionError("secret"), 500)):
            with patch.object(self.runtime, "get_runtime", side_effect=exception):
                response = self.call("POST", disease, status, body={"caseId": 1, "symptoms": "test"})
                self.assertNotIn(str(exception), response["error"]["message"])
        with (
            patch.object(self.runtime, "get_runtime", return_value={"version": "fixture", "keywords":[{"term":"test"}]}),
            patch.object(self.runtime, "diseases_for", return_value=[]),
        ):
            zero = self.call("POST", disease, 200, body={"caseId": 1, "symptoms": " test "})
        self.assertEqual((zero["candidates"], zero["total"], zero["symptoms"]), ([], 0, "test"))
        history = self.call("GET", "/api/consultations/1/searches", 200)["records"]
        self.assertEqual([row["status"] for row in history][-3:], ["FAILED", "FAILED", "COMPLETED"])
        for sid, status in ((history[-3]["searchId"], 503), (history[-2]["searchId"], 500)):
            self.call("GET", f"/api/ai/searches/{sid}", status)
        payload = {"caseId": 1, "symptoms": "test", "diseaseSearchId": "1", "selectedDiseases": [5062]}
        for updates, status, code in (
            ({"selectedDiseases": []}, 400, "INVALID_SELECTED_DISEASE"),
            ({"selectedDiseases": [5062, 5062]}, 400, "INVALID_SELECTED_DISEASE"),
            ({"selectedDiseases": [5]}, 400, "INVALID_SELECTED_DISEASE"),
            ({"diseaseSearchId": "999"}, 404, None), ({"diseaseSearchId": "3"}, 403, None),
            ({"diseaseSearchId": "4"}, 409, None), ({"diseaseSearchId": "5"}, 409, None),
            ({"symptoms": "changed"}, 409, None),
        ):
            self.call("POST", prescription, status, body={**payload, **updates}, code=code)

    def test_explanation_source_and_cancel_authorization(self):
        path = "/api/ai/searches/1"
        self.call("GET", path, 200, user="peer")
        self.call("GET", path, 403, user="outsider")
        self.call("GET", "/api/ai/searches/999", 404)
        self.call("GET", "/api/ai/sources/nonexistent?searchId=1", 404)
        self.call("GET", "/api/ai/sources/nonexistent", 400)
        self.call("POST", f"{path}/explanations", 400, body={"candidateIds": [5062, 5062]})
        self.call("POST", f"{path}/explanations", 400, body={"candidateIds": [123]})
        self.call("POST", f"{path}/explanations", 403, user="peer", body={"candidateIds": [5062]})
        self.call("POST", f"{path}/cancel", 403, user="peer")
        first = self.call("POST", f"{path}/cancel", 200)
        self.assertEqual(self.call("POST", f"{path}/cancel", 200), first)
        self.call("POST", f"{path}/explanations", 409, body={"candidateIds": [5062]})

    def test_prescription_validation_versions_and_delivered_snapshot(self):
        for changes in ({"prescriptionName": " "}, {"caseId": True}, {"prescriptionSearchId": "1"},
                        {"authorId": 1}, {"ingredients": [{"name": "missing keys"}]}):
            self.call("POST", "/api/prescriptions", 400, body=self.prescription(**changes))
        self.call("POST", "/api/prescriptions", 403, user="peer", body=self.prescription())
        initial = self.call("POST", "/api/prescriptions", 201, body=self.prescription())["record"]
        path = f"/api/prescriptions/{initial['rxId']}"
        old_id = initial["versionId"]
        self.assertEqual(self.call("GET", "/api/prescription-deliveries", 200, user="desk")["total"], 0)
        self.call("PATCH", f"{path}/send", 403, user="peer", body={"versionId": old_id})
        self.call("PATCH", f"{path}/send", 404, body={"versionId": 999})
        self.call("PATCH", f"{path}/send", 400, body={"versionId": str(old_id)})
        old = self.call("PATCH", f"{path}/send", 200, body={"versionId": old_id})["record"]
        self.assertEqual(self.call("PATCH", f"{path}/send", 200, body={"versionId": old_id})["record"], old)
        correction = self.prescription(versionId=old_id, reason="test", prescriptionName="updated")
        self.call("PATCH", path, 400, body={**correction, "caseId": 999})
        self.call("PATCH", path, 400, body={**correction, "reason": " "})
        self.call("PATCH", path, 403, user="peer", body=correction)
        updated = self.call("PATCH", path, 200, body=correction)["record"]
        self.call("PATCH", path, 409, body=correction)
        self.call("PATCH", f"{path}/send", 200, body={"versionId": updated["versionId"]})
        delivered = self.call("GET", f"/api/prescription-deliveries/{old['id']}", 200, user="desk")["record"]
        self.assertEqual(delivered["version"]["prescriptionName"], initial["prescriptionName"])
        self.call("GET", f"{path}/versions/{old_id}", 403, user="desk")
        self.call("GET", f"{path}/versions/999", 404)

    def test_actual_dose_survives_save_correction_and_delivered_snapshot(self):
        herb = {"compositionId": None, "id": None, "name": "manual fixture", "amount": None,
                "unit": None, "preparation": None, "originalDoseInfo": None,
                "prescribedAmount": "1.25", "prescribedUnit": "mL"}
        initial = self.call("POST", "/api/prescriptions", 201,
                            body=self.prescription(ingredients=[herb]))["record"]
        path = f"/api/prescriptions/{initial['rxId']}"
        old_id = initial["versionId"]
        stored = self.call("GET", f"{path}/versions/{old_id}", 200)["record"]
        self.assertEqual(stored["ingredients"], [herb])
        delivery = self.call("PATCH", f"{path}/send", 200, body={"versionId": old_id})["record"]
        changed = {**herb, "prescribedAmount": "2.5"}
        updated = self.call("PATCH", path, 200, body=self.prescription(
            versionId=old_id, reason="actual dose correction", ingredients=[changed]))["record"]
        self.assertEqual(updated["ingredients"], [changed])
        self.assertIn("ingredients", updated["change"]["changedFields"])
        self.assertEqual(self.call("GET", f"{path}/versions/{old_id}", 200)["record"]["ingredients"], [herb])
        delivered = self.call("GET", f"/api/prescription-deliveries/{delivery['id']}", 200, user="desk")["record"]
        self.assertEqual(delivered["version"]["ingredients"], [herb])

    def test_transaction_rollback_when_later_writes_fail(self):
        self.sql("""ALTER TABLE "VISIT_STATUS_HISTORY" ADD CONSTRAINT reject_complete
                    CHECK ("AFTER_STATUS" != 'COMPLETED')""")
        self.call("POST", "/api/consultations/1/complete", 503, body=self.draft())
        saved = self.call("GET", "/api/consultations/1", 200)["record"]
        self.assertEqual(saved["status"], "IN_PROGRESS")
        self.assertEqual(saved["consultationText"], "")
        self.sql('ALTER TABLE "PATIENT_PRESP_VERSION" ADD CONSTRAINT reject_version CHECK (FALSE)')
        self.call("POST", "/api/prescriptions", 503, body=self.prescription())
        self.assertEqual(self.sql('SELECT count(*) FROM "PATIENT_PRESP"').scalar_one(), 0)
        self.assertEqual(self.sql('SELECT count(*) FROM "PRESP_DELIVERY"').scalar_one(), 0)

    def test_catalog_invalid_requests_empty_and_dependency_failure(self):
        self.call("GET", "/api/catalog/search?type=unknown&query=x", 400)
        self.call("GET", "/api/catalog/search?type=herb", 400)
        empty = self.call("GET", "/api/catalog/search?type=herb&query=%20", 200)
        self.assertEqual(empty, {"items": [], "total": 0, "message": None})
        self.call("GET", "/api/catalog/herb/1?selectedDiseaseId=1", 400)
        with patch("catalog.load_catalog", side_effect=FileNotFoundError("internal path")):
            self.call("GET", "/api/catalog/search?type=herb&query=x", 503)

    def test_other_clinic_references_and_combined_filters(self):
        for path in (
            "/api/consultations?patientId=2", "/api/consultations?visitId=2", "/api/consultations/2/revisions",
            "/api/prescriptions?caseId=2", "/api/prescriptions?patientId=2",
            "/api/prescription-deliveries?caseId=2", "/api/prescription-deliveries?patientId=2",
        ):
            self.call("GET", path, 403)
        self.call("GET", "/api/consultations?patientId=3&visitId=1", 200)
        self.call("POST", "/api/visits", 403, user="desk", body={"patientId": 2})
        self.call("PATCH", "/api/visits/2/status", 403, body=self.visit("START"))
        self.call("POST", "/api/prescriptions", 403, body=self.prescription(caseId=2))
        rx = self.call("POST", "/api/prescriptions", 201, user="outsider",
                       body=self.prescription(caseId=2))["record"]
        delivery = self.call("PATCH", f"/api/prescriptions/{rx['rxId']}/send", 200, user="outsider",
                             body={"versionId": rx["versionId"]})["record"]
        self.call("GET", f"/api/prescriptions/{rx['rxId']}/versions", 403)
        self.call("GET", f"/api/prescription-deliveries/{delivery['id']}", 403, user="desk")

    def test_cancel_marks_queued_work_and_preserves_finished_work(self):
        jobs = {
            "5062": {"result": self.service.state("READY", text="preserved")},
            "5000": self.service.queued_job(),
            "5001": {"result": self.service.state("RUNNING")},
        }
        self.sql("""UPDATE "SEARCH_LOG"
                    SET "INPUT_CONTEXT" = "INPUT_CONTEXT" || jsonb_build_object('explanations', CAST(:jobs AS jsonb))
                    WHERE "SEARCH_UNIQN" = 1""", jobs=json.dumps(jobs))
        self.call("POST", "/api/ai/searches/1/cancel", 200)
        snapshot = self.sql(
            'SELECT "INPUT_CONTEXT" FROM "SEARCH_LOG" WHERE "SEARCH_UNIQN" = 1'
        ).scalar_one()
        self.assertTrue(snapshot["cancelRequestedAt"])
        self.assertEqual(snapshot["explanations"]["5062"], jobs["5062"])
        self.assertEqual(snapshot["explanations"]["5000"]["result"]["status"], "INCOMPLETE")
        self.assertTrue(snapshot["explanations"]["5000"]["finishedAt"])
        self.assertEqual(snapshot["explanations"]["5001"]["result"]["status"], "RUNNING")

    def test_unconfigured_prescription_policy_persists_unscored_results(self):
        from numpy import empty

        embedder = Mock()
        fixture = {
            "version": "fixture", "diseases": [{"DIS_UNIQN": 5062}],
            "keywords": [{"DIS_UNIQN": 5062, "term": "test"}],
            "prescriptions": [
                {"PRESP_UNIQN": 51, "PRESP_NM": "가", "PRESP_CONT": "등록 설명", "TABO_CONT": ""},
                {"PRESP_UNIQN": 52, "PRESP_NM": "나", "PRESP_CONT": "", "TABO_CONT": ""},
            ],
            "relations": [{"DIS_UNIQN": 5062, "PRESP_UNIQN": item} for item in (51, 52)],
            "chunks": [], "matrix": empty((0, 384)), "embedder": embedder,
        }
        payload = {"caseId": 1, "symptoms": "test", "diseaseSearchId": "1", "selectedDiseases": [5062]}
        with (
            patch.dict(os.environ, {"KM_CDSS_PRESCRIPTION_EVALUATION_POLICY": ""}),
            patch.object(self.runtime, "get_runtime", return_value=fixture),
            patch.object(self.runtime, "load_catalog", return_value=([], [])),
        ):
            result = self.call("POST", "/api/ai/prescriptions", 200, body=payload)
        embedder.encode_query.assert_not_called()
        self.assertEqual(result["summary"], {
            "connectedCount": 2, "scoredCount": 0, "insufficientCount": 1, "policyUnconfiguredCount": 1,
        })
        self.assertEqual(result, self.call("GET", f"/api/ai/searches/{result['searchId']}", 200))
        rows = self.sql("""SELECT "SCORE_STATUS", "RESULT_RANK", "RELEVANCE_SCORE"
                           FROM "PRESP_SEARCH_RESULT" ORDER BY "PRESP_UNIQN" """).all()
        self.assertEqual(rows, [("POLICY_NOT_CONFIGURED", None, None), ("INSUFFICIENT_DATA", None, None)])

    def test_legacy_waiting_cannot_revert_saved_consultation(self):
        self.call('PATCH', '/api/consultations/1', 200, body=self.draft())
        before = self.sql('SELECT "STATUS_CD", "DOCTOR_UNIQN", "STARTED_AT" FROM "VISIT" WHERE "VISIT_UNIQN"=1').one()
        self.call('PATCH', '/api/waiting/1', 409, body={'status':'대기'})
        self.call('PATCH', '/api/visits/1/status', 409, body=self.visit('CORRECT_START', 'reason'))
        after = self.sql('SELECT "STATUS_CD", "DOCTOR_UNIQN", "STARTED_AT" FROM "VISIT" WHERE "VISIT_UNIQN"=1').one()
        self.assertEqual(before, after)

    def test_legacy_start_creates_consultation_via_current_workflow(self):
        result = self.call('PATCH', '/api/waiting/3', 200, body={'status':'진료 중', 'doctor':'spoofed'})
        case_id = result['patient']['caseId']
        self.assertIsNotNone(case_id)
        self.assertEqual(self.sql('SELECT "AUTHOR_UNIQN" FROM "CASE_RECORD" WHERE "CASE_UNIQN"=:id',id=case_id).scalar_one(),1)
        self.assertNotEqual(result['patient']['doctor'],'spoofed')

    def test_visit_response_preserves_patient_contact(self):
        self.sql('UPDATE "PATIENT" SET "PHONE"=:phone, "ADDRESS"=:address WHERE "PATIENT_UNIQN"=1',phone='010-0000-0000',address='synthetic')
        response = self.call('GET','/api/visits',200)
        record = next(row for row in response['records'] if row['id']==1)
        self.assertEqual((record['phone'],record['address']),('010-0000-0000','synthetic'))

    def test_password_change_revokes_other_sessions_but_keeps_current(self):
        self.sql('''INSERT INTO "LOGIN_SESSION" ("ACCOUNT_UNIQN","TOKEN_HASH","CREATED_AT","EXPIRES_AT")
                    VALUES (1,:token,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP + interval '1 hour')''',
                 token=self.main.hash_session_token('other-browser'))
        self.call('PATCH','/api/profile/password',200,body={'currentPassword':PASSWORD,
                  'newPassword':'Changed-test-only-93!', 'confirmPassword':'Changed-test-only-93!'})
        self.call('GET','/api/auth/me',200)
        self.call('GET','/api/auth/me',401,user='other-browser')
        self.call('POST','/api/auth/login',401,user=None,body={'email':'author@example.invalid','password':PASSWORD})
        self.call('POST','/api/auth/login',200,user=None,body={'email':'author@example.invalid','password':'Changed-test-only-93!'})

