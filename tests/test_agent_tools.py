"""服务端工具层单元测试：工具输入输出映射与失败兜底。"""

import unittest
from unittest.mock import patch

from backend.agent_tools import (
    _category_name,
    _compact_question,
    _compact_solve,
    _normalize_categories,
    _normalize_types,
    _save_solved,
    _solve_pipeline,
    _split_list,
    run_tool,
    tool_descriptions,
)


class HelperFunctionTest(unittest.TestCase):
    def test_compact_question_truncates(self):
        q = {
            "id": 1,
            "content": "题" * 300,
            "category_level1": "数列",
            "question_type": "大题",
            "difficulty_level": "中等",
            "source_type": "高考题",
            "knowledge_points": ["通项"],
        }
        compact = _compact_question(q)
        self.assertEqual(compact["content"], ("题" * 300)[:140] + "…")
        self.assertEqual(compact["category"], "数列")

    def test_split_list(self):
        self.assertEqual(_split_list("a,b, c"), ["a", "b", "c"])
        self.assertEqual(_split_list([" a ", "b"]), ["a", "b"])
        self.assertEqual(_split_list(123), [])

    def test_normalize_categories_and_types(self):
        self.assertEqual(_normalize_categories(["函数", "解析几何"]), ["函数与导数", "解析几何"])
        self.assertEqual(_normalize_types(["选择", "解答题", "多选题"]), ["选择题", "大题", "多选题"])

    def test_category_name(self):
        self.assertEqual(_category_name({"level1": "数列", "level2": "等差"}), "数列")
        self.assertEqual(_category_name("解析几何"), "解析几何")
        self.assertEqual(_category_name(None), "")

    def test_tool_descriptions(self):
        desc = tool_descriptions()
        for name in ("search_questions", "solve_question", "teach_question", "grade_answer", "plan_study", "get_context"):
            self.assertIn(name, desc)


class SolvePipelineTest(unittest.TestCase):
    def test_solver_error_propagates(self):
        with patch("backend.agent_tools.step_solver_only", return_value={"error": "雪碧了", "detail": "不可解"}):
            result = _solve_pipeline("题")
        self.assertEqual(result["error"], "雪碧了")

    def test_verifier_error_propagates(self):
        with patch("backend.agent_tools.step_solver_only", return_value={"content": "解", "category": "数列"}), \
             patch("backend.agent_tools.step_verify_all", return_value={"error": "解析失败"}):
            result = _solve_pipeline("题")
        self.assertEqual(result["error"], "解析失败")

    def test_success_returns_final(self):
        final = {"final_answer": "A"}
        with patch("backend.agent_tools.step_solver_only", return_value={"content": "解", "category": "数列"}), \
             patch("backend.agent_tools.step_verify_all", return_value={"chunk_results": []}), \
             patch("backend.agent_tools.step_final_check", return_value=final) as mock_final:
            result = _solve_pipeline("题", question_type="选择题", teacher="taotao")
        self.assertEqual(result, final)
        mock_final.assert_called_once()


class SaveSolvedTest(unittest.TestCase):
    def test_category_filled_from_first_chunk(self):
        final = {
            "chunk_results": [{
                "category": {"level1": "数列", "level2": "等差"},
                "final_answer": "A",
                "knowledge_points": ["通项"],
            }],
        }
        with patch("backend.agent_tools.save_question", return_value=9) as mock_save:
            qid = _save_solved("题", final)
        self.assertEqual(qid, 9)
        saved = mock_save.call_args[0][1]
        self.assertEqual(saved["category"]["level1"], "数列")

    def test_existing_category_kept(self):
        final = {
            "category": {"level1": "函数与导数", "level2": ""},
            "chunk_results": [{"category": {"level1": "数列", "level2": ""}}],
        }
        with patch("backend.agent_tools.save_question", return_value=1):
            _save_solved("题", final)
        self.assertEqual(final["category"]["level1"], "函数与导数")


class CompactSolveTest(unittest.TestCase):
    def test_compact_solve_maps_fields(self):
        final = {
            "final_answer": "A",
            "knowledge_points": ["通项"],
            "overall_difficulty": {"level": "中等"},
            "chunk_results": [{
                "chunk_id": 1,
                "chunk_type": "大题",
                "category": {"level1": "数列"},
                "final_answer": "A",
                "knowledge_points": ["通项"],
                "steps": [{
                    "step_number": 1,
                    "title": "求通项",
                    "knowledge_point": "通项",
                    "step_difficulty": {"level": "容易"},
                }],
            }],
        }
        compact = _compact_solve("题", final, qid=5)
        self.assertEqual(compact["saved_id"], 5)
        self.assertEqual(compact["category"], "数列")
        self.assertEqual(compact["difficulty_level"], "中等")
        self.assertEqual(compact["chunks"][0]["steps"][0]["difficulty_level"], "容易")


class SearchToolTest(unittest.TestCase):
    def test_search_compacts_results(self):
        rows = [{
            "id": 1,
            "content": "题" * 200,
            "category_level1": "解析几何",
            "question_type": "大题",
            "difficulty_level": "困难",
            "source_type": "高考题",
            "knowledge_points": ["椭圆"],
        }]
        with patch("backend.agent_tools.search_questions", return_value=rows) as mock_search:
            result = run_tool("search_questions", {"query": "椭圆", "category": "解析几何", "limit": 2})

        self.assertEqual(result["count"], 1)
        item = result["items"][0]
        self.assertEqual(item["id"], 1)
        self.assertEqual(item["category"], "解析几何")
        self.assertEqual(item["content"], ("题" * 200)[:140] + "…")
        self.assertEqual(mock_search.call_args.kwargs["keywords"], ["椭圆"])
        self.assertEqual(mock_search.call_args.kwargs["categories"], ["解析几何"])
        self.assertEqual(mock_search.call_args.kwargs["limit"], 2)

    def test_search_accepts_nested_filters_and_normalizes_alias(self):
        with patch("backend.agent_tools.search_questions", return_value=[]) as mock_search:
            result = run_tool("search_questions", {"filters": {"category": "函数"}, "limit": 3})

        self.assertEqual(result["count"], 0)
        self.assertEqual(mock_search.call_args.kwargs["categories"], ["函数与导数"])


class SolveToolTest(unittest.TestCase):
    def test_solve_maps_pipeline_result(self):
        final = {
            "final_answer": "x=2",
            "knowledge_points": ["开方"],
            "overall_difficulty": {"level": "中等"},
            "chunk_results": [{
                "chunk_id": 1,
                "chunk_type": "大题",
                "category": {"level1": "函数与导数"},
                "final_answer": "x=2",
                "knowledge_points": ["开方"],
                "steps": [{
                    "step_number": 1,
                    "title": "第一步",
                    "knowledge_point": "开方",
                    "step_difficulty": {"level": "容易"},
                }],
            }],
        }
        with patch("backend.agent_tools._solve_pipeline", return_value=final), \
             patch("backend.agent_tools._save_solved", return_value=99):
            result = run_tool("solve_question", {"question": "题面", "save": True})

        self.assertEqual(result["saved_id"], 99)
        self.assertEqual(result["final_answer"], "x=2")
        self.assertEqual(result["category"], "函数与导数")
        self.assertEqual(result["difficulty_level"], "中等")
        self.assertEqual(result["chunks"][0]["steps"][0]["difficulty_level"], "容易")

    def test_solve_requires_question(self):
        result = run_tool("solve_question", {})
        self.assertEqual(result["error"], "missing_question")


class TeachToolTest(unittest.TestCase):
    def test_teach_maps_session_result(self):
        session = {
            "session_id": "abc",
            "question": "题",
            "teacher": "taotao",
            "message": "先看第一步",
            "total_steps": 2,
            "steps": [{"title": "第一步"}, {"title": "第二步"}],
            "step_titles": ["第一步", "第二步"],
            "chunk_results": [{
                "chunk_type": "大题",
                "category": {"level1": "数列"},
                "knowledge_points": ["通项"],
                "steps": [{"step_number": 1}],
            }],
            "question_id": 7,
        }
        with patch("backend.agent_tools.teach_session_start", return_value=session):
            result = run_tool("teach_question", {"question": "题"})

        self.assertEqual(result["session_id"], "abc")
        self.assertEqual(result["teacher"], "taotao")
        self.assertEqual(result["step_titles"], ["第一步", "第二步"])
        self.assertEqual(result["chunks"][0]["category"], "数列")


class GradeToolTest(unittest.TestCase):
    def test_grade_maps_result(self):
        grade_result = {
            "mode": "step_ai",
            "question_id": 3,
            "question_type": "大题",
            "is_correct": False,
            "result_matched": False,
            "earned_score": 2.0,
            "full_score": 10,
            "expected_answer": "x=2",
            "student_answer": "x=1",
            "feedback": "部分正确",
            "suggested_approach": "先化简",
            "step_results": [{
                "step_number": 1,
                "title": "化简",
                "is_correct": False,
                "is_partial": True,
                "feedback": "符号错了",
                "error_type": "符号错误",
            }],
            "missing_steps": [],
            "not_rigorous_steps": [],
        }
        with patch("backend.agent_tools.grade_text", return_value=grade_result) as mock_grade:
            result = run_tool("grade_answer", {"question_id": 3, "student_answer": "x=1"})

        mock_grade.assert_called_once()
        self.assertEqual(result["mode"], "step_ai")
        self.assertEqual(result["step_results"][0]["error_type"], "符号错误")

    def test_grade_requires_student_answer(self):
        with patch("backend.agent_tools.grade_text") as mock_grade:
            result = run_tool("grade_answer", {"question_id": 3})
        mock_grade.assert_not_called()
        self.assertEqual(result["error"], "empty_answer")


class PlanToolTest(unittest.TestCase):
    def test_plan_maps_and_applies(self):
        plan = {
            "template": None,
            "per_day": 2,
            "start_date": "2026-08-10",
            "total_patterns": 3,
            "days": 2,
            "plan": [
                {"date": "2026-08-10", "patterns": [{"name": "套路A"}, {"name": "套路B"}]},
                {"date": "2026-08-11", "patterns": [{"name": "套路C"}]},
            ],
        }
        with patch("backend.agent_tools.build_plan", return_value=plan), \
             patch("backend.agent_tools.apply_plan", return_value=2) as mock_apply:
            result = run_tool("plan_study", {"per_day": 2, "apply": True})

        self.assertEqual(result["applied_count"], 2)
        self.assertEqual(result["preview"][0]["patterns"], ["套路A", "套路B"])
        mock_apply.assert_called_once()


class ContextToolTest(unittest.TestCase):
    def test_context_returns_compact_snapshot(self):
        ctx = {
            "total_questions": 5,
            "wrong_questions": 1,
            "practice_records": 15,
            "patterns_total": 5,
            "patterns_mastered": 2,
            "due_reviews": 0,
            "recent_wrong": [],
            "categories": ["解析几何"],
        }
        with patch("backend.agent_tools.agent_context", return_value=ctx):
            result = run_tool("get_context", {})
        self.assertEqual(result["total_questions"], 5)
        self.assertEqual(result["recent_wrong"], [])


class ToolFailureTest(unittest.TestCase):
    def test_unknown_tool(self):
        result = run_tool("no_such_tool", {})
        self.assertEqual(result["error"], "unknown_tool")

    def test_tool_exception_is_captured(self):
        from backend.agent_tools import TOOLS

        def boom(_args):
            raise RuntimeError("boom")

        with patch.dict(TOOLS, {"search_questions": {**TOOLS["search_questions"], "fn": boom}}):
            result = run_tool("search_questions", {})
        self.assertEqual(result["error"], "tool_failed")
        self.assertIn("boom", result["detail"])


if __name__ == "__main__":
    unittest.main()
