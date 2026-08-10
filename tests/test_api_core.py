"""核心 API 测试：解题、题目、题单、教学、批改、agent、基础路由。"""

import json
import unittest
from unittest.mock import patch

from tests.api_base import ApiTestCase, seed_answer


def _chunk_fixture():
    return {
        "chunk_results": [{
            "chunk_id": 1,
            "chunk_type": "选择题",
            "category": {"level1": "集合与逻辑用语", "level2": ""},
            "final_answer": "A",
            "knowledge_points": ["集合与元素"],
            "steps": [{
                "step_number": 1,
                "title": "判断",
                "standard_writing": "逐项判断",
                "detailed_writing": "逐项判断并排除",
                "knowledge_point": "集合与元素",
                "step_difficulty": {"level": "容易", "score": 1, "dimensions": {}},
            }],
        }],
        "final_answer": "A",
        "knowledge_points": ["集合与元素"],
        "overall_difficulty": {"level": "容易", "score": 1, "dimensions": {}},
        "category": {"level1": "集合与逻辑用语", "level2": ""},
        "question_type": "选择题",
    }


class SolveApiTest(ApiTestCase):
    def test_step1(self):
        fixture = {"content": "解：x=2", "category": "函数与导数", "chunks": [], "token_usage": {}}
        with patch("backend.main.step_solver_only", return_value=fixture) as mock:
            resp = self.client.post("/solve/step1", json={"question": "题"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["content"], "解：x=2")
        mock.assert_called_once_with("题", None, teacher=None)

    def test_step2(self):
        fixture = _chunk_fixture()
        with patch("backend.main.step_verify_all", return_value=fixture) as mock:
            resp = self.client.post("/solve/step2", json={"question": "题", "content": "解答"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["final_answer"], "A")
        mock.assert_called_once()

    def test_step3_saves_question(self):
        fixture = _chunk_fixture()
        with patch("backend.main.step_final_check", return_value=fixture), \
             patch("backend.database.save_question", return_value=42):
            resp = self.client.post("/solve/step3", json={
                "question": "题",
                "chunk_results": json.dumps(fixture["chunk_results"]),
                "save": True,
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["saved_question_id"], 42)

    def test_step3_without_save(self):
        fixture = _chunk_fixture()
        with patch("backend.main.step_final_check", return_value=fixture), \
             patch("backend.database.save_question") as mock_save:
            resp = self.client.post("/solve/step3", json={
                "question": "题",
                "chunk_results": json.dumps(fixture["chunk_results"]),
                "save": False,
            })
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("saved_question_id", resp.json())
        mock_save.assert_not_called()


class QuestionApiTest(ApiTestCase):
    def test_save_and_list(self):
        resp = self.client.post("/questions/save", json={"question": "新题", "answer_json": seed_answer()})
        self.assertEqual(resp.status_code, 200)
        qid = resp.json()["id"]
        self.assertTrue(resp.json()["saved"])

        resp = self.client.get("/questions")
        self.assertEqual(resp.status_code, 200)
        ids = [q["id"] for q in resp.json()]
        self.assertIn(qid, ids)

    def test_search_with_filters(self):
        self.seed_question()
        resp = self.client.get("/questions/search", params={"category": "集合与逻辑用语", "limit": 5})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 1)

    def test_search_knowledge_and_step_filters(self):
        qid = self.seed_question()

        resp = self.client.get("/questions/search", params={"knowledge_points": "集合与元素"})
        self.assertEqual(len(resp.json()), 1)

        resp = self.client.get("/questions/search", params={"knowledge_points": "集合与元素,集合间的基本关系"})
        self.assertEqual(len(resp.json()), 0)

        resp = self.client.get("/questions/search", params={"step_level1": "判断元素归属"})
        self.assertEqual(len(resp.json()), 1)

        resp = self.client.get("/questions/search", params={"step_level1": "判断元素归属,不存在的步骤"})
        self.assertEqual(len(resp.json()), 0)

    def test_get_and_delete_question(self):
        qid = self.seed_question()
        resp = self.client.get(f"/questions/{qid}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("集合与逻辑用语", resp.json()["category_level1"])

        resp = self.client.delete(f"/questions/{qid}")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["deleted"])

        resp = self.client.get(f"/questions/{qid}")
        self.assertEqual(resp.json()["error"], "not_found")

    def test_get_question_not_found(self):
        resp = self.client.get("/questions/9999")
        self.assertEqual(resp.json()["error"], "not_found")

    def test_exam_touch(self):
        qid = self.seed_question()
        resp = self.client.post(f"/questions/{qid}/exam-touch")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["touched"])

    def test_step_error_add_and_delete(self):
        qid = self.seed_question()
        resp = self.client.post(f"/questions/{qid}/step-error", json={
            "step_number": 1,
            "chunk_id": 1,
            "mistake_type": "计算错误",
            "mistake_detail": "符号写反",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["saved"])
        eid = resp.json()["id"]

        detail = self.client.get(f"/questions/{qid}").json()
        self.assertEqual(len(detail["step_errors"]), 1)

        resp = self.client.delete(f"/questions/{qid}/step-error/{eid}")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["deleted"])

    def test_step_error_invalid_type(self):
        qid = self.seed_question()
        resp = self.client.post(f"/questions/{qid}/step-error", json={
            "step_number": 1,
            "chunk_id": 1,
            "mistake_type": "不存在的错因",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["error"], "invalid_mistake_type")

    def test_step_error_batch(self):
        qid = self.seed_question()
        resp = self.client.post(f"/questions/{qid}/step-errors/batch", json={
            "tags": [{
                "step_number": 1,
                "chunk_id": 1,
                "mistake_type": "思路错误",
                "mistake_detail": "方向反了",
            }],
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["saved"], 1)

        resp = self.client.post(f"/questions/{qid}/step-errors/batch", json={
            "tags": [{"step_number": 1, "chunk_id": 1, "mistake_type": "坏类型"}],
        })
        self.assertEqual(resp.json()["error"], "invalid_mistake_type")

    def test_update_source_type(self):
        qid = self.seed_question()
        resp = self.client.put(f"/questions/{qid}/source-type", json={
            "source_type": "高考题",
            "source_meta": {"paper": "2026 模考"},
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])

        resp = self.client.put(f"/questions/{qid}/source-type", json={"source_type": "未知来源"})
        self.assertEqual(resp.json()["error"], "invalid_source_type")

    def test_questions_with_errors(self):
        self.seed_question()
        resp = self.client.get("/questions/errors")
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.json(), list)


class QuestionListApiTest(ApiTestCase):
    def test_list_crud_and_membership(self):
        resp = self.client.get("/question-lists")
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(len(resp.json()), 3)

        resp = self.client.post("/question-lists", json={"name": "我的错题"})
        lid = resp.json()["id"]
        self.assertTrue(resp.json()["created"])

        resp = self.client.put(f"/question-lists/{lid}", json={"name": "新名字"})
        self.assertTrue(resp.json()["ok"])

        qid = self.seed_question()
        resp = self.client.post(f"/questions/{qid}/lists", json={"list_ids": [lid]})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["added"], 1)

        resp = self.client.get(f"/questions/{qid}/lists")
        self.assertIn(lid, resp.json()["list_ids"])

        resp = self.client.get(f"/question-lists/{lid}/questions")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["total"], 1)
        self.assertEqual(len(resp.json()["data"]), 1)

        resp = self.client.get("/question-lists/wrong/questions")
        self.assertEqual(resp.status_code, 200)

        resp = self.client.get("/question-lists/abc/questions")
        self.assertEqual(resp.json()["error"], "invalid_target")

        resp = self.client.delete(f"/questions/{qid}/lists/{lid}")
        self.assertTrue(resp.json()["ok"])

        resp = self.client.delete(f"/question-lists/{lid}")
        self.assertTrue(resp.json()["ok"])


class TeachApiTest(ApiTestCase):
    def test_find_not_found(self):
        resp = self.client.post("/teach/find", json={"question": "不存在的题"})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["found"])

    def test_find_found(self):
        qid = self.seed_question()
        from backend.database import get_question_by_id

        content = get_question_by_id(qid)["content"]
        resp = self.client.post("/teach/find", json={"question": content})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["found"])
        self.assertGreaterEqual(resp.json()["total_steps"], 1)

    def test_teach_start(self):
        fixture = {"question": "题", "steps": [{"title": "第一步"}], "total_steps": 1, "chunk_results": []}
        with patch("backend.main.teach_start", return_value=fixture):
            resp = self.client.post("/teach/start", json={"question": "题"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["total_steps"], 1)

    def test_teach_check(self):
        fixture = {"is_correct": True, "feedback": "正确"}
        with patch("backend.main.teach_check", return_value=fixture):
            resp = self.client.post("/teach/check", json={
                "question": "题",
                "step_prompt": "第一步",
                "step_answer": "x=2",
                "user_answer": "x=2",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["is_correct"])

    def test_session_start(self):
        fixture = {"session_id": "s1", "message": "开始", "total_steps": 2, "steps": []}
        with patch("backend.main.teach_session_start", return_value=fixture):
            resp = self.client.post("/teach/session/start", json={"question": "题"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["session_id"], "s1")

    def test_session_chat_and_get(self):
        session = {"session_id": "s1", "message": "继续"}
        with patch("backend.main.teach_get_session", return_value=session), \
             patch("backend.main.teach_session_chat", return_value={"message": "好"}) as mock_chat:
            resp = self.client.post("/teach/session/s1/chat", json={"message": "下一步"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["message"], "好")
        mock_chat.assert_called_once_with("s1", "下一步")

        resp = self.client.post("/teach/session/missing/chat", json={"message": "x"})
        self.assertEqual(resp.json()["error"], "session_not_found")

        with patch("backend.main.teach_get_session", return_value=session):
            resp = self.client.get("/teach/session/s1")
        self.assertEqual(resp.status_code, 200)

        resp = self.client.get("/teach/session/missing")
        self.assertEqual(resp.json()["error"], "session_not_found")

    def test_session_ack(self):
        with patch("backend.teach.teach_ack_prompt", return_value={"ack": True}) as mock_ack:
            resp = self.client.post("/teach/session/s1/ack")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ack"])
        mock_ack.assert_called_once_with("s1")


class GradeApiTest(ApiTestCase):
    def test_grade_text_endpoint(self):
        fixture = {"mode": "answer_match", "is_correct": True, "question_id": 1}
        with patch("backend.grade.grade_text", return_value=fixture) as mock:
            resp = self.client.post("/grade/text", json={"student_answer": "A"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["is_correct"])
        mock.assert_called_once()

        with patch("backend.grade.grade_text", return_value=fixture):
            resp = self.client.post("/grade", json={"student_answer": "A"})
        self.assertEqual(resp.status_code, 200)


class AgentApiTest(ApiTestCase):
    def test_agent_context(self):
        ctx = {"total_questions": 1, "wrong_questions": 0}
        with patch("backend.agent.agent_context", return_value=ctx):
            resp = self.client.get("/agent/context")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["total_questions"], 1)

    def test_agent_act_streams_ndjson(self):
        resp = self.client.post("/agent/act", json={"message": "打开题库"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("application/x-ndjson", resp.headers["content-type"])
        events = [json.loads(line) for line in resp.text.splitlines() if line.strip()]
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(events[-1]["result"]["actions"][0]["page"], "history")


class MiscApiTest(ApiTestCase):
    def test_root_redirects_home(self):
        resp = self.client.get("/", follow_redirects=False)
        self.assertEqual(resp.status_code, 307)

    def test_categories(self):
        resp = self.client.get("/categories")
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.json(), list)
        self.assertTrue(any(c["level1"] == "解析几何" for c in resp.json()))

    def test_steps(self):
        resp = self.client.get("/steps")
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.json()["types"], list)

    def test_ai_assemble_placeholder(self):
        resp = self.client.post("/exam/ai-assemble", json={"query": "数列"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["results"], [])

    def test_multimodal_parse_unsupported(self):
        resp = self.client.post("/multimodal/parse", files={"file": ("a.txt", b"abc", "text/plain")})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("error", resp.json())

    def test_multimodal_parse_supported(self):
        with patch("backend.main.parse_file", return_value=["题1", "题2"]):
            resp = self.client.post("/multimodal/parse", files={"file": ("a.pdf", b"%PDF-1.4", "application/pdf")})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["total"], 2)

    def test_ocr_unsupported(self):
        resp = self.client.post("/ocr/answer", files={"file": ("a.pdf", b"%PDF-1.4", "application/pdf")})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["error"], "unsupported")

    def test_ocr_supported(self):
        fixture = {"text": "x=2", "confidence": 0.9}
        with patch("backend.multimodal.recognize_answer_image", return_value=fixture):
            resp = self.client.post("/ocr/answer", files={"file": ("a.png", b"png", "image/png")})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["text"], "x=2")


if __name__ == "__main__":
    unittest.main()
