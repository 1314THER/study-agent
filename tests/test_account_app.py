"""Real public app startup, guest selection, accounts and shared curriculum."""

import json
import logging
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend import database, jobs, patterns, settings
from backend.account_app import build_account_app
from backend.auth import AccountStore, account_context
from backend.data_paths import workspace, workspace_directory
from backend.identity import current_identity, identity_context
from tests.api_base import seed_answer
from tests.test_auth import FakeMailer


class AccountAppTests(unittest.TestCase):
    # The visitor gateway permits insecure cookies only on actual loopback HTTP.
    ORIGIN = "http://localhost"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.owner = self.root / "owner"
        self.owner.mkdir()
        self.now = time.time()
        self.headers = {"Origin": self.ORIGIN}
        self.mailer = FakeMailer()
        self.shared_config = self.root / "shared-ai.json"
        self.shared_config.write_text(json.dumps({"api": {"deepseek": {"api_key": "sk-shared-example-key"}}}))
        self.env = patch.dict(os.environ, {
            "STUDY_AUTH_ENABLED": "0", "STUDY_AUTH_COOKIE_SECURE": "0", "STUDY_AUTH_ORIGIN": self.ORIGIN,
            "STUDY_AGENT_DATA_DIR": "", "STUDY_DEMO_AI_ENABLED": "0", "DEEPSEEK_API_KEY": "sk-owner-env-example-key",
            "STUDY_AGENT_LOG_DIR": str(self.root / "logs"), "STUDY_AGENT_JOB_DIR": str(self.root / "owner-jobs"),
            "STUDY_DEMO_AI_CONFIG": str(self.shared_config),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        logger = logging.getLogger("backend.database")
        previous_level = logger.level
        logger.setLevel(logging.ERROR)
        self.addCleanup(logger.setLevel, previous_level)
        self.sentinels = []
        for module, attr in ((database, "DB_PATH"), (patterns, "MASTERY_DB"), (patterns, "PATTERNS_YAML"),
                             (settings, "SETTINGS_PATH"), (settings, "_ENV_PATH")):
            sentinel = self.root / (attr + ".sentinel")
            sentinel.write_bytes(b"private original path must never be touched\n")
            self.sentinels.append(sentinel)
            patcher = patch.object(module, attr, str(sentinel))
            patcher.start()
            self.addCleanup(patcher.stop)
        cache = patch.object(settings, "_cache", {})
        cache.start()
        self.addCleanup(cache.stop)
        self.store = AccountStore(self.root / "accounts", self.owner, encryption_key=Fernet.generate_key(), mailer=self.mailer, clock=lambda: self.now)
        self.store.bootstrap_owner("owner-password-123")
        self.owner_identity = {"id": "studyadmin", "username": "studyadmin", "role": "owner"}
        with identity_context(self.owner_identity), workspace(self.owner):
            database.init_db()
            patterns.init_mastery_db()
            self.qid = database.save_question("公共集合题：集合有几个子集？", seed_answer())
            self.pid = patterns.add_mother_question(self.qid, "集合与逻辑用语", "共享集合套路")["pattern_id"]
            self.private_qid = database.save_question("主人私有题，禁止发布", seed_answer())
        (self.owner / "settings.json").write_text(json.dumps({"api": {"deepseek": {"api_key": "sk-owner-settings-example-key"}}}))
        (self.owner / ".env").write_text("DEEPSEEK_API_KEY=sk-owner-file-example-key\n")
        self.observed_jobs = []
        def generate(args, ctx):
            user = dict(current_identity())
            directory = workspace_directory()
            self.observed_jobs.append({"user": user, "directory": directory, "key": settings.get_api_key("deepseek")})
            question = database.get_question_by_id(args["question_id"])
            return {"question_id": args["question_id"], "found_shared_question": question["catalog_id"] == self.qid,
                    "user_id": user["id"], "has_account_key": settings.get_api_key("deepseek").startswith("sk-account-")}
        self.manager = jobs.JobManager(runners={**jobs.RUNNERS, "generate": generate})
        manager_patch = patch.object(jobs, "_manager", self.manager)
        manager_patch.start()
        self.addCleanup(manager_patch.stop)
        from backend.main import core_app
        from backend import main
        from backend.demo import SessionStore
        draining_patch = patch.object(main, "_deploy_draining", False)
        draining_patch.start()
        self.addCleanup(draining_patch.stop)
        self.guest_store = SessionStore(self.root / "guests", clock=lambda: self.now, account_mode=True)
        self.app = build_account_app(core_app, store=self.store, guest_store=self.guest_store, local_preview=True)
        self.client = TestClient(self.app, base_url=self.ORIGIN)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.addCleanup(self.check_original_sentinels)

    def check_original_sentinels(self):
        for path in self.sentinels:
            self.assertEqual(path.read_bytes(), b"private original path must never be touched\n")

    def new_client(self):
        # Only the fixture's main client owns the app lifespan.
        return TestClient(self.app, base_url=self.ORIGIN)

    def register(self, name="alice", email="alice@example.com", client=None, key="sk-account-alice-example"):
        client = client or self.client
        response = client.post("/auth/email-code", json={"email": email}, headers=self.headers)
        self.assertEqual(response.status_code, 202, response.text)
        code = self.mailer.messages[-1][1]
        response = client.post("/auth/register", json={"username": name, "email": email, "code": code,
                               "password": "learner-password-123", "api_key": key}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn(key, response.text)
        return response.json()["user"]

    def owner_client(self):
        client = self.new_client()
        result = client.post("/auth/login", json={"login": "studyadmin", "password": "owner-password-123"}, headers=self.headers)
        self.assertEqual(result.status_code, 200, result.text)
        return client

    def save_private(self, client, content):
        result = client.post("/questions/save", json={"question": content, "answer_json": seed_answer()}, headers=self.headers)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertTrue(result.json()["saved"])
        return result.json()["id"]

    def wait_job(self, client, job_id):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            response = client.get("/jobs/" + job_id)
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
            if result["status"] in jobs.TERMINAL:
                return result
            time.sleep(0.01)
        self.fail("isolated background job did not finish")

    def test_startup_and_three_choices_do_not_create_guest(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        for choice in ("游客登录", "创建账号", "账号登录"):
            self.assertIn(choice, page.text)
        self.assertFalse(self.guest_store.sessions)
        self.assertFalse(self.client.get("/auth/me").json()["authenticated"])
        page = self.client.get("/home.html", follow_redirects=False)
        self.assertEqual(page.status_code, 303)
        self.assertEqual(page.headers["location"], "/login.html")
        self.assertFalse(self.guest_store.sessions)
        self.assertTrue((self.store.root / "bootstrap" / "study_agent.db").exists())
        self.assertTrue((self.store.root / "catalog.db").exists())
        self.assertEqual(self.client.get("/health").json()["mode"], "accounts")

    def test_guest_selection_has_two_hour_cookie_and_private_identity(self):
        response = self.client.post("/auth/guest", json={}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["user"]["role"], "guest")
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertIn("study_demo_local", response.headers["set-cookie"])
        token = self.client.cookies.get("study_demo_local")
        session = self.guest_store.sessions[token]
        self.assertEqual(session.expires - self.now, 7200)
        cookie_age = int(response.headers["set-cookie"].split("Max-Age=", 1)[1].split(";", 1)[0])
        self.assertGreaterEqual(cookie_age, 7199)
        self.assertLessEqual(cookie_age, 7200)
        self.assertEqual(self.client.get("/auth/me").json()["user"]["id"], "guest:" + token)
        questions = self.client.get("/questions")
        self.assertEqual(questions.status_code, 200, questions.text)
        self.assertNotIn("主人私有题", questions.text)
        self.assertIn("公共集合题", questions.text)
        pattern = self.client.get("/patterns").json()[0]
        self.assertLess(pattern["id"], 0)
        self.assertEqual(self.client.put("/patterns/" + str(pattern["id"]), json={"name": "游客篡改"}, headers=self.headers).status_code, 403)
        self.now += 7201
        self.assertFalse(self.client.get("/auth/me").json()["authenticated"])

    def test_accounts_have_private_questions_and_own_encrypted_keys(self):
        alice = self.register()
        home = self.client.get("/home.html")
        self.assertIn("window.STUDY_USER=", home.text)
        self.assertIn(alice["id"], home.text)
        self.assertIn("no-store", home.headers["cache-control"])
        self.assertNotIn("sk-account-alice-example", home.text)
        bob_client = self.new_client()
        bob = self.register("bob", "bob@example.com", bob_client, "sk-account-bob-example")
        alice_qid = self.save_private(self.client, "Alice 专属学习题")
        bob_qid = self.save_private(bob_client, "Bob 专属学习题")
        self.assertGreater(alice_qid, 0)
        self.assertGreater(bob_qid, 0)
        self.assertIn("Alice 专属", self.client.get("/questions").text)
        self.assertNotIn("Bob 专属", self.client.get("/questions").text)
        self.assertIn("Bob 专属", bob_client.get("/questions").text)
        self.assertNotIn("Alice 专属", bob_client.get("/questions").text)
        for user, key in ((alice, "sk-account-alice-example"), (bob, "sk-account-bob-example")):
            directory = self.store.workspace_for(user)
            with account_context(self.store, user), workspace(directory):
                self.assertEqual(settings.get_api_key("deepseek"), key)
                self.assertEqual(set(settings.get_api()), {"deepseek"})
            self.assertFalse((directory / ".env").exists())
            with sqlite3.connect(directory / "study_agent.db") as conn:
                self.assertEqual(conn.execute("SELECT DISTINCT user_id FROM questions WHERE catalog_id IS NULL").fetchall(), [(user["id"],)])
        data = self.client.get("/settings").json()
        self.assertEqual(data["api"]["deepseek"]["api_key"], "")
        self.assertEqual(data["api"]["deepseek"]["key_source"], "account")
        response = self.client.put("/settings", json={"api": {"deepseek": {"api_key": "sk-account-alice-updated"}}}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("sk-account-alice-updated", response.text)
        self.assertNotIn("sk-account-alice-updated", (self.store.workspace_for(alice) / "settings.json").read_text())
        self.assertEqual(self.store.get_api_key(alice["id"]), "sk-account-alice-updated")
        self.assertEqual(self.store.get_api_key(bob["id"]), "sk-account-bob-example")
        # Removing a user's encrypted key must never fall back to owner/shared settings.
        with self.store.connection() as conn:
            conn.execute("UPDATE users SET api_key_encrypted=NULL WHERE id=?", (alice["id"],))
        with account_context(self.store, alice), workspace(self.store.workspace_for(alice)):
            self.assertEqual(settings.get_api_key("deepseek"), "")

    def test_owner_updates_shared_definitions_without_resetting_progress(self):
        alice = self.register()
        initial = self.client.get("/questions").json()
        self.assertEqual(len(initial), 1)
        self.assertEqual(initial[0]["id"], -self.qid)
        self.assertFalse(initial[0]["can_edit"])
        error = self.client.post(f"/questions/{-self.qid}/step-error", json={"chunk_id": 1, "step_number": 1,
                                 "mistake_type": "计算错误", "student_input": "B"}, headers=self.headers)
        self.assertTrue(error.json()["saved"], error.text)
        self.assertEqual(self.client.post(f"/patterns/{-self.pid}/complete", json={"passed": True}, headers=self.headers).status_code, 200)
        self.assertEqual(self.client.get("/patterns").json()[0]["mastery"]["state"], "first_pass")
        owner = self.owner_client()
        self.assertIn("主人私有题", owner.get("/questions").text)
        self.assertEqual(owner.put(f"/patterns/{self.pid}", json={"name": "更新后的共享套路"}, headers=self.headers).status_code, 200)
        answer = seed_answer()
        answer["final_answer"] = "更新后的答案"
        self.assertEqual(owner.post("/questions/save", json={"question": "公共集合题：集合有几个子集？", "answer_json": answer}, headers=self.headers).status_code, 200)
        patterns_result = self.client.get("/patterns").json()
        self.assertEqual(patterns_result[0]["name"], "更新后的共享套路")
        self.assertEqual(patterns_result[0]["mastery"]["state"], "first_pass")
        question = self.client.get(f"/questions/{-self.qid}").json()
        self.assertEqual(question["answer_json"]["final_answer"], "更新后的答案")
        self.assertEqual(len(question["step_errors"]), 1)
        self.assertEqual(question["step_errors"][0]["mistake_type"], "计算错误")
        self.assertNotIn("主人私有题", self.client.get("/questions").text)
        self.assertEqual(self.client.delete(f"/questions/{-self.qid}", headers=self.headers).status_code, 403)
        with sqlite3.connect(self.store.workspace_for(alice) / "study_agent.db") as conn:
            self.assertEqual(conn.execute("SELECT user_id FROM step_errors").fetchone()[0], alice["id"])
        with sqlite3.connect(self.store.root / "catalog.db") as conn:
            public = conn.execute("SELECT definitions_json FROM shared_catalog").fetchone()[0]
            self.assertNotIn("主人私有题", public)
            self.assertNotIn("sk-owner-", public)

    def test_negative_shared_ids_work_in_background_jobs_and_keep_account_context(self):
        alice = self.register()
        self.client.get("/questions")  # Ensure the catalog projection exists.
        generate = self.client.post("/jobs", json={"kind": "generate", "args": {"question_id": -self.qid}, "request_id": "alice-generate-shared"}, headers=self.headers)
        self.assertEqual(generate.status_code, 202, generate.text)
        result = self.wait_job(self.client, generate.json()["job_id"])
        self.assertEqual(result["status"], "done", result)
        self.assertTrue(result["result"]["found_shared_question"])
        self.assertTrue(result["result"]["has_account_key"])
        self.assertEqual(self.observed_jobs[0]["user"]["id"], alice["id"])
        self.assertEqual(self.observed_jobs[0]["directory"], str(self.store.workspace_for(alice)))
        self.assertEqual(self.observed_jobs[0]["key"], "sk-account-alice-example")
        with patch("backend.grade.call_deepseek", side_effect=AssertionError("choice grading must not use paid AI")):
            grade = self.client.post("/jobs", json={"kind": "grade", "args": {"question_id": -self.qid, "student_answer": "A"}, "request_id": "alice-grade-shared"}, headers=self.headers)
            self.assertEqual(grade.status_code, 202, grade.text)
            graded = self.wait_job(self.client, grade.json()["job_id"])
            self.assertEqual(graded["status"], "done", graded)
            self.assertTrue(graded["result"]["is_correct"])
        bob_client = self.new_client()
        self.register("bob", "bob@example.com", bob_client, "sk-account-bob-example")
        self.assertEqual(bob_client.get("/jobs/" + generate.json()["job_id"]).status_code, 404)

    def test_switching_entrances_revokes_account_and_keeps_guest_data_separate(self):
        self.register()
        account_token = self.client.cookies.get("study_account_local")
        self.save_private(self.client, "原账号私有题")
        guest = self.client.post("/auth/guest", json={}, headers=self.headers)
        self.assertEqual(guest.status_code, 200, guest.text)
        self.assertIsNone(self.store.resolve_session(account_token))
        self.assertEqual(self.client.get("/auth/me").json()["user"]["role"], "guest")
        self.save_private(self.client, "游客临时私有题")
        bob = self.register("bob", "bob@example.com", key="sk-account-bob-example")
        self.assertEqual(self.client.get("/auth/me").json()["user"]["id"], bob["id"])
        questions = self.client.get("/questions")
        self.assertNotIn("原账号私有题", questions.text)
        self.assertNotIn("游客临时私有题", questions.text)
        self.assertEqual(len(questions.json()), 1)

    def test_origin_and_loopback_internal_deployment_guards(self):
        self.assertEqual(self.client.post("/auth/guest", json={}).status_code, 403)
        self.assertEqual(self.client.post("/auth/email-code", json={"email": "test@example.com"}, headers={"Origin": "https://evil.example"}).status_code, 403)
        # deployment_guard recognizes TestClient as local, so shell POSTs remain usable.
        response = self.client.post("/_internal/deploy-drain", json={"draining": False})
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.post("/_internal/deploy-drain", json={"draining": True}, headers={"X-Forwarded-For": "127.0.0.1"})
        self.assertEqual(response.status_code, 404)
        status = self.client.get("/_internal/deploy-status")
        self.assertEqual(status.status_code, 200)
        self.assertFalse(status.json()["draining"])


if __name__ == "__main__":
    unittest.main()
