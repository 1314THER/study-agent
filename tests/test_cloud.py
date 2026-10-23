"""Runs on SQLite by default and on an isolated PostgreSQL via the test runner."""
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select, func, insert
from backend.storage.database import Database, repository_context
from backend.storage.accounts import CloudAccountStore
from backend.storage.repository import Repository
from backend.storage import models as m
from backend.cloud_app import build_cloud_app
from backend.identity import identity_context
from backend.auth import AuthError


class Mailer:
    enabled = True
    def __init__(self): self.codes = {}
    def send_code(self, email, code): self.codes[email] = code


class CloudTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        url = os.environ.get("STUDY_TEST_DATABASE_URL", "sqlite:///:memory:")
        if "STUDY_TEST_DATABASE_URL" in os.environ and os.environ.get("STUDY_TEST_ISOLATED_DATABASE") != "1":
            raise RuntimeError("PostgreSQL 测试仅允许显式标记的隔离数据库")
        self.db = Database(url)
        if self.db.engine.dialect.name == "postgresql": m.metadata.drop_all(self.db.engine)
        self.db.create_schema()
        self.mailer = Mailer()
        self.store = CloudAccountStore(self.db, self.root / "cloud", encryption_key=Fernet.generate_key(), mailer=self.mailer)
        self.store.bootstrap_owner("owner-password-123")
        self.alice = self.register("alice")
        self.bob = self.register("bob")
        self.app = build_cloud_app(database=self.db, store=self.store, root=self.root / "cloud", secure_cookie=False, origin="http://testserver")
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.owner_headers = self.login("studyadmin", "owner-password-123")
        self.a_headers = self.login("alice")
        self.b_headers = self.login("bob")

    def register(self, name):
        email = name + "@example.com"
        self.store.send_email_code(email, name)
        token, user, _ = self.store.register(name, email, self.mailer.codes[email], "test-password-123", "sk-example-user-key", name)
        return user

    def login(self, name, password="test-password-123"):
        response = self.client.post("/api/v1/auth/login", json={"login": name, "password": password, "device_name": name + " iPad"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("api_key_encrypted", response.text)
        self.assertNotIn("password_hash", response.text)
        return {"Authorization": "Bearer " + response.json()["access_token"]}

    def question(self, headers=None, public=False):
        response = self.client.post("/api/v1/questions", headers=headers or self.a_headers,
            json={"content": "计算 $1+1$", "answer_json": {"question_type": "填空题", "final_answer": "2"}, "public": public})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def wait(self, job_id, headers=None):
        for _ in range(300):
            result = self.client.get("/api/v1/jobs/" + job_id, headers=headers or self.a_headers).json()
            if result["status"] in ("done", "error", "interrupted"):
                return result
            time.sleep(0.01)
        self.fail("job did not terminate")

    def test_native_and_cookie_auth_share_data_without_weakening_origin(self):
        q = self.question()
        self.assertEqual(self.client.get("/api/v1/questions").status_code, 401)
        login = self.client.post("/auth/login", headers={"Origin": "http://testserver"}, json={"login": "alice@example.com", "password": "test-password-123"})
        self.assertEqual(login.status_code, 200, login.text)
        self.assertEqual(self.client.get("/api/v1/questions").json()["items"][0]["id"], q["id"])
        self.assertEqual(self.client.post("/api/v1/questions", json={"content": "bad"}).status_code, 403)
        self.assertEqual(self.client.get("/api/v1/questions", headers={"Authorization": "Bearer invalid"}).status_code, 401)

    def test_private_questions_and_public_publication_permissions(self):
        private = self.question()
        self.assertEqual(self.client.get("/api/v1/questions/" + private["id"], headers=self.b_headers).status_code, 404)
        denied = self.client.post("/api/v1/questions", headers=self.a_headers, json={"content": "伪造公共题", "public": True})
        self.assertEqual(denied.status_code, 403)
        public = self.question(self.owner_headers, True)
        for headers in (self.a_headers, self.b_headers):
            self.assertEqual(self.client.get("/api/v1/questions/" + public["id"], headers=headers).status_code, 200)
        self.assertEqual(self.client.delete("/api/v1/questions/" + public["id"], headers=self.a_headers).status_code, 403)

    def test_versions_survive_withdrawal_and_stale_edits_conflict(self):
        q = self.question(self.owner_headers, True)
        job = self.client.post("/api/v1/jobs", headers=self.a_headers, json={"kind": "grade", "args": {"question_id": q["id"], "student_answer": "2"}, "request_id": "first-attempt"}).json()
        self.assertEqual(self.wait(job["id"])["status"], "done")
        edit = self.client.put("/api/v1/questions/" + q["id"], headers=self.owner_headers, json={"content": "计算 $2+2$", "answer_json": {"final_answer": "4"}, "expected_revision": 1})
        self.assertEqual(edit.status_code, 200, edit.text)
        self.assertEqual(edit.json()["revision"], 2)
        self.assertEqual(self.client.put("/api/v1/questions/" + q["id"], headers=self.owner_headers, json={"content": "stale", "expected_revision": 1}).status_code, 409)
        self.client.delete("/api/v1/questions/" + q["id"], headers=self.owner_headers)
        history = self.client.get("/api/v1/attempts", headers=self.a_headers).json()["items"][0]
        self.assertEqual(history["question_revision"], 1)
        self.assertEqual(history["question_content"], "计算 $1+1$")
        old_version = self.client.get("/api/v1/questions/" + q["id"] + "/versions/1", headers=self.a_headers)
        self.assertEqual(old_version.status_code, 200, old_version.text)
        self.assertEqual(old_version.json()["content"], "计算 $1+1$")
        with self.db.transaction() as c:
            self.assertEqual(c.scalar(select(func.count()).select_from(m.question_versions).where(m.question_versions.c.question_id == q["id"])), 2)

    def test_grade_idempotence_and_cross_account_jobs(self):
        q = self.question()
        body = {"kind": "grade", "args": {"question_id": q["id"], "student_answer": "2"}, "request_id": "same-request"}
        first = self.client.post("/api/v1/jobs", headers=self.a_headers, json=body)
        second = self.client.post("/api/v1/jobs", headers=self.a_headers, json=body)
        self.assertEqual(first.status_code, 202, first.text)
        self.assertEqual(first.json()["id"], second.json()["id"])
        result = self.wait(first.json()["id"])
        self.assertEqual(result["status"], "done", result)
        self.assertTrue(result["result"]["result"]["is_correct"])
        self.assertEqual(self.client.get("/api/v1/jobs/" + first.json()["id"], headers=self.b_headers).status_code, 404)
        body["args"]["student_answer"] = "3"
        self.assertEqual(self.client.post("/api/v1/jobs", headers=self.a_headers, json=body).status_code, 409)
        self.assertEqual(self.client.get("/api/v1/progress", headers=self.a_headers).json()["attempt_count"], 1)
        self.assertEqual(self.client.get("/api/v1/progress", headers=self.b_headers).json()["attempt_count"], 0)

    def test_refresh_rotation_and_replay_revokes_device(self):
        response = self.client.post("/api/v1/auth/login", json={"login": "alice", "password": "test-password-123"}).json()
        rotated = self.client.post("/api/v1/auth/refresh", json={"refresh_token": response["refresh_token"]})
        self.assertEqual(rotated.status_code, 200, rotated.text)
        self.assertNotEqual(rotated.json()["refresh_token"], response["refresh_token"])
        headers = {"Authorization": "Bearer " + rotated.json()["access_token"]}
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=headers).status_code, 200)
        self.assertEqual(self.client.post("/api/v1/auth/refresh", json={"refresh_token": response["refresh_token"]}).status_code, 401)
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=headers).status_code, 401)

    def test_device_revocation_cannot_revoke_someone_else(self):
        device = self.client.get("/api/v1/auth/devices", headers=self.a_headers).json()["items"][0]["id"]
        self.client.delete("/api/v1/auth/devices/" + device, headers=self.b_headers)
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=self.a_headers).status_code, 200)
        self.client.delete("/api/v1/auth/devices/" + device, headers=self.a_headers)
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=self.a_headers).status_code, 401)

    def test_assets_and_admin_are_private(self):
        png = io.BytesIO(); Image.new("RGB", (10, 10)).save(png, format="PNG")
        asset = self.client.post("/api/v1/assets", headers=self.a_headers, files={"file": ("answer.png", png.getvalue(), "image/png")})
        self.assertEqual(asset.status_code, 201, asset.text)
        self.assertNotIn("storage_key", asset.json())
        path = "/api/v1/assets/" + asset.json()["id"]
        self.assertEqual(self.client.get(path, headers=self.a_headers).content, png.getvalue())
        self.assertEqual(self.client.get(path, headers=self.b_headers).status_code, 404)
        self.assertEqual(self.client.get("/api/v1/admin/records?kind=pool.pool_items", headers=self.a_headers).status_code, 403)
        invalid = self.client.post("/api/v1/assets", headers=self.a_headers, files={"file": ("answer.png", b"fake", "image/png")})
        self.assertEqual(invalid.status_code, 415)
        invalid_key = self.client.put("/api/v1/auth/api-key", headers=self.a_headers, json={"api_key": "bad"})
        self.assertEqual(invalid_key.status_code, 400)

    def test_teaching_persistence_scope_and_conflicts(self):
        state = {"session_id": "859ea05c-abbb-452e-bbbc-556d01232213", "question": "1+1", "revision": 3, "messages": [], "steps": []}
        with identity_context(self.alice): self.app.state.repository.persist_teaching(state)
        path = "/api/v1/teaching/" + state["session_id"]
        self.assertEqual(self.client.get(path, headers=self.a_headers).json()["revision"], 3)
        self.assertEqual(self.client.get(path, headers=self.b_headers).status_code, 404)
        stale = self.client.post("/api/v1/jobs", headers=self.a_headers, json={"kind": "teach_chat", "args": {"session_id": state["session_id"], "expected_revision": 2, "message": "2"}, "request_id": "stale-revision"})
        self.assertEqual(stale.status_code, 409)

    def test_native_registration_and_password_reset(self):
        request = {"email": "charlie@example.com"}
        self.assertEqual(self.client.post("/api/v1/auth/email-code", json=request).status_code, 200)
        body = {**request, "username": "charlie", "password": "charlie-password-123", "code": self.mailer.codes[request["email"]], "api_key": "sk-charlie-example"}
        registered = self.client.post("/api/v1/auth/register", json=body)
        self.assertEqual(registered.status_code, 200, registered.text)
        self.assertNotIn("sk-charlie-example", registered.text)
        self.store.bootstrap_owner("new-owner-password-123", replace_password=True)
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=self.owner_headers).status_code, 401)

    def test_historical_version_is_used_for_grading(self):
        q = self.question(self.owner_headers, True)
        self.client.put("/api/v1/questions/" + q["id"], headers=self.owner_headers, json={"content": "计算 $2+2$", "answer_json": {"question_type": "填空题", "final_answer": "4"}, "expected_revision": 1})
        body = {"kind": "grade", "args": {"question_id": q["id"], "question_revision": 1, "student_answer": "2"}, "request_id": "old-version-answer"}
        job = self.client.post("/api/v1/jobs", headers=self.a_headers, json=body).json()
        result = self.wait(job["id"])
        self.assertEqual(result["status"], "done", result)
        self.assertTrue(result["result"]["result"]["is_correct"])
        self.assertEqual(result["result"]["question_revision"], 1)

    def test_postgres_rejects_foreign_private_question_grants(self):
        if self.db.engine.dialect.name != "postgresql": self.skipTest("PostgreSQL constraint integration test")
        q = self.question()
        from sqlalchemy.exc import IntegrityError
        with self.assertRaises(IntegrityError):
            with self.db.transaction() as c:
                c.execute(insert(m.question_access).values(user_id=self.bob["id"], question_id=q["id"]))

    def test_private_question_images_follow_the_shared_repository(self):
        from backend.question_assets import store_image, resolve_asset
        from backend.data_paths import workspace
        png = io.BytesIO(); Image.new("RGB", (12, 12)).save(png, format="PNG")
        with repository_context(self.app.state.repository), identity_context(self.alice), workspace(self.root / "unused"):
            asset_id = store_image(png.getvalue())
            self.assertTrue(resolve_asset(asset_id).is_file())
        self.assertEqual(self.client.get("/api/v1/assets/" + asset_id, headers=self.b_headers).status_code, 404)

    def test_existing_teaching_engine_runs_on_cloud_without_sqlite_or_ai(self):
        prepared = {"chunk_results": [{"chunk_id": 1, "chunk_type": "填空题", "final_answer": "2", "steps": [
            {"step_number": 1, "title": "计算", "standard_writing": "1+1=2", "step_prompt": "请计算 1+1", "step_answer": "2"}]}]}
        q = self.client.post("/api/v1/questions", headers=self.owner_headers, json={"content": "计算 1+1", "answer_json": prepared, "public": True}).json()
        from unittest.mock import patch
        with patch("backend.solver.call_deepseek", side_effect=AssertionError("Unexpected paid AI")):
            job = self.client.post("/api/v1/jobs", headers=self.a_headers, json={"kind": "teach_start", "args": {"question_id": q["id"]}, "request_id": "start-cloud-teaching"}).json()
            result = self.wait(job["id"])
            self.assertEqual(result["status"], "done", result)
            sid = result["result"]["session_id"]
            state = self.client.get("/api/v1/teaching/" + sid, headers=self.a_headers).json()
            self.assertTrue(state["step_introduced"])
            self.assertEqual(len(state["messages"]), 1)
            follow = self.client.post("/api/v1/jobs", headers=self.a_headers, json={"kind": "teach_chat", "args": {"session_id": sid, "expected_revision": state["revision"], "message": "跳过"}, "request_id": "skip-cloud-step"}).json()
            self.assertEqual(self.wait(follow["id"])["status"], "done")
            state = self.client.get("/api/v1/teaching/" + sid, headers=self.a_headers).json()
            self.assertEqual(state["current_step"], 1)
            self.assertEqual(self.client.get("/api/v1/teaching/" + sid, headers=self.b_headers).status_code, 404)
            self.assertFalse((self.root / "cloud" / "users" / ("user-" + self.alice["id"]) / "study_agent.db").exists())

    def test_owner_can_import_review_and_publish_through_shared_services(self):
        payload = {"kind": "pool.pool_items", "external_id": "source-exam-1", "data": {"question": "1+1=?", "answer": "2"}}
        self.assertEqual(self.client.post("/api/v1/admin/records", headers=self.a_headers, json=payload).status_code, 403)
        imported = self.client.post("/api/v1/admin/records", headers=self.owner_headers, json=payload)
        self.assertEqual(imported.status_code, 201, imported.text)
        record_id = imported.json()["id"]
        self.assertTrue(self.client.post("/api/v1/admin/records", headers=self.owner_headers, json=payload).json()["already_imported"])
        review = self.client.put("/api/v1/admin/records/" + record_id + "/review", headers=self.owner_headers, json={"expected_revision": 0, "status": "confirmed"})
        self.assertEqual(review.status_code, 200, review.text)
        publish = self.client.post("/api/v1/admin/records/" + record_id + "/publish", headers=self.owner_headers, json={"content": "1+1=?", "answer_json": {"final_answer": "2"}, "expected_revision": 1})
        self.assertEqual(publish.status_code, 200, publish.text)
        self.assertIsNone(publish.json()["owner_user_id"])
        self.assertEqual(self.client.get("/api/v1/questions/" + publish.json()["id"], headers=self.b_headers).status_code, 200)


if __name__ == "__main__": unittest.main()
