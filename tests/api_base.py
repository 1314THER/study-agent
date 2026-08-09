"""API 测试基础设施：临时双库 + patterns.yaml + settings.json 全隔离。"""

import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import backend.database as database_mod
import backend.patterns as patterns_mod
import backend.settings as settings_mod


def seed_answer(category="集合与逻辑用语"):
    return {
        "category": {"level1": category, "level2": ""},
        "chunk_results": [{
            "chunk_type": "选择题",
            "category": {"level1": category, "level2": ""},
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
        "overall_difficulty": {"level": "容易", "score": 1, "dimensions": {}},
    }


class ApiTestCase(unittest.TestCase):
    """每个用例使用独立的临时数据库、套路库、patterns.yaml 和 settings.json。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.study_db = os.path.join(self.tmp.name, "study.db")
        self.mastery_db = os.path.join(self.tmp.name, "mastery.db")
        self.patterns_yaml = os.path.join(self.tmp.name, "patterns.yaml")
        self.settings_json = os.path.join(self.tmp.name, "settings.json")

        self._patches = [
            patch.object(database_mod, "DB_PATH", self.study_db),
            patch.object(patterns_mod, "MASTERY_DB", self.mastery_db),
            patch.object(patterns_mod, "PATTERNS_YAML", self.patterns_yaml),
            patch.object(settings_mod, "SETTINGS_PATH", self.settings_json),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)
        settings_mod._cache = {"mtime": None, "data": None}

        from backend.main import app

        self.app = app
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def seed_question(self, question_text=None, category="集合与逻辑用语"):
        from backend.database import save_question

        question_text = question_text or "设集合 $A=\\{1,2\\}$，则 $A$ 的子集个数是？"
        return save_question(question_text, seed_answer(category))

    def create_pattern(self, category="集合与逻辑用语", name="套路甲"):
        from backend.patterns import add_mother_question

        qid = self.seed_question(category=category)
        return add_mother_question(qid, category, name)
