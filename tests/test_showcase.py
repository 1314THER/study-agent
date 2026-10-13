"""Exercise the independent, read-only showcase ASGI and deployment boundary."""

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import httpx

from backend.showcase import ASSET_PATHS, HOME_PATHS, MAX_DRAIN_BODY, create_app


ROOT = Path(__file__).resolve().parents[1]


class ShowcaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.frontend = self.root / "frontend"
        for url in ASSET_PATHS | {"/showcase/index.html"}:
            target = self.frontend / url.lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("<!doctype html><h1>项目展示</h1>" if url.endswith(".html") else "public sample")
        self.private = self.root / "owner.sqlite3"
        self.private.write_bytes(b"owner database sentinel")
        (self.frontend / "settings.json").write_text('{"api_key":"private"}')
        self.app = create_app(self.frontend, draining=False)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app, client=("127.0.0.1", 1234)), base_url="http://demo.test")
        self.addAsyncCleanup(self.client.aclose)

    async def test_public_home_aliases_and_head_require_no_session(self):
        for path in HOME_PATHS:
            with self.subTest(path=path):
                response = await self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn("项目展示", response.text)
                self.assertNotIn("set-cookie", response.headers)
                head = await self.client.head(path)
                self.assertEqual(head.status_code, 200)
                self.assertEqual(head.content, b"")
                self.assertEqual(head.headers["content-length"], response.headers["content-length"])
                self.assertEqual(head.headers["x-content-type-options"], "nosniff")
        self.assertEqual(self.app.state.active_requests, 0)
        self.assertEqual(self.private.read_bytes(), b"owner database sentinel")

    async def test_only_reviewed_showcase_and_local_math_assets_are_served(self):
        for path in ASSET_PATHS:
            with self.subTest(path=path):
                self.assertEqual((await self.client.get(path)).status_code, 200)
        for path in ("/settings.json", "/.env", "/study_agent.db", "/backend/settings.json", "/vendor/geometry-manifest.json",
                     "/nav.js", "/demo-session.js", "/showcase/unreviewed.js", "/showcase/assets",
                     "/showcase/assets/unreviewed.pdf", "/showcase/assets/unreviewed.svg", "/docs", "/openapi.json"):
            with self.subTest(path=path):
                self.assertEqual((await self.client.get(path)).status_code, 404)

    async def test_api_and_upload_paths_never_reach_owner_or_teaching(self):
        for path in ("/questions", "/settings", "/solve/step1", "/teach/start", "/jobs", "/jobs/uploads",
                     "/demo/session", "/demo/reset", "/auth/guest", "/multimodal/parse", "/grade", "/patterns", "/exam/ai-assemble"):
            for method in ("GET", "POST", "PUT", "DELETE"):
                with self.subTest(path=path, method=method):
                    response = await self.client.request(method, path, content=b"private upload")
                    self.assertEqual(response.status_code, 404)
                    self.assertNotIn("set-cookie", response.headers)
        self.assertEqual((await self.client.post("/home.html")).status_code, 404)
        self.assertEqual(self.app.state.active_requests, 0)
        self.assertEqual(self.private.read_bytes(), b"owner database sentinel")

    async def test_legacy_pages_redirect_to_relevant_sections_without_query_echo(self):
        for path, anchor in (("/teach.html", "teaching"), ("/multimodal.html", "solution"),
                             ("/grade.html", "diagnosis"), ("/routine-graph.html", "graph"),
                             ("/routine-review.html", "pool"), ("/question-pool.html", "pool"),
                             ("/settings.html", "research"), ("/loop.html", "research"),
                             ("/board.html", "research"), ("/history.html", "library"),
                             ("/exam.html", "library"), ("/calendar.html", "library"),
                             ("/login.html", "overview")):
            response = await self.client.get(path + "?private=discarded")
            self.assertEqual(response.status_code, 307)
            self.assertEqual(response.headers["location"], "/#" + anchor)

    async def test_health_and_deploy_drain_work_without_database_or_jobs(self):
        self.assertEqual((await self.client.get("/health")).json(),
                         {"ok": True, "mode": "demo", "demo_mode": "showcase", "ai_enabled": False})
        for draining in (True, False):
            changed = await self.client.post("/_internal/deploy-drain", json={"draining": draining})
            self.assertEqual(changed.status_code, 200)
            self.assertIs(changed.json()["draining"], draining)
            self.assertEqual(changed.json()["active_jobs"], 0)
            self.assertEqual(changed.json()["active_requests"], 0)
            self.assertEqual((await self.client.get("/home.html")).status_code, 200)
            self.assertEqual((await self.client.post("/jobs")).status_code, 404)
        self.assertEqual((await self.client.get("/_internal/deploy-status")).json()["active_requests"], 0)

    async def test_remote_or_forwarded_maintenance_calls_are_hidden(self):
        for headers in ({"Forwarded": "for=127.0.0.1"}, {"X-Forwarded-For": "127.0.0.1"},
                        {"X-Forwarded-Host": "demo.150.chat"}, {"X-Study-Demo-Client": "127.0.0.1"},
                        {"X-Real-IP": "127.0.0.1"}):
            for path, method in (("/_internal/deploy-status", "GET"), ("/_internal/deploy-drain", "POST")):
                response = await self.client.request(method, path, headers=headers, content=b'{"draining":true}')
                self.assertEqual(response.status_code, 404)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app, client=("198.51.100.3", 1234)), base_url="http://demo.test") as remote:
            self.assertEqual((await remote.get("/_internal/deploy-status")).status_code, 404)
            self.assertEqual((await remote.post("/_internal/deploy-drain", json={"draining": True})).status_code, 404)
            self.assertEqual((await remote.get("/home.html")).status_code, 200)
        self.assertFalse(self.app.state.draining)

    async def test_malformed_or_oversized_drain_bodies_do_not_change_state(self):
        for payload in (b"bad JSON", b"null", b"[]", b"{}", b'{"draining":"false"}', b'{"draining":0}',
                        b'{"draining":true,"extra":1}'):
            response = await self.client.post("/_internal/deploy-drain", content=payload)
            self.assertEqual(response.status_code, 400)
        response = await self.client.post("/_internal/deploy-drain", content=b" " * (MAX_DRAIN_BODY + 1))
        self.assertEqual(response.status_code, 413)
        self.assertFalse(self.app.state.draining)

    async def test_path_traversal_and_asset_symlinks_cannot_serve_owner_files(self):
        for path in ("/showcase/%2e%2e/settings.json", "/showcase/%252e%252e/settings.json", "/vendor/%2e%2e/.env",
                     "/showcase/app.js%2f..%2f..%2fowner.sqlite3", "/showcase/app.js%00"):
            self.assertEqual((await self.client.get(path)).status_code, 404)
        asset = self.frontend / "showcase/app.js"
        asset.unlink()
        asset.symlink_to(self.private)
        self.assertEqual((await self.client.get("/showcase/app.js")).status_code, 404)
        fonts = self.frontend / "vendor/katex/fonts"
        saved = self.root / "fonts"
        fonts.rename(saved)
        fonts.symlink_to(saved, target_is_directory=True)
        self.assertEqual((await self.client.get("/vendor/katex/fonts/KaTeX_Main-Regular.woff2")).status_code, 404)
        self.assertEqual(self.private.read_bytes(), b"owner database sentinel")

    async def test_live_response_is_counted_until_its_body_completes(self):
        started = asyncio.Event()
        resume = asyncio.Event()
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "scheme": "http",
                 "method": "GET", "path": "/showcase/app.js", "raw_path": b"/showcase/app.js", "query_string": b"",
                 "root_path": "", "headers": [], "client": ("127.0.0.1", 1234), "server": ("demo.test", 80)}
        received = False

        async def receive():
            nonlocal received
            if not received:
                received = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await resume.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.body":
                started.set()
                await resume.wait()

        task = asyncio.create_task(self.app(scope, receive, send))
        await asyncio.wait_for(started.wait(), timeout=3)
        state = (await self.client.get("/_internal/deploy-status")).json()
        self.assertEqual(state["active_requests"], 1)
        self.assertEqual(state["active_jobs"], 0)
        resume.set()
        await asyncio.wait_for(task, timeout=3)
        self.assertEqual(self.app.state.active_requests, 0)


class ShowcaseIsolationAndDeploymentTests(unittest.TestCase):
    def test_import_has_no_owner_modules_or_private_runtime_side_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory) / "does-not-exist"
            env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "STUDY_DEMO_ROOT": str(runtime),
                   "STUDY_DEMO_AI_CONFIG": str(runtime / "missing-ai.json"), "DEEPSEEK_API_KEY": "never-read"}
            result = subprocess.run([sys.executable, "-c", "import sys; import backend.showcase; "
                                     "assert not any(n in sys.modules for n in ('backend.main', 'backend.demo', 'backend.database', 'backend.settings', 'backend.jobs')); "
                                     "assert backend.showcase.app.state.active_requests == 0"], cwd=ROOT, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(runtime.exists())

    def test_sync_health_check_accepts_only_explicit_showcase_or_legacy_experience(self):
        script = (ROOT / "deploy/sync-sites.sh").read_text()
        marker = 'python3 - "$STAGING/health.json" <<\'PY\'\n'
        start = script.index(marker) + len(marker)
        block = script[start:script.index("\nPY", start)]
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "health.json"
            for value, success in (({"mode": "demo", "demo_mode": "showcase", "ok": True, "ai_enabled": False}, True),
                                   ({"mode": "demo", "ai_enabled": True}, True),
                                   ({"mode": "demo", "ai_enabled": False}, False),
                                   ({"mode": "demo", "demo_mode": "showcase", "ok": True, "ai_enabled": True}, False),
                                   ({"mode": "owner", "ai_enabled": True}, False)):
                target.write_text(json.dumps(value))
                result = subprocess.run([sys.executable, "-c", block, str(target)], capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, success, result.stderr)


if __name__ == "__main__":
    unittest.main()
