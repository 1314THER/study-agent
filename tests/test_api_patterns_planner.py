"""母题套路、闯关地图与规划 API 测试。"""

import unittest
from unittest.mock import patch

from tests.api_base import ApiTestCase


class PatternApiTest(ApiTestCase):
    def test_add_mother_and_list(self):
        qid = self.seed_question()
        resp = self.client.post("/patterns/mother", json={
            "question_id": qid,
            "category": "集合与逻辑用语",
            "name": "集合子集计数",
        })
        self.assertEqual(resp.status_code, 200)
        pid = resp.json()["pattern_id"]

        resp = self.client.get("/patterns")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any(p["id"] == pid for p in resp.json()))

    def test_add_mother_with_difficulty_and_match(self):
        qid = self.seed_question()
        resp = self.client.post("/patterns/mother", json={
            "question_id": qid,
            "category": "集合与逻辑用语",
            "name": "集合子集计数",
            "difficulty": 3,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["difficulty"], 3)
        pid = resp.json()["pattern_id"]

        listed = [p for p in self.client.get("/patterns").json() if p["id"] == pid][0]
        self.assertEqual(listed["difficulty"], 3)

        from backend.patterns import match_question_to_pattern
        m = match_question_to_pattern(
            content="设集合 A={1,2}，则 A 的子集个数是？",
            category="集合与逻辑用语",
            kps=["集合与元素"],
            question_type="选择题",
        )
        self.assertTrue(m["matches"], "应匹配到套路")
        self.assertEqual(m["pattern_id"], pid)
        self.assertEqual(m["difficulty"], 3)

    def test_add_mother_invalid_category(self):
        qid = self.seed_question()
        resp = self.client.post("/patterns/mother", json={
            "question_id": qid,
            "category": "不存在的板块",
            "name": "x",
        })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "invalid_mother")

    def test_update_and_delete_pattern(self):
        pattern = self.create_pattern()
        pid = pattern["pattern_id"]

        resp = self.client.put(f"/patterns/{pid}", json={"name": "改后名字"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["name"], "改后名字")

        resp = self.client.delete(f"/patterns/{pid}")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["deleted"])

        resp = self.client.delete(f"/patterns/{pid}")
        self.assertEqual(resp.status_code, 404)

    def test_link_and_unlink_question(self):
        pattern = self.create_pattern()
        pid = pattern["pattern_id"]
        qid2 = self.seed_question("第二道题：判断 $1\\in\\{1,2\\}$。")

        resp = self.client.post(f"/patterns/{pid}/questions", json={"question_id": qid2, "role": "variant1"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn(qid2, resp.json()["variant_ids"])

        resp = self.client.delete(f"/patterns/{pid}/questions/{qid2}", params={"role": "variant1"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["unlinked"])

    def test_export_yaml(self):
        self.create_pattern()
        resp = self.client.post("/patterns/export-yaml")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["exported"])

    def test_sync_patterns(self):
        with patch("backend.patterns.sync_mother_questions", return_value={"synced": 1}):
            resp = self.client.post("/patterns/sync")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["synced"], 1)

    def test_match_wrong(self):
        with patch("backend.patterns.match_mother_for_wrong_question", return_value={"matched": False}):
            resp = self.client.post("/patterns/match-wrong", json={"question_id": 1})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["matched"])

    def test_mark_pattern_wrong(self):
        with patch("backend.patterns.mark_pattern_wrong", return_value={"marked": True}):
            resp = self.client.post("/patterns/1/wrong", json={"question_id": 1})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["marked"])

    def test_get_pattern_loop(self):
        fixture = {"pattern_id": 1, "mother_id": 1, "variants": []}
        with patch("backend.patterns.get_pattern_loop", return_value=fixture):
            resp = self.client.get("/patterns/1/loop")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["pattern_id"], 1)

        with patch("backend.patterns.get_pattern_loop", side_effect=ValueError("no")):
            resp = self.client.get("/patterns/999/loop")
        self.assertEqual(resp.status_code, 404)

    def test_pattern_calendar(self):
        with patch("backend.patterns.get_pattern_calendar", return_value={"today_items": []}):
            resp = self.client.get("/patterns/calendar")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["today_items"], [])

    def test_pattern_calendar_ics(self):
        with patch("backend.patterns.get_pattern_calendar_ics", return_value="BEGIN:VCALENDAR"):
            resp = self.client.get("/patterns/calendar.ics")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/calendar", resp.headers["content-type"])
        self.assertIn("BEGIN:VCALENDAR", resp.text)

    def test_schedule_and_remove_pattern_calendar(self):
        with patch("backend.patterns.schedule_pattern_review") as sched, \
             patch("backend.patterns.get_pattern_calendar", return_value={"items": []}):
            resp = self.client.post("/patterns/calendar", json={
                "pattern_id": 1,
                "due_date": "2026-08-15",
            })
        self.assertEqual(resp.status_code, 200)
        sched.assert_called_once_with(1, "2026-08-15")

        with patch("backend.patterns.schedule_pattern_review", side_effect=ValueError("日期格式应为 YYYY-MM-DD")):
            resp = self.client.post("/patterns/calendar", json={
                "pattern_id": 1,
                "due_date": "bad",
            })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "invalid_schedule")

        with patch("backend.patterns.unschedule_pattern_review") as unsched, \
             patch("backend.patterns.get_pattern_calendar", return_value={"items": []}):
            resp = self.client.delete("/patterns/calendar/1")
        self.assertEqual(resp.status_code, 200)
        unsched.assert_called_once_with(1)

        with patch("backend.patterns.unschedule_pattern_review", side_effect=ValueError("套路不存在: 999")):
            resp = self.client.delete("/patterns/calendar/999")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["error"], "not_found")

    def test_record_attempt(self):
        pattern = self.create_pattern()
        pid = pattern["pattern_id"]
        qid = pattern["mother_id"]
        resp = self.client.post(f"/patterns/{pid}/attempt", json={
            "question_id": qid,
            "role": "mother",
            "correct": True,
            "is_first_try": True,
            "duration_seconds": 30,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["saved"])
        self.assertIsNotNone(resp.json()["attempt_id"])

    def test_complete_pattern_loop(self):
        with patch("backend.patterns.complete_pattern_loop", return_value={"passed": True}):
            resp = self.client.post("/patterns/1/complete", json={"passed": True})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["passed"])

    def test_check_pattern_answer(self):
        with patch("backend.patterns.check_pattern_answer", return_value={"is_correct": True}):
            resp = self.client.post("/patterns/1/check", json={"question_id": 1, "user_answer": "A"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["is_correct"])

        with patch("backend.patterns.check_pattern_answer", side_effect=ValueError("no")):
            resp = self.client.post("/patterns/999/check", json={"question_id": 1, "user_answer": "A"})
        self.assertEqual(resp.status_code, 404)

    def test_ensure_variants(self):
        with patch("backend.patterns.ensure_variants", return_value={"generated": 2}):
            resp = self.client.post("/patterns/1/ensure-variants", json={"teacher": "liangliang"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["generated"], 2)

        with patch("backend.patterns.ensure_variants", side_effect=RuntimeError("llm failed")):
            resp = self.client.post("/patterns/1/ensure-variants", json={})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "generate_failed")


class BoardApiTest(ApiTestCase):
    def test_get_boards(self):
        with patch("backend.patterns.get_boards", return_value=[{"id": 1, "category": "数列"}]):
            resp = self.client.get("/boards")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()[0]["category"], "数列")

    def test_save_board_layout(self):
        fixture = {"saved": 1}
        with patch("backend.patterns.save_board_layout", return_value=fixture) as mock:
            resp = self.client.put("/boards/1", json={
                "nodes": [{"question_id": 1, "x": 10, "y": 20}],
                "edges": [{"from_question_id": 1, "to_question_id": 2}],
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["saved"], 1)
        nodes, edges = mock.call_args[0][1], mock.call_args[0][2]
        self.assertEqual(nodes[0]["x"], 10)
        self.assertEqual(edges[0]["to_question_id"], 2)

        with patch("backend.patterns.save_board_layout", side_effect=ValueError("bad")):
            resp = self.client.put("/boards/1", json={"nodes": [], "edges": []})
        self.assertEqual(resp.status_code, 400)

    def test_save_board_layout_with_level_names(self):
        fixture = {"saved": 1}
        with patch("backend.patterns.save_board_layout", return_value=fixture) as mock:
            resp = self.client.put("/boards/1", json={
                "nodes": [{"question_id": 1, "x": 0, "y": 0}],
                "edges": [],
                "levels": [{"level_index": 0, "name": "基础关", "description": "$x^2$"}],
            })
        self.assertEqual(resp.status_code, 200)
        levels = mock.call_args[0][3]
        self.assertEqual(levels, [{"level_index": 0.0, "name": "基础关", "description": "$x^2$"}])


class PlannerApiTest(ApiTestCase):
    def test_board_order_get_and_put(self):
        with patch("backend.planner.get_board_order_config", return_value={"board_order": ["数列"]}):
            resp = self.client.get("/planner/board-order")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["board_order"], ["数列"])

        with patch("backend.planner.save_board_order_config", return_value={"saved": True}) as mock:
            resp = self.client.put("/planner/board-order", json={"board_order": ["函数与导数"]})
        self.assertEqual(resp.status_code, 200)
        mock.assert_called_once_with(["函数与导数"])

    def test_plan_preview(self):
        plan = {
            "template": None,
            "per_day": 2,
            "start_date": "2026-08-10",
            "total_patterns": 2,
            "days": 1,
            "plan": [{"date": "2026-08-10", "patterns": [{"name": "A"}]}],
        }
        with patch("backend.planner.build_plan", return_value=plan):
            resp = self.client.post("/planner/plan", json={"per_day": 2})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["days"], 1)

    def test_plan_apply(self):
        plan = {
            "template": None,
            "per_day": 2,
            "start_date": "2026-08-10",
            "total_patterns": 2,
            "days": 1,
            "plan": [{"date": "2026-08-10", "patterns": [{"name": "A"}]}],
        }
        with patch("backend.planner.build_plan", return_value=plan), \
             patch("backend.planner.apply_plan", return_value={"applied": 2}) as mock_apply:
            resp = self.client.post("/planner/apply", json={"per_day": 2})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["total_patterns"], 2)
        self.assertIn("days", resp.json())
        mock_apply.assert_called_once()


if __name__ == "__main__":
    unittest.main()
