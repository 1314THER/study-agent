"""grade.py / planner.py / teach.py 纯函数与关键流程测试。"""

import os
import tempfile
import unittest
from datetime import date, timedelta
from fractions import Fraction
from unittest.mock import patch

import backend.planner as planner_mod
from backend.grade import (
    _as_bool,
    _collect_steps,
    _compare_choice,
    _fill_equivalent,
    _final_answer,
    _normalize_fill,
    _resolve_question_type,
    _sanitize_ai_grade,
    _to_number,
    grade_text,
)
from backend.planner import (
    _ordered_patterns,
    _parse_date,
    _topo_order,
    apply_plan,
    build_plan,
    get_board_order_config,
    save_board_order_config,
)
from backend.teach import _bs, _ej, _set_category_from_chunks


class GradeHelperTest(unittest.TestCase):
    def test_resolve_question_type(self):
        self.assertEqual(_resolve_question_type({}, "单选题"), "选择题")
        self.assertEqual(_resolve_question_type({"question_type": "填空"}, None), "填空题")
        self.assertEqual(_resolve_question_type({"chunk_results": [{"chunk_type": "大题"}]}, None), "大题")
        self.assertEqual(_resolve_question_type({}, None), "大题")

    def test_final_answer(self):
        self.assertEqual(_final_answer({"final_answer": "A"}), "A")
        self.assertEqual(
            _final_answer({"chunk_results": [{"final_answer": "A"}, {"final_answer": "B"}]}),
            "A | B",
        )

    def test_collect_steps(self):
        aj = {
            "chunk_results": [{
                "chunk_id": 1,
                "final_answer": "A",
                "steps": [
                    {"step_number": 1, "title": "化简"},
                    {"step_number": 1, "title": "重复"},
                ],
            }],
        }
        steps = _collect_steps(aj)
        ids = [s["id"] for s in steps]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(steps[-1]["title"], "最终答案")

    def test_normalize_fill(self):
        self.assertEqual(_normalize_fill("答案：$x=2$"), "x=2")
        self.assertEqual(_normalize_fill("1/2"), "1/2")
        self.assertEqual(_normalize_fill(""), "")

    def test_to_number(self):
        self.assertEqual(_to_number("1/2"), Fraction(1, 2))
        self.assertEqual(_to_number("0.5"), Fraction(1, 2))
        self.assertIsNone(_to_number("abc"))

    def test_fill_equivalent(self):
        self.assertTrue(_fill_equivalent("1/2", "0.5"))
        self.assertTrue(_fill_equivalent("$x=2$", "x=2"))
        self.assertFalse(_fill_equivalent("1", "2"))

    def test_compare_choice(self):
        self.assertTrue(_compare_choice("AB", "B A"))
        self.assertTrue(_compare_choice("A", "A"))
        self.assertFalse(_compare_choice("AB", "AC"))

    def test_as_bool(self):
        self.assertTrue(_as_bool(True))
        self.assertTrue(_as_bool("对"))
        self.assertFalse(_as_bool("错"))
        self.assertFalse(_as_bool(None))

    def test_sanitize_ai_grade(self):
        steps = [{
            "id": "1-1",
            "chunk_id": 1,
            "step_number": 1,
            "title": "化简",
            "standard_writing": "x=2",
        }]
        data = {
            "approach": "different",
            "result_matched": False,
            "steps": [{
                "id": "1-1",
                "status": "partial",
                "error_types": ["符号错误", "坏类型"],
                "error_detail": "符号反了",
                "comment": "差一点",
            }],
            "overall": {"is_correct": False, "earned_score": 5, "feedback": "部分正确"},
            "suggested_approach": "换一种思路",
            "missing_steps": [],
            "not_rigorous_steps": [],
        }
        result = _sanitize_ai_grade(data, steps, 10)
        self.assertEqual(result["earned_score"], 5.0)
        self.assertEqual(result["steps"][0]["error_types"], ["符号错误"])
        self.assertIn("换一种思路", result["feedback"])
        self.assertEqual(result["error_suggestions"][0]["mistake_type"], "符号错误")

    def test_grade_text_empty_answer(self):
        result = grade_text(question_id=1, student_answer="")
        self.assertEqual(result["error"], "empty_answer")

    def test_grade_text_question_not_found(self):
        with patch("backend.grade.get_question_by_id", return_value=None):
            result = grade_text(question_id=1, student_answer="A")
        self.assertEqual(result["error"], "not_found")

    def test_grade_text_choice_match(self):
        row = {
            "content": "题",
            "answer_json": {
                "question_type": "选择题",
                "final_answer": "A",
                "chunk_results": [{"chunk_type": "选择题", "final_answer": "A"}],
            },
        }
        with patch("backend.grade.get_question_by_id", return_value=row), \
             patch("backend.grade.add_practice_record", return_value=1):
            result = grade_text(question_id=1, student_answer="A")
        self.assertEqual(result["mode"], "answer_match")
        self.assertTrue(result["is_correct"])


class TeachHelperTest(unittest.TestCase):
    def test_ej_extracts_json(self):
        self.assertEqual(_ej('```json\n{"a": 1}\n```'), '{"a": 1}')
        self.assertEqual(_ej('前 {"a": 1} 后'), '{"a": 1}')

    def test_bs_builds_steps(self):
        crs = [{
            "chunk_id": 1,
            "chunk_type": "大题",
            "category": {"level1": "数列"},
            "final_answer": "n^2",
            "steps": [{
                "step_number": 1,
                "title": "求通项",
                "step_prompt": "先看首项",
                "step_answer": "a1=1",
                "standard_writing": "a1=1",
                "detailed_writing": "a1=1",
                "knowledge_point": "数列基础",
            }],
        }]
        steps, has_prompt = _bs(crs)
        self.assertTrue(has_prompt)
        self.assertEqual(steps[0]["title"], "求通项")
        self.assertEqual(steps[-1]["title"], "最终答案")

    def test_set_category_from_chunks(self):
        aj = {"chunk_results": [{"category": {"level1": "数列", "level2": "等差"}}]}
        _set_category_from_chunks(aj)
        self.assertEqual(aj["category"]["level1"], "数列")

        aj2 = {"category": {"level1": "函数与导数", "level2": ""}, "chunk_results": []}
        _set_category_from_chunks(aj2)
        self.assertEqual(aj2["category"]["level1"], "函数与导数")

        aj3 = {"chunk_results": []}
        _set_category_from_chunks(aj3)
        self.assertNotIn("category", aj3)


class PlannerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config_path = os.path.join(self.tmp.name, "board_order.yaml")
        patcher = patch.object(planner_mod, "CONFIG_PATH", self.config_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_board_order_config_roundtrip(self):
        config = get_board_order_config()
        self.assertTrue(any(item["category"] == "数列" for item in config["board_order"]))

        saved = save_board_order_config([{"category": "数列", "nodes": [1, 2]}])
        self.assertEqual(saved["board_order"][0]["nodes"], [1, 2])

    def test_parse_date(self):
        self.assertEqual(_parse_date("2026-08-10"), date(2026, 8, 10))
        self.assertEqual(_parse_date("bad"), date.today() + timedelta(days=1))

    def test_topo_order(self):
        board = {
            "nodes": [
                {"pattern_id": 1, "question_id": 11},
                {"pattern_id": 2, "question_id": 12},
                {"pattern_id": 3, "question_id": 13},
            ],
            "edges": [
                {"from_question_id": 11, "to_question_id": 12},
                {"from_question_id": 12, "to_question_id": 13},
            ],
        }
        self.assertEqual(_topo_order(board), [1, 2, 3])

    def test_topo_order_uses_board_x_when_no_edges(self):
        board = {
            "nodes": [
                {"pattern_id": 3, "question_id": 13, "x": 2, "y": 0},
                {"pattern_id": 1, "question_id": 11, "x": 0, "y": 0},
                {"pattern_id": 2, "question_id": 12, "x": 1, "y": 0},
            ],
            "edges": [],
        }
        self.assertEqual(_topo_order(board), [1, 2, 3])

    def test_ordered_patterns_falls_back_to_category_order(self):
        patterns = [
            {"id": 1, "category": "数列", "name": "A", "mother_id": 11, "mastery": {"state": "never"}},
            {"id": 2, "category": "解析几何", "name": "B", "mother_id": 12, "mastery": {"state": "never"}},
        ]
        ordered = _ordered_patterns(patterns, [], {"board_order": []})
        self.assertEqual([p["id"] for p in ordered], [1, 2])

    def test_build_plan(self):
        patterns = [{
            "id": 1,
            "category": "数列",
            "name": "套路A",
            "mother_id": 11,
            "mastery": {"state": "never"},
        }]
        with patch.object(planner_mod, "get_patterns", return_value=patterns), \
             patch.object(planner_mod, "get_boards", return_value=[]), \
             patch.object(planner_mod, "get_board_order_config", return_value={"board_order": []}):
            plan = build_plan(per_day=1, start_date="2026-08-10")
        self.assertEqual(plan["days"], 1)
        self.assertEqual(plan["plan"][0]["patterns"][0]["name"], "套路A")

    def test_apply_plan(self):
        plan = {
            "plan": [{
                "date": "2026-08-10",
                "patterns": [{"pattern_id": 1}, {"pattern_id": "bad"}],
            }],
        }
        with patch.object(planner_mod, "set_pattern_schedule", return_value=None) as mock_schedule:
            result = apply_plan(plan)
        self.assertEqual(result, {"applied": 1})
        mock_schedule.assert_called_once_with(1, "2026-08-10 08:00:00", need_check=1)


if __name__ == "__main__":
    unittest.main()
