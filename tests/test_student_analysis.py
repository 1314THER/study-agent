"""Evidence and versioning tests for cross-exam student analysis."""
import hashlib
from io import BytesIO
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tests.api_base import ApiTestCase
from backend import exam_analysis, student_analysis as analysis
from backend.grade import _fill_equivalent, _sanitize_ai_grade, grade_prepared


def question(qid, *, canonical=None, paper_quality="valid", correct=False, knowledge="K1",
             mistake="计算错误", routine="r1", difficulty="容易", depends=False):
    content = "试题 " + qid
    canonical = canonical or hashlib.sha256(content.encode()).hexdigest()
    error = {"step_id": "1-1", "step_number": 1, "mistake_type": mistake,
             "mistake_detail": "计算位置错", "answer_evidence": "学生原文中的运算", "depends_on_error": depends}
    return {"id": qid, "question_no": int(''.join(c for c in qid if c.isdigit()) or 1),
        "question": content, "question_type": "大题", "answer_result": {"final_answer": "2"},
        "canonical_question_id": canonical, "difficulty": {"level": difficulty},
        "knowledge_core": [knowledge], "labels_reviewed": True, "knowledge_links_reviewed": True,
        "routines": ([{"id": routine, "name": "移项法"}] if routine else []), "paper_quality": paper_quality,
        "paper_note": "题目选项有歧义" if paper_quality != "valid" else "",
        "full_score": 5, "earned_score": 5 if correct else 2, "grade_status": "done",
        "grade_review_status": "confirmed", "response": {"review_status": "confirmed",
            "student_answer": "已核对作答", "manual_error_evidence": []},
        "grade_result": {"is_correct": correct,
            "error_suggestions": [] if correct else [error],
            "step_results": [{"id": "1-1", "status": "correct" if correct else "partial",
                              "answer_evidence": "关键步骤证据"}],
            "knowledge_links": {"1-1": [knowledge]}}}


def attempt(aid, q, *, kind="first", date="2026-10-01", viewed=False, condition="unknown"):
    return {"id": aid, "status": "complete", "title": "试卷 " + aid, "exam_date": date,
        "created_at": 1000 + int(aid[-1]), "attempt_type": kind, "viewed_answer": viewed,
        "time_limit_minutes": 90, "questionnaire": {"condition": condition,
            "stuck_period": "unknown", "skipped_and_returned": "unknown", "checked_work": "unknown"},
        "questions": [q]}


class StudentAnalysisRulesTest(unittest.TestCase):
    def test_one_mistake_is_only_an_initial_clue(self):
        result = analysis.build_report([attempt("a1", question("q1"))])
        finding = next(row for row in result["findings"] if row["kind"] == "knowledge")
        self.assertEqual(finding["evidence_level"], "initial")
        self.assertEqual(len(finding["supporting_evidence"]), 1)

    def test_repeated_knowledge_requires_two_exams_and_distinct_questions(self):
        result = analysis.build_report([
            attempt("a1", question("q1")), attempt("a2", question("q2"), date="2026-10-08")])
        finding = next(row for row in result["findings"] if row["kind"] == "knowledge")
        self.assertEqual(finding["evidence_level"], "repeated")
        self.assertEqual(result["independent_question_count"], 2)

    def test_retakes_and_viewed_answers_are_not_independent_samples(self):
        original = question("q1", canonical="same-paper-item")
        retake = question("q2", canonical="another-item")
        result = analysis.build_report([attempt("a1", original),
            attempt("a2", retake, kind="retake", date="2026-10-05")])
        self.assertEqual(result["independent_question_count"], 1)
        self.assertEqual(result["practice_attempt_question_count"], 1)
        self.assertEqual([f for f in result["findings"] if f["kind"] == "knowledge"][0]["evidence_level"], "initial")

    def test_pending_or_invalid_item_cannot_create_ability_findings_or_score(self):
        result = analysis.build_report([attempt("a1", question("q1", paper_quality="pending"))])
        self.assertFalse(any(f["kind"] in ("knowledge", "basic_performance", "routine") for f in result["findings"]))
        self.assertEqual(result["timeline"][0]["score"], None)
        self.assertEqual(len(result["paper_issues"]), 1)

    def test_dependent_follow_on_errors_count_once_per_step(self):
        q = question("q1", depends=False)
        q["grade_result"]["error_suggestions"].append({**q["grade_result"]["error_suggestions"][0],
            "step_id": "1-1", "depends_on_error": True})
        result = analysis.build_report([attempt("a1", q)])
        finding = next(row for row in result["findings"] if row["kind"] == "knowledge")
        self.assertEqual(len(finding["supporting_evidence"]), 1)

    def test_self_reported_tension_is_not_a_psychological_diagnosis(self):
        result = analysis.build_report([attempt("a1", question("q1"), condition="tense")])
        self.assertFalse(any(f["kind"] in ("psychology", "state_diagnosis") for f in result["findings"]))

    def test_blank_responses_combine_with_self_report_without_estimated_minutes(self):
        q=question("q1")
        q["response"]["review_status"]="blank"
        result=analysis.build_report([attempt("a1",q)])
        finding=next(row for row in result["findings"] if row["kind"]=="timing")
        self.assertEqual(finding["supporting_evidence"][0]["response_signals"][0]["confirmed_blank_question_numbers"],[1])
        self.assertFalse(any("minutes" in str(row).lower() for row in finding["supporting_evidence"]))

    def test_unconfirmed_step_labels_remain_out_of_knowledge_conclusions(self):
        q=question("q1")
        q["knowledge_links_reviewed"]=False
        result=analysis.build_report([attempt("a1",q)])
        self.assertFalse(any(row["kind"]=="knowledge" for row in result["findings"]))

    def test_basic_comparison_groups_only_confirmed_same_labels_and_requires_cross_exam_errors(self):
        first = question("q1", correct=False, knowledge="K1", routine=None)
        second = question("q2", correct=True, knowledge="K1", routine=None)
        third = question("q3", correct=False, knowledge="K2", routine=None)
        result = analysis.build_report([attempt("a1", first), attempt("a2", second, date="2026-10-08"),
                                        attempt("a3", third, date="2026-10-10")])
        basic = [row for row in result["findings"] if row["kind"] == "basic_performance"]
        by_title = {row["title"]: row for row in basic}
        self.assertEqual(set(by_title), {"基础题发挥 · 知识点 K1", "基础题发挥 · 知识点 K2"})
        self.assertEqual(by_title["基础题发挥 · 知识点 K1"]["evidence_level"], "initial")
        self.assertEqual(len(by_title["基础题发挥 · 知识点 K1"]["counter_evidence"]), 1)
        repeated = analysis.build_report([attempt("a1", first),
            attempt("a2", question("q4", correct=False, knowledge="K1", routine=None), date="2026-10-08")])
        k1 = next(row for row in repeated["findings"] if row["kind"] == "basic_performance")
        self.assertEqual(k1["evidence_level"], "repeated")

    def test_priorities_are_limited_to_three_and_structured(self):
        questions = [question("q"+str(i), knowledge="K"+str(i), routine="r"+str(i)) for i in range(1, 6)]
        result = analysis.build_report([{"id":"a1", "status":"complete", "title":"卷", "exam_date":"2026-10-01",
            "created_at":1, "attempt_type":"first", "viewed_answer":False, "questionnaire":{},
            "questions":questions}])
        self.assertLessEqual(len(result["priority_recommendations"]), 3)
        self.assertTrue(all(set(("finding_id", "recommendation", "validation_target")) <= set(item)
                            for item in result["priority_recommendations"]))


class SharedGradingRulesTest(unittest.TestCase):
    def test_multi_select_partial_credit_and_penalty(self):
        answer = {"question_type":"多选题", "final_answer":"A,C", "chunk_results":[]}
        result = grade_prepared("题", answer, "A,B", question_type="多选题", full_score=6,
            objective_rule={"mode":"per_option", "wrong_option_penalty":1})
        self.assertFalse(result["is_correct"])
        self.assertEqual(result["earned_score"], 2)
        self.assertEqual(result["score_basis"], "confirmed_multi_select_rule")

    def test_interval_boundaries_are_preserved_and_ambiguous_comparison_is_reviewed(self):
        self.assertFalse(_fill_equivalent("[1,2]", "1,2"))
        result = grade_prepared("題", {"question_type":"填空题", "final_answer":"[1,2]"},
            "[1,3]", question_type="填空题", full_score=4)
        self.assertIsNone(result["is_correct"])
        self.assertIsNone(result["earned_score"])
        self.assertTrue(result["review_required"])

    def test_missing_ai_score_stays_unknown_and_missing_step_does_not_infer_reason(self):
        steps = [{"id":"1-1", "chunk_id":1, "step_number":1, "title":"計算", "standard_writing":"x=2"}]
        result = _sanitize_ai_grade({"overall":{"is_correct":False}, "steps":[{"id":"1-1","status":"missing"}]}, steps, 5)
        self.assertIsNone(result["earned_score"])
        self.assertEqual(result["error_suggestions"], [])
        self.assertTrue(result["steps"][0]["review_required"])


class StudentAnalysisApiTest(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.student_db=Path(self.tmp.name)/"student.sqlite3"
        self.student_uploads=Path(self.tmp.name)/"student-uploads"
        self._student_patches=[patch.object(analysis,"storage_path",lambda:self.student_db),
                               patch.object(analysis,"upload_root",lambda:self.student_uploads)]
        for item in self._student_patches:
            item.start(); self.addCleanup(item.stop)
        self.analysis_id="a"*32
        source={"analysis_id":self.analysis_id,"status":"complete","review_confirmed":1,
            "title":"已核对试卷","teacher":"liangliang",
            "questions_json":json.dumps([{"id":"source-q1","question_no":1,"latex":"求 x 的值。",
                "question_type":"大题","solve_status":"done","answer_result":{"final_answer":"2",
                    "question_type":"大题","chunk_results":[{"chunk_id":1,"final_answer":"2",
                        "steps":[{"step_number":1,"title":"代入","standard_writing":"x=2",
                            "knowledge_point":"函数的性质"}]}]},"knowledge_core":["K1"],"labels_reviewed":True,
                "confirmed_routines":[]}])}
        self._source_patch=patch.object(exam_analysis,"_get_row",return_value=source)
        self._source_patch.start(); self.addCleanup(self._source_patch.stop)

    def test_create_review_record_hide_private_paths_and_report_versions_go_stale(self):
        created=self.client.post("/student-analysis/attempts",json={"exam_analysis_id":self.analysis_id,
            "exam_date":"2026-10-01","attempt_type":"first"})
        self.assertEqual(created.status_code,201,created.text)
        attempt_id=created.json()["id"]
        attempt=analysis._require_attempt(attempt_id)
        attempt["pages"]=[{"page_no":1,"image_path":"/private/student-answer.png","status":"done","fragments":[]}]
        self.assertTrue(analysis._write_attempt(attempt,expected_revision=attempt["revision"]))
        public=self.client.get("/student-analysis/attempts/"+attempt_id).json()
        self.assertNotIn("image_path",json.dumps(public))
        question_id=public["questions"][0]["id"]
        saved=self.client.patch("/student-analysis/attempts/"+attempt_id+"/questions/"+question_id,
            json={"student_answer":"x=2","review_status":"confirmed","full_score":5,"earned_score":4})
        self.assertEqual(saved.status_code,200,saved.text)
        complete=analysis._require_attempt(attempt_id)
        complete["status"]="complete"
        self.assertTrue(analysis._write_attempt(complete,expected_revision=complete["revision"]))
        report=self.client.post("/student-analysis/reports",json={"limit":5})
        self.assertEqual(report.status_code,201,report.text)
        report_id=report.json()["id"]
        single=self.client.post("/student-analysis/attempts/"+attempt_id+"/report")
        self.assertEqual(single.status_code,201,single.text)
        self.assertEqual(single.json()["report_type"],"single")
        source=single.json()["source_snapshot"][attempt_id]["questions"][0]
        self.assertEqual(source["full_score"],5)
        self.assertIn("answer_result",source)
        self.assertEqual(single.json()["rules_snapshot"]["repeat_min_questions"],2)
        revised=self.client.patch("/student-analysis/attempts/"+attempt_id+"/questions/"+question_id,
            json={"earned_score":2})
        self.assertEqual(revised.status_code,200,revised.text)
        history=revised.json()["questions"][0]["revision_history"]
        self.assertEqual(history[-1]["earned_score"],4)
        previous=self.client.get("/student-analysis/reports/"+report_id)
        self.assertTrue(previous.json()["stale"])
        self.assertEqual(previous.json()["data"]["timeline"][0]["score"],4)

    def test_mock_page_ocr_saves_unconfirmed_original_response_and_progress(self):
        created=self.client.post("/student-analysis/attempts",json={"exam_analysis_id":self.analysis_id,
            "exam_date":"2026-10-02"})
        self.assertEqual(created.status_code,201,created.text)
        attempt_id=created.json()["id"]
        attempt=analysis._require_attempt(attempt_id)
        image=self.student_uploads/attempt_id/"r1"/"page-001.png"
        image.parent.mkdir(parents=True,exist_ok=True);image.write_bytes(b"mock page image")
        attempt["pages"]=[{"page_no":1,"image_path":str(image),"sha256":hashlib.sha256(b"mock page image").hexdigest(),
            "status":"pending","fragments":[],"unmatched_fragments":[],"error":None}]
        self.assertTrue(analysis._write_attempt(attempt,expected_revision=attempt["revision"],bump_revision=False))
        class JobContext:
            def __init__(self):
                self.parts=[];self.manager=self
            def progress(self,*_args): pass
            def partial(self,_ctx,value): self.parts.append(value)
        ctx=JobContext()
        with patch.object(analysis,"ANSWER_EXTRACTOR") as extractor, patch("backend.jobs.ensure_active"):
            extractor.extract_page.return_value='[{"question_no":1,"text":"x=2","confidence":"high"}]'
            result=analysis.run_extract_job({"attempt_id":attempt_id,"revision":attempt["revision"]},ctx)
        self.assertEqual(result["pages"][0]["status"],"done")
        self.assertTrue(ctx.parts)
        saved=analysis._require_attempt(attempt_id)
        response=saved["questions"][0]["response"]
        self.assertEqual(saved["status"],"awaiting_review")
        self.assertEqual(response["student_answer"],"x=2")
        self.assertEqual(response["review_status"],"pending")
        self.assertEqual(response["ocr_fragments"][0]["text"],"x=2")
        page=self.client.get("/student-analysis/attempts/"+attempt_id+"/pages/1/image")
        self.assertEqual(page.status_code,200)

    def test_three_exam_flow_mocked_ocr_grade_revision_and_followup(self):
        from PIL import Image
        from backend import database
        from backend.exam_analysis import knowledge_id

        image_buffer = BytesIO()
        Image.new("RGB", (80, 80), "white").save(image_buffer, format="PNG")
        image_bytes = image_buffer.getvalue()
        analysis_ids = [f"{index:032x}" for index in range(1, 4)]
        skill_id = knowledge_id("集合与逻辑用语", "集合与元素")
        sources = {}
        for index, source_id in enumerate(analysis_ids, 1):
            content = f"第 {index} 套卷：判断元素是否属于集合 A。"
            question_source = {"id": f"source-q{index}", "question_no": 1, "latex": content,
                "question_type": "选择题", "solve_status": "done", "knowledge_core": [skill_id],
                "labels_reviewed": True, "confirmed_routines": [],
                "answer_result": {"question_type": "选择题", "final_answer": "A",
                    "overall_difficulty": {"level": "容易", "score": 2},
                    "chunk_results": [{"chunk_id": 1, "final_answer": "A",
                        "category": {"level1": "集合与逻辑用语"},
                        "steps": [{"step_number": 1, "title": "判断元素归属",
                            "standard_writing": "逐项判断元素归属", "knowledge_point": "集合与元素"}]}]}}
            sources[source_id] = {"analysis_id": source_id, "status": "complete", "review_confirmed": 1,
                "title": f"模拟试卷 {index}", "teacher": "liangliang",
                "questions_json": json.dumps([question_source], ensure_ascii=False)}

        class JobContext:
            def __init__(self):
                self.parts = []
                self.manager = self
            def progress(self, *_args):
                pass
            def partial(self, _ctx, value):
                self.parts.append(value)

        class SimulatedGrader:
            def grade(self, assessment, response, **_kwargs):
                return {"mode": "simulated_step_grade", "is_correct": False, "result_matched": False,
                    "earned_score": 2.0, "full_score": 5.0, "score_basis": "simulated_confirmed_rubric",
                    "grading_confidence": "high", "review_required": False,
                    "step_results": [{"id": "1-1", "status": "partial", "answer_evidence": response.reviewed_text}],
                    "error_suggestions": [], "feedback": "模拟批改结果"}

        with patch.object(exam_analysis, "_get_row", side_effect=sources.get), \
             patch.object(analysis, "ANSWER_EXTRACTOR") as extractor, \
             patch.object(analysis, "GRADER", SimulatedGrader()), \
             patch("backend.jobs.ensure_active"):
            extractor.extract_page.return_value = '[{"question_no":1,"text":"B","confidence":"high"}]'
            attempt_rows = []
            for index, source_id in enumerate(analysis_ids, 1):
                created = self.client.post("/student-analysis/attempts", json={"exam_analysis_id": source_id,
                    "exam_date": f"2026-10-{index * 5:02d}", "time_limit_minutes": 90})
                self.assertEqual(created.status_code, 201, created.text)
                attempt_id = created.json()["id"]
                with patch("backend.jobs.submit_job", return_value={"job_id": f"ocr-{index}"}):
                    uploaded = self.client.post(f"/student-analysis/attempts/{attempt_id}/answers",
                        files=[("files", ("answer.png", image_bytes, "image/png"))])
                self.assertEqual(uploaded.status_code, 202, uploaded.text)
                extract_revision = uploaded.json()["attempt"]["revision"]
                extract_context = JobContext()
                analysis.run_extract_job({"attempt_id": attempt_id, "revision": extract_revision}, extract_context)
                self.assertTrue(extract_context.parts)
                question_row = self.client.get(f"/student-analysis/attempts/{attempt_id}").json()["questions"][0]
                question_id = question_row["id"]
                reviewed = self.client.patch(f"/student-analysis/attempts/{attempt_id}/questions/{question_id}", json={
                    "student_answer": "B", "review_status": "confirmed", "full_score": 5,
                    "manual_error_evidence": [{"mistake_type": "知识性错误", "step_id": "1-1",
                        "detail": "把元素与集合混淆", "answer_evidence": "作答写为 B"}]})
                self.assertEqual(reviewed.status_code, 200, reviewed.text)
                with patch("backend.jobs.submit_job", return_value={"job_id": f"grade-{index}"}):
                    started = self.client.post(f"/student-analysis/attempts/{attempt_id}/grade")
                self.assertEqual(started.status_code, 202, started.text)
                grade_context = JobContext()
                analysis.run_grade_job({"attempt_id": attempt_id, "revision": started.json()["attempt"]["revision"]},
                                       grade_context)
                awaiting_survey = self.client.get(f"/student-analysis/attempts/{attempt_id}").json()
                self.assertEqual(awaiting_survey["status"], "awaiting_questionnaire")
                if index == 1:
                    self.assertEqual(self.client.post("/student-analysis/reports", json={"limit": 5}).status_code, 409)
                survey = self.client.patch(f"/student-analysis/attempts/{attempt_id}/questionnaire", json={
                    "completion": "completed", "stuck_period": "middle", "stuck_duration_range": "5_15m",
                    "skipped_and_returned": "yes", "checked_work": "yes", "confidence": "mixed",
                    "condition": "tense", "stuck_question_numbers": [1]})
                self.assertEqual(survey.status_code, 200, survey.text)
                finished = self.client.get(f"/student-analysis/attempts/{attempt_id}").json()
                self.assertEqual(finished["status"], "complete")
                self.assertEqual(finished["questions"][0]["response"]["ocr_fragments"][0]["text"], "B")
                attempt_rows.append((attempt_id, question_id))

        report = self.client.post("/student-analysis/reports", json={"limit": 5})
        self.assertEqual(report.status_code, 201, report.text)
        report_data = report.json()["data"]
        self.assertEqual(report_data["window_exam_count"], 3)
        knowledge_finding = next(row for row in report_data["findings"] if row["kind"] == "knowledge")
        self.assertEqual(knowledge_finding["evidence_level"], "repeated")
        self.assertEqual(len(knowledge_finding["supporting_evidence"]), 3)
        self.assertTrue(any(row["kind"] == "timing" for row in report_data["findings"]))

        first_attempt, first_question = attempt_rows[0]
        changed = self.client.patch(f"/student-analysis/attempts/{first_attempt}/questions/{first_question}",
            json={"earned_score": 3})
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(changed.json()["questions"][0]["revision_history"][-1]["earned_score"], 2.0)
        self.assertTrue(self.client.get(f"/student-analysis/reports/{report.json()['id']}").json()["stale"])

        practice_question_id = self.seed_question("新题：求集合 A 的元素个数并判断子集关系。")
        conn = database.get_connection()
        try:
            cursor = conn.execute("INSERT INTO practice_records(question_id,correct,student_answer,source_type) "
                "VALUES (?,?,?,?)", (practice_question_id, 1, "A", "复测"))
            practice_record_id = cursor.lastrowid
            conn.commit()
        finally:
            conn.close()
        linked = self.client.post(f"/student-analysis/attempts/{first_attempt}/questions/{first_question}/followup",
            json={"practice_record_id": practice_record_id, "finding_id": knowledge_finding["id"]})
        self.assertEqual(linked.status_code, 200, linked.text)
        refreshed = self.client.post("/student-analysis/reports", json={"limit": 5})
        linked_finding = next(row for row in refreshed.json()["data"]["findings"]
                              if row["id"] == knowledge_finding["id"])
        self.assertEqual(linked_finding["evidence_level"], "followup")
        self.assertTrue(any(e.get("evidence_type") == "independent_followup"
                            for e in linked_finding["supporting_evidence"]))
