"""categories / difficulty / steps / multimodal / generate / repair 纯函数测试。"""

import os
import tempfile
import unittest
from unittest.mock import patch

import backend.categories as categories_mod
from backend.categories import (
    _load_categories,
    get_all_categories,
    get_knowledge_points,
    solver_prompt_snippet,
    validate_knowledge_points,
    verify_prompt_knowledge_points,
)
from backend.difficulty import (
    _weight_for,
    aggregate_chunk_results,
    aggregate_dims,
    difficulty_from_dims,
    has_step_dimensions,
    level_from_score,
    normalize_dims,
    score_from_dims,
    step_difficulty_from_dims,
)
from backend.generate import (
    _add_usage,
    _build_user_prompt,
    _collect_knowledge_points,
    _collect_step_titles,
    _fit_score,
    _job_snapshot,
    _load_reference,
    _normalize_step_name,
    _parse_candidates,
    _progress_text,
)
from backend.multimodal import (
    _fallback_parse,
    _image_mime,
    _parse_questions,
    _post_process,
    get_supported_extensions,
)
from backend.repair_questions import (
    _extract_chunk_dims,
    _extract_final_from_steps,
    _extract_kp,
    _extract_sd,
    _norm_dims,
    _strip_meta,
)
from backend.steps import (
    _load_steps,
    clear_cache,
    format_step_prompt_snippet,
    get_all_level1_names,
    get_all_level2_names,
    get_all_question_types,
    get_level2_names,
    get_step_structure,
    has_predefined_steps,
)


class CategoriesTest(unittest.TestCase):
    def test_load_and_get_all(self):
        data = _load_categories()
        self.assertIn("解析几何", data)
        self.assertTrue(any(c["level1"] == "解析几何" for c in get_all_categories()))

    def test_knowledge_points(self):
        kps = get_knowledge_points("解析几何")
        self.assertIn("椭圆", kps)
        self.assertEqual(get_knowledge_points("不存在"), [])

    def test_snippets(self):
        self.assertIn("解析几何", solver_prompt_snippet())
        self.assertIn("椭圆", verify_prompt_knowledge_points("解析几何"))

    def test_validate_knowledge_points(self):
        self.assertEqual(validate_knowledge_points("解析几何", ["椭圆", "坏点"]), ["椭圆"])


class DifficultyTest(unittest.TestCase):
    def test_weight_for(self):
        self.assertEqual(_weight_for({0: 0, 1: 1, 2: 2, 3: 4}, 3), 4)
        self.assertEqual(_weight_for([0, 1, 2, 4], 2), 2)
        self.assertEqual(_weight_for(None, 2), 0)

    def test_normalize_dims(self):
        self.assertEqual(normalize_dims({"计算量": 2, "未知维度": 9}), {"计算量": 2})
        self.assertEqual(normalize_dims({"计算量": 99}), {"计算量": 3})
        self.assertEqual(normalize_dims("bad"), {})

    def test_has_step_dimensions(self):
        good = [{"steps": [{"step_difficulty": {"dimensions": {"计算量": 1}}}]}]
        bad = [{"steps": [{"step_difficulty": {"dimensions": {}}}]}]
        self.assertTrue(has_step_dimensions(good))
        self.assertFalse(has_step_dimensions(bad))
        self.assertFalse(has_step_dimensions([]))

    def test_aggregate_dims(self):
        result = aggregate_dims([{"计算量": 2}, {"计算量": 2}])
        self.assertIn("计算量", result)
        self.assertLessEqual(result["计算量"], 3)

    def test_score_and_level(self):
        self.assertEqual(score_from_dims({"计算量": 3, "知识广度": 3}), 8)
        self.assertEqual(level_from_score(2), "容易")
        self.assertEqual(level_from_score(5), "中等")
        self.assertEqual(level_from_score(8), "困难")
        self.assertEqual(level_from_score(12), "极难")
        self.assertEqual(level_from_score("x"), "未知")

    def test_difficulty_from_dims(self):
        d = difficulty_from_dims({"计算量": 2})
        self.assertIn("level", d)
        self.assertIn("dimensions", d)
        s = step_difficulty_from_dims({"计算量": 1})
        self.assertIn("score", s)

    def test_aggregate_chunk_results(self):
        crs = [{
            "steps": [{"step_difficulty": {"dimensions": {"计算量": 2, "知识广度": 1}}}],
        }]
        chunk_results, overall = aggregate_chunk_results(crs)
        self.assertEqual(chunk_results[0]["difficulty"]["level"], "中等")
        self.assertIn("level", overall)


class StepsTest(unittest.TestCase):
    def setUp(self):
        clear_cache()

    def test_load_and_query(self):
        data = _load_steps()
        self.assertIsInstance(data, dict)
        self.assertTrue(data)
        self.assertIn("立体几何大题", get_all_question_types())
        self.assertIsInstance(get_step_structure("立体几何大题"), dict)
        self.assertTrue(has_predefined_steps("立体几何大题"))
        self.assertTrue(get_all_level1_names("立体几何大题"))
        self.assertIsInstance(get_level2_names("立体几何大题", "证明线线平行关系"), list)
        self.assertIsInstance(get_all_level2_names("立体几何大题"), list)

    def test_format_snippet(self):
        snippet = format_step_prompt_snippet("立体几何大题")
        self.assertIn("步骤N：<一级步骤名>", snippet)
        self.assertEqual(format_step_prompt_snippet("不存在"), "")


class MultimodalTest(unittest.TestCase):
    def test_parse_questions_json(self):
        raw = '```json\n[{"latex": "$x^2=1$", "difficulty": "中等"}]\n```'
        items = _parse_questions(raw)
        self.assertEqual(items[0]["latex"], "$x^2=1$")

    def test_parse_questions_fallback(self):
        items = _parse_questions("1. 求导数\n2. 求积分")
        self.assertEqual(len(items), 2)

    def test_fallback_parse(self):
        items = _fallback_parse("1. 题一\n续行\n2. 题二")
        self.assertEqual(len(items), 2)
        self.assertIn("续行", items[0]["latex"])

    def test_post_process(self):
        processed = _post_process([{"latex": "题", "difficulty": "简单", "question_type": "选择题"}])
        self.assertEqual(processed[0]["difficulty"], "容易")
        self.assertEqual(processed[0]["recommended_teacher"], "liangliang")
        empty = _post_process([{"difficulty": "未知"}])
        self.assertEqual(empty[0]["difficulty"], "中等")

    def test_image_mime_and_extensions(self):
        self.assertEqual(_image_mime("JPG"), "jpeg")
        self.assertEqual(_image_mime("png"), "png")
        self.assertIn(".pdf", get_supported_extensions())


class GenerateHelperTest(unittest.TestCase):
    def test_add_usage(self):
        total = {}
        _add_usage(total, {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3})
        self.assertEqual(total["total_tokens"], 3)

    def test_normalize_step_name(self):
        self.assertEqual(_normalize_step_name(" 求通项： "), "求通项")

    def test_collect_step_titles(self):
        crs = [{"steps": [{"title": "求通项"}, {"title": "求通项"}, {"title": "求和"}]}]
        self.assertEqual(_collect_step_titles(crs), ["求通项", "求和"])

    def test_collect_knowledge_points(self):
        result = {"knowledge_points": ["数列"], "chunk_results": [{"knowledge_points": ["数列", "通项"]}]}
        self.assertEqual(_collect_knowledge_points(result), ["数列", "通项"])

    def test_build_user_prompt(self):
        ref = {"id": 1, "question": "题", "question_type": "选择题", "category": "数列", "difficulty": {}, "steps": [], "student_errors": []}
        prompt = _build_user_prompt(ref, 2)
        self.assertIn("reference_question", prompt)
        self.assertIn('"requested_count": 2', prompt)

    def test_parse_candidates(self):
        content = '{"candidates": [{"question": "题1"}, {"question": ""}, {"question": "题2"}]}'
        self.assertEqual(len(_parse_candidates(content, 2)), 2)
        with self.assertRaises(ValueError):
            _parse_candidates('{"candidates": []}', 2)

    def test_load_reference(self):
        question = {
            "content": "题",
            "category_level1": "数列",
            "question_type": "大题",
            "answer_json": {"chunk_results": [{"chunk_type": "大题"}]},
        }
        with patch("backend.generate.get_question_by_id", return_value=question), \
             patch("backend.generate.get_step_errors", return_value=[]):
            ref = _load_reference(1)
        self.assertEqual(ref["category"], "数列")
        self.assertEqual(ref["question_type"], "大题")

        with patch("backend.generate.get_question_by_id", return_value=None):
            with self.assertRaises(ValueError):
                _load_reference(999)

    def test_fit_score(self):
        reference = {
            "difficulty": {"total_score": 5},
            "chunk_results": [{"steps": [{"title": "求通项"}]}],
            "question_type": "大题",
            "answer_json": {"knowledge_points": ["数列"]},
        }
        result = {
            "result": {
                "overall_difficulty": {"total_score": 5},
                "chunk_results": [{"chunk_type": "大题", "steps": [{"title": "求通项"}]}],
                "knowledge_points": ["数列"],
            },
        }
        score, detail = _fit_score(reference, result)
        self.assertEqual(score, 100.0)
        self.assertIn("step_ratio", detail)

    def test_job_snapshot_and_progress(self):
        job = _job_snapshot({"id": "j1", "status": "running", "progress": 1, "total": 3, "phase": "solve"})
        self.assertEqual(job["id"], "j1")
        self.assertIn("progress", job)
        text = _progress_text("solver", 1, 3)
        self.assertIn("Solver", text)


class RepairHelperTest(unittest.TestCase):
    def test_norm_dims(self):
        self.assertEqual(_norm_dims({"常规程度": 2}), {"非常规程度": 2})

    def test_strip_meta(self):
        text = "标准过程：x=2\n## 难度评分\n| 计算量 | 2 |\n知识点：数列\n正文"
        cleaned = _strip_meta(text)
        self.assertNotIn("难度评分", cleaned)
        self.assertIn("标准过程：x=2", cleaned)

    def test_extract_sd(self):
        text = '步骤难度：{"level": "中等", "score": 3}'
        self.assertEqual(_extract_sd(text)["score"], 3)
        self.assertIsNone(_extract_sd("没有难度"))

    def test_extract_kp(self):
        self.assertEqual(_extract_kp("知识点：数列基础"), "数列基础")
        self.assertEqual(_extract_kp("知识点：\n- 数列\n- 通项"), "数列、通项")

    def test_extract_chunk_dims(self):
        text = "## 难度评分\n| 计算量 | 2 |\n| 知识广度 | 1 |"
        dims = _extract_chunk_dims(text)
        self.assertEqual(dims["计算量"], 2)

    def test_extract_final_from_steps(self):
        steps = [{"standard_writing": "所以选 A", "detailed_writing": ""}]
        self.assertEqual(_extract_final_from_steps(steps), "选 A")


if __name__ == "__main__":
    unittest.main()
