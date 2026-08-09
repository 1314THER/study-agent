"""全局 agent 单元测试：规则快路径、工具循环、历史与流式协议。"""

import json
import unittest
from unittest.mock import patch

from backend.agent import (
    _extract_json,
    _normalize_history,
    _validate_action,
    agent_act,
    agent_act_stream,
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


class FastPathTest(unittest.TestCase):
    """不依赖 LLM 的规则快路径。"""

    def test_navigate_history(self):
        result = agent_act("打开题库")
        self.assertEqual(result["actions"], [{"type": "navigate", "page": "history", "params": {}}])

    def test_open_question(self):
        result = agent_act("打开第3题")
        self.assertEqual(result["actions"], [{"type": "open_question", "id": 3}])

    def test_stats_path(self):
        with patch("backend.agent.agent_context", return_value=CTX):
            result = agent_act("我该学什么")
        self.assertEqual(result["actions"], [{"type": "context"}])
        self.assertIn("3 个套路到期复习", result["reply"])
        self.assertEqual(result["context"]["total_questions"], 10)

    def test_handwriting_grade_path(self):
        result = agent_act("帮我用手机拍手写作答批改一下")
        self.assertEqual(result["actions"][0]["page"], "grade")


class ToolLoopTest(unittest.TestCase):
    """多步工具循环：模型返回动作、服务端执行、结果回传。"""

    def test_search_tool_round_trip(self):
        first_json = json.dumps({
            "reply": "找到题目了",
            "actions": [{
                "type": "search_questions",
                "query": "",
                "filters": {"category": "解析几何"},
                "limit": 2,
            }],
        }, ensure_ascii=False)
        final_json = json.dumps({"reply": "找到题目并完成", "actions": []}, ensure_ascii=False)
        items = [{
            "id": 1,
            "question_type": "选择题",
            "category": "解析几何",
            "difficulty": "容易",
            "source_type": "精选母题",
            "knowledge_points": [],
            "content": "题目内容",
        }]

        with patch("backend.agent.agent_context", return_value=CTX), \
             patch("backend.agent._call_llm_messages", side_effect=[first_json, final_json]) as mock_llm, \
             patch("backend.agent.run_tool", return_value={"count": 1, "limit": 2, "items": items}) as mock_tool:
            result = agent_act("拿2道解析几何")

        self.assertEqual(result["reply"], "找到题目并完成")
        self.assertEqual(result["actions"], [])
        self.assertEqual(len(result["blocks"]), 1)
        self.assertEqual(result["blocks"][0]["type"], "search")
        self.assertEqual(result["blocks"][0]["title"], "找到 1 道题")
        mock_tool.assert_called_once()
        tool_name, tool_args = mock_tool.call_args[0]
        self.assertEqual(tool_name, "search_questions")
        self.assertEqual(tool_args["category"], "解析几何")
        self.assertEqual(tool_args["limit"], 2)
        self.assertEqual(mock_llm.call_count, 2)

    def test_loop_caps_at_four_rounds(self):
        llm_json = json.dumps({
            "reply": "继续",
            "actions": [{"type": "get_context"}],
        }, ensure_ascii=False)

        with patch("backend.agent.agent_context", return_value=CTX), \
             patch("backend.agent._call_llm_messages", return_value=llm_json) as mock_llm, \
             patch("backend.agent.run_tool", return_value=CTX):
            result = agent_act("反复获取学习数据")

        self.assertEqual(mock_llm.call_count, 4)
        self.assertIsInstance(result, dict)
        self.assertTrue(result["reply"])

    def test_multi_step_context_then_navigate(self):
        responses = iter([
            json.dumps({"reply": "先看学情", "actions": [{"type": "get_context"}]}, ensure_ascii=False),
            json.dumps({"reply": "已经安排", "actions": [{"type": "navigate", "page": "calendar", "params": {}}]}, ensure_ascii=False),
        ])

        def fake_llm(messages, temperature=0.4):
            return next(responses)

        with patch("backend.agent.agent_context", return_value=CTX), \
             patch("backend.agent._call_llm_messages", side_effect=fake_llm) as mock_llm, \
             patch("backend.agent.run_tool", return_value=CTX) as mock_tool:
            result = agent_act("给我安排复习")

        self.assertEqual(result["reply"], "已经安排")
        self.assertEqual(result["actions"], [{"type": "navigate", "page": "calendar", "params": {}}])
        self.assertEqual(result["context"]["due_reviews"], 3)
        self.assertEqual(mock_llm.call_count, 2)
        mock_tool.assert_called_once_with("get_context", {})

    def test_frontend_only_action_does_not_run_tool(self):
        llm_json = json.dumps({
            "reply": "走",
            "actions": [{"type": "navigate", "page": "calendar", "params": {}}],
        }, ensure_ascii=False)

        with patch("backend.agent.agent_context", return_value=CTX), \
             patch("backend.agent._call_llm_messages", return_value=llm_json), \
             patch("backend.agent.run_tool") as mock_tool:
            result = agent_act("打开巩固日历")

        self.assertEqual(result["actions"][0]["page"], "calendar")
        mock_tool.assert_not_called()

    def test_llm_unavailable_falls_back_to_rules(self):
        with patch("backend.agent.agent_context", return_value=CTX), \
             patch("backend.agent._call_llm_messages", return_value=None):
            result = agent_act("帮我解这道题：已知 $x^2=4$，求 $x$。")

        self.assertEqual(result["actions"][0]["type"], "solve")
        self.assertIn("$x^2=4$", result["actions"][0]["question"])


class HistoryAndValidationTest(unittest.TestCase):
    def test_normalize_history_keeps_last_ten_rounds(self):
        history = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": str(i)}
            for i in range(25)
        ]
        history.extend([
            {"role": "system", "content": "忽略我"},
            {"role": "user", "content": "   "},
        ])
        normalized = _normalize_history(history)
        self.assertEqual(len(normalized), 20)
        self.assertEqual(normalized[0]["content"], "5")
        self.assertEqual(normalized[-1]["content"], "24")

    def test_normalize_history_rejects_non_dicts(self):
        self.assertEqual(_normalize_history(["bad", None, 1]), [])

    def test_validate_plan_study(self):
        action = _validate_action({"type": "plan_study", "per_day": 3, "apply": True})
        self.assertEqual(action["per_day"], 3)
        self.assertTrue(action["apply"])

    def test_validate_plan_study_bad_per_day(self):
        action = _validate_action({"type": "plan_study", "per_day": "abc"})
        self.assertIsNone(action.get("per_day"))

    def test_validate_grade_answer(self):
        action = _validate_action({"type": "grade_answer", "question": "题", "student_answer": "答"})
        self.assertEqual(action["student_answer"], "答")
        self.assertIsNone(_validate_action({"type": "grade_answer", "question": "题"}))

    def test_validate_solve_question_requires_question(self):
        self.assertIsNone(_validate_action({"type": "solve_question", "question": ""}))
        self.assertIsNotNone(_validate_action({"type": "solve_question", "question": "题"}))

    def test_validate_search_normalizes_category_alias(self):
        action = _validate_action({
            "type": "search_questions",
            "query": "",
            "filters": {"category": "函数"},
            "limit": 3,
        })
        self.assertEqual(action["filters"]["category"], "函数与导数")

    def test_extract_json_with_fence(self):
        self.assertEqual(_extract_json('```json\n{"a": 1}\n```'), '{"a": 1}')


class StreamProtocolTest(unittest.TestCase):
    def test_stream_events_terminate_with_done(self):
        events = list(agent_act_stream("打开题库"))
        types = [ev["type"] for ev in events]
        self.assertIn("progress", types)
        self.assertIn("token", types)
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(events[-1]["result"]["actions"][0]["page"], "history")

    def test_stream_empty_message(self):
        events = list(agent_act_stream(""))
        done = events[-1]
        self.assertEqual(done["type"], "done")
        self.assertEqual(done["result"]["reply"], "请告诉我你想做什么。")


if __name__ == "__main__":
    unittest.main()
