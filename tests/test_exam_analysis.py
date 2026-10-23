"""Whole-exam scoring, extraction integrity and workspace-scoped API tests."""
import base64
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.api_base import ApiTestCase
from backend import exam_analysis as exam
from backend.jobs import JobStopped


def difficulty_question(number, score, **extra):
    return {"id": f"q{number}", "question_no": number, "answer_result": {
        "overall_difficulty": {"total_score": score}, **extra}}


class ExamScoringTest(unittest.TestCase):
    def test_formatter_difficulty_has_no_question_type_ceiling(self):
        prompt = (Path(__file__).resolve().parents[1] / "backend" / "prompts" / "formatter.md").read_text(encoding="utf-8")
        self.assertIn("不得按题型设置难度上限", prompt)
        self.assertIn("题型、题号和试卷位置本身不能作为加分或封顶依据", prompt)
        self.assertNotIn("小题原则上不应出现 2 分及以上", prompt)

    def test_mock_difficulty_targets_and_single_question_outlier(self):
        template = exam.default_templates()[0]
        self.assertEqual([item["target"] for item in template["difficulty_targets"]],
                         [2, 2, 2, 2, 2, 5, 5, 8, 2, 5, 8, 5, 5, 8, 2, 2, 5, 8, 12])
        questions = [difficulty_question(i, target) for i, target in enumerate(
            [2, 2, 2, 2, 2, 5, 5, 8, 2, 5, 8, 5, 5, 8, 2, 2, 5, 8, 12], 1)]
        questions[7]["answer_result"]["overall_difficulty"]["total_score"] = 5
        report = exam.score_difficulty(questions, template)
        self.assertEqual(report["questions"][7]["difference"], -3)
        self.assertEqual(report["questions"][7]["squared_error"], 9)
        self.assertEqual(report["questions"][7]["direction"], "偏易")
        self.assertAlmostEqual(report["rmse"], (9 / 19) ** .5, places=3)

    def test_uniform_one_point_deviation_scores_fourteen(self):
        template = exam.default_templates()[0]
        targets = [item["target"] for item in template["difficulty_targets"]]
        questions = [difficulty_question(i, target + 1) for i, target in enumerate(targets, 1)]
        report = exam.score_difficulty(questions, template)
        self.assertEqual(report["score"], 14)
        self.assertTrue(report["ready"])

    def test_coverage_counts_question_once_and_uses_squared_weighted_gap(self):
        target_id = exam.knowledge_id("集合与逻辑用语", "集合的基本运算")
        template = {"knowledge_targets": [{"id": target_id, "level1": "集合与逻辑用语",
                                           "level2": "集合的基本运算", "min": 3, "max": 5, "weight": 2}],
                    "attribute_targets": []}
        questions = [{"question_no": 1, "knowledge_core": [target_id, target_id], "solve_status": "done"},
                     {"question_no": 2, "knowledge_core": [], "solve_status": "done"},
                     {"question_no": 3, "knowledge_core": [], "solve_status": "done"},
                     {"question_no": 4, "knowledge_core": [], "solve_status": "done"}]
        report = exam.score_coverage(questions, template)
        row = report["knowledge"][0]
        self.assertEqual(row["actual_count"], 1)
        self.assertEqual(row["gap"], 2)
        self.assertEqual(row["penalty"], 8)
        self.assertEqual(report["maximum"], 18)
        self.assertEqual(report["score"], 10)
        questions[0]["knowledge_core"] = [target_id]
        questions[1]["knowledge_core"] = [target_id]
        questions[2]["knowledge_core"] = [target_id]
        self.assertEqual(exam.score_coverage(questions, template)["penalty"], 0)

    def test_unknown_knowledge_is_not_marked_as_confirmed_missing(self):
        template = {"knowledge_targets": [{"id": "x", "level1": "函数与导数", "level2": "函数的单调性",
                                           "min": 1, "max": 2, "weight": 2}], "attribute_targets": []}
        report = exam.score_coverage([{"question_no": 1, "knowledge_core": [],
                                       "unmapped_knowledge": [{"text": "无法识别的知识点"}]}], template)
        self.assertFalse(report["ready"])
        self.assertIsNone(report["score"])
        self.assertTrue(report["knowledge"][0]["pending_review"])
        self.assertEqual(report["knowledge"][0]["penalty"], 0)

    def test_adjacent_cross_page_continuation_keeps_question_number_and_page_refs(self):
        pages = [
            {"page_no": 1, "filename": "exam.pdf", "file_page": 1, "asset_refs": ["a"], "items": [{"index": 4, "latex": "第4题上半部分",
              "continues_to_next": True, "is_complete": False}]},
            {"page_no": 2, "filename": "exam.pdf", "file_page": 2, "asset_refs": ["b"], "items": [
                {"index": 4, "latex": "第4题下半部分", "continues_from_previous": True, "is_complete": True},
                {"index": 5, "latex": "第5题", "is_complete": True}]},
        ]
        questions, issues = exam._merge_page_questions(pages, [])
        q4 = next(q for q in questions if q["question_no"] == 4)
        self.assertEqual(q4["source_pages"], [1, 2])
        self.assertEqual(q4["asset_refs"], ["a", "b"])
        self.assertEqual([page["filename"] for page in q4["source_page_details"]], ["exam.pdf", "exam.pdf"])
        self.assertEqual([page["file_page"] for page in q4["source_page_details"]], [1, 2])
        self.assertIn("上半部分\n第4题下半部分", q4["latex"])
        self.assertEqual(issues["duplicate_question_numbers"], [])

    def test_cancelled_extraction_is_not_recorded_as_an_error(self):
        analysis = {"source_files_json": json.dumps([{"path": "/tmp/page.png", "filename": "page.png"}]),
                    "template_json": json.dumps(exam.default_templates()[0])}

        class CancelledContext:
            def progress(self, *_args):
                raise JobStopped("cancelled")

        with patch.object(exam, "_get_row", return_value=analysis), \
             patch.object(exam, "_save_row") as save_row, \
             patch("backend.multimodal.image_to_base64", return_value="encoded"):
            with self.assertRaises(JobStopped):
                exam.extract_analysis("analysis-id", CancelledContext())
        self.assertEqual(save_row.call_args.kwargs["status"], "cancelled")


class ExamAnalysisApiTest(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.exam_db = Path(self.tmp.name) / "exam.db"
        self.exam_uploads = Path(self.tmp.name) / "exam-uploads"
        self._exam_patches = [patch.object(exam, "storage_path", lambda: self.exam_db),
                              patch.object(exam, "upload_root", lambda: self.exam_uploads)]
        for item in self._exam_patches:
            item.start()
            self.addCleanup(item.stop)

    def test_seed_templates_and_admin_version_publish(self):
        response = self.client.get("/exam/templates")
        self.assertEqual(response.status_code, 200)
        templates = response.json()["templates"]
        balanced = next(item for item in templates if item["id"] == "balanced-mock")
        self.assertEqual(len(balanced["knowledge_targets"]), 12)
        balanced["name"] = "均衡模拟卷（修订）"
        updated = self.client.put("/exam/templates/balanced-mock", json=balanced)
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["version"], 2)
        versions = self.client.get("/exam/templates").json()["templates"]
        self.assertEqual(next(item["version"] for item in versions if item["id"] == "balanced-mock"), 2)

    def test_upload_creates_private_review_record_and_does_not_expose_paths(self):
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/pZcAAAAASUVORK5CYII=")
        fake_job = {"job_id": "a" * 32, "kind": "exam_extract", "status": "queued", "progress": 0, "detail": "排队中"}
        with patch("backend.jobs.submit_job", return_value=fake_job), patch("backend.jobs.get_job", return_value=fake_job):
            response = self.client.post("/exam/analyses", data={"template_id": "balanced-mock", "teacher": "liangliang"},
                                        files=[("files", ("page-1.png", png, "image/png"))])
        self.assertEqual(response.status_code, 202, response.text)
        record = response.json()
        self.assertEqual(record["status"], "extracting")
        self.assertEqual(record["source_files"][0]["filename"], "page-1.png")
        self.assertNotIn("path", json.dumps(record))
        saved = next(self.exam_uploads.glob("*/000.png"))
        self.assertTrue(saved.is_file())
        listed = self.client.get("/exam/analyses").json()["analyses"]
        self.assertEqual([item["id"] for item in listed], [record["id"]])

    def test_mock_review_blocks_missing_numbers_then_starts_after_full_check(self):
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/pZcAAAAASUVORK5CYII=")
        fake_extract = {"job_id": "b" * 32, "kind": "exam_extract", "status": "queued", "progress": 0, "detail": "排队中"}
        fake_solve = {"job_id": "c" * 32, "kind": "exam_solve", "status": "queued", "progress": 0, "detail": "排队中"}
        with patch("backend.jobs.submit_job", return_value=fake_extract), patch("backend.jobs.get_job", return_value=fake_extract):
            response = self.client.post("/exam/analyses", data={"template_id": "balanced-mock"},
                                        files=[("files", ("mock.png", png, "image/png"))])
        self.assertEqual(response.status_code, 202, response.text)
        analysis_id = response.json()["id"]
        incomplete = [{"id": f"q{i}", "question_no": i, "latex": f"第{i}题", "is_complete": True,
                       "solve_status": "pending", "source_pages": [1], "asset_refs": []} for i in range(1, 19)]
        exam._save_row(analysis_id, status="awaiting_review", questions_json=json.dumps(incomplete, ensure_ascii=False))
        blocked = self.client.post(f"/exam/analyses/{analysis_id}/start", json={"confirm_review": True})
        self.assertEqual(blocked.status_code, 409)
        full = incomplete + [{"id": "q19", "question_no": 19, "latex": "第19题", "is_complete": True,
                              "solve_status": "pending", "source_pages": [1], "asset_refs": []}]
        exam._save_row(analysis_id, status="awaiting_review", questions_json=json.dumps(full, ensure_ascii=False))
        with patch("backend.jobs.submit_job", return_value=fake_solve):
            started = self.client.post(f"/exam/analyses/{analysis_id}/start", json={"confirm_review": True})
        self.assertEqual(started.status_code, 202, started.text)
        with patch("backend.jobs.get_job", return_value=fake_solve):
            record = self.client.get(f"/exam/analyses/{analysis_id}").json()
        self.assertEqual(record["status"], "solving")
        self.assertTrue(record["review_confirmed"])

    def test_question_edit_invalidates_solution_and_keeps_manual_label_source(self):
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/pZcAAAAASUVORK5CYII=")
        fake_job = {"job_id": "d" * 32, "kind": "exam_extract", "status": "queued", "progress": 0, "detail": "排队中"}
        with patch("backend.jobs.submit_job", return_value=fake_job), patch("backend.jobs.get_job", return_value=fake_job):
            created = self.client.post("/exam/analyses", data={"template_id": "balanced-mock"},
                                       files=[("files", ("page.png", png, "image/png"))])
        self.assertEqual(created.status_code, 202, created.text)
        analysis_id = created.json()["id"]
        kid = exam.knowledge_id("集合与逻辑用语", "集合的基本运算")
        original = {"id": "question-one", "question_no": 1, "latex": "旧题干", "is_complete": True,
                    "solve_status": "done", "source_pages": [1], "asset_refs": [],
                    "answer_result": {"overall_difficulty": {"total_score": 2}},
                    "knowledge_core": [kid], "knowledge_prerequisites": [], "attributes": ["direct_application"],
                    "unmapped_knowledge": [], "labels_source": "candidate"}
        exam._save_row(analysis_id, status="complete", review_confirmed=1,
                       questions_json=json.dumps([original], ensure_ascii=False), report_json=json.dumps({"old": True}))
        patched = self.client.patch(f"/exam/analyses/{analysis_id}/questions", json={"questions": [{
            "id": "question-one", "latex": "修订题干", "knowledge_core": [kid],
            "knowledge_prerequisites": [], "attributes": ["thinking"]}]})
        self.assertEqual(patched.status_code, 200, patched.text)
        question = patched.json()["questions"][0]
        self.assertEqual(question["latex"], "修订题干")
        self.assertIsNone(question["answer_result"])
        self.assertEqual(question["solve_status"], "pending")
        self.assertEqual(question["labels_source"], "manual")
        self.assertEqual(question["label_revision_history"][0]["source"], "manual_correction")
        self.assertEqual(len(patched.json()["report_versions"]), 1)
