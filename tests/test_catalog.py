import json
import logging
from pathlib import Path
import sqlite3
import tempfile
import unittest

from fastapi import HTTPException

from backend.catalog import publish_catalog, sync_catalog
from backend.data_paths import workspace
from backend.database import init_db, save_question, get_question_by_id, get_all_questions, delete_question, update_question_source, add_step_error
from backend.identity import identity_context
from backend.patterns import init_mastery_db, add_mother_question, get_patterns, update_pattern, complete_pattern_loop, delete_pattern, get_mastery_summary, record_attempt
from tests.api_base import seed_answer


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.owner = self.root / "owner"
        self.owner.mkdir()
        self.catalog = self.root / "catalog.db"
        with workspace(self.owner):
            init_db()
            init_mastery_db()
            self.qid = save_question("公共题：集合有几个子集？", seed_answer())
            self.pid = add_mother_question(self.qid, "集合与逻辑用语", "公共集合套路")["pattern_id"]
            save_question("主人私有题", seed_answer())
            publish_catalog(self.owner, self.catalog)

    def learner(self, name):
        directory = self.root / name
        directory.mkdir(exist_ok=True)
        return identity_context({"id": name, "username": name, "role": "user"}), workspace(directory)

    def test_shared_library_private_progress_and_updates(self):
        identity, files = self.learner("alice")
        with identity, files:
            init_db()
            init_mastery_db()
            self.assertTrue(sync_catalog(self.catalog))
            self.assertFalse(sync_catalog(self.catalog))
            question = get_question_by_id(-self.qid)
            self.assertEqual(question["catalog_id"], self.qid)
            self.assertIsNone(question["user_id"])
            self.assertFalse(question["can_edit"])
            self.assertEqual(len(get_all_questions()), 1)
            complete_pattern_loop(-self.pid, True)
            add_step_error(-self.qid, 1, 1, "计算错误")
            private = save_question("Alice私有题", seed_answer())
            self.assertGreater(private, 0)
            self.assertEqual(get_question_by_id(private)["user_id"], "alice")
        identity, files = self.learner("bob")
        with identity, files:
            init_db()
            init_mastery_db()
            sync_catalog(self.catalog)
            self.assertEqual(get_patterns()[0]["mastery"]["state"], "never")
            self.assertEqual(len(get_all_questions()), 1)
        with workspace(self.owner):
            update_pattern(self.pid, name="公共集合套路更新")
            publish_catalog(self.owner, self.catalog)
        identity, files = self.learner("alice")
        with identity, files:
            sync_catalog(self.catalog)
            self.assertEqual(get_patterns()[0]["name"], "公共集合套路更新")
            self.assertEqual(get_patterns()[0]["mastery"]["state"], "first_pass")
            self.assertEqual(len(get_all_questions()), 2)
            with sqlite3.connect(str(self.root / "alice" / "study_agent.db")) as conn:
                self.assertEqual(conn.execute("SELECT count(*) FROM step_errors").fetchone()[0], 1)
        with sqlite3.connect(self.catalog) as conn:
            encoded = conn.execute("SELECT definitions_json FROM shared_catalog").fetchone()[0]
            self.assertNotIn("主人私有题", encoded)
            self.assertNotIn("Alice私有题", encoded)
            self.assertNotIn("step_errors", encoded)

    def test_mutation_guards_cover_direct_tools_and_save_upsert(self):
        identity, files = self.learner("alice")
        with identity, files:
            init_db()
            init_mastery_db()
            sync_catalog(self.catalog)
            original = get_question_by_id(-self.qid)["answer_json"]
            self.assertEqual(save_question("公共题：集合有几个子集？", {"final_answer": "篡改"}), -self.qid)
            self.assertEqual(get_question_by_id(-self.qid)["answer_json"], original)
            for action in (
                lambda: delete_question(-self.qid),
                lambda: update_question_source(-self.qid, "模拟题"),
                lambda: add_mother_question(None, "集合与逻辑用语", "伪造母题"),
                lambda: update_pattern(-self.pid, name="篡改"),
                lambda: save_question("伪造题", {"source_type": "精选母题"}),
                lambda: publish_catalog(self.owner, self.catalog),
            ):
                with self.assertRaises(HTTPException) as caught:
                    action()
                self.assertEqual(caught.exception.status_code, 403)

    def test_existing_duplicate_reuses_id_and_keeps_errors(self):
        identity, files = self.learner("alice")
        with identity, files:
            init_db()
            init_mastery_db()
            own_id = save_question("公共题：集合有几个子集？", seed_answer())
            add_step_error(own_id, 1, 1, "审题错误")
            sync_catalog(self.catalog)
            self.assertEqual(get_question_by_id(own_id)["catalog_id"], self.qid)
            self.assertIsNone(get_question_by_id(-self.qid))
            self.assertEqual(get_patterns()[0]["mother_id"], own_id)

    def test_choice_option_normalization_cannot_bypass_shared_question_guard(self):
        original_text = "选出正确的数：A、1 B、2"
        with workspace(self.owner):
            qid = save_question(original_text, seed_answer())
            add_mother_question(qid, "集合与逻辑用语", "公共选择套路")
            publish_catalog(self.owner, self.catalog)
        identity, files = self.learner("alice")
        with identity, files:
            init_db()
            init_mastery_db()
            sync_catalog(self.catalog)
            original = get_question_by_id(-qid)["answer_json"]
            self.assertEqual(save_question(original_text, {"final_answer": "篡改"}), -qid)
            self.assertEqual(get_question_by_id(-qid)["answer_json"], original)

    def test_withdrawn_mother_stays_out_of_curriculum_after_database_reinitialization(self):
        identity, files = self.learner("alice")
        with identity, files:
            init_db()
            init_mastery_db()
            sync_catalog(self.catalog)
            add_step_error(-self.qid, 1, 1, "计算错误")
        with workspace(self.owner):
            delete_pattern(self.pid)
            update_question_source(self.qid, "模拟题")
            publish_catalog(self.owner, self.catalog)
        identity, files = self.learner("alice")
        with identity, files:
            sync_catalog(self.catalog)
            init_db()  # Account workspace reopening / service restart.
            sync_catalog(self.catalog)
            self.assertIsNotNone(get_question_by_id(-self.qid))
            with sqlite3.connect(str(self.root / "alice" / "study_agent.db")) as conn:
                count = conn.execute("SELECT COUNT(*) FROM question_list_members m JOIN question_lists l ON l.id=m.list_id WHERE m.question_id=? AND l.list_type='system' AND l.name='母题' AND m.is_removed=0", (-self.qid,)).fetchone()[0]
                self.assertEqual(count, 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM step_errors WHERE question_id=?", (-self.qid,)).fetchone()[0], 1)

    def test_withdrawn_pattern_leaves_active_summary_and_keeps_attempt_history(self):
        identity, files = self.learner("alice")
        with identity, files:
            init_db()
            init_mastery_db()
            sync_catalog(self.catalog)
            complete_pattern_loop(-self.pid, True)
            record_attempt(-self.pid, -self.qid, "mother", True)
        with workspace(self.owner):
            delete_pattern(self.pid)
            publish_catalog(self.owner, self.catalog)
        identity, files = self.learner("alice")
        with identity, files:
            sync_catalog(self.catalog)
            self.assertEqual(get_patterns(), [])
            summary = get_mastery_summary()
            self.assertEqual(sum(summary["pattern_states"].values()), 0)
            self.assertEqual(sum(item["total_patterns"] for item in summary["categories"]), 0)
            with sqlite3.connect(str(self.root / "alice" / "mastery.db")) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM attempts WHERE pattern_id=?", (-self.pid,)).fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
