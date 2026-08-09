"""轻量集成测试：用临时 SQLite 库验证搜索工具与学情快照。"""

import os
import tempfile
import unittest
from unittest.mock import patch


def _seed_answer():
    return {
        "chunk_results": [{
            "chunk_type": "选择题",
            "category": {"level1": "集合与逻辑用语", "level2": ""},
            "final_answer": "A",
            "knowledge_points": ["集合与元素"],
            "steps": [{
                "step_number": 1,
                "title": "判断元素归属",
                "standard_writing": "逐项判断",
                "detailed_writing": "逐项判断并排除",
                "knowledge_point": "集合与元素",
                "step_difficulty": {"level": "容易", "score": 1, "dimensions": {}},
            }],
        }],
        "final_answer": "A",
        "knowledge_points": ["集合与元素"],
    }


class TempDbIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "test.db")
        self.addCleanup(self.tmp.cleanup)
        patcher = patch("backend.database.DB_PATH", self.db_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_search_tool_finds_seeded_question(self):
        from backend.agent_tools import run_tool
        from backend.database import init_db, save_question

        init_db()
        qid = save_question("设集合 $A=\\{1,2\\}$，则 $A$ 的子集个数是？", _seed_answer())
        self.assertIsNotNone(qid)

        result = run_tool("search_questions", {"category": "集合与逻辑用语", "limit": 5})
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["id"], qid)
        self.assertEqual(result["items"][0]["question_type"], "选择题")

    def test_agent_context_reads_temp_db(self):
        from backend.agent_tools import agent_context
        from backend.database import init_db, save_question

        init_db()
        save_question("已知 $A=\\{x\\mid x>0\\}$，判断 $1\\in A$。", _seed_answer())

        with patch("backend.agent_tools.get_patterns", return_value=[
            {"mastery": {"state": "third_pass"}},
            {"mastery": {"state": "never"}},
        ]), patch("backend.agent_tools.get_pattern_calendar", return_value={"today_items": [1, 2]}):
            ctx = agent_context()

        self.assertEqual(ctx["total_questions"], 1)
        self.assertEqual(ctx["due_reviews"], 2)
        self.assertEqual(ctx["patterns_total"], 2)
        self.assertEqual(ctx["patterns_mastered"], 1)


if __name__ == "__main__":
    unittest.main()
