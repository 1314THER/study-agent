import json
from contextlib import ExitStack, closing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.source_policy import apply_year_policy, is_old, year_evidence


class SourcePolicyTests(unittest.TestCase):
    def test_boundary_unknown_and_body_numbers(self):
        self.assertTrue(is_old({"year": 2015}))
        self.assertFalse(is_old({"year": 2016}))
        record = {"question": "2015 人进行实验，样本数据 1952", "raw": {"original": {"updateDate": "2015-10-10", "scrapedAt": "2026-06-26"}}}
        self.assertIsNone(year_evidence(record)["year"])
        self.assertEqual(apply_year_policy(record)["raw"]["year_status"], "unknown")

    def test_reliable_titles_paths_ranges_and_conflicts(self):
        self.assertTrue(is_old({"raw": {"paper": "2015年全国数学卷", "file": "content/2015/paper.tex"}}))
        self.assertIsNone(year_evidence({"raw": {"paper": "2015-2016学年数学期中考试"}})["year"])
        self.assertIsNone(year_evidence({"raw": {"file": "20261004-release.jsonl"}})["year"])
        proof = year_evidence({"year": 2015, "raw": {"paper": "2016年数学试卷"}})
        self.assertEqual(proof["status"], "conflict")
        self.assertFalse(is_old({"year": 2015, "raw": {"paper": "2016年数学试卷"}}))


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        from backend import database, patterns, question_pool
        from backend.data_paths import workspace
        from backend.identity import identity_context
        from tests.api_base import seed_answer
        self.pool, self.database, self.patterns, self.seed = question_pool, database, patterns, seed_answer
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(workspace(self.root))
        self.stack.enter_context(identity_context({"id": "studyadmin", "username": "studyadmin", "role": "owner"}))
        database.init_db()
        patterns.init_mastery_db()
        self.paths = [self.root / "question_pool.db", self.root / "study_agent.db", self.root / "mastery.db"]

    def record(self, key, question, year):
        return {"source_key": key, "question": question, "answer": "2", "categories": ["集合与逻辑用语"],
                "year": year, "raw": {}, "completeness": "complete"}

    def import_legacy(self, records):
        with patch("backend.question_pool.is_old", return_value=False):
            return self.pool.import_records({"name": "legacy", "kind": "jsonl"}, records)

    def test_delete_references_backups_idempotence_and_reimport(self):
        from backend.question_pool_maintenance import build_plan, apply_plan, backup_databases
        records = [self.record("old", "旧题集合甲", 2015), self.record("modern", "新题集合乙", 2016),
                   self.record("unknown", "2015个人参加的未知年份题", None), self.record("mixed-old", "重复题集合丙", 2015),
                   self.record("mixed-new", "重复题集合丙", 2025)]
        result = self.import_legacy(records)
        answer = self.seed()
        answer["source_meta"] = {"year": 2015, "paper": "2015数学试卷"}
        answer["provenance"] = [{"year": 2015, "paper": "2015数学试卷"}]
        old_qid = self.database.save_question("旧的正式集合题", answer)
        modern_qid = self.database.save_question("新的正式集合题", self.seed())
        mother = self.patterns.add_mother_question(old_qid, "集合与逻辑用语", "待清理母题")
        with closing(self.patterns._get_conn()) as conn, conn:
            bid = conn.execute("INSERT INTO boards (category,name) VALUES (?,?)", ("集合与逻辑用语", "清理测试看板")).lastrowid
            conn.execute("INSERT INTO board_nodes (board_id,question_id) VALUES (?,?)", (bid, old_qid))
            conn.execute("INSERT INTO board_edges (board_id,from_question_id,to_question_id) VALUES (?,?,?)", (bid, old_qid, modern_qid))
            conn.execute("INSERT INTO loop_rounds (round_id,pattern_id,queue_json) VALUES (?,?,?)", ("old-round", mother["pattern_id"], json.dumps([{"question_id": old_qid}])))
            conn.execute("INSERT INTO loop_job_results (job_id,round_id,result_json) VALUES (?,?,?)", ("old-job", "old-round", "{}"))
        plan = build_plan(*self.paths)
        self.assertEqual(len(plan["delete_items"]), 1)
        self.assertEqual(len(plan["delete_occurrences"]), 2)
        self.assertEqual([q["id"] for q in plan["delete_formal_questions"]], [old_qid])
        backup = backup_databases(self.paths, self.root / "backup")
        self.assertEqual(len(backup), 3)
        report = apply_plan(*self.paths, plan)
        self.assertEqual(report["after"]["pool_items"], 3)
        self.assertEqual(report["after"]["formal_questions"], 1)
        self.assertFalse(any(report["references_after"].values()))
        second = build_plan(*self.paths)
        self.assertEqual(apply_plan(*self.paths, second)["deleted"]["pool_items"], 0)
        replay = self.pool.import_records(result["source_id"], records, retry_failed=True)
        self.assertEqual(replay["report"]["skipped_old"], 2)
        self.assertEqual(replay["added_occurrences"], 0)
        items = self.pool.list_items(completeness=None)["data"]
        self.assertEqual({i["year"] for i in items}, {"2016", "2025", ""})

    def test_stale_manifest_rolls_back_and_legacy_commit_is_blocked(self):
        from backend.question_pool_maintenance import build_plan, apply_plan
        self.import_legacy([self.record("old", "旧题甲", 2015)])
        item = self.pool.list_items(completeness=None)["data"][0]
        with self.assertRaises(ValueError):
            self.pool.validate_prepare_args({"item_ids": [item["id"]]})
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            self.pool.commit_items([item["id"]], "legacy-replay")
        plan = build_plan(*self.paths)
        self.pool.import_records({"name": "new", "kind": "jsonl"}, [self.record("new", "新题乙", 2026)])
        with self.assertRaises(ValueError):
            apply_plan(*self.paths, plan)
        self.assertEqual(self.pool.list_items(completeness=None)["total"], 2)


if __name__ == "__main__":
    unittest.main()
