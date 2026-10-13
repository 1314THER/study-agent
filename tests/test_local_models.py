"""Local entry points must stay unavailable in a normal/cloud checkout."""
from contextlib import ExitStack
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from backend import local_models as local, solver, jobs, question_pool as pool, routine_review as rr


class LocalModelTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {"STUDY_LOCAL_CODEX":"0", "STUDY_DEMO_ROOT":""}))
        self.stack.enter_context(patch.object(pool, "_require_owner"))
        app = FastAPI()
        app.include_router(local.router)
        app.include_router(pool.router)
        app.include_router(rr.router)
        @app.middleware("http")
        async def guard(request, call_next):
            with local.request_context(request):
                return await call_next(request)
        self.client = TestClient(app)

    def enable_fake(self, caller):
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        path = Path(directory) / "provider.py"
        path.write_text("# fake local provider")
        module = SimpleNamespace(available=lambda: True, pipeline_caller=lambda: caller,
                                 routine_config=lambda: {"engine":"codex_luna"},
                                 validate_routine_config=lambda config: None)
        self.stack.enter_context(patch.object(local, "PLUGIN", path))
        self.stack.enter_context(patch.object(local, "_plugin", module))
        self.stack.enter_context(patch.dict(os.environ, {"STUDY_LOCAL_CODEX":"1"}))
        return module

    def test_cloud_has_placeholder_and_cannot_submit_local_jobs(self):
        with patch.object(local.importlib.util, "spec_from_file_location") as loader, patch.object(jobs, "submit_job") as submit:
            result = self.client.get("/local-models/status").json()
            self.assertFalse(result["codex_cli"]["available"])
            self.assertIn("云端暂不可用", result["codex_cli"]["detail"])
            response = self.client.post("/question-pool/prepare", json={"item_ids":[1], "engine":"codex_cli"})
            self.assertEqual(response.status_code,503)
            submit.assert_not_called()
            with self.assertRaises(HTTPException) as caught:
                pool.validate_prepare_args({"item_ids":[1], "engine":"codex_cli"})
            self.assertEqual(caught.exception.status_code, 503)
            with self.assertRaises(HTTPException):
                rr.model_config("codex_luna")
            loader.assert_not_called()

    def test_env_flag_without_private_files_does_not_enable_cloud(self):
        with patch.dict(os.environ, {"STUDY_LOCAL_CODEX":"1"}), patch.object(local, "PLUGIN", Path("/nonexistent/provider.py")):
            self.assertFalse(local.enabled())
            self.assertFalse(self.client.get("/local-models/status").json()["codex_cli"]["available"])

    def test_forwarded_or_public_requests_cannot_use_local_provider(self):
        caller = Mock()
        self.enable_fake(caller)
        self.assertTrue(self.client.get("/local-models/status").json()["codex_cli"]["available"])
        for headers in ({"X-Forwarded-For":"203.0.113.1"}, {"Host":"study.example"}, {"Forwarded":"for=203.0.113.1"}):
            self.assertFalse(self.client.get("/local-models/status", headers=headers).json()["codex_cli"]["available"])
            response = self.client.post("/question-pool/prepare", headers=headers, json={"item_ids":[1],"engine":"codex_cli"})
            self.assertEqual(response.status_code,503)
        caller.assert_not_called()

    def test_local_pipeline_uses_override_without_ds_key_and_restores_scope(self):
        caller = Mock(return_value=("CLI output", {"prompt_tokens":3}))
        self.enable_fake(caller)
        with patch.object(solver, "get_api_key", side_effect=AssertionError("DS key must not be read")):
            with local.pipeline("codex_cli"):
                for stage in ("Solver", "Verifier", "Formatter"):
                    self.assertEqual(solver.call_deepseek(stage,"synthetic question")[0],"CLI output")
            self.assertIsNone(local.current_caller())
        self.assertEqual(caller.call_count,3)

    def test_local_errors_never_fall_back_and_do_not_leak_into_ds(self):
        caller = Mock(side_effect=RuntimeError("CLI unavailable"))
        self.enable_fake(caller)
        with patch.object(solver, "get_api_key", side_effect=AssertionError("paid fallback forbidden")):
            with self.assertRaisesRegex(RuntimeError,"CLI unavailable"):
                with local.pipeline("codex_cli"):
                    solver.call_deepseek("Solver","synthetic")
        self.assertIsNone(local.current_caller())
        with local.pipeline("deepseek"):
            self.assertIsNone(local.current_caller())

    def test_pool_job_keeps_engine_for_entire_prepare_operation(self):
        caller = Mock()
        self.enable_fake(caller)
        observed=[]
        def prepare(args,ctx):
            observed.append(local.current_caller())
            return {"ready":1}
        with patch.object(pool,"prepare_items",side_effect=prepare):
            self.assertEqual(jobs._pool_prepare({"item_ids":[1],"engine":"codex_cli"},None),{"ready":1})
            jobs._pool_prepare({"item_ids":[2]},None)
        self.assertEqual(observed,[caller,None])


if __name__ == "__main__":
    unittest.main()
