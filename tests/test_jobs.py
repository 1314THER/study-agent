"""Background acceptance, workspace isolation, idempotence and real fallback gates."""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI

from backend import database, jobs, teach
from backend.data_paths import background_lease, workspace, workspace_directory
from backend.identity import identity_context


class JobArgumentTest(unittest.TestCase):
    def test_shared_negative_ids_are_accepted(self):
        for kind, args in (("generate", {"question_id": -1}),
                           ("pattern_check", {"pattern_id": -2, "question_id": -1}),
                           ("pattern_variants", {"pattern_id": -2})):
            with self.subTest(kind=kind):
                self.assertEqual(jobs.validate_args(kind, args), args)
        payload = {"question_id": -1, "student_answer": "2", "loop": {
            "round_id": "shared-round", "pattern_id": -2, "queue_index": 0,
            "queue": [{"role": "mother", "question_id": -1}], "mother_only": True,
        }}
        self.assertEqual(jobs.validate_args("grade", payload)["loop"]["pattern_id"], -2)

    def test_zero_bool_and_non_integer_ids_are_rejected(self):
        for bad_id in (0, True, False, "-1", 1.5):
            for kind, args in (("generate", {"question_id": bad_id}),
                               ("pattern_check", {"pattern_id": -2, "question_id": bad_id}),
                               ("pattern_variants", {"pattern_id": bad_id}),
                               ("grade", {"question_id": bad_id, "student_answer": "2"})):
                with self.subTest(kind=kind, bad_id=bad_id), self.assertRaises(ValueError):
                    jobs.validate_args(kind, args)

    def test_only_deepseek_provider_is_accepted(self):
        self.assertEqual(jobs.validate_args("provider_test", {"provider": "deepseek"}), {"provider": "deepseek"})
        with self.assertRaises(ValueError):
            jobs.validate_args("provider_test", {"provider": "dashscope"})

    def test_account_workspaces_keep_history_seven_days(self):
        with tempfile.TemporaryDirectory() as directory, workspace(directory):
            self.assertEqual(jobs._history_ttl(), 7200)
            with identity_context({"id": "visitor", "role": "guest"}):
                self.assertEqual(jobs._history_ttl(), 7200)
            for role in ("user", "owner"):
                with identity_context({"id": "account", "role": role}):
                    self.assertEqual(jobs._history_ttl(), 7 * 86400)


class ManualTimer:
    """A deadline callback without waiting 300 real seconds or invoking AI."""
    instances = []

    def __init__(self, interval, function):
        self.interval, self.function = interval, function
        self.cancelled = False
        self.started = threading.Event()
        self.instances.append(self)

    def start(self):
        self.started.set()

    def cancel(self):
        self.cancelled = True

    def fire(self):
        return self.function()


class JobsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.a, self.b = self.root / "a", self.root / "b"
        self.a.mkdir()
        self.b.mkdir()
        self.manager = jobs.JobManager()
        ManualTimer.instances = []
        self.patchers = [patch.object(jobs, "_manager", self.manager),
                         patch.dict(os.environ, {"STUDY_AGENT_JOB_DIR": str(self.root / "owner"), "STUDY_AGENT_DATA_DIR": ""}),
                         patch.object(teach, "_session_manager", teach.TeachSessionManager())]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def wait(self, job_id):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            result = self.manager.get(job_id)
            if result and result["status"] in jobs.TERMINAL:
                return result
            time.sleep(0.005)
        self.fail("test job did not finish")

    def drain(self):
        deadline = time.monotonic() + 4
        while self.manager.runtimes and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertFalse(self.manager.runtimes)

    def test_navigation_resume_context_lease_and_workspace_access(self):
        started, finish, released = threading.Event(), threading.Event(), threading.Event()
        count = []
        def run(args, ctx):
            count.append(workspace_directory())
            started.set()
            self.assertTrue(finish.wait(3))
            return {"final_answer": "2"}
        self.manager.runners = {"solve": run}
        try:
            with workspace(self.a), background_lease(lambda: released.set):
                submitted = self.manager.submit("solve", {"question": "1+1等于多少？"}, "navigation-1")
            self.assertTrue(started.wait(2))
            with workspace(self.a):
                self.assertEqual(self.manager.list()["jobs"][0]["status"], "running")
                self.assertFalse(released.is_set())
            with workspace(self.b):
                self.assertIsNone(self.manager.get(submitted["job_id"]))
            self.assertIsNone(self.manager.get(submitted["job_id"]))
            finish.set()
            with workspace(self.a):
                self.assertEqual(self.wait(submitted["job_id"])["result"]["final_answer"], "2")
            self.assertTrue(released.wait(2))
            self.assertEqual(count, [str(self.a)])
        finally:
            finish.set()
            self.drain()

    def test_retries_are_idempotent_and_changed_payload_conflicts(self):
        calls = []
        self.manager.runners = {"solve": lambda args, ctx: (calls.append(args["question"]) or {"answer": 2})}
        with workspace(self.a):
            first = self.manager.submit("solve", {"question": "1+1等于多少？"}, "deduplicate-1")
            second = self.manager.submit("solve", {"question": "1+1等于多少？"}, "deduplicate-1")
            self.assertEqual(first["job_id"], second["job_id"])
            with self.assertRaises(jobs.JobConflict):
                self.manager.submit("solve", {"question": "2+2等于多少？"}, "deduplicate-1")
            self.wait(first["job_id"])
        self.drain()
        self.assertEqual(calls, ["1+1等于多少？"])

    def test_only_two_jobs_execute_and_accepted_third_waits(self):
        lock = threading.Lock()
        finish, two_started = threading.Event(), threading.Event()
        active = [0, 0]
        def run(args, ctx):
            with lock:
                active[0] += 1
                active[1] = max(active[1], active[0])
                if active[0] == 2:
                    two_started.set()
            self.assertTrue(finish.wait(3))
            with lock:
                active[0] -= 1
            return {"ok": True}
        self.manager.runners = {"solve": run}
        try:
            with workspace(self.a):
                ids = [self.manager.submit("solve", {"question": f"计算第{i}道题"}, f"workers-{i}")["job_id"] for i in range(3)]
            self.assertTrue(two_started.wait(2))
            self.assertEqual(active[1], 2)
            with workspace(self.a):
                self.assertEqual(sum(j["status"] == "queued" for j in self.manager.list()["jobs"]), 1)
            finish.set()
            with workspace(self.a):
                for job_id in ids:
                    self.wait(job_id)
        finally:
            finish.set()
            self.drain()

    def test_restart_retains_finished_and_marks_running_interrupted(self):
        with workspace(self.a):
            self.manager.prepare(jobs.storage_path())
            with self.manager._connection(jobs.storage_path()) as conn:
                for job_id, state in (("a" * 32, "running"), ("b" * 32, "done")):
                    conn.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                 (job_id, "solve", job_id, "fingerprint", '{}', state, state, 50, "test", time.time(), time.time(), '{"answer":2}', None, "live_ai", "old-runtime"))
            restarted = jobs.JobManager()
            self.assertEqual(restarted.get("a" * 32)["status"], "interrupted")
            self.assertEqual(restarted.get("b" * 32)["result"], {"answer": 2})

    def test_restart_reclaims_abandoned_uploads_and_preserves_active_upload(self):
        with workspace(self.a):
            path = jobs.storage_path()
            self.manager.prepare(path)
            base = path.parent / "job-uploads"
            directories = {state: base / ("upload-" + state) for state in ("running", "done", "orphan", "active")}
            for directory in directories.values():
                directory.mkdir(parents=True)
                (directory / "input.png").write_bytes(b"example")
            restarted = jobs.JobManager()
            with self.manager._connection(path) as conn:
                for index, state in enumerate(("running", "done", "active"), 1):
                    args = {"_upload_dir": str(directories[state]), "_upload_path": str(directories[state] / "input.png")}
                    status = "queued" if state == "active" else state
                    runtime_id = restarted.runtime_id if state == "active" else "old-runtime"
                    conn.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                 (str(index) * 32, "ocr_file", "restart-upload-" + state, "fp", json.dumps(args),
                                  status, status, 50, "test", time.time(), time.time(), None, None, None, runtime_id))
            restarted.prepare(path)
            self.assertEqual(restarted.get("1" * 32)["status"], "interrupted")
            for state in ("running", "done", "orphan"):
                self.assertFalse(directories[state].exists(), state)
            self.assertEqual((directories["active"] / "input.png").read_bytes(), b"example")

    def test_upload_recovery_does_not_follow_escape_paths_or_symlinks(self):
        outside = self.root / "outside"
        outside.mkdir()
        protected = outside / "protected.png"
        protected.write_bytes(b"keep")
        with workspace(self.a):
            path = jobs.storage_path()
            self.manager.prepare(path)
            base = path.parent / "job-uploads"
            base.mkdir()
            linked = base / "upload-link"
            linked.symlink_to(outside, target_is_directory=True)
            abandoned = base / "upload-old"
            abandoned.mkdir()
            (abandoned / "nested-link").symlink_to(outside, target_is_directory=True)
            with self.manager._connection(path) as conn:
                args = {"_upload_dir": str(outside), "_upload_path": str(protected)}
                conn.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             ("c" * 32, "ocr_file", "outside-path", "fp", json.dumps(args), "running", "running",
                              50, "test", time.time(), time.time(), None, None, None, "old-runtime"))
            restarted = jobs.JobManager()
            restarted.prepare(path)
            jobs._remove_upload_directory(path, outside)
            jobs._remove_upload_directory(path, base / ".." / ".." / "outside")
            jobs._remove_upload_directory(path, linked)
            self.assertFalse(abandoned.exists())
            self.assertTrue(linked.is_symlink())
            self.assertEqual(protected.read_bytes(), b"keep")
        # Even the whole upload root may be replaced with a link: recovery must
        # never walk it, although it points at otherwise matching child names.
        external_child = outside / "upload-external"
        external_child.mkdir()
        (self.b / "job-uploads").symlink_to(outside, target_is_directory=True)
        jobs.JobManager().prepare(self.b / "jobs.sqlite3")
        self.assertTrue(external_child.is_dir())
        self.assertEqual(protected.read_bytes(), b"keep")

    def test_summary_omits_result_and_direct_get_enforces_retention(self):
        self.manager.runners = {"solve": lambda args, ctx: {"answer": 2}}
        with workspace(self.a):
            job = self.manager.submit("solve", {"question": "计算1+1"}, "retention-1")
            self.wait(job["job_id"])
            self.drain()
            self.assertNotIn("result", self.manager.list()["jobs"][0])
            with self.manager._connection(jobs.storage_path()) as conn:
                conn.execute("UPDATE jobs SET updated_at=? WHERE job_id=?", (time.time() - 7201, job["job_id"]))
            self.assertIsNone(self.manager.get(job["job_id"]))

    def test_all_domain_kinds_dispatch_expected_arguments_and_result_shapes(self):
        from backend import agent, generate, grade, multimodal, patterns, settings
        class Context:
            def progress(self, *args):
                pass
        ctx = Context()
        contracts = [
            ("teach_start", {"question": "题干", "teacher": "liangliang"}, teach, "teach_session_start", {"session_id": "s", "revision": 0}),
            ("teach_legacy_start", {"question": "题干"}, teach, "teach_start", {"steps": []}),
            ("teach_chat", {"session_id": "s", "message": "作答", "expected_revision": 1}, teach, "teach_session_chat", {"action": "guide", "revision": 2}),
            ("teach_check", {"question": "题干", "step_prompt": "问题", "step_answer": "答案", "user_answer": "作答"}, teach, "teach_check", {"is_correct": True}),
            ("teach_ack", {"session_id": "s", "expected_revision": 2}, teach, "teach_ack_prompt", {"ok": True, "revision": 3}),
            ("teach_finish", {"session_id": "s", "step_errors": {}}, teach, "teach_finish_session", {"saved": True, "saved_question_id": 1}),
            ("generate", {"question_id": 1, "count": 2}, generate, "generate_variants", {"accepted": 2, "items": []}),
            ("grade", {"question_id": 1, "student_answer": "2", "source": "首次"}, grade, "grade_text", {"is_correct": True, "practice_record_id": 1}),
            ("parse_file", {"_upload_path": "input.png", "filename": "试卷.png"}, multimodal, "parse_file", [{"latex": "x=1"}]),
            ("ocr_file", {"_upload_path": "input.png"}, multimodal, "recognize_answer_image", {"text": "x=1", "confidence": "high"}),
            ("agent", {"message": "打开题库", "history": []}, agent, "agent_act", {"reply": "好", "actions": [{"type": "navigate", "page": "history"}], "blocks": []}),
            ("pattern_check", {"pattern_id": 1, "question_id": 2, "user_answer": "3"}, patterns, "check_pattern_answer", {"is_correct": True}),
            ("pattern_variants", {"pattern_id": 1}, patterns, "ensure_variants", {"generated": 3}),
        ]
        for kind, args, module, function, result in contracts:
            with self.subTest(kind=kind), patch.object(module, function, autospec=True, return_value=result) as mocked:
                dispatched = jobs.RUNNERS[kind](args, ctx)
                self.assertEqual(dispatched, {"questions": result, "total": len(result)} if kind == "parse_file" else result)
                mocked.assert_called_once()
                if kind == "grade":
                    self.assertEqual(mocked.call_args.kwargs["student_answer"], "2")
                if kind == "teach_chat":
                    self.assertEqual(mocked.call_args.kwargs["expected_revision"], 1)
        with patch.object(settings, "get_api", return_value={"deepseek": {"base_url": "https://example.invalid/v1"}}), \
                patch.object(settings, "get_api_key", return_value="private-test-key"), \
                patch.object(httpx, "get", return_value=type("Response", (), {"status_code": 200})()) as get:
            self.assertEqual(jobs.RUNNERS["provider_test"]({"provider": "deepseek"}, ctx), {"ok": True, "provider": "deepseek"})
            self.assertEqual(get.call_args.kwargs["headers"], {"Authorization": "Bearer private-test-key"})

    def test_batch_partial_results_preserve_success_after_another_question_fails(self):
        def solve(args, ctx):
            if args["question"] == "失败题":
                raise ValueError("mock failure")
            return jobs.Outcome({"final_answer": "2"})
        with patch.object(jobs, "_solve", side_effect=solve), workspace(self.a):
            accepted = self.manager.submit("batch_solve", {"questions": [{"question": "成功题"}, {"question": "失败题"}]}, "batch-test")
            completed = self.wait(accepted["job_id"])
            self.drain()
            self.assertEqual(completed["result"]["done"], 2)
            self.assertEqual(completed["result"]["failed"], 1)
            self.assertEqual([item["status"] for item in completed["result"]["items"]], ["done", "error"])

    def test_draining_rejects_new_submission_but_allows_retry_and_read(self):
        self.manager.runners = {"solve": lambda args, ctx: {"ok": True}}
        with workspace(self.a):
            existing = self.manager.submit("solve", {"question": "计算1+1"}, "draining-1")
            self.wait(existing["job_id"])
            self.manager.draining = True
            self.assertEqual(self.manager.submit("solve", {"question": "计算1+1"}, "draining-1")["job_id"], existing["job_id"])
            with self.assertRaises(jobs.JobBusy):
                self.manager.submit("solve", {"question": "计算2+2"}, "draining-2")
        self.drain()

    def test_provider_limit_is_shared_between_deepseek_tasks(self):
        entered, release = threading.Event(), threading.Event()
        lock = threading.Lock()
        counts = [0, 0]
        def run(provider):
            with jobs.provider_slot(provider):
                with lock:
                    counts[0] += 1
                    counts[1] = max(counts[1], counts[0])
                    if counts[0] == 2:
                        entered.set()
                self.assertTrue(release.wait(3))
                with lock:
                    counts[0] -= 1
        threads = [threading.Thread(target=run, args=(provider,)) for provider in ("deepseek", "deepseek", "deepseek")]
        try:
            for thread in threads:
                thread.start()
            self.assertTrue(entered.wait(2))
            self.assertEqual(jobs.provider_active_count(), 2)
            self.assertEqual(counts[1], 2)
        finally:
            release.set()
            for thread in threads:
                thread.join(3)
        self.assertEqual(jobs.provider_active_count(), 0)

    def test_pdf_parse_renders_and_recognizes_one_page_before_next_render(self):
        from backend import multimodal
        events = []
        def pages(*args):
            for page in (1, 2):
                events.append(("render", page))
                yield page, 2, str(page)
        def recognize(**args):
            events.append(("recognize", int(args["image_base64"])))
            return '[{"latex":"x=1"}]'
        with patch.object(multimodal, "iter_pdf_images", side_effect=pages), \
                patch.object(multimodal, "_call_deepseek_vision", side_effect=recognize):
            questions = multimodal.parse_file("fake.pdf")
        self.assertEqual(events, [("render", 1), ("recognize", 1), ("render", 2), ("recognize", 2)])
        self.assertEqual(len(questions), 2)

    def test_preset_calls_solver_before_deadline_cache_and_late_result_cannot_save(self):
        from backend.demo_presets import get_preset, DEFAULT_PRESET_ID
        preset = get_preset(DEFAULT_PRESET_ID)
        started, finish = threading.Event(), threading.Event()
        saves = []
        now = [1000.0]
        def solve(*args, **kwargs):
            started.set()
            self.assertTrue(finish.wait(3))
            return {"content": "late", "token_usage": {}}
        try:
            with patch("backend.solver.step_solver_only", side_effect=solve), \
                    patch("backend.database.save_question", side_effect=lambda q, aj: (saves.append(deepcopy(aj)) or 9)), \
                    patch.object(jobs.time, "monotonic", side_effect=lambda: now[0]), \
                    patch.object(jobs.threading, "Timer", ManualTimer):
                with workspace(self.a):
                    accepted = self.manager.submit("solve", {"question": preset["question"], "preset_id": preset["id"]}, "preset-deadline")
                self.assertTrue(started.wait(2))
                with workspace(self.a):
                    runtime = self.manager.runtimes[accepted["job_id"]]
                    self.assertEqual(runtime.deadline, 1300)
                    now[0] = 1299
                    token = jobs._CURRENT.set(runtime)
                    try:
                        jobs.ensure_active()
                        self.assertEqual(jobs.request_timeout(600), 1)
                        self.assertFalse(ManualTimer.instances[0].fire())
                        self.assertEqual(self.manager.get(accepted["job_id"])["status"], "running")
                        self.assertEqual(saves, [])
                        now[0] = 1300
                        with self.assertRaises(jobs.JobStopped):
                            jobs.ensure_active()
                    finally:
                        jobs._CURRENT.reset(token)
                    self.assertTrue(ManualTimer.instances[0].fire())
                    cached = self.manager.get(accepted["job_id"])
                    self.assertEqual(cached["source"], "prepared_cache")
                    self.assertEqual(cached["result"]["saved_question_id"], 9)
                finish.set()
                self.drain()
                with workspace(self.a):
                    self.assertEqual(self.manager.get(accepted["job_id"])["source"], "prepared_cache")
                self.assertEqual(len(saves), 1)
                self.assertTrue(saves[0]["prepared_example"])
        finally:
            finish.set()
            self.drain()

    def test_modified_preset_has_no_deadline_and_live_worker_result_is_saved(self):
        from backend.demo_presets import get_preset, DEFAULT_PRESET_ID
        preset = get_preset(DEFAULT_PRESET_ID)
        started, finish = threading.Event(), threading.Event()
        saves = []
        def solve(args, ctx):
            self.assertIsNone(ctx.prepared)
            self.assertIsNone(ctx.deadline)
            started.set()
            self.assertTrue(finish.wait(3))
            return jobs.Outcome({"source": "live_ai", "final_answer": "custom"},
                                lambda value: saves.append(deepcopy(value)))
        self.manager.runners = {"solve": solve}
        try:
            with patch.object(jobs.threading, "Timer", ManualTimer), workspace(self.a):
                job = self.manager.submit("solve", {"question": preset["question"] + "\n改变条件", "preset_id": preset["id"]}, "edited-preset-1")
                self.assertTrue(started.wait(2))
                self.assertEqual(ManualTimer.instances, [])
                finish.set()
                self.assertEqual(self.wait(job["job_id"])["result"]["final_answer"], "custom")
            self.drain()
            self.assertEqual(len(saves), 1)
        finally:
            finish.set()
            self.drain()

    def test_batch_preset_deadlines_are_per_leaf_and_late_calls_do_not_save(self):
        from backend.demo_presets import public_presets
        first, second = public_presets()[:2]
        starts = [threading.Event(), threading.Event()]
        finishes = [threading.Event(), threading.Event()]
        released = threading.Event()
        now, calls, contexts, saves = [1000.0], [], [], []
        edited = first["question"] + "\n改变条件"
        questions = [{"question": first["question"], "preset_id": first["id"]},
                     {"question": edited, "preset_id": first["id"]},
                     {"question": "失败题"},
                     {"question": second["question"], "preset_id": second["id"]}]
        def solver(question, *args, **kwargs):
            with jobs.provider_slot("deepseek"):
                calls.append(question)
                if question in (first["question"], second["question"]):
                    index = int(question == second["question"])
                    contexts.append(jobs._CURRENT.get())
                    starts[index].set()
                    self.assertTrue(finishes[index].wait(3))
                if question == "失败题":
                    raise ValueError("mock partial failure")
                return {"content": question, "token_usage": {}}
        def save(question, answer):
            saves.append((question, deepcopy(answer), workspace_directory()))
            return len(saves)
        try:
            with patch("backend.solver.step_solver_only", side_effect=solver), \
                    patch("backend.solver.step_verify_all", return_value={"chunk_results": [{"final_answer": "edited"}]}) as verify, \
                    patch("backend.solver.step_final_check", return_value={"final_answer": "edited", "chunk_results": []}), \
                    patch("backend.database.save_question", side_effect=save), \
                    patch.object(jobs.time, "monotonic", side_effect=lambda: now[0]), \
                    patch.object(jobs.threading, "Timer", ManualTimer):
                with workspace(self.a), background_lease(lambda: released.set):
                    accepted = self.manager.submit("batch_solve", {"questions": questions}, "batch-preset-deadlines")
                self.assertTrue(starts[0].wait(2))
                self.assertTrue(ManualTimer.instances[0].started.wait(2))
                self.assertEqual(contexts[0].deadline, 1300)
                self.assertIsNot(contexts[0], self.manager.runtimes[accepted["job_id"]])
                now[0] = 1299
                self.assertFalse(ManualTimer.instances[0].fire())
                self.assertEqual(saves, [])
                self.assertFalse(starts[1].is_set())
                now[0] = 1300
                self.assertTrue(ManualTimer.instances[0].fire())
                self.assertTrue(starts[1].wait(2))
                self.assertTrue(ManualTimer.instances[1].started.wait(2))
                self.assertEqual(contexts[1].deadline, 1600)
                self.assertEqual(len(ManualTimer.instances), 2)  # Edited preset uses no cache.
                self.assertEqual(jobs.provider_active_count(), 2)
                now[0] = 1599
                self.assertFalse(ManualTimer.instances[1].fire())
                now[0] = 1600
                self.assertTrue(ManualTimer.instances[1].fire())
                with workspace(self.a):
                    completed = self.wait(accepted["job_id"])
                    self.assertEqual(completed["result"]["failed"], 1)
                    items = completed["result"]["items"]
                    self.assertEqual([item["status"] for item in items], ["done", "done", "error", "done"])
                    self.assertEqual([items[i]["result"]["source"] for i in (0, 1, 3)],
                                     ["prepared_cache", "live_ai", "prepared_cache"])
                    self.assertTrue(items[0]["result"]["prepared_example"])
                    self.assertEqual(self.manager.submit("batch_solve", {"questions": questions}, "batch-preset-deadlines")["job_id"], accepted["job_id"])
                    cold = jobs.JobManager()
                    self.assertEqual(cold.get(accepted["job_id"])["result"], completed["result"])
                with workspace(self.b):
                    self.assertIsNone(self.manager.get(accepted["job_id"]))
                self.assertIn(accepted["job_id"], self.manager.runtimes)
                self.assertFalse(released.is_set())  # Late HTTP calls still retain the visitor workspace.
                self.assertEqual(calls, [item["question"] for item in questions])
                self.assertEqual(len(saves), 3)
                self.assertTrue(all(directory == str(self.a) for _, _, directory in saves))
                for finish in finishes:
                    finish.set()
                self.drain()
                self.assertTrue(released.wait(2))
                self.assertEqual(jobs.provider_active_count(), 0)
                self.assertEqual(len(saves), 3)
                verify.assert_called_once()  # Neither late preset continues to another AI step.
        finally:
            for finish in finishes:
                finish.set()
            self.drain()

    def test_batch_preset_early_failure_returns_error_without_cache(self):
        from backend.demo_presets import get_preset, DEFAULT_PRESET_ID
        preset = get_preset(DEFAULT_PRESET_ID)
        with patch("backend.solver.step_solver_only", side_effect=RuntimeError("mock early failure")), \
                patch("backend.database.save_question") as save, \
                patch.object(jobs.threading, "Timer", ManualTimer), workspace(self.a):
            accepted = self.manager.submit("batch_solve", {"questions": [{"question": preset["question"], "preset_id": preset["id"]}]}, "batch-preset-error")
            result = self.wait(accepted["job_id"])
            self.drain()
            item = result["result"]["items"][0]
            self.assertEqual(item["status"], "error")
            self.assertIsNone(item["result"])
            self.assertIn("mock early failure", item["error"]["detail"])
            save.assert_not_called()
            self.assertEqual(len(ManualTimer.instances), 1)
            self.assertTrue(ManualTimer.instances[0].cancelled)

    def test_preset_worker_return_at_299_is_live_and_at_300_is_cache(self):
        from backend.demo_presets import get_preset, DEFAULT_PRESET_ID
        preset = get_preset(DEFAULT_PRESET_ID)
        question = {"question": preset["question"], "preset_id": preset["id"]}
        for kind in ("solve", "batch_solve"):
            for elapsed in (299, 300):
                with self.subTest(kind=kind, elapsed=elapsed):
                    now, commits = [1000.0], []
                    def solve(args, ctx):
                        self.assertEqual(ctx.deadline, 1300)
                        now[0] += elapsed
                        return jobs.Outcome({"source": "live_ai", "final_answer": "live"},
                                            lambda value: commits.append("live"))
                    self.manager.runners = {"solve": solve, "batch_solve": jobs._batch_solve}
                    with patch.object(jobs, "_solve", side_effect=solve), \
                            patch.object(jobs.time, "monotonic", side_effect=lambda: now[0]), \
                            patch.object(jobs.threading, "Timer", ManualTimer), \
                            patch("backend.database.save_question", side_effect=lambda q, aj: (commits.append("cache") or 7)), \
                            workspace(self.a):
                        args = question if kind == "solve" else {"questions": [question]}
                        accepted = self.manager.submit(kind, args, f"boundary-{kind}-{elapsed}")
                        # The fake clock deliberately jumps beyond wait()'s
                        # ordinary four-second test deadline inside the worker.
                        for _ in range(200):
                            completed = self.manager.get(accepted["job_id"])
                            if completed["status"] in jobs.TERMINAL:
                                break
                            time.sleep(.005)
                        self.assertEqual(completed["status"], "done")
                        self.drain()
                        result = completed["result"]
                        if kind == "batch_solve":
                            result = result["items"][0]["result"]
                        self.assertEqual(result["source"], "live_ai" if elapsed == 299 else "prepared_cache")
                        self.assertEqual(commits, ["live"] if elapsed == 299 else ["cache"])

    def test_early_ai_failure_is_error_and_does_not_return_cache(self):
        from backend.demo_presets import get_preset, DEFAULT_PRESET_ID
        preset = get_preset(DEFAULT_PRESET_ID)
        with patch("backend.solver.step_solver_only", side_effect=RuntimeError("mock API failure")):
            with workspace(self.a):
                accepted = self.manager.submit("solve", {"question": preset["question"], "preset_id": preset["id"]}, "preset-failure")
                result = self.wait(accepted["job_id"])
                self.assertEqual(result["status"], "error")
                self.assertIsNone(result["result"])
        self.drain()

    def teaching_session(self, two_steps=False):
        answer = {"chunk_results": [{"chunk_type": "填空题", "category": {}, "final_answer": "2", "steps": [{
            "step_number": 1, "title": "计算", "step_prompt": "1+1是多少？", "standard_writing": "2", "step_answer": "2"}]}]}
        if two_steps:
            answer["chunk_results"][0]["steps"].append({"step_number": 2, "title": "再计算", "step_prompt": "2+2是多少？", "standard_writing": "4", "step_answer": "4"})
        database.init_db()
        database.save_question("计算1+1", answer)
        return teach.teach_session_start("计算1+1")

    def test_cold_teaching_restore_does_not_wait_for_job_submission_lock(self):
        # Model a concurrent submit holding jobs.lock before it reserves a turn,
        # while a cold teaching GET reloads SQLite under the teaching lock.
        with workspace(self.a):
            session = self.teaching_session()
        with self.manager.prepare_lock:
            self.manager.prepared_paths.clear()
        cold_manager = teach.TeachSessionManager()
        entered, restored = threading.Event(), threading.Event()
        errors = []
        def reload():
            try:
                with workspace(self.a), cold_manager._lock:
                    entered.set()
                    self.assertEqual(cold_manager.get(session["session_id"])["revision"], 0)
                    restored.set()
            except BaseException as exc:
                errors.append(exc)
        thread = threading.Thread(target=reload, daemon=True)
        try:
            with self.manager.lock:
                thread.start()
                self.assertTrue(entered.wait(1))
                self.assertTrue(restored.wait(1), "cold teaching reload acquired the job submission lock")
                with workspace(self.a):
                    cold_manager.reserve(session["session_id"], "cold-path-job", 0)
        finally:
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertFalse(errors)

    def test_teaching_failure_rolls_back_and_persists_original_state(self):
        with workspace(self.a):
            session = self.teaching_session()
            original = deepcopy(teach.teach_get_session(session["session_id"]))
            with patch.object(teach, "call_deepseek", side_effect=RuntimeError("mock network failure")):
                accepted = self.manager.submit("teach_chat", {"session_id": session["session_id"], "message": "2", "expected_revision": 0}, "teach-fail")
                self.assertEqual(self.wait(accepted["job_id"])["status"], "error")
                self.drain()
            restored = teach.TeachSessionManager().get(session["session_id"])
            self.assertEqual(restored["messages"], original["messages"])
            self.assertEqual(restored["stats"], original["stats"])
            self.assertEqual(restored["revision"], 0)
            self.assertEqual(restored["attempt_count"], 0)
            self.assertIsNone(restored.get("pending_job"))

    def test_teaching_retries_do_not_double_count_and_stale_turn_conflicts(self):
        with workspace(self.a):
            session = self.teaching_session()
            with patch.object(teach, "call_deepseek", return_value=(json.dumps({"is_correct": True, "feedback": "正确"}), {})) as called:
                args = {"session_id": session["session_id"], "message": "2", "expected_revision": 0}
                accepted = self.manager.submit("teach_chat", args, "teach-success")
                completed = self.wait(accepted["job_id"])
                self.drain()
                self.assertEqual(completed["result"]["revision"], 1)
                self.assertEqual(self.manager.submit("teach_chat", args, "teach-success")["job_id"], accepted["job_id"])
                with self.assertRaises(jobs.JobConflict):
                    self.manager.submit("teach_chat", args, "teach-stale")
                restored = teach.TeachSessionManager().get(session["session_id"])
                self.assertEqual(restored["stats"]["correct"], 1)
                self.assertEqual(restored["current_step"], 1)
                self.assertTrue(restored["results_saved"])
                called.assert_called_once()

    def test_next_prompt_and_revision_restore_without_browser_ack(self):
        with workspace(self.a):
            session = self.teaching_session(two_steps=True)
            with patch.object(teach, "call_deepseek", return_value=(json.dumps({"is_correct": True, "feedback": "正确"}), {})):
                accepted = self.manager.submit("teach_chat", {"session_id": session["session_id"], "message": "2", "expected_revision": 0}, "teach-next")
                self.wait(accepted["job_id"])
                restored = teach.TeachSessionManager().get(session["session_id"])
                self.assertIsNone(restored.get("pending_job"))
                self.assertEqual(restored["current_step"], 1)
                self.assertEqual(restored["messages"][-1]["content"], "2+2是多少？")
                self.assertTrue(restored["step_introduced"])
                self.assertEqual(restored["revision"], 1)
            self.drain()

    def test_wrong_feedback_saved_once_at_completion_and_retries_do_not_duplicate(self):
        with workspace(self.a):
            session = self.teaching_session()
            responses = [(json.dumps({"is_correct": False, "feedback": "再试一次", "error_type": "计算错误", "error_detail": "加法算错"}), {}),
                         (json.dumps({"is_correct": True, "feedback": "正确"}), {})]
            with patch.object(teach, "call_deepseek", side_effect=responses):
                wrong = self.manager.submit("teach_chat", {"session_id": session["session_id"], "message": "3", "expected_revision": 0}, "teach-wrong")
                self.wait(wrong["job_id"])
                args = {"session_id": session["session_id"], "message": "2", "expected_revision": 1}
                correct = self.manager.submit("teach_chat", args, "teach-correct")
                self.wait(correct["job_id"])
                self.drain()
                self.manager.submit("teach_chat", args, "teach-correct")
                restored = teach.TeachSessionManager().get(session["session_id"])
                self.assertEqual(restored["stats"], {"correct": 1, "wrong": 1, "skipped": 0, "viewed_answer": 0})
                errors = database.get_step_errors(restored["question_id"])
                self.assertEqual(len(errors), 1)
                self.assertEqual(errors[0]["student_input"], "3")

    def test_viewing_answer_counts_once_per_step_and_restores_after_reload(self):
        with workspace(self.a):
            session = self.teaching_session(two_steps=True)
            sid = session["session_id"]
            teach.teach_session_chat(sid, "答案", expected_revision=0)
            teach.teach_session_chat(sid, "看一下答案", expected_revision=1)
            # A fresh manager restores the in-progress flag and its statistics
            # from SQLite rather than retaining the original process cache.
            restored_manager = teach.TeachSessionManager()
            restored = restored_manager.get(sid)
            self.assertEqual(restored["stats"]["viewed_answer"], 1)
            self.assertTrue(restored["step_viewed_answer"])
            with patch.object(teach, "_session_manager", restored_manager), \
                    patch.object(teach, "call_deepseek", return_value=(json.dumps({"is_correct": True, "feedback": "正确"}), {})) as called:
                teach.teach_session_chat(sid, "2", expected_revision=2)
                advanced = teach.teach_get_session(sid)
                self.assertEqual(advanced["current_step"], 1)
                self.assertTrue(advanced["step_results"][0]["viewed_answer"])
                self.assertFalse(advanced["step_viewed_answer"])
                teach.teach_session_chat(sid, "答案", expected_revision=3)
                called.assert_called_once()
            final = teach.TeachSessionManager().get(sid)
            self.assertEqual(final["stats"]["viewed_answer"], 2)
            self.assertTrue(final["step_viewed_answer"])
            self.assertTrue(final["step_results"][0]["viewed_answer"])

    def test_skipping_after_viewing_answer_retains_the_step_flag(self):
        with workspace(self.a):
            session = self.teaching_session(two_steps=True)
            sid = session["session_id"]
            teach.teach_session_chat(sid, "答案", expected_revision=0)
            teach.teach_session_chat(sid, "跳过", expected_revision=1)
            restored = teach.TeachSessionManager().get(sid)
            self.assertEqual(restored["stats"]["viewed_answer"], 1)
            self.assertEqual(restored["stats"]["skipped"], 1)
            self.assertTrue(restored["step_results"][0]["viewed_answer"])
            self.assertFalse(restored["step_viewed_answer"])

    def loop_fixture(self, *, mastered=False, variants=False):
        from backend import patterns
        database.init_db()
        answer = {"question_type": "填空题", "final_answer": "2", "chunk_results": [{"chunk_type": "填空题", "final_answer": "2"}]}
        mother = database.save_question("循环母题：1+1", deepcopy(answer))
        pattern = patterns.add_mother_question(mother, "集合与逻辑用语", "循环恢复测试")
        queue = [{"role": "mother", "question_id": mother}]
        if variants:
            for index in (1, 2, 3):
                qid = database.save_question("循环变式 " + str(index), deepcopy(answer))
                patterns.add_variant_question(pattern["pattern_id"], qid, "variant" + str(index))
                queue.append({"role": "variant" + str(index), "question_id": qid})
        if mastered:
            patterns.complete_pattern_loop(pattern["pattern_id"], True)
            queue = queue[:1]
        loop = {"round_id": "loop-round-test", "pattern_id": pattern["pattern_id"], "queue": queue,
                "queue_index": 0, "mother_only": not mastered and not variants, "elapsed_seconds": 5}
        return {"question_id": mother, "student_answer": "2", "duration_seconds": 5, "loop": loop}

    def test_loop_grade_finishes_after_leaving_page_and_replays_without_duplicate_stats(self):
        from backend import patterns
        with workspace(self.a):
            args = self.loop_fixture(mastered=True)
            with patch("backend.grade.call_deepseek", side_effect=AssertionError("must not call paid AI")):
                accepted = self.manager.submit("grade", args, "loop-off-page")
        # No browser callback sends attempt/complete requests; only the worker
        # runs, using the workspace captured at acceptance.
        with workspace(self.a):
            completed = self.wait(accepted["job_id"])
            self.drain()
            result = completed["result"]["loop"]
            self.assertTrue(result["completed"])
            self.assertEqual(result["mastery"]["state"], "second_pass")
            self.assertEqual(self.manager.submit("grade", args, "loop-off-page")["job_id"], accepted["job_id"])
            self.assertEqual(patterns.commit_loop_grade(args["loop"], args["question_id"], accepted["job_id"], True, 5), result)
            self.assertEqual(jobs.JobManager().get(accepted["job_id"])["result"]["loop"], result)
            with patterns._get_conn() as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 1)
            with database.get_connection() as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM practice_records").fetchone()[0], 1)
            self.assertEqual(patterns.get_pattern(args["loop"]["pattern_id"])["mastery"]["state"], "second_pass")

    def test_loop_wrong_then_correct_commits_once_and_keeps_first_try_history(self):
        from backend import patterns
        with workspace(self.a):
            args = self.loop_fixture(mastered=True)
            args["student_answer"] = "3"
            wrong = self.manager.submit("grade", args, "loop-wrong-grade")
            self.assertFalse(self.wait(wrong["job_id"])["result"]["is_correct"])
            self.drain()
            self.assertEqual(patterns.get_pattern(args["loop"]["pattern_id"])["mastery"]["state"], "never")
            self.assertEqual(self.manager.submit("grade", args, "loop-wrong-grade")["job_id"], wrong["job_id"])
            correct_args = deepcopy(args)
            correct_args["student_answer"] = "2"
            correct = self.manager.submit("grade", correct_args, "loop-correct-grade")
            done = self.wait(correct["job_id"])
            self.drain()
            self.assertTrue(done["result"]["loop"]["session_failed"])
            self.assertEqual(done["result"]["loop"]["mastery"]["state"], "first_pass")
            with patterns._get_conn() as conn:
                attempts = conn.execute("SELECT correct,is_first_try FROM attempts ORDER BY id").fetchall()
                self.assertEqual([tuple(row) for row in attempts], [(0, 1), (1, 0)])

    def test_loop_context_cannot_skip_questions_or_fake_roles_to_advance(self):
        with workspace(self.a):
            args = self.loop_fixture(variants=True)
            shortened = deepcopy(args)
            shortened["loop"]["queue"] = shortened["loop"]["queue"][:1]
            wrong_role = deepcopy(args)
            wrong_role["loop"]["queue"][0]["role"] = "variant1"
            skipped = deepcopy(args)
            skipped["loop"]["queue_index"] = 3
            skipped["question_id"] = skipped["loop"]["queue"][3]["question_id"]
            with patch("backend.grade.grade_text") as grade:
                for index, payload in enumerate((shortened, wrong_role, skipped)):
                    with self.assertRaises(jobs.JobConflict):
                        self.manager.submit("grade", payload, "loop-spoof-" + str(index))
                grade.assert_not_called()

    def test_loop_full_queue_advances_mastery_only_after_all_roles_pass(self):
        from backend import patterns
        with workspace(self.a):
            args = self.loop_fixture(variants=True)
            for index, question in enumerate(args["loop"]["queue"]):
                payload = deepcopy(args)
                payload["question_id"] = question["question_id"]
                payload["loop"]["queue_index"] = index
                job = self.manager.submit("grade", payload, "loop-full-" + str(index))
                result = self.wait(job["job_id"])["result"]["loop"]
                self.drain()
                self.assertEqual(result["next_index"], index + 1)
                self.assertEqual(result["completed"], index == 3)
                self.assertEqual(patterns.get_pattern(args["loop"]["pattern_id"])["mastery"]["state"], "first_pass" if index == 3 else "never")
            with patterns._get_conn() as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 4)

    def test_loop_pending_turn_blocks_another_paid_grade_and_failure_releases_it(self):
        started, release = threading.Event(), threading.Event()
        def grade(**args):
            started.set()
            release.wait(3)
            return {"error": "ai_failed", "detail": "mock offline"}
        with workspace(self.a):
            args = self.loop_fixture(mastered=True)
            try:
                with patch("backend.grade.grade_text", side_effect=grade) as graded:
                    accepted = self.manager.submit("grade", args, "loop-pending-first")
                    self.assertTrue(started.wait(2))
                    with self.assertRaises(jobs.JobConflict):
                        self.manager.submit("grade", args, "loop-pending-second")
                    other_tab = deepcopy(args)
                    other_tab["loop"]["round_id"] = "loop-other-tab"
                    with self.assertRaises(jobs.JobConflict):
                        self.manager.submit("grade", other_tab, "loop-pending-other-tab")
                    graded.assert_called_once()
                    release.set()
                    self.assertEqual(self.wait(accepted["job_id"])["status"], "error")
                    self.drain()
                retried = self.manager.submit("grade", args, "loop-after-error")
                self.assertTrue(self.wait(retried["job_id"])["result"]["loop"]["completed"])
                self.drain()
            finally:
                release.set()
                self.drain()

    def test_mother_only_pass_still_requires_variants_and_timeout_skips_ai(self):
        from backend import patterns
        with workspace(self.a):
            args = self.loop_fixture()
            job = self.manager.submit("grade", args, "loop-mother-pass")
            result = self.wait(job["job_id"])["result"]["loop"]
            self.drain()
            self.assertTrue(result["needs_variants"])
            self.assertFalse(result["completed"])
            self.assertEqual(patterns.get_pattern(args["loop"]["pattern_id"])["mastery"]["state"], "never")
            timed = deepcopy(args)
            timed["loop"]["round_id"] = "loop-timeout-round"
            timed["loop"]["elapsed_seconds"] = 121.2
            timed["duration_seconds"] = 121
            with patch("backend.grade.grade_text", side_effect=AssertionError("timeout must not call grade")):
                job = self.manager.submit("grade", timed, "loop-timeout-grade")
                result = self.wait(job["job_id"])["result"]
                self.drain()
            self.assertTrue(result["timed_out"])
            self.assertEqual(result["loop"]["mastery"]["state"], "never")


class UploadJobsTest(unittest.IsolatedAsyncioTestCase):
    async def test_upload_rejects_a_symlinked_upload_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "outside"
            outside.mkdir()
            ledger = root / "ledger"
            ledger.mkdir()
            (ledger / "job-uploads").symlink_to(outside, target_is_directory=True)
            manager = jobs.JobManager()
            app = FastAPI()
            app.include_router(jobs.router)
            with patch.object(jobs, "_manager", manager), workspace(ledger):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                    response = await client.post("/jobs/uploads", data={"kind": "ocr_file", "request_id": "symlink-root-upload"},
                                                 files={"file": ("input.png", b"image-data", "image/png")})
            self.assertEqual(response.status_code, 500)
            self.assertEqual(list(outside.iterdir()), [])
            self.assertFalse(manager.runtimes)

    async def test_upload_is_accepted_before_recognition_finishes_and_duplicate_reuses_job(self):
        with tempfile.TemporaryDirectory() as directory:
            orphan = Path(directory) / "job-uploads" / "upload-before-restart"
            orphan.mkdir(parents=True)
            (orphan / "input.png").write_bytes(b"abandoned")
            started, finish = threading.Event(), threading.Event()
            def run(args, ctx):
                self.assertEqual(Path(args["_upload_path"]).read_bytes(), b"image-data")
                started.set()
                self.assertTrue(finish.wait(3))
                return {"text": "x=2"}
            manager = jobs.JobManager(runners={"ocr_file": run})
            app = FastAPI()
            app.include_router(jobs.router)
            with patch.object(jobs, "_manager", manager), workspace(directory):
                try:
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                        response = await client.post("/jobs/uploads", data={"kind": "ocr_file", "request_id": "upload-test-1"}, files={"file": ("../../outside.png", b"image-data", "image/png")})
                        self.assertEqual(response.status_code, 202, response.text)
                        job = response.json()
                        self.assertNotIn("_upload_path", job["args"])
                        self.assertEqual(job["args"]["filename"], "outside.png")
                        self.assertFalse(orphan.exists())
                        self.assertTrue(await asyncio.to_thread(started.wait, 2))
                        repeated = await client.post("/jobs/uploads", data={"kind": "ocr_file", "request_id": "upload-test-1"}, files={"file": ("outside.png", b"image-data", "image/png")})
                        self.assertEqual(repeated.status_code, 202, repeated.text)
                        self.assertEqual(repeated.json()["job_id"], job["job_id"])
                        self.assertEqual(len(list((Path(directory) / "job-uploads").iterdir())), 1)
                        self.assertEqual((await client.get("/jobs/" + job["job_id"])).json()["status"], "running")
                        finish.set()
                        for _ in range(100):
                            result = (await client.get("/jobs/" + job["job_id"])).json()
                            if result["status"] == "done" and not manager.runtimes:
                                break
                            await asyncio.sleep(.01)
                        self.assertEqual(result["result"], {"text": "x=2"})
                        self.assertEqual(list((Path(directory) / "job-uploads").iterdir()), [])
                finally:
                    finish.set()
                    for _ in range(100):
                        if not manager.runtimes:
                            break
                        await asyncio.sleep(.01)


if __name__ == "__main__":
    unittest.main()
