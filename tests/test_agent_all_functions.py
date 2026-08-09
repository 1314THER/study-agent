"""agent.py 全函数覆盖：规则探测器、回复构造、工具循环内部件与 LLM 调用。"""

import json
import unittest
from unittest.mock import patch

import backend.agent as agent_mod
from backend.agent import (
    _action_args,
    _agent_flow,
    _agent_system_prompt,
    _call_llm_messages,
    _chunk_reply,
    _detect_navigation,
    _detect_open_question,
    _detect_qid,
    _detect_search,
    _extract_json,
    _extract_question,
    _fallback_path,
    _fast_path,
    _is_cart,
    _is_grade,
    _is_solve,
    _is_stats,
    _is_teach,
    _run_agent_loop_gen,
    _search_reply,
    _stats_reply,
    _tool_block,
    _tool_result_text,
    _validate_action,
)


CTX = {
    "total_questions": 10,
    "wrong_questions": 2,
    "practice_records": 30,
    "patterns_total": 5,
    "patterns_mastered": 2,
    "due_reviews": 3,
    "recent_wrong": [],
    "categories": ["解析几何"],
}


class RuleDetectorTest(unittest.TestCase):
    def test_detect_navigation(self):
        self.assertEqual(_detect_navigation("打开题库"), "history")
        self.assertEqual(_detect_navigation("带我去巩固日历"), "calendar")
        self.assertIsNone(_detect_navigation("今天天气不错"))

    def test_detect_open_question(self):
        self.assertEqual(_detect_open_question("打开第3题"), 3)
        self.assertEqual(_detect_open_question("题号12题"), 12)
        self.assertEqual(_detect_open_question("看下第 5 题"), 5)
        self.assertIsNone(_detect_open_question("随便聊聊"))

    def test_detect_qid(self):
        self.assertEqual(_detect_qid("第 3 题"), 3)
        self.assertEqual(_detect_qid("题目 #7"), 7)
        self.assertIsNone(_detect_qid("没有题号"))

    def test_extract_question(self):
        self.assertEqual(_extract_question("帮我解：已知 $x=1$"), "已知 $x=1$")
        self.assertEqual(_extract_question("题目：求导数并说明"), "求导数并说明")
        self.assertEqual(_extract_question("没有分隔符"), "")

    def test_detect_search(self):
        search = _detect_search("拿3道解析几何大题")
        self.assertIsNotNone(search)
        self.assertEqual(search["limit"], 3)
        self.assertIn("解析几何", search["filters"]["category"])

        search = _detect_search("给我看看错题")
        self.assertEqual(search["filters"]["error_type"], "errors")

        self.assertIsNone(_detect_search("你好"))

    def test_flag_detectors(self):
        self.assertTrue(_is_stats("我该学什么"))
        self.assertFalse(_is_stats("打开题库"))
        self.assertTrue(_is_teach("教我做这道题"))
        self.assertFalse(_is_teach("打开题库"))
        self.assertTrue(_is_solve("帮我解一下"))
        self.assertFalse(_is_solve("打开题库"))
        self.assertTrue(_is_grade("帮我改卷"))
        self.assertFalse(_is_grade("打开题库"))
        self.assertTrue(_is_cart("帮我组卷"))
        self.assertTrue(_is_cart("出3道题组卷"))
        self.assertFalse(_is_cart("打开题库"))


class ReplyBuilderTest(unittest.TestCase):
    def test_stats_reply(self):
        reply = _stats_reply(CTX)
        self.assertIn("3 个套路到期复习", reply)
        self.assertIn("2 道带错因标记", reply)
        self.assertIn("2 / 5", reply)

        self.assertEqual(_stats_reply({}), "目前还没有足够的学习数据，先去解题或上传题目吧。")

    def test_search_reply(self):
        search = {
            "limit": 3,
            "filters": {
                "category": "解析几何",
                "question_type": "大题",
                "difficulty": "困难",
                "error_type": "",
            },
        }
        self.assertIn("解析几何、大题、困难", _search_reply(search))

        wrong = {"limit": 2, "filters": {"category": "", "question_type": "", "difficulty": "", "error_type": "errors"}}
        self.assertEqual(_search_reply(wrong), "好，帮你找 2 道错题。")

    def test_chunk_reply(self):
        self.assertEqual(list(_chunk_reply("123456789", size=3)), ["123", "456", "789"])
        self.assertEqual(list(_chunk_reply("")), [])


class ActionHelperTest(unittest.TestCase):
    def test_action_args_flattens_search_filters(self):
        action = {
            "type": "search_questions",
            "query": "",
            "filters": {"category": "函数与导数"},
            "limit": 2,
        }
        args = _action_args(action)
        self.assertEqual(args["category"], "函数与导数")
        self.assertEqual(args["limit"], 2)

    def test_action_args_keeps_plan_fields(self):
        args = _action_args({"type": "plan_study", "per_day": 3, "apply": True})
        self.assertEqual(args["per_day"], 3)
        self.assertTrue(args["apply"])

    def test_agent_system_prompt_lists_tools(self):
        prompt = _agent_system_prompt()
        for name in ("search_questions", "solve_question", "teach_question", "grade_answer", "plan_study", "get_context"):
            self.assertIn(name, prompt)
        self.assertIn("navigate", prompt)

    def test_tool_result_text_truncates(self):
        text = _tool_result_text("x", {"data": "长" * 10000})
        self.assertLessEqual(len(text), 6000)
        self.assertIn("长", text)

    def test_tool_block_variants(self):
        self.assertIsNone(_tool_block("get_context", {"x": 1}))
        self.assertIsNone(_tool_block("unknown", {"x": 1}))

        search = _tool_block("search_questions", {"count": 1, "items": [{"id": 1}]})
        self.assertEqual(search["type"], "search")
        self.assertEqual(_tool_block("search_questions", {"count": 0, "items": []})["empty"], True)

        solve = _tool_block("solve_question", {"question": "题", "final_answer": "A"})
        self.assertEqual(solve["type"], "solve")
        self.assertEqual(_tool_block("solve_question", {"error": "x", "detail": "y"})["type"], "solve_error")

        teach = _tool_block("teach_question", {"session_id": "s1", "step_titles": []})
        self.assertEqual(teach["type"], "teach")
        self.assertEqual(_tool_block("teach_question", {"error": "x", "detail": "y"})["type"], "solve_error")

        grade = _tool_block("grade_answer", {"is_correct": True})
        self.assertEqual(grade["type"], "grade")
        self.assertEqual(_tool_block("grade_answer", {"error": "x", "detail": "y"})["type"], "solve_error")

        plan = _tool_block("plan_study", {"days": 1})
        self.assertEqual(plan["type"], "plan")
        self.assertEqual(_tool_block("plan_study", {"error": "x", "detail": "y"})["type"], "solve_error")

    def test_extract_json_variants(self):
        self.assertEqual(_extract_json('{"a": 1}'), '{"a": 1}')
        self.assertEqual(_extract_json('```json\n{"a": 1}\n```'), '{"a": 1}')
        self.assertEqual(_extract_json("  前面 {\"a\": 1} 后面"), '{"a": 1}')


class FlowInternalTest(unittest.TestCase):
    def test_fast_path(self):
        with patch.object(agent_mod, "agent_context", return_value=CTX):
            self.assertEqual(_fast_path("打开题库")["actions"][0]["page"], "history")
            self.assertEqual(_fast_path("我该学什么")["actions"][0]["type"], "context")
        self.assertEqual(_fast_path("打开第3题")["actions"][0]["type"], "open_question")
        self.assertIsNone(_fast_path("随便聊聊"))

    def test_fallback_path(self):
        result = _fallback_path("帮我解这道题：求 $x$")
        self.assertEqual(result["actions"][0]["type"], "solve")
        result = _fallback_path("教我做这道题：求导数")
        self.assertEqual(result["actions"][0]["type"], "teach")
        result = _fallback_path("帮我改卷")
        self.assertEqual(result["actions"][0]["type"], "grade")
        result = _fallback_path("拿3道数列题")
        self.assertEqual(result["actions"][0]["type"], "search_questions")
        result = _fallback_path("帮我组卷")
        self.assertEqual(result["actions"][0]["type"], "search_questions")
        self.assertIn("add_to_cart", [a["type"] for a in result["actions"]])
        self.assertIn("navigate", [a["type"] for a in result["actions"]])

    def test_agent_flow_fast_path(self):
        events = list(_agent_flow("打开题库"))
        self.assertEqual(events[0]["type"], "progress")
        self.assertEqual(events[-1]["type"], "result")

    def test_run_agent_loop_gen_failure_yields_none(self):
        with patch.object(agent_mod, "agent_context", return_value=CTX), \
             patch.object(agent_mod, "_call_llm_messages", return_value=None):
            items = list(_run_agent_loop_gen("你好"))
        self.assertIsNone(items[-1])

    def test_run_agent_loop_gen_success(self):
        llm_json = json.dumps({"reply": "好", "actions": [{"type": "get_context"}]}, ensure_ascii=False)
        final_json = json.dumps({"reply": "完成", "actions": []}, ensure_ascii=False)
        with patch.object(agent_mod, "agent_context", return_value=CTX), \
             patch.object(agent_mod, "_call_llm_messages", side_effect=[llm_json, final_json]), \
             patch.object(agent_mod, "run_tool", return_value=CTX):
            items = list(_run_agent_loop_gen("查学情"))
        self.assertIsInstance(items[-1], dict)
        self.assertEqual(items[-1]["reply"], "完成")


class LlmCallTest(unittest.TestCase):
    def test_no_api_key(self):
        with patch.object(agent_mod.runtime_settings, "get_api_key", return_value=""):
            self.assertIsNone(_call_llm_messages([{"role": "user", "content": "hi"}]))

    def test_http_error_and_exception(self):
        with patch.object(agent_mod.runtime_settings, "get_api_key", return_value="k"), \
             patch.object(agent_mod.runtime_settings, "get_api", return_value={"deepseek": {"base_url": "https://x/v1"}}), \
             patch.object(agent_mod.runtime_settings, "get_settings", return_value={}), \
             patch.object(agent_mod.runtime_settings, "get_limits", return_value={"api_max_tokens": 32000}), \
             patch.object(agent_mod.httpx, "post", return_value=type("R", (), {"status_code": 500})()):
            self.assertIsNone(_call_llm_messages([{"role": "user", "content": "hi"}]))

        class Boom(Exception):
            pass

        with patch.object(agent_mod.runtime_settings, "get_api_key", return_value="k"), \
             patch.object(agent_mod.runtime_settings, "get_api", return_value={"deepseek": {"base_url": "https://x/v1"}}), \
             patch.object(agent_mod.runtime_settings, "get_settings", return_value={}), \
             patch.object(agent_mod.runtime_settings, "get_limits", return_value={"api_max_tokens": 32000}), \
             patch.object(agent_mod.httpx, "post", side_effect=Boom("net")):
            self.assertIsNone(_call_llm_messages([{"role": "user", "content": "hi"}]))

    def test_success_returns_content(self):
        resp = type("R", (), {"status_code": 200, "json": lambda self: {"choices": [{"message": {"content": "ok"}}]}})()
        with patch.object(agent_mod.runtime_settings, "get_api_key", return_value="k"), \
             patch.object(agent_mod.runtime_settings, "get_api", return_value={"deepseek": {"base_url": "https://x/v1"}}), \
             patch.object(agent_mod.runtime_settings, "get_settings", return_value={}), \
             patch.object(agent_mod.runtime_settings, "get_limits", return_value={"api_max_tokens": 32000}), \
             patch.object(agent_mod.httpx, "post", return_value=resp):
            self.assertEqual(_call_llm_messages([{"role": "user", "content": "hi"}]), "ok")


if __name__ == "__main__":
    unittest.main()
