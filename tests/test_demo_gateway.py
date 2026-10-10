"""Exercise the actual demo ASGI boundary, not just path helpers."""

import json
import sqlite3
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.demo import COOKIE, MAX_BODY, create_app
import backend.database as database
import backend.patterns as patterns
import backend.settings as settings
import backend.planner as planner
import backend.main as main
from backend.data_paths import workspace_directory
from backend.demo_presets import DEFAULT_PRESET_ID, list_presets, prepared_result


class DemoGatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.now = time.time()
        self.app = create_app(self.root / "visitors", clock=lambda: self.now, ai_enabled=False)
        self.a = self.client()
        self.b = self.client()
        # A fallback to ANY original path would either alter these sentinels or fail.
        self.owner_files = []
        for module, attr, name in (
            (database, "DB_PATH", "owner-study.db"),
            (patterns, "MASTERY_DB", "owner-mastery.db"),
            (patterns, "PATTERNS_YAML", "owner-patterns.yaml"),
            (settings, "SETTINGS_PATH", "owner-settings.json"),
            (settings, "_ENV_PATH", "owner.env"),
            (planner, "CONFIG_PATH", "owner-board-order.yaml"),
        ):
            path = self.root / name
            path.write_bytes(b"owner sentinel\n")
            self.owner_files.append(path)
            p = patch.object(module, attr, str(path))
            p.start()
            self.addCleanup(p.stop)
        env = patch.dict("os.environ", {"DEEPSEEK_API_KEY": "owner-test-secret", "DASHSCOPE_API_KEY": "owner-test-secret"})
        env.start()
        self.addCleanup(env.stop)

    def client(self):
        client = TestClient(self.app, base_url="https://demo.test")
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        return client

    def test_recent_demo_presets_exclude_solid_geometry_and_keep_prepared_answers(self):
        catalog = list_presets()
        presets = catalog["presets"]
        self.assertEqual(catalog["default_id"], "national-2025-q16")
        self.assertEqual(DEFAULT_PRESET_ID, "national-2025-q16")
        self.assertEqual({item["id"] for item in presets}, {
            "national-2025-q16", "national-2023-q17", "shanghai-2024-q18",
        })
        for item in presets:
            with self.subTest(preset=item["id"]):
                self.assertNotIn("立体几何", item["label"])
                self.assertNotIn("四棱锥", item["question"])
                cached = prepared_result(item["id"])
                self.assertTrue(cached["prepared_example"])
                self.assertTrue(cached["chunk_results"])

    def test_preset_question_keeps_latex_not_equal_and_part_breaks(self):
        shanghai = next(item for item in list_presets()["presets"]
                        if item["id"] == "shanghai-2024-q18")
        self.assertIn(r"$a\ne1$", shanghai["question"])
        self.assertIn("\n(1)", shanghai["question"])
        self.assertIn("\n(2)", shanghai["question"])

    def test_demo_home_is_separate_from_owner_and_head_keeps_headers(self):
        self.enter(self.a)
        landing = self.a.get("/")
        home = self.a.get("/home.html")
        self.assertEqual(landing.status_code, 200)
        self.assertIn('href="multimodal.html"', home.text)
        self.assertIn("进入多模态解答", home.text)
        self.assertNotIn('href="index.html"', home.text)
        self.assertIn("/demo-session.js", landing.text)
        head = self.a.head("/home.html")
        self.assertEqual(head.status_code, 200)
        self.assertEqual(head.content, b"")
        self.assertGreater(int(head.headers["content-length"]), 0)
        owner = TestClient(main.app).get("/home.html")
        self.assertEqual(owner.status_code, 200)
        self.assertNotIn("window.STUDY_DEMO=", owner.text)
        self.assertIn('href="index.html"', owner.text)

    def test_demo_seed_removes_private_metadata_and_rebuilds_replaced_steps(self):
        token = self.enter(self.a)
        directory = self.app.store.sessions[token].directory
        with sqlite3.connect(str(directory / "study_agent.db")) as conn:
            rows = conn.execute("SELECT id, content, source_meta, answer_json, steps_structure FROM questions").fetchall()
            clean = [row for row in rows if "判断下列对象能否构成集合" in row[1]]
            self.assertTrue(clean)
            for qid, content, source_text, answer_text, structure in rows:
                self.assertNotIn("owner", json.loads(source_text or "{}"))
                parsed = json.loads(answer_text or "{}")
                if isinstance(parsed, dict):
                    self.assertNotIn("owner", parsed.get("source_meta", {}))
            for qid, content, source_text, answer_text, structure in clean:
                self.assertNotIn("coco", structure.lower())
                self.assertNotIn("现任男友", structure)
                self.assertIn("检查条件是否明确", structure)
                indexed = conn.execute("SELECT step_level1, step_level2 FROM question_steps WHERE question_id=?", (qid,)).fetchall()
                self.assertEqual(len(indexed), 2)
                self.assertNotIn("coco", json.dumps(indexed).lower())
        for path in self.owner_files:
            self.assertEqual(path.read_bytes(), b"owner sentinel\n")

    def enter(self, client):
        response = client.get("/home.html")
        self.assertEqual(response.status_code, 200)
        token = client.cookies.get(COOKIE)
        self.assertEqual(len(token), 32)
        self.assertIn('"session_id": "' + token + '"', response.text)
        self.assertLess(response.text.index("/demo-session.js"), response.text.index("nav-init"))
        return token

    def test_two_visitors_can_edit_without_changing_each_other_or_owner(self):
        self.enter(self.a)
        self.enter(self.b)
        questions = self.a.get("/questions").json()
        self.assertTrue(questions)
        qid = questions[0]["id"]
        self.assertEqual(self.a.delete("/questions/" + str(qid)).status_code, 200)
        self.assertEqual(len(self.a.get("/questions").json()), len(questions) - 1)
        self.assertEqual(len(self.b.get("/questions").json()), len(questions))
        self.assertEqual(self.a.post("/question-lists", json={"name": "游客A临时题单"}).status_code, 200)
        self.assertIn("游客A临时题单", json.dumps(self.a.get("/question-lists").json(), ensure_ascii=False))
        self.assertNotIn("游客A临时题单", json.dumps(self.b.get("/question-lists").json(), ensure_ascii=False))
        order = [{"category": "函数", "nodes": [12, 10]}]
        # The API normalizes categories; the file write still belongs only to A.
        self.assertEqual(self.a.put("/planner/board-order", json={"board_order": order}).status_code, 200)
        a_dir = self.app.store.sessions[self.a.cookies.get(COOKIE)].directory
        b_dir = self.app.store.sessions[self.b.cookies.get(COOKIE)].directory
        self.assertNotEqual((a_dir / "board_order.yaml").read_bytes(), (b_dir / "board_order.yaml").read_bytes())
        for path in self.owner_files:
            self.assertEqual(path.read_bytes(), b"owner sentinel\n")

    def test_no_owner_keys_and_ai_or_unknown_routes_are_blocked(self):
        self.enter(self.a)
        public = self.a.get("/settings").json()
        for provider in ("deepseek",):
            self.assertFalse(public["api"][provider]["has_key"])
            self.assertEqual(public["api"][provider]["api_key"], "")
        blocked = [
            "/solve/step1", "/solve/step2", "/solve/step3", "/agent/act",
            "/teach/session/start", "/teach/session/test/chat", "/teach/check",
            "/grade", "/multimodal/parse", "/ocr/answer", "/questions/1/generate/async",
            "/questions/ai-search", "/patterns/1/check", "/patterns/1/ensure-variants",
        ]
        for path in blocked:
            with self.subTest(path=path):
                r = self.a.post(path, json={})
                self.assertEqual(r.status_code, 403)
                self.assertEqual(r.json()["error"], "demo_ai_disabled")
        self.assertEqual(self.a.get("/teach/session/test").status_code, 403)
        self.assertEqual(self.a.get("/generate-jobs/test").status_code, 403)
        self.assertEqual(self.a.put("/settings", json={"api": {}}).json()["error"], "demo_settings_locked")
        self.assertEqual(self.a.get("/openapi.json").status_code, 403)
        self.assertEqual(self.a.post("/future/new-ai-endpoint", json={}).status_code, 403)

    def test_reset_restores_data_and_rejects_an_old_tab(self):
        old = self.enter(self.a)
        count = len(self.a.get("/questions").json())
        qid = self.a.get("/questions").json()[0]["id"]
        self.a.delete("/questions/" + str(qid))
        old_dir = self.app.store.sessions[old].directory
        r = self.a.post("/demo/reset", headers={"X-Demo-Session": old})
        self.assertEqual(r.status_code, 200)
        self.assertNotEqual(self.a.cookies.get(COOKIE), old)
        self.assertFalse(old_dir.exists())
        self.assertEqual(len(self.a.get("/questions").json()), count)
        old_tab = self.a.get("/questions", headers={"X-Demo-Session": old})
        self.assertEqual(old_tab.status_code, 401)
        self.assertEqual(old_tab.json()["error"], "demo_session_expired")

    def test_expiry_rejects_api_and_new_page_starts_fresh(self):
        old = self.enter(self.a)
        old_dir = self.app.store.sessions[old].directory
        self.now += 7201
        self.assertEqual(self.a.get("/questions").status_code, 401)
        self.assertFalse(old_dir.exists())
        new = self.enter(self.a)
        self.assertNotEqual(old, new)
        self.assertEqual(self.a.get("/questions").status_code, 200)

    def test_cookie_csrf_body_and_capacity_limits(self):
        response = self.a.get("/home.html")
        cookie = response.headers["set-cookie"]
        for flag in ("HttpOnly", "Secure", "SameSite=strict", "Path=/"):
            self.assertIn(flag, cookie)
        self.assertNotIn("Domain=", cookie)
        self.assertEqual(self.a.post("/question-lists", json={"name": "bad"}, headers={"Origin": "https://other.test"}).status_code, 403)
        self.assertEqual(self.a.post("/question-lists", content=b"x" * (MAX_BODY + 1)).status_code, 413)
        self.app.store.max_sessions = 1
        self.assertEqual(self.b.get("/home.html").status_code, 429)
        # A visitor can reset their own sandbox even at the global capacity limit.
        self.assertEqual(self.a.post("/demo/reset").status_code, 200)

    def test_anonymous_api_does_not_allocate_a_sandbox(self):
        self.assertEqual(self.a.get("/questions").status_code, 401)
        self.assertEqual(len(self.app.store.sessions), 0)
        self.assertEqual(self.a.get("/demo-session.js").status_code, 200)
        self.assertEqual(len(self.app.store.sessions), 0)

    def test_enabled_ai_uses_shared_key_and_saves_only_in_visitor_workspace(self):
        self.app.ai_enabled = True
        config = self.root / "private-ai.json"
        config.write_text(json.dumps({"api": {"deepseek": {
            "api_key": "private-shared-key", "base_url": "https://trusted.invalid/v1"
        }}}), encoding="utf-8")
        with patch.dict("os.environ", {"STUDY_DEMO_AI_CONFIG": str(config)}):
            token = self.enter(self.a)
            self.enter(self.b)
            public = self.a.get("/settings")
            self.assertNotIn("private-shared-key", public.text)
            self.assertEqual(public.json()["api"]["deepseek"]["api_key"], "")
            self.assertTrue(public.json()["api"]["deepseek"]["has_key"])
            self.assertEqual(public.json()["api"]["deepseek"]["base_url"], "https://trusted.invalid/v1")

            def fake_solver(question, question_type=None, teacher=None):
                self.assertEqual(workspace_directory(), str(self.app.store.sessions[token].directory))
                self.assertEqual(settings.get_api_key("deepseek"), "private-shared-key")
                database.save_question("AI临时测试题", {})
                return {"content": "mock AI answer"}

            with patch.object(main, "step_solver_only", side_effect=fake_solver):
                response = self.a.post("/solve/step1", json={"question": "test"})
            self.assertEqual(response.status_code, 200)
            self.assertIn("AI临时测试题", json.dumps(self.a.get("/questions").json(), ensure_ascii=False))
            self.assertNotIn("AI临时测试题", json.dumps(self.b.get("/questions").json(), ensure_ascii=False))
            a_dir = self.app.store.sessions[token].directory
            self.assertNotIn("private-shared-key", (a_dir / "settings.json").read_text())
            self.assertEqual(self.a.get("/teach/session/" + "a" * 32).status_code, 200)
            self.assertEqual(self.a.get("/generate-jobs/" + "a" * 32).status_code, 404)

    def test_local_http_preview_cookie_is_scoped_to_loopback_only(self):
        self.app.local_preview = True
        with TestClient(self.app, base_url="http://127.0.0.1:8000") as local:
            response = local.get("/home.html")
            self.assertIn("study_demo_local=", response.headers["set-cookie"])
            self.assertNotIn("Secure", response.headers["set-cookie"])
            self.assertEqual(local.get("/questions").status_code, 200)
        with TestClient(self.app, base_url="http://demo.150.chat") as remote:
            response = remote.get("/home.html")
            self.assertIn(COOKIE + "=", response.headers["set-cookie"])
            self.assertIn("Secure", response.headers["set-cookie"])


if __name__ == "__main__":
    unittest.main()
