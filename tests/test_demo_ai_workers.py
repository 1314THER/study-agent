"""AI workers retain their workspace and cannot expose another visitor's state."""

from copy import deepcopy
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from backend import database, generate, teach, jobs
from backend.data_paths import background_lease, workspace, workspace_directory


class DemoAIWorkersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.a = self.root / "visitor-a"
        self.b = self.root / "visitor-b"
        self.owner = self.root / "owner"
        for directory in (self.a, self.b, self.owner):
            directory.mkdir()
        for patcher in (
            patch.dict(os.environ, {"STUDY_AGENT_DATA_DIR": ""}),
            patch.object(database, "DB_PATH", str(self.owner / "study_agent.db")),
            patch.object(generate, "_GENERATE_JOBS", {}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_candidate_pool_copies_workspace_for_each_worker(self):
        with workspace(self.a):
            database.init_db()
        database.init_db()
        reference = {"id": 1, "answer_json": {}}

        def solve(candidate, teacher, on_phase=None):
            self.assertEqual(workspace_directory(), str(self.a))
            database.save_question(candidate["question"], {})
            return {"question": candidate["question"], "status": "rejected", "token_usage": {}}

        with workspace(self.a), patch.object(generate, "_load_reference", return_value=reference), \
                patch.object(generate, "_call_generation", return_value=[{"question": "变式甲"}, {"question": "变式乙"}]), \
                patch.object(generate, "_solve_candidate", side_effect=solve):
            generate.generate_variants(1, count=2)
            self.assertEqual({q["content"] for q in database.get_all_questions()}, {"变式甲", "变式乙"})
        self.assertEqual(database.get_all_questions(), [])

    def test_background_job_copies_context_and_holds_lease_until_finished(self):
        started = threading.Event()
        finish = threading.Event()
        released = threading.Event()
        calls = []

        def lease():
            calls.append("acquired")
            return lambda: (calls.append("released"), released.set())

        def run(*args, **kwargs):
            self.assertEqual(calls, ["acquired"])
            self.assertEqual(workspace_directory(), str(self.a))
            started.set()
            if not finish.wait(3):
                raise RuntimeError("test worker timed out")
            (self.a / "worker-result.txt").write_text("done", encoding="utf-8")
            return {"accepted": 1}

        try:
            with patch.object(generate, "get_question_by_id", return_value={"id": 1}), \
                    patch.object(generate, "generate_variants", side_effect=run):
                with workspace(self.a), background_lease(lease):
                    job = generate.start_generate_job(1, count=1)
                self.assertTrue(started.wait(3))
                self.assertFalse(released.is_set())
                self.assertNotIn("_workspace", job)
                with workspace(self.b):
                    self.assertIsNone(generate.get_generate_job(job["job_id"]))
                self.assertIsNone(generate.get_generate_job(job["job_id"]))
                with workspace(self.a):
                    self.assertEqual(generate.get_generate_job(job["job_id"])["status"], "running")
                finish.set()
                self.assertTrue(released.wait(3))
                with workspace(self.a):
                    completed = generate.get_generate_job(job["job_id"])
                    self.assertEqual(completed["status"], "done")
                    self.assertEqual(completed["result"], {"accepted": 1})
                self.assertEqual(calls, ["acquired", "released"])
                self.assertTrue((self.a / "worker-result.txt").is_file())
                self.assertFalse((self.owner / "worker-result.txt").exists())
        finally:
            finish.set()
            released.wait(3)

    def test_failed_background_job_also_releases_lease(self):
        released = threading.Event()
        with workspace(self.a), background_lease(lambda: released.set), \
                patch.object(generate, "get_question_by_id", return_value={"id": 1}), \
                patch.object(generate, "generate_variants", side_effect=ValueError("mock AI failure")):
            job = generate.start_generate_job(1, count=1)
            self.assertTrue(released.wait(3))
            self.assertEqual(generate.get_generate_job(job["job_id"])["status"], "error")

    def test_queue_submission_failure_releases_lease_and_removes_job(self):
        releases = []
        with workspace(self.a), background_lease(lambda: lambda: releases.append("released")), \
                patch.object(generate, "get_question_by_id", return_value={"id": 1}), \
                patch.object(jobs._manager.pending, "put_nowait", side_effect=RuntimeError("queue failed")):
            with self.assertRaisesRegex(RuntimeError, "queue failed"):
                generate.start_generate_job(1, count=1)
            self.assertEqual(jobs._manager.list()["jobs"], [])
        self.assertEqual(releases, ["released"])
        self.assertEqual(generate._GENERATE_JOBS, {})

    def test_teaching_session_lookup_and_mutation_require_own_workspace(self):
        manager = teach.TeachSessionManager()
        result = {
            "chunk_results": [{"chunk_type": "大题", "category": {"level1": "数列"}, "steps": [{
                "step_number": 1, "title": "求通项", "standard_writing": "n", "step_prompt": "求通项？"
            }]}]
        }
        with patch("backend.database.find_question", side_effect=lambda _: deepcopy(result)), \
                patch.object(teach, "find_question", side_effect=lambda _: deepcopy(result)), \
                patch.object(teach, "db_save_question", return_value=1), \
                patch.object(teach, "call_deepseek", side_effect=AssertionError("unexpected paid call")):
            with workspace(self.a):
                created = manager.create("原题甲")
            session_id = created["session_id"]
            with workspace(self.b):
                self.assertIsNone(manager.get(session_id))
                manager.add_message(session_id, "student", "foreign message")
                manager.advance_step(session_id)
                self.assertFalse(manager.is_complete(session_id))
            self.assertIsNone(manager.get(session_id))
            with workspace(self.a):
                own = manager.get(session_id)
                self.assertEqual(own["messages"], [])
                self.assertEqual(own["current_step"], 0)
                manager.add_message(session_id, "student", "own message")
                manager.advance_step(session_id)
                self.assertTrue(manager.is_complete(session_id))
                self.assertEqual(own["messages"][0]["content"], "own message")
            owner_session = manager.create("主人题目")
            self.assertIsNotNone(manager.get(owner_session["session_id"]))
            with workspace(self.a):
                self.assertIsNone(manager.get(owner_session["session_id"]))

    def test_demo_keeps_latest_twenty_teaching_sessions_and_owner_is_unlimited(self):
        manager = teach.TeachSessionManager()
        result = {"chunk_results": [{"chunk_type": "大题", "category": {}, "steps": []}]}
        with patch("backend.database.find_question", side_effect=lambda _: deepcopy(result)), \
                patch.object(teach, "find_question", side_effect=lambda _: deepcopy(result)), \
                patch.object(teach, "db_save_question", return_value=1), \
                patch.object(teach, "call_deepseek", side_effect=AssertionError("unexpected paid call")):
            with workspace(self.b):
                other_id = manager.create("游客乙")['session_id']
            with workspace(self.a):
                visitor_ids = [manager.create("游客甲")['session_id'] for _ in range(21)]
                self.assertIsNone(manager.get(visitor_ids[0]))
                self.assertNotIn(visitor_ids[0], manager._session_owners)
                self.assertTrue(all(manager.get(sid) is not None for sid in visitor_ids[1:]))
            owner_ids = [manager.create("主人")['session_id'] for _ in range(21)]
            self.assertTrue(all(manager.get(sid) is not None for sid in owner_ids))
            with workspace(self.b):
                self.assertIsNotNone(manager.get(other_id))
            self.assertEqual(len(manager._sessions), 42)
            self.assertEqual(set(manager._sessions), set(manager._session_owners))

    def test_cleanup_discards_only_the_target_workspace_state(self):
        manager = teach.TeachSessionManager()
        manager._sessions = {"a": {}, "b": {}, "owner": {}}
        manager._session_owners = {"a": str(self.a), "b": str(self.b), "owner": None}
        generate._GENERATE_JOBS.update({
            "a": {"job_id": "a", "_workspace": str(self.a)},
            "b": {"job_id": "b", "_workspace": str(self.b)},
            "owner": {"job_id": "owner", "_workspace": None},
        })
        with patch.object(teach, "_session_manager", manager):
            teach.forget_workspace(self.a)
        generate.forget_workspace(self.a)
        self.assertEqual(set(manager._sessions), {"b", "owner"})
        self.assertEqual(set(generate._GENERATE_JOBS), {"b", "owner"})

    def test_real_store_expiry_waits_for_the_background_worker(self):
        from backend.demo import SessionStore

        store = SessionStore(self.root / "sessions")
        session, _ = store.acquire(None, "test-client", create=True)
        started = threading.Event()
        finish = threading.Event()
        released = threading.Event()

        def lease():
            release = store.borrow(session)
            def done():
                release()
                released.set()
            return done

        def run(*args, **kwargs):
            started.set()
            if not finish.wait(3):
                raise RuntimeError("test worker timed out")
            self.assertTrue(session.directory.exists())
            return {"accepted": 0}

        try:
            with patch.object(generate, "get_question_by_id", return_value={"id": 1}), \
                    patch.object(generate, "generate_variants", side_effect=run):
                with workspace(session.directory), background_lease(lease):
                    generate.start_generate_job(1, count=1)
                self.assertTrue(started.wait(3))
                store.expire(session)
                store.release(session)  # The HTTP request ends while AI is running.
                self.assertTrue(session.directory.exists())
                self.assertEqual(session.active, 1)
                finish.set()
                self.assertTrue(released.wait(3))
                self.assertFalse(session.directory.exists())
                self.assertNotIn(session.token, store.sessions)
        finally:
            finish.set()
            released.wait(3)


if __name__ == "__main__":
    unittest.main()
