"""Question pool isolation, provenance and human-confirmed promotion.

All learning, pattern and pool databases live in temporary workspaces. The
solver is mocked at its existing job boundary so these tests cannot make AI
requests or alter the owner's repository data.
"""

from contextlib import ExitStack
from copy import deepcopy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend import database, jobs, patterns, settings
from backend.data_paths import background_lease, workspace
from backend.identity import identity_context
from tests.api_base import seed_answer


CATEGORY = "集合与逻辑用语"
OWNER = {"id": "studyadmin", "username": "studyadmin", "role": "owner"}


class PoolContext:
    """Run a preparation worker without a thread, provider or persistent job."""

    def __init__(self):
        self.job_id = "pool-test-job"
        self.events = []

    def progress(self, *args, **kwargs):
        self.events.append((args, kwargs))


class QuestionPoolTests(unittest.TestCase):
    def setUp(self):
        from backend import question_pool

        self.pool = question_pool
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            "STUDY_AGENT_DATA_DIR": "",
            "STUDY_DEMO_AI_CONFIG": "",
        }))
        self.stack.enter_context(workspace(self.root))
        self.stack.enter_context(identity_context(OWNER))
        self.stack.enter_context(patch.object(settings, "_cache", {}))
        database.init_db()
        patterns.init_mastery_db()

    def source(self, name="试题来源", publication_allowed=True):
        return {
            "name": name, "kind": "json", "url": "https://example.org/questions",
            "revision": "test-v1", "license": "CC0-1.0",
            "publication_allowed": publication_allowed,
        }

    def record(self, n=1, **changes):
        record = {
            "source_key": f"paper-1-question-{n}",
            "question": f"集合 $A=\\{{1,{n + 1}\\}}$ 的子集有多少个？",
            "answer": "A", "solution": "两个元素的集合有四个子集。",
            "categories": [CATEGORY], "question_type": "选择题",
            "year": 2024, "region": "全国", "question_no": str(n),
            "page_start": 3, "page_end": 4, "completeness": "complete",
            "raw": {"paper": "集合练习", "n": n},
        }
        record.update(changes)
        return record

    def test_diagram_conditions_are_part_of_duplicate_identity(self):
        first = self.record(raw={"image_refs": [{"url": "https://example.org/ellipse-1.png"}]})
        other = self.record(2, question=first["question"], raw={"image_refs": [{"url": "https://example.org/ellipse-2.png"}]})
        replay = self.record(3, question=first["question"], raw=deepcopy(first["raw"]))
        result = self.pool.import_records(self.source(), [first, other, replay])
        self.assertEqual(result["stats"]["unique"], 2)
        self.assertEqual(result["stats"]["duplicates"], 1)
        items = self.pool.list_items(completeness="", page_size=100)["data"]
        self.pool.update_item(items[0]["id"], {"question": first["question"]})
        result = self.pool.import_records(self.source(), [first, other, replay], retry_failed=True)
        self.assertEqual(result["added_occurrences"], 0)

    def test_available_graphic_restores_candidate_and_replay_keeps_owner_edits(self):
        from backend.question_assets import store_image
        from PIL import Image
        from io import BytesIO
        root = self.pool.files_directory().parent
        root.mkdir(parents=True)
        image = BytesIO()
        Image.new("RGB", (30, 20), "white").save(image, format="PNG")
        (root / "figure.png").write_bytes(image.getvalue())
        record = self.record(question="如图求面积", completeness="deferred_graphic", raw={"source_root": str(root), "image_refs": [{"path": "figure.png"}]})
        self.pool.import_records(self.source(), [record])
        item = self.pool.list_items()["data"][0]
        self.assertEqual(item["completeness"], "needs_review")
        self.assertEqual(item["asset_count"], 1)
        self.assertEqual(self.pool.import_records(self.source(), [record], retry_failed=True)["recovered_occurrences"], 0)
        self.pool.update_item(item["id"], {"question": "主人修正的题目", "completeness": "complete"})
        self.pool.import_records(self.source(), [record], retry_failed=True)
        self.assertEqual(self.pool.get_item(item["id"])["question"], "主人修正的题目")

    def test_complete_label_cannot_bypass_missing_diagram_before_preparation(self):
        item = self.import_one(self.record(question="如图求面积", raw={"image_refs": [{"path": "missing.png"}]}))
        with self.assertRaisesRegex(ValueError, "题图缺失"):
            self.pool.validate_prepare_args({"item_ids": [item["id"]]})

    def test_pdf_diagram_identity_survives_edits_and_replay(self):
        first = self.record(raw={"graphic_file": {"sha256": "first-pdf", "page_start": 1, "question_no": "1"}})
        other = self.record(2, question=first["question"], raw={"graphic_file": {"sha256": "second-pdf", "page_start": 1, "question_no": "1"}})
        result = self.pool.import_records(self.source(), [first, other])
        self.assertEqual(result["stats"]["unique"], 2)
        self.assertEqual(self.pool.import_records(self.source(), [first, other], retry_failed=True)["added_occurrences"], 0)

    def test_online_collection_is_owner_only_and_bounds_years_and_concurrency(self):
        self.assertEqual(jobs.validate_args('pool_collect', {'years': [2026, 2025, 2026]})['years'], [2025, 2026])
        for args in ({'years': [2015]}, {'concurrency': 21}, {'years': [True]}):
            with self.assertRaises(ValueError):
                jobs.validate_args('pool_collect', args)
        with identity_context({'id': 'guest', 'username': 'guest', 'role': 'guest'}):
            with self.assertRaises(HTTPException) as caught:
                jobs.validate_args('pool_collect', {'years': [2026]})
            self.assertEqual(caught.exception.status_code, 403)

    def test_collection_reparse_uses_question_identity_and_preserves_manual_edits(self):
        raw = {"collector": True, "file_sha256": "fixture-file", "paper_validation": {"valid": True}, "conversion_parser": 1}
        first = self.record(raw=raw)
        result = self.pool.import_records(self.source(), [first])
        sid = result["source_id"]
        updated = self.record(source_key="reordered-ocr-locator", question="集合的完整新条件", raw={**raw, "conversion_parser": 2})
        second = self.pool.import_records(sid, [updated], retry_failed=True)
        self.assertEqual(second["added_occurrences"], 0)
        self.assertEqual(second["recovered_occurrences"], 1)
        item = self.pool.list_items(completeness="", page_size=100)["data"][0]
        self.assertEqual(item["question"], updated["question"])
        self.pool.update_item(item["id"], {"question": "主人已修订的条件"})
        replay = self.pool.import_records(sid, [first], retry_failed=True)
        self.assertEqual(replay["added_occurrences"], 0)
        self.assertEqual(replay["recovered_occurrences"], 0)
        self.assertEqual(self.pool.get_item(item["id"])["question"], "主人已修订的条件")

    def test_collection_api_submits_job_and_keeps_report_owner_only(self):
        from backend.source_conversion import atomic_json
        atomic_json(self.pool.files_directory().parent / "collections/progress.json", {"stage": "done", "question_records": 19})
        def submit(kind, args, request_id):
            validated = jobs.validate_args(kind, args)
            self.assertEqual(validated["concurrency"], 20)
            return {"job_id": "collection-test", "kind": kind, "status": "queued"}
        with patch.object(jobs, "submit_job", side_effect=submit), self.client() as client:
            response = client.post("/question-pool/collect", json={"years": [2026]})
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json()["kind"], "pool_collect")
            self.assertEqual(client.get("/question-pool/collection").json()["question_records"], 19)
            self.assertEqual(client.post("/question-pool/collect", json={"years": [2015]}).status_code, 400)
            with identity_context({"id": "guest", "username": "guest", "role": "guest"}):
                self.assertEqual(client.get("/question-pool/collection").status_code, 403)

    def test_repair_into_existing_item_uses_target_version_before_manual_edit(self):
        import json
        raw = {"collector": True, "file_sha256": "shared-pdf", "conversion_parser": 1, "paper_validation": {"valid": True}}
        failed = self.record(question="", completeness="failed", raw=raw)
        existing = self.record(2)
        sid = self.pool.import_records(self.source(), [failed, existing])["source_id"]
        repaired = self.record(question=existing["question"], raw=raw)
        self.pool.import_records(sid, [repaired], retry_failed=True)
        with self.pool._connection() as conn:
            occurrence = conn.execute("SELECT * FROM pool_occurrences WHERE source_id=? AND source_key=?", (sid, failed["source_key"])).fetchone()
            version = conn.execute("SELECT version FROM pool_items WHERE id=?", (occurrence["item_id"],)).fetchone()[0]
        self.assertEqual(json.loads(occurrence["raw_json"])["automatic_repair_version"], version)
        self.pool.update_item(occurrence["item_id"], {"categories": ["概率统计"]})
        replay = self.pool.import_records(sid, [self.record(question="新提取条件", raw={**raw, "conversion_parser": 2})], retry_failed=True)
        self.assertEqual(replay["recovered_occurrences"], 0)
        self.assertEqual(self.pool.get_item(occurrence["item_id"])["categories"], ["概率统计"])

    def import_one(self, record=None, source=None):
        record = record or self.record()
        self.pool.import_records(source or self.source(), [record])
        return next(item for item in self.pool.list_items(completeness=None, page=1, page_size=100)["data"]
                    if item["question"] == record["question"])

    def prepare(self, item_id, result=None):
        result = deepcopy(result or seed_answer())
        with patch.object(jobs, "_solve", return_value=jobs.Outcome(result)) as solve:
            self.pool.prepare_items({"item_ids": [item_id], "teacher": "liangliang"}, PoolContext())
        return solve

    def client(self):
        app = FastAPI()
        app.include_router(self.pool.router)
        app.include_router(jobs.router)
        return TestClient(app)

    def test_pagination_reaches_every_candidate_after_the_old_200_limit(self):
        count = 513
        self.pool.import_records(self.source(), (self.record(n) for n in range(count)))
        ids = []
        for page in range(1, 9):
            result = self.pool.list_items(page=page, page_size=73)
            self.assertEqual(result["total"], count)
            ids.extend(item["id"] for item in result["data"])
        self.assertEqual(len(ids), count)
        self.assertEqual(len(set(ids)), count)
        self.assertEqual(self.pool.list_items(page=9, page_size=73)["data"], [])
        self.assertEqual(database.get_all_questions(), [])

    def test_import_replay_and_cross_source_duplicates_preserve_occurrences(self):
        first = self.pool.import_records(self.source("真题甲"), [self.record()])
        self.pool.import_records(self.source("真题甲"), [self.record()])
        self.pool.import_records(self.source("教辅乙"), [self.record(source_key="book-page-12")])
        listed = self.pool.list_items(completeness=None)
        self.assertEqual(listed["total"], 1)
        item = self.pool.get_item(listed["data"][0]["id"])
        self.assertEqual(len(item["occurrences"]), 2)
        self.assertEqual({o["source_name"] for o in item["occurrences"]}, {"真题甲", "教辅乙"})
        self.assertEqual(item["occurrences"][0]["page_start"], 3)
        self.assertEqual(item["occurrences"][0]["page_end"], 4)
        self.assertTrue(first["source_id"])

    def test_partial_source_failure_keeps_completed_locators_and_can_resume_idempotently(self):
        def interrupted():
            yield self.record(41)
            raise RuntimeError("来源在第二题中断")

        with self.assertRaises(RuntimeError):
            self.pool.import_records(self.source("可重试来源"), interrupted())
        source = self.pool.meta()["sources"][0]
        self.assertEqual(source["import_status"], "error")
        self.assertEqual(source["stats"]["total"], 1)
        retried = self.pool.import_records(self.source("可重试来源"), [self.record(41), self.record(42)])
        self.assertEqual(retried["added_occurrences"], 1)
        self.assertEqual(retried["stats"]["total"], 2)
        self.assertEqual(self.pool.list_items()["total"], 2)
        self.assertEqual(self.pool.meta()["sources"][0]["import_status"], "done")

    def test_failed_extraction_can_recover_without_losing_its_original_evidence(self):
        failed = self.record(question="", completeness="failed", reason="OCR 超时", raw={"response": "原失败响应"})
        initial = self.pool.import_records(self.source(), [failed])
        item_id = self.pool.list_items(completeness="failed")["data"][0]["id"]
        replay = self.pool.import_records(initial["source_id"], [self.record()], retry_failed=True)
        self.assertEqual(replay["added_occurrences"], 0)
        self.assertEqual(replay["recovered_occurrences"], 1)
        self.assertEqual(replay["stats"]["failed"], 0)
        self.assertEqual(self.pool.list_items(completeness=None)["total"], 1)
        restored = self.pool.get_item(item_id)
        self.assertEqual(restored["question"], self.record()["question"])
        self.assertGreater(restored["version"], 1)
        attempts = restored["occurrences"][0]["raw"]["previous_extraction_attempts"]
        self.assertEqual(attempts[0]["reason"], "OCR 超时")
        self.assertEqual(attempts[0]["raw"]["response"], "原失败响应")

    def test_failed_retry_does_not_overwrite_manual_corrections(self):
        self.pool.import_records(self.source(), [self.record(question="", completeness="failed")])
        item_id = self.pool.list_items(completeness="failed")["data"][0]["id"]
        self.pool.update_item(item_id, {"question": "主人修正的集合题", "completeness": "complete"})
        recovered = self.pool.import_records(self.pool.meta()["sources"][0]["id"], [self.record()], retry_failed=True)
        self.assertEqual(recovered["recovered_occurrences"], 0)
        self.assertEqual(self.pool.get_item(item_id)["question"], "主人修正的集合题")

    def test_missing_and_malformed_source_rows_are_visible_failures(self):
        self.pool.import_records(self.source(), [None, {"source_key": "missing-stem", "question_no": "2"}, self.record(3)])
        source = self.pool.meta()["sources"][0]
        self.assertEqual(source["stats"]["total"], 3)
        self.assertEqual(source["stats"]["failed"], 2)
        self.assertEqual(self.pool.list_items()["total"], 3)
        self.assertEqual(self.pool.list_items(completeness="text_only")["total"], 1)
        failed = self.pool.list_items(completeness="failed")["data"]
        self.assertEqual(len(failed), 2)
        self.assertTrue(all(item["occurrences"] and item["reason"] for item in failed))

    def test_distinct_numbers_and_conditions_are_not_fuzzy_deduplicated(self):
        self.pool.import_records(self.source(), [self.record(1), self.record(2)])
        self.assertEqual(self.pool.list_items()["total"], 2)

    def test_default_includes_diagrams_and_text_filter_remains_available(self):
        self.pool.import_records(self.source(), [
            self.record(1),
            self.record(2, completeness="needs_review", reason="选项缺少文字"),
            self.record(3, completeness="deferred_graphic", reason="题干条件依赖所附图"),
            self.record(4, completeness="failed", reason="无法提取题干"),
        ])
        self.assertEqual(self.pool.list_items()["total"], 4)
        self.assertEqual(self.pool.list_items(completeness="text_only")["total"], 2)
        all_items = self.pool.list_items(completeness=None)
        self.assertEqual(all_items["total"], 4)
        deferred = next(i for i in all_items["data"] if i["completeness"] == "deferred_graphic")
        detail = self.pool.get_item(deferred["id"])
        self.assertEqual(detail["occurrences"][0]["question_no"], "3")
        self.assertIn("依赖", detail["reason"])

    def test_queries_treat_sql_and_wildcards_as_data(self):
        self.import_one(self.record(question="判断集合中的元素 $1$ 是否存在。"))
        self.assertEqual(self.pool.list_items(keyword="' OR 1=1 --")["total"], 0)
        self.assertEqual(self.pool.list_items(keyword="%")["total"], 0)
        self.assertEqual(self.pool.list_items(keyword="_")["total"], 0)
        self.assertEqual(self.pool.list_items(keyword="元素")["total"], 1)
        self.assertEqual(self.pool.list_items()["total"], 1)

    def test_preparation_calls_existing_pipeline_without_publishing(self):
        item = self.import_one()
        solve = self.prepare(item["id"])
        self.assertEqual(solve.call_args.args[0]["save"], False)
        self.assertEqual(solve.call_args.args[0]["teacher"], "liangliang")
        self.assertEqual(database.get_all_questions(), [])
        preview = self.pool.preview_items([item["id"]])
        self.assertTrue(preview["items"][0]["can_commit"])

    def test_changed_question_invalidates_prepared_result(self):
        item = self.import_one()
        self.prepare(item["id"])
        self.pool.update_item(item["id"], {"question": "集合 $A=\\{1,2,3\\}$ 的子集有多少个？"})
        preview = self.pool.preview_items([item["id"]])
        self.assertFalse(preview["items"][0]["can_commit"])
        self.assertTrue(preview["items"][0]["blocking_errors"])
        self.assertEqual(database.get_all_questions(), [])

    def test_stale_worker_result_cannot_restore_prepared_state_after_edit(self):
        item = self.import_one()

        def solve(args, ctx):
            self.pool.update_item(item["id"], {"question": "新题干：求集合交集。"})
            return jobs.Outcome(seed_answer())

        with patch.object(jobs, "_solve", side_effect=solve):
            self.pool.prepare_items({"item_ids": [item["id"]]}, PoolContext())
        self.assertFalse(self.pool.preview_items([item["id"]])["items"][0]["can_commit"])

    def test_failed_preparation_can_retry_without_creating_formal_questions(self):
        item = self.import_one()
        with patch.object(jobs, "_solve", side_effect=RuntimeError("测试解析失败")):
            self.pool.prepare_items({"item_ids": [item["id"]]}, PoolContext())
        self.assertFalse(self.pool.preview_items([item["id"]])["items"][0]["can_commit"])
        self.prepare(item["id"])
        self.assertTrue(self.pool.preview_items([item["id"]])["items"][0]["can_commit"])
        self.assertEqual(self.pool.list_items()["total"], 1)
        self.assertEqual(database.get_all_questions(), [])

    def test_commit_is_idempotent_and_keeps_provenance_after_mother_promotion(self):
        item = self.import_one()
        self.prepare(item["id"])
        first = self.pool.commit_items([item["id"]], "commit-replay")
        second = self.pool.commit_items([item["id"]], "commit-replay")
        self.assertEqual(first, second)
        formal = database.get_all_questions()
        self.assertEqual(len(formal), 1)
        question = database.get_question_by_id(formal[0]["id"])
        provenance = deepcopy(question["answer_json"]["provenance"])
        self.assertIn("试题来源", str(provenance))
        patterns.add_mother_question(question["id"], CATEGORY, "人工确认的集合套路")
        promoted = database.get_question_by_id(question["id"])
        self.assertEqual(promoted["answer_json"]["provenance"], provenance)
        self.assertEqual(promoted["source_type"], "精选母题")

    def test_existing_formal_answer_is_never_overwritten_by_pool_commit(self):
        record = self.record()
        original = seed_answer()
        original["final_answer"] = "原有答案不得覆盖"
        existing_id = database.save_question(record["question"], original)
        original_stored = deepcopy(database.get_question_by_id(existing_id)["answer_json"])
        item = self.import_one(record)
        self.prepare(item["id"])
        preview = self.pool.preview_items([item["id"]])["items"][0]
        self.assertEqual(preview["existing_answer"], original["final_answer"])
        self.assertTrue(preview["needs_confirmation"])
        blocked = self.pool.commit_items([item["id"]], "existing-formal-blocked")
        self.assertEqual(blocked["imported"], 0)
        self.pool.commit_items([item["id"]], "existing-formal", [item["id"]])
        self.assertEqual(len(database.get_all_questions()), 1)
        after = database.get_question_by_id(existing_id)["answer_json"]
        after.pop("provenance", None)
        self.assertEqual(after, original_stored)

    def test_preformatted_single_and_multi_choice_questions_reuse_existing_formal_rows(self):
        for n, question_type, answer in ((51, "选择题", "A"), (52, "多选题", "选 AB")):
            with self.subTest(question_type=question_type):
                question = f"题目 {n}：判断集合包含关系。 A．甲 B．乙 C．丙 D．丁"
                solved = seed_answer()
                solved["final_answer"] = answer
                solved["chunk_results"][0]["final_answer"] = answer
                solved["chunk_results"][0]["chunk_type"] = question_type
                existing = database.save_question(question, deepcopy(solved))
                self.assertNotEqual(database.get_question_by_id(existing)["content"], question)
                item = self.import_one(self.record(n, question=question, question_type=question_type, answer=answer))
                self.prepare(item["id"], solved)
                preview = self.pool.preview_items([item["id"]])["items"][0]
                self.assertEqual(preview["action"], "reuse")
                self.assertEqual(preview["question_id"], existing)
                result = self.pool.commit_items([item["id"]], "normalized-reuse-" + str(n))
                self.assertEqual(result["items"][0]["question_id"], existing)
                self.assertTrue(result["items"][0]["reused"])
        self.assertEqual(len(database.get_all_questions()), 2)

    def test_conflicting_source_answers_are_retained_and_require_review(self):
        self.pool.import_records(self.source("原答案甲"), [self.record(answer="A", solution="甲解析")])
        self.pool.import_records(self.source("原答案乙"), [self.record(answer="B", solution="乙解析")])
        item = self.pool.get_item(self.pool.list_items()["data"][0]["id"])
        self.assertEqual(item["completeness"], "needs_review")
        self.assertEqual({o["original_answer"] for o in item["occurrences"]}, {"A", "B"})
        self.assertEqual({o["original_solution"] for o in item["occurrences"]}, {"甲解析", "乙解析"})
        with self.assertRaises(ValueError):
            self.pool.validate_prepare_args({"item_ids": [item["id"]]})

    def test_answer_conflict_and_unverified_answer_require_explicit_confirmation(self):
        for original, generated, expected in (("B", "A", "conflict"), ("", "A", "unverified")):
            with self.subTest(expected=expected):
                record = self.record(10 if original else 11, answer=original)
                item = self.import_one(record, self.source("答案核验" + expected))
                result = seed_answer()
                result["final_answer"] = generated
                self.prepare(item["id"], result)
                preview = self.pool.preview_items([item["id"]])["items"][0]
                self.assertEqual(preview["answer_check"]["status"], expected)
                self.assertTrue(preview["can_commit"])
                self.assertTrue(preview["needs_confirmation"])
                blocked = self.pool.commit_items([item["id"]], "blocked-" + expected)
                self.assertEqual(blocked["imported"], 0)
                self.assertEqual(blocked["failed"], 1)
                accepted = self.pool.commit_items([item["id"]], "confirmed-" + expected, [item["id"]])
                self.assertEqual(accepted["imported"], 1)
        self.assertEqual(len(database.get_all_questions()), 2)

    def test_decimal_punctuation_does_not_turn_different_answers_into_matches(self):
        for reference, generated in (("1.5", "15"), ("0.25", "025"), ("-0.5", "-05")):
            with self.subTest(reference=reference, generated=generated):
                self.assertEqual(self.pool._compare_answers(reference, generated)["status"], "conflict")
        self.assertEqual(self.pool._compare_answers("0.5", r"\frac{1}{2}")["status"], "match")

    def test_coordinate_and_set_separators_are_preserved_during_answer_check(self):
        for reference, generated in (("(1,23)", "(12,3)"), (r"\{1,23\}", r"\{12,3\}"), ("[1,23]", "[12,3]")):
            self.assertNotEqual(self.pool._compare_answers(reference, generated)["status"], "match")
        self.assertEqual(self.pool._compare_answers("答案：A、B", "BA")["status"], "match")

    def test_pool_commit_does_not_merge_questions_with_different_internal_whitespace(self):
        original = "集合元素为字符串 $\\text{a b}$。求元素个数。"
        changed = "集合元素为字符串 $\\text{ab}$。求元素个数。"
        database.save_question(original, seed_answer())
        item = self.import_one(self.record(question=changed))
        self.prepare(item["id"])
        result = self.pool.commit_items([item["id"]], "distinct-text-elements")
        self.assertEqual(result["imported"], 1)
        self.assertEqual(len(database.get_all_questions()), 2)

    def test_scan_waiting_for_ocr_retains_its_page_as_needs_review(self):
        self.pool.import_records(self.source(), [self.record(question="", completeness="needs_review", reason="等待 OCR", raw={"scan": True})])
        items = self.pool.list_items(completeness="needs_review")["data"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["occurrences"][0]["page_start"], 3)

    def test_unapproved_pool_question_is_excluded_even_if_later_promoted(self):
        from backend.catalog import publish_catalog
        import json
        import sqlite3
        item = self.import_one(source=self.source(publication_allowed=False))
        self.prepare(item["id"])
        result = self.pool.commit_items([item["id"]], "private-then-promoted")
        qid = result["items"][0]["question_id"]
        patterns.add_mother_question(qid, CATEGORY, "私有来源后续晋升")
        catalog = self.root / "catalog.db"
        publish_catalog(self.root, catalog)
        with sqlite3.connect(catalog) as conn:
            public = json.loads(conn.execute("SELECT definitions_json FROM shared_catalog").fetchone()[0])
        self.assertEqual(public["questions"], [])
        self.assertIn("两个元素", database.get_question_by_id(qid)["answer_json"]["source_solution"])

    def test_public_catalog_keeps_locations_without_unapproved_reference_solutions(self):
        from backend.catalog import publish_catalog
        import json
        import sqlite3
        record = self.record(solution="主人教辅的私有解析")
        self.pool.import_records(self.source("主人教辅", publication_allowed=False), [record])
        self.pool.import_records(self.source("已核验来源", publication_allowed=True), [self.record(solution="可公开原解析")])
        item = self.pool.get_item(self.pool.list_items()["data"][0]["id"])
        self.prepare(item["id"])
        self.pool.update_item(item["id"], {"assignment": {"role": "mother", "new_pattern": {"category": CATEGORY, "name": "出处发布范围"}}})
        result = self.pool.commit_items([item["id"]], "publish-reference-scope")
        qid = result["items"][0]["question_id"]
        self.assertIn("私有解析", str(database.get_question_by_id(qid)["answer_json"]))
        catalog = self.root / "catalog.db"
        publish_catalog(self.root, catalog)
        with sqlite3.connect(catalog) as conn:
            encoded = conn.execute("SELECT definitions_json FROM shared_catalog").fetchone()[0]
        self.assertNotIn("私有解析", encoded)
        self.assertIn("主人教辅", encoded)
        self.assertIn("可公开原解析", encoded)

    def test_publication_unconfirmed_source_can_only_save_as_ordinary_private_question(self):
        item = self.import_one(source=self.source(publication_allowed=False))
        self.prepare(item["id"])
        for role in ("mother", "variant1", "variant2", "variant3"):
            self.pool.update_item(item["id"], {"assignment": {
                "role": role,
                "new_pattern": {"category": CATEGORY, "name": "许可未核验的套路"},
            }})
            preview = self.pool.preview_items([item["id"]])["items"][0]
            self.assertFalse(preview["can_commit"])
            self.assertTrue(preview["blocking_errors"])
        self.pool.update_item(item["id"], {"assignment": {"role": "question"}})
        self.assertTrue(self.pool.preview_items([item["id"]])["items"][0]["can_commit"])
        committed = self.pool.commit_items([item["id"]], "ordinary-private")
        self.assertEqual(committed["imported"], 1)
        self.assertEqual(patterns.get_patterns(), [])
        self.assertNotEqual(database.get_all_questions()[0]["source_type"], "精选母题")

    def test_occupied_pattern_slot_is_never_replaced(self):
        existing = database.save_question("原有母题：判断集合元素。", seed_answer())
        pid = patterns.add_mother_question(existing, CATEGORY, "已有母题套路")["pattern_id"]
        item = self.import_one()
        self.prepare(item["id"])
        self.pool.update_item(item["id"], {"assignment": {"role": "mother", "pattern_id": pid}})
        preview = self.pool.preview_items([item["id"]])["items"][0]
        self.assertFalse(preview["can_commit"])
        self.assertTrue(any("占用" in message for message in preview["blocking_errors"]))
        result = self.pool.commit_items([item["id"]], "occupied-mother")
        self.assertEqual(result["imported"], 0)
        self.assertEqual(patterns.get_pattern(pid)["mother_id"], existing)
        self.assertEqual(len(database.get_all_questions()), 1)

    def test_batch_cannot_assign_two_candidates_to_the_same_new_pattern_slot(self):
        self.pool.import_records(self.source(), [self.record(21), self.record(22)])
        items = self.pool.list_items()["data"]
        assignment = {"role": "mother", "new_pattern": {"category": CATEGORY, "name": "同批新套路"}}
        for item in items:
            self.prepare(item["id"])
            self.pool.update_item(item["id"], {"assignment": assignment})
        ids = [item["id"] for item in items]
        preview = self.pool.preview_items(ids)
        self.assertFalse(preview["can_commit"])
        self.assertTrue(all(not row["can_commit"] for row in preview["items"]))
        committed = self.pool.commit_items(ids, "batch-slot-conflict")
        self.assertEqual(committed["imported"], 0)
        self.assertEqual(patterns.get_patterns(), [])
        self.assertEqual(database.get_all_questions(), [])

    def test_committing_mother_to_new_pattern_keeps_original_source_evidence(self):
        item = self.import_one()
        self.prepare(item["id"])
        self.pool.update_item(item["id"], {"assignment": {
            "role": "mother", "new_pattern": {"category": CATEGORY, "name": "子集数计算", "difficulty": 2},
        }})
        result = self.pool.commit_items([item["id"]], "new-mother-commit")
        self.assertEqual(result["imported"], 1)
        qid = result["items"][0]["question_id"]
        pattern = patterns.get_patterns()[0]
        self.assertEqual(pattern["mother_id"], qid)
        self.assertEqual(pattern["difficulty"], 2)
        question = database.get_question_by_id(qid)
        self.assertEqual(question["source_type"], "精选母题")
        self.assertEqual(question["answer_json"]["source_answer"], "A")
        origin = question["answer_json"]["provenance"][0]
        self.assertEqual((origin["page_start"], origin["page_end"], origin["question_no"]), (3, 4, "1"))

    def test_stale_manual_edits_and_attempt_to_forge_prepared_result_are_rejected(self):
        item = self.import_one()
        self.pool.update_item(item["id"], {"question": "人工修正后的集合题干。", "expected_version": item["version"]})
        for changes in ({"question": "过期修改", "expected_version": item["version"]},
                        {"prepared": seed_answer()}, {"prepared_json": "{}"},
                        {"formal_question_id": 123}, {"status": "imported"}):
            with self.subTest(changes=changes), self.assertRaises(HTTPException):
                self.pool.update_item(item["id"], changes)
        self.assertEqual(self.pool.get_item(item["id"])["question"], "人工修正后的集合题干。")

    def test_reused_commit_request_cannot_apply_to_a_different_selection(self):
        self.pool.import_records(self.source(), [self.record(31), self.record(32)])
        items = self.pool.list_items()["data"]
        for item in items:
            self.prepare(item["id"])
        self.pool.commit_items([items[0]["id"]], "immutable-commit-key")
        with self.assertRaises(HTTPException) as error:
            self.pool.commit_items([items[1]["id"]], "immutable-commit-key")
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(len(database.get_all_questions()), 1)

    def test_non_owner_direct_functions_are_denied(self):
        item = self.import_one()
        actions = [
            lambda: self.pool.meta(),
            lambda: self.pool.list_items(),
            lambda: self.pool.get_item(item["id"]),
            lambda: self.pool.update_item(item["id"], {"question": "无权修改"}),
            lambda: self.pool.import_records(self.source("无权来源"), [self.record(2)]),
            lambda: self.pool.prepare_items({"item_ids": [item["id"]]}, PoolContext()),
            lambda: self.pool.preview_items([item["id"]]),
            lambda: self.pool.commit_items([item["id"]], "unauthorized"),
        ]
        for role in ("guest", "user"):
            with identity_context({"id": role, "username": role, "role": role}):
                for action in actions:
                    with self.subTest(role=role, action=action), self.assertRaises(HTTPException) as error:
                        action()
                    self.assertEqual(error.exception.status_code, 403)
        self.assertEqual(database.get_all_questions(), [])

    def test_non_owner_http_routes_and_generic_jobs_cannot_bypass_pool_permissions(self):
        item = self.import_one()
        source_id = item["occurrences"][0]["source_id"]
        requests = [
            ("GET", "/question-pool/meta", {}),
            ("GET", "/question-pool/items", {}),
            ("GET", f"/question-pool/items/{item['id']}", {}),
            ("PATCH", f"/question-pool/items/{item['id']}", {"json": {"question": "无权修改"}}),
            ("POST", "/question-pool/prepare", {"json": {"item_ids": [item["id"]]}}),
            ("POST", "/question-pool/preview", {"json": {"item_ids": [item["id"]]}}),
            ("POST", "/question-pool/commit", {"json": {"item_ids": [item["id"]], "request_id": "unauthorized-commit"}}),
            ("PATCH", f"/question-pool/sources/{source_id}", {"json": {"publication_allowed": True}}),
            ("GET", f"/question-pool/sources/{source_id}/file", {}),
            ("POST", f"/question-pool/sources/{source_id}/retry", {}),
            ("POST", "/question-pool/uploads", {"files": {"file": ("secret.txt", b"unauthorized")}}),
            ("POST", "/jobs", {"json": {"kind": "pool_prepare", "args": {"item_ids": [item["id"]]}, "request_id": "unauthorized-prepare"}}),
            ("POST", "/jobs", {"json": {"kind": "pool_import", "args": {"source_id": source_id}, "request_id": "unauthorized-import"}}),
        ]
        with self.client() as client:
            for role in ("guest", "user"):
                with identity_context({"id": role, "username": role, "role": role}):
                    for method, url, kwargs in requests:
                        with self.subTest(role=role, method=method, url=url):
                            response = client.request(method, url, **kwargs)
                            self.assertEqual(response.status_code, 403, response.text)
        self.assertFalse(self.pool.files_directory().exists())
        self.assertEqual(database.get_all_questions(), [])

    def test_legacy_demo_lease_without_identity_is_denied_before_creating_jobs(self):
        item = self.import_one()
        # Legacy demo gateways convey visitor status through the lease context.
        # Mock acceptance after validation to prevent an unsafe regression from
        # launching AI even if authorization is accidentally removed.
        def validated_submission(kind, args, request_id):
            jobs.validate_args(kind, args)
            return {"job_id": "unexpected-acceptance", "status": "queued"}

        with self.client() as client, identity_context(None), \
                background_lease(lambda: lambda: None), \
                patch.object(jobs, "submit_job", side_effect=validated_submission):
            for kind, args in (("pool_prepare", {"item_ids": [item["id"]]}),
                               ("pool_import", {"source_id": item["occurrences"][0]["source_id"]})):
                response = client.post("/jobs", json={"kind": kind, "args": args, "request_id": "legacy-demo-" + kind})
                self.assertEqual(response.status_code, 403, response.text)
            self.assertEqual(client.get("/question-pool/meta").status_code, 403)
        self.assertFalse((self.root / "jobs.sqlite3").exists())

    def test_api_database_pagination_and_filters_match_core_behavior(self):
        self.pool.import_records(self.source(), [self.record(n) for n in range(251)])
        with self.client() as client:
            response = client.get("/question-pool/items", params={"page": 3, "page_size": 100, "category": CATEGORY, "year": "2024"})
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()
            self.assertEqual((data["total"], len(data["data"])), (251, 51))
            for query in ({"page": 0}, {"page_size": 101}, {"completeness": "invented"}):
                self.assertIn(client.get("/question-pool/items", params=query).status_code, (400, 422))
            meta = client.get("/question-pool/meta").json()
            self.assertEqual(meta["stats"]["total"], 251)
            self.assertEqual(len(meta["categories"]), 12)

    def test_uploaded_original_file_is_retained_privately_and_retrievable(self):
        content = "第 1 题：求集合交集。\n答案：A".encode("utf-8")
        with self.client() as client, patch.object(jobs, "submit_job", return_value={"job_id": "import-file", "status": "queued"}) as submitted:
            response = client.post("/question-pool/uploads", files={"file": ("../private-book.txt", content)}, data={"source_name": "主人教辅"})
            self.assertEqual(response.status_code, 202, response.text)
            source_id = response.json()["source_id"]
            self.assertEqual(submitted.call_args.args[0], "pool_import")
            self.assertEqual(submitted.call_args.args[1], {"source_id": source_id})
            source = self.pool.meta()["sources"][0]
            self.assertEqual(source["filename"], "private-book.txt")
            self.assertTrue(source["has_file"])
            self.assertFalse(source["publication_allowed"])
            original = client.get(f"/question-pool/sources/{source_id}/file")
            self.assertEqual(original.status_code, 200)
            self.assertEqual(original.content, content)
            self.assertEqual(original.headers["cache-control"], "no-store")
            self.assertEqual(database.get_all_questions(), [])
            invalid = client.post("/question-pool/uploads", files={"file": ("run.sh", b"echo unsafe")})
            self.assertEqual(invalid.status_code, 400)

    def test_original_file_locator_cannot_escape_the_private_upload_directory(self):
        for token in ("../settings.json", "/etc/passwd", "a" * 64 + ".txt/../settings.json"):
            source_id = self.pool.create_source({**self.source(token), "file_token": token})
            with self.assertRaises(HTTPException) as error:
                self.pool._source_file(source_id)
            self.assertEqual(error.exception.status_code, 404)

    def test_pdf_original_opens_inline_and_retry_only_extracts_selected_failed_pages(self):
        content = b"%PDF-1.4 fake test original"
        with self.client() as client, patch.object(jobs, "submit_job", return_value={"job_id": "import-file", "status": "queued"}):
            source_id = client.post("/question-pool/uploads", files={"file": ("book.pdf", content)}).json()["source_id"]
            response = client.get(f"/question-pool/sources/{source_id}/file")
            self.assertTrue(response.headers["content-disposition"].startswith("inline"))
            self.assertEqual(response.content, content)
        self.pool.import_records(source_id, [
            self.record(1, question="提取失败第2页", completeness="failed", page_start=2, page_end=3),
            self.record(2, question="提取失败第5页", completeness="failed", page_start=5, page_end=5),
            self.record(3, question="文字完整页", page_start=1, page_end=1),
        ])
        selected = self.pool.list_items(completeness="failed")["data"][0]["id"]
        with patch("backend.pool_sources.iter_source_records", return_value=iter([])) as extract:
            self.pool.import_source_job({"source_id": source_id, "item_ids": [selected]}, PoolContext())
            self.assertEqual(extract.call_args.args[2]["page_numbers"], [2, 3])
        with self.client() as client, patch.object(jobs, "submit_job", return_value={"job_id": "retry", "status": "queued"}) as submitted:
            self.assertEqual(client.post(f"/question-pool/sources/{source_id}/retry", json={"item_ids": [selected]}).status_code, 202)
            self.assertEqual(submitted.call_args.args[1], {"source_id": source_id, "item_ids": [selected]})


if __name__ == "__main__":
    unittest.main()
