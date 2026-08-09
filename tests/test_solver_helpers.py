"""solver.py 纯函数与关键流程测试（LLM 调用全部 mock）。"""

import json
from contextlib import ExitStack
import unittest
from unittest.mock import patch

import httpx

import backend.solver as solver_mod
from backend.solver import (
    _aggregate_from_chunks,
    _check_solver_viable,
    _collect_kps_from_steps,
    _extract_category,
    _extract_json,
    _extract_solver_status,
    _extract_verifier_template,
    _is_well_formed_chunk_results,
    _parse_chunk_meta,
    _parse_steps,
    _resolve_question_type,
    _split_chunks,
    _strip_bullet,
    _validate_step_names,
    _xuebile,
    call_deepseek,
    get_api_key,
    step_final_check,
    step_solver_only,
)


class PureParserTest(unittest.TestCase):
    def test_strip_bullet(self):
        self.assertEqual(_strip_bullet("- 步骤"), "步骤")
        self.assertEqual(_strip_bullet("* x"), "x")
        self.assertEqual(_strip_bullet("• y"), "y")
        self.assertEqual(_strip_bullet("plain"), "plain")

    def test_extract_json(self):
        self.assertEqual(_extract_json('```json\n{"a": 1}\n```'), '{"a": 1}')
        self.assertEqual(_extract_json('前缀 {"a": 1} 后缀'), '{"a": 1}')

    def test_solver_status(self):
        self.assertEqual(_extract_solver_status("[状态：不会做]"), "不会做")
        self.assertEqual(_extract_solver_status("[状态：错题]"), "错题")
        self.assertIsNone(_extract_solver_status("[状态：可解]"))

    def test_check_solver_viable(self):
        self.assertIsNone(_check_solver_viable("是否数学题：[是]\n是否能做出来：[是]"))
        self.assertEqual(_check_solver_viable("是否数学题：[否]"), "不是数学题")
        self.assertEqual(_check_solver_viable("是否错题：[是]"), "题目本身有错")
        self.assertEqual(_check_solver_viable("是否能做出来：[否]"), "Solver 判定：不会做")
        self.assertEqual(_check_solver_viable("[状态：不会做]"), "Solver 判定：不会做")
        self.assertIsNone(_check_solver_viable("正常解答"))

    def test_extract_category(self):
        self.assertEqual(_extract_category("板块：函数与导数"), "函数与导数")
        self.assertEqual(_extract_category("板块：函数与导数（导数应用）"), "函数与导数")
        self.assertIsNone(_extract_category("板块：未知板块"))

    def test_extract_verifier_template(self):
        self.assertEqual(_extract_verifier_template("所需校验模板：数列"), "数列")
        self.assertIsNone(_extract_verifier_template("没有模板"))

    def test_resolve_question_type(self):
        self.assertEqual(_resolve_question_type("题", "解", "多选题"), "多选题")
        self.assertEqual(_resolve_question_type("（多选）题", "解"), "多选题")
        self.assertEqual(_resolve_question_type("题", "题型：填空题"), "填空题")
        self.assertEqual(_resolve_question_type("题", "解"), "")

    def test_parse_chunk_meta(self):
        text = (
            "块类型：选择题\n"
            "板块：集合与逻辑用语\n"
            "块最终答案：A\n"
            "块知识点：集合与元素、常用逻辑用语"
        )
        meta = _parse_chunk_meta(text)
        self.assertEqual(meta["chunk_type"], "选择题")
        self.assertEqual(meta["category"], "集合与逻辑用语")
        self.assertEqual(meta["final_answer"], "A")
        self.assertEqual(meta["knowledge_points"], ["集合与元素", "常用逻辑用语"])

    def test_parse_steps(self):
        text = (
            "步骤1：判断元素归属\n"
            "二级步骤：无\n"
            "标准过程：逐项判断\n"
            "详细过程：逐项判断并排除\n"
            "知识点：集合与元素"
        )
        steps = _parse_steps(text)
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["title"], "判断元素归属")
        self.assertEqual(steps[0]["standard_writing"], "逐项判断")
        self.assertEqual(steps[0]["knowledge_point"], "集合与元素")

    def test_split_chunks(self):
        text = "头部\n### 块1\n内容1\n### 块2\n内容2"
        header, chunks = _split_chunks(text)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0]["id"], 1)
        self.assertIn("内容1", chunks[0]["content"])
        header2, chunks2 = _split_chunks("无块")
        self.assertEqual(len(chunks2), 1)
        self.assertEqual(header2, "无块")

    def test_xuebile(self):
        result = _xuebile("不会做", "原因")
        self.assertEqual(result["error"], "雪碧了")
        self.assertEqual(result["final_answer"], "无法解答（不会做）")


class WellFormedTest(unittest.TestCase):
    def test_is_well_formed(self):
        good = [{"steps": [{
            "title": "t",
            "standard_writing": "s",
            "detailed_writing": "d",
        }]}]
        self.assertTrue(_is_well_formed_chunk_results(good))
        self.assertFalse(_is_well_formed_chunk_results([]))
        self.assertFalse(_is_well_formed_chunk_results([{"steps": [{"title": "t"}]}]))

    def test_aggregate_from_chunks(self):
        crs = [{
            "final_answer": "A",
            "knowledge_points": ["集合与元素"],
            "steps": [{"knowledge_point": "集合与元素、常用逻辑用语"}],
        }]
        result = _aggregate_from_chunks("题", crs, {"total_tokens": 1})
        self.assertEqual(result["final_answer"], "A")
        self.assertIn("常用逻辑用语", result["knowledge_points"])
        self.assertEqual(result["overall_difficulty"]["level"], "未知")

    def test_collect_kps_from_steps(self):
        crs = [{"steps": [{"knowledge_point": "集合与元素、集合与元素"}]}]
        self.assertEqual(_collect_kps_from_steps(crs), ["集合与元素"])

    def test_validate_step_names_with_no_predefined(self):
        steps = [{"title": "任意步骤", "step_level1": None}]
        self.assertEqual(_validate_step_names("未知板块", steps), steps)


class ApiCallTest(unittest.TestCase):
    def test_get_api_key(self):
        with patch.object(solver_mod.runtime_settings, "get_api_key", return_value="k"):
            self.assertEqual(get_api_key(), "k")
        with patch.object(solver_mod.runtime_settings, "get_api_key", return_value=""):
            with self.assertRaises(ValueError):
                get_api_key()

    def _api_patches(self):
        return (
            patch.object(solver_mod, "get_api_key", return_value="k"),
            patch.object(solver_mod.runtime_settings, "get_api", return_value={"deepseek": {"base_url": "https://x/v1"}}),
            patch.object(solver_mod.runtime_settings, "get_limits", return_value={"api_timeout_seconds": 5, "api_max_tokens": 1000}),
        )

    def _api_stack(self):
        stack = ExitStack()
        for p in self._api_patches():
            stack.enter_context(p)
        return stack

    def test_call_deepseek_success(self):
        resp = type("R", (), {
            "status_code": 200,
            "json": lambda self: {"choices": [{"message": {"content": "ok"}}], "usage": {"total_tokens": 1}},
        })()
        with self._api_stack(), patch.object(solver_mod.httpx, "post", return_value=resp):
            content, usage = call_deepseek("sys", "user")
        self.assertEqual(content, "ok")
        self.assertEqual(usage["total_tokens"], 1)

    def test_call_deepseek_http_error(self):
        resp = type("R", (), {"status_code": 500, "text": "boom"})()
        with self._api_stack(), patch.object(solver_mod.httpx, "post", return_value=resp):
            with self.assertRaises(Exception):
                call_deepseek("sys", "user")

    def test_call_deepseek_timeout(self):
        with self._api_stack(), patch.object(solver_mod.httpx, "post", side_effect=httpx.TimeoutException("t")):
            with self.assertRaises(Exception) as ctx:
                call_deepseek("sys", "user")
        self.assertIn("超时", str(ctx.exception))

    def test_call_deepseek_connect_error(self):
        with self._api_stack(), patch.object(solver_mod.httpx, "post", side_effect=httpx.ConnectError("c")):
            with self.assertRaises(Exception) as ctx:
                call_deepseek("sys", "user")
        self.assertIn("无法连接", str(ctx.exception))


class StepFlowTest(unittest.TestCase):
    def test_step_solver_only_success(self):
        content = "是否数学题：[是]\n是否能做出来：[是]\n板块：数列\n解：略"
        with patch.object(solver_mod, "call_deepseek", return_value=(content, {})), \
             patch.object(solver_mod.runtime_settings, "get_teacher_config", return_value={
                 "solver": {"model": "deepseek-v4-flash", "reasoning_effort": None},
             }):
            result = step_solver_only("题")
        self.assertEqual(result["category"], "数列")
        self.assertIn("解：略", result["content"])

    def test_step_solver_only_not_math(self):
        content = "是否数学题：[否]"
        with patch.object(solver_mod, "call_deepseek", return_value=(content, {})), \
             patch.object(solver_mod.runtime_settings, "get_teacher_config", return_value={
                 "solver": {"model": "deepseek-v4-flash", "reasoning_effort": None},
             }):
            result = step_solver_only("题")
        self.assertEqual(result["error"], "雪碧了")

    def test_step_final_check_success(self):
        result_fixture = {"final_answer": "A", "chunk_results": []}
        with patch.object(solver_mod, "_call_formatter", return_value=(result_fixture, None)):
            result = step_final_check("题", [], [], {})
        self.assertEqual(result["final_answer"], "A")

    def test_step_final_check_fallback(self):
        crs = [{
            "final_answer": "A",
            "knowledge_points": ["集合与元素"],
            "steps": [{"knowledge_point": "集合与元素"}],
        }]
        with patch.object(solver_mod, "_call_formatter", return_value=(None, "格式不合格")):
            result = step_final_check("题", crs, [], {}, solver_content="解")
        self.assertTrue(result["formatter_fallback"])
        self.assertEqual(result["error"], "formatter_failed")


if __name__ == "__main__":
    unittest.main()
