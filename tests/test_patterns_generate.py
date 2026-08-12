"""patterns.py 状态机 / 匹配 / 日历，以及 generate.py 完整流水线测试。"""

import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch

import backend.database as dbmod
import backend.generate as gen_mod
import backend.patterns as pat_mod
from backend.database import init_db, save_question, update_question_source
from backend.generate import (
    _call_generation,
    _is_duplicate,
    _save_accepted,
    _solve_candidate,
    generate_variants,
    get_generate_job,
    start_generate_job,
)
from backend.patterns import (
    _cn_now,
    _load_yaml,
    _match_similarity,
    _match_tokens,
    _parse_cn_time,
    _question_kps,
    add_mother_question,
    add_variant_question,
    check_pattern_answer,
    complete_pattern_loop,
    delete_question_links,
    ensure_variants,
    export_patterns_yaml,
    get_boards,
    get_mastery_summary,
    get_pattern,
    get_pattern_calendar,
    get_pattern_calendar_ics,
    get_pattern_loop,
    mark_pattern_wrong,
    match_mother_for_wrong_question,
    record_attempt,
    schedule_pattern_review,
    save_board_layout,
    set_pattern_schedule,
    sync_mother_questions,
    unschedule_pattern_review,
)


def _answer(category="集合与逻辑用语", final_answer="A"):
    return {
        "category": {"level1": category, "level2": ""},
        "chunk_results": [{
            "chunk_id": 1,
            "chunk_type": "选择题",
            "category": {"level1": category, "level2": ""},
            "final_answer": final_answer,
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
        "final_answer": final_answer,
        "knowledge_points": ["集合与元素"],
        "overall_difficulty": {"level": "容易", "score": 1, "dimensions": {}},
    }


class PatternsDbCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._patches = [
            patch.object(dbmod, "DB_PATH", os.path.join(self.tmp.name, "study.db")),
            patch.object(pat_mod, "MASTERY_DB", os.path.join(self.tmp.name, "mastery.db")),
            patch.object(pat_mod, "PATTERNS_YAML", os.path.join(self.tmp.name, "patterns.yaml")),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)
        init_db()
        pat_mod.init_mastery_db()

    def seed_question(self, text="设集合 $A=\\{1,2\\}$，则 $A$ 的子集个数是？", category="集合与逻辑用语"):
        return save_question(text, _answer(category))

    def create_pattern(self, category="集合与逻辑用语", name="集合子集计数", question_text=None):
        qid = self.seed_question(text=question_text or "设集合 $A=\\{1,2\\}$，则 $A$ 的子集个数是？", category=category)
        return add_mother_question(qid, category, name)


class PatternFlowTest(PatternsDbCase):
    def test_export_yaml_and_variant(self):
        pattern = self.create_pattern()
        pid = pattern["pattern_id"]
        qid2 = self.seed_question("第二道题")
        add_variant_question(pid, qid2, "variant1")
        self.assertIn(qid2, get_pattern(pid)["variant_ids"])
        with self.assertRaises(ValueError):
            add_variant_question(pid, qid2, "bad_role")

        data = export_patterns_yaml()
        self.assertIn("集合与逻辑用语", data)
        self.assertEqual(_load_yaml()["集合与逻辑用语"]["集合子集计数"]["key"], pattern["yaml_key"])

    def test_complete_pattern_loop_state_machine(self):
        pattern = self.create_pattern()
        pid = pattern["pattern_id"]
        states = []
        for _ in range(3):
            states.append(complete_pattern_loop(pid, True)["state"])
        self.assertEqual(states, ["first_pass", "second_pass", "third_pass"])
        self.assertEqual(complete_pattern_loop(pid, True)["state"], "third_pass")
        self.assertEqual(complete_pattern_loop(pid, False)["state"], "never")

    def test_match_tokens_similarity_kps(self):
        self.assertTrue(_match_tokens("集合 $A$ 与 $B$"))
        self.assertEqual(_match_similarity("集合 A", "集合 A"), 1.0)
        self.assertEqual(_match_similarity("集合", ""), 0.0)
        q = {
            "knowledge_points": ["集合与元素"],
            "answer_json": {
                "chunk_results": [{
                    "knowledge_points": ["常用逻辑用语"],
                    "steps": [{"knowledge_point": "集合与元素"}],
                }],
            },
        }
        self.assertIn("集合与元素", _question_kps(q))

    def test_match_mother_for_wrong_question(self):
        pattern = self.create_pattern()
        wrong_qid = self.seed_question(category=pattern["category"])
        result = match_mother_for_wrong_question(wrong_qid)
        self.assertIn("matches", result)
        self.assertTrue(result["matches"])

        missing = match_mother_for_wrong_question(9999)
        self.assertEqual(missing["error"], "not_found")

    def test_mark_pattern_wrong(self):
        pattern = self.create_pattern()
        result = mark_pattern_wrong(pattern["pattern_id"])
        self.assertEqual(result["state"], "again_wrong")
        with self.assertRaises(ValueError):
            mark_pattern_wrong(9999)

    def test_delete_question_links(self):
        pattern = self.create_pattern()
        pid = pattern["pattern_id"]
        qid2 = self.seed_question("变式")
        add_variant_question(pid, qid2, "variant1")
        delete_question_links(qid2)
        self.assertNotIn(qid2, get_pattern(pid)["variant_ids"])

    def test_mastery_summary(self):
        self.create_pattern()
        summary = get_mastery_summary()
        self.assertTrue(summary["categories"])
        self.assertIn("never", summary["pattern_states"])

    def test_sync_mother_questions(self):
        qid = self.seed_question()
        update_question_source(qid, "精选母题", {"category": "集合与逻辑用语", "pattern": "同步套路"})
        result = sync_mother_questions()
        self.assertEqual(result["synced"], 1)
        self.assertTrue(any(p["name"] == "同步套路" for p in pat_mod.get_patterns()))

    def test_get_pattern_loop_and_check_answer(self):
        pattern = self.create_pattern()
        pid = pattern["pattern_id"]
        loop = get_pattern_loop(pid)
        self.assertEqual(len(loop["questions"]), 4)
        self.assertEqual(loop["questions"][0]["answer"], "A")

        with patch("backend.teach.teach_check", return_value={"is_correct": True, "feedback": "对"}):
            result = check_pattern_answer(pid, pattern["mother_id"], "A")
        self.assertTrue(result["is_correct"])

        with patch("backend.patterns.get_pattern_loop", return_value={
            "questions": [{"question_id": 1, "answer": ""}],
        }):
            result = check_pattern_answer(pid, 1, "A")
        self.assertEqual(result["error"], "no_answer")

    def test_calendar_and_ics(self):
        pattern = self.create_pattern()
        pid = pattern["pattern_id"]
        set_pattern_schedule(pid, "2026-08-10 08:00:00", need_check=1)
        calendar = get_pattern_calendar()
        self.assertTrue(calendar["items"])

        schedule_pattern_review(pid, "2026-08-15")
        moved = next(it for it in get_pattern_calendar()["items"] if it["pattern_id"] == pid)
        self.assertEqual(moved["due_date"], "2026-08-15")
        unschedule_pattern_review(pid)
        self.assertNotIn(pid, [it["pattern_id"] for it in get_pattern_calendar()["items"]])
        with self.assertRaises(ValueError):
            schedule_pattern_review(9999, "2026-08-15")

        with patch("backend.patterns.get_pattern_calendar", return_value={
            "items": [{
                "pattern_id": pid,
                "due_date": "2026-08-10",
                "name": "套路",
                "category": "数列",
                "state": "never",
            }],
        }):
            ics = get_pattern_calendar_ics()
        self.assertIn("BEGIN:VCALENDAR", ics)
        self.assertIn("SUMMARY:巩固：套路", ics)

    def test_cn_time_helpers(self):
        self.assertIsNotNone(_cn_now().tzinfo)
        self.assertIsNotNone(_parse_cn_time("2026-08-10 08:00:00"))
        self.assertIsNone(_parse_cn_time("bad"))

    def test_record_attempt(self):
        pattern = self.create_pattern()
        aid = record_attempt(pattern["pattern_id"], pattern["mother_id"], "mother", True)
        self.assertIsInstance(aid, int)

    def test_ensure_variants(self):
        pattern = self.create_pattern()
        pid = pattern["pattern_id"]
        qid2 = self.seed_question("变式一")
        with patch("backend.generate.generate_variants", return_value={
            "candidates": [{"status": "accepted", "question_id": qid2}],
        }):
            result = ensure_variants(pid)
        self.assertEqual(result["generated"], 1)
        self.assertIn(qid2, result["variants"])

        pattern2 = self.create_pattern("数列", "无母题套路", question_text="判断数列 $a_n=n^2$ 的单调性。")
        conn = pat_mod._get_conn()
        conn.execute("DELETE FROM pattern_questions WHERE pattern_id = ?", (pattern2["pattern_id"],))
        conn.commit()
        conn.close()
        with self.assertRaises(ValueError):
            ensure_variants(pattern2["pattern_id"])

    def test_boards(self):
        pattern = self.create_pattern()
        boards = get_boards()
        board = next(b for b in boards if b["category"] == pattern["category"])
        saved = save_board_layout(board["id"], [{"question_id": pattern["mother_id"], "x": 1, "y": 2}], [])
        self.assertEqual(saved["nodes"][0]["question_id"], pattern["mother_id"])
        saved = save_board_layout(
            board["id"],
            [{"question_id": pattern["mother_id"], "x": 1, "y": 2}],
            [],
            [{"level_index": 1, "name": "入门关", "description": "$x^2+y^2=r^2$"}],
        )
        self.assertEqual(saved["levels"][0]["description"], "$x^2+y^2=r^2$")
        with self.assertRaises(ValueError):
            save_board_layout(9999, [], [])


class GeneratePipelineTest(unittest.TestCase):
    def _config_patch(self):
        return patch.object(gen_mod.runtime_settings, "get_teacher_config", return_value={
            "solver": {"model": "deepseek-v4-flash", "reasoning_effort": None},
        })

    def test_call_generation_success(self):
        content = json.dumps({"candidates": [{"question": "题1"}, {"question": "题2"}]}, ensure_ascii=False)
        reference = {
            "id": 1, "question": "题", "question_type": "大题", "category": "数列",
            "difficulty": {}, "steps": [], "student_errors": [],
        }
        with self._config_patch(), patch.object(gen_mod, "call_deepseek", return_value=(content, {})):
            result = _call_generation(reference, 2, "liangliang")
        self.assertEqual(len(result), 2)

    def test_call_generation_retry(self):
        good = json.dumps({"candidates": [{"question": "题"}]}, ensure_ascii=False)
        reference = {
            "id": 1, "question": "题", "question_type": "大题", "category": "数列",
            "difficulty": {}, "steps": [], "student_errors": [],
        }
        with self._config_patch(), patch.object(
            gen_mod, "call_deepseek",
            side_effect=[("bad", {}), (good, {})],
        ):
            result = _call_generation(reference, 1, "liangliang")
        self.assertEqual(len(result), 1)

    def test_is_duplicate(self):
        with patch.object(gen_mod, "find_question", return_value=None):
            self.assertFalse(_is_duplicate("新题"))
        with patch.object(gen_mod, "find_question", return_value={"id": 1}):
            self.assertTrue(_is_duplicate("旧题"))

    def test_solve_candidate_accepted(self):
        final = {
            "chunk_results": [{
                "steps": [{
                    "title": "t",
                    "standard_writing": "s",
                    "detailed_writing": "d",
                }],
            }],
            "token_usage": {"total_tokens": 1},
        }
        phases = []
        with patch.object(gen_mod, "_is_duplicate", return_value=False), \
             patch.object(gen_mod, "step_solver_only", return_value={
                 "content": "解", "category": "数列", "token_usage": {},
             }), \
             patch.object(gen_mod, "step_verify_all", return_value={
                 "chunk_results": [], "token_usage": {},
             }), \
             patch.object(gen_mod, "step_final_check", return_value=final):
            result = _solve_candidate({"question": "题"}, "liangliang", on_phase=phases.append)
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(phases, ["solver", "verifier", "formatter"])

    def test_solve_candidate_rejected_and_duplicate(self):
        with patch.object(gen_mod, "_is_duplicate", return_value=False), \
             patch.object(gen_mod, "step_solver_only", return_value={"error": "雪碧了", "detail": "不可解"}):
            result = _solve_candidate({"question": "题"}, "liangliang")
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["rejected_reason"], "不可解")

        with patch.object(gen_mod, "_is_duplicate", return_value=True):
            result = _solve_candidate({"question": "旧题"}, "liangliang")
        self.assertEqual(result["rejected_reason"], "题目已存在于题库")

    def test_save_accepted(self):
        final = {
            "chunk_results": [{"chunk_type": "选择题", "category": {"level1": "数列"}}],
            "final_answer": "A",
        }
        with patch.object(gen_mod, "save_question", return_value=9) as mock_save:
            qid = _save_accepted({"id": 1}, {"question": "题", "result": final})
        self.assertEqual(qid, 9)
        saved = mock_save.call_args[0][1]
        self.assertEqual(saved["source_type"], "ai生成")
        self.assertEqual(saved["source_meta"]["reference_id"], "1")

    def test_generate_variants(self):
        ref = {
            "id": 1,
            "difficulty": {"total_score": 5},
            "chunk_results": [{"steps": [{"title": "求通项"}]}],
            "question_type": "大题",
            "answer_json": {"knowledge_points": ["数列"]},
        }
        accepted = {
            "question": "新题",
            "status": "accepted",
            "result": {
                "overall_difficulty": {"total_score": 5},
                "chunk_results": [{"chunk_type": "大题", "steps": [{"title": "求通项"}]}],
                "knowledge_points": ["数列"],
            },
            "token_usage": {"total_tokens": 1},
        }
        rejected = {"question": "旧题", "status": "rejected", "rejected_reason": "重复", "token_usage": {}}
        with patch.object(gen_mod, "_load_reference", return_value=ref), \
             patch.object(gen_mod, "_call_generation", return_value=[
                 {"question": "新题"}, {"question": "旧题"}, {"question": "新题"},
             ]), \
             patch.object(gen_mod, "_solve_candidate", side_effect=[accepted, rejected]), \
             patch.object(gen_mod, "_save_accepted", return_value=9), \
             patch.object(gen_mod, "_fit_score", return_value=(90.0, {})), \
             patch.object(gen_mod.runtime_settings, "get_limits", return_value={"generate_concurrency": 2, "generate_count": 3}):
            result = generate_variants(1, count=2)
        self.assertEqual(result["accepted"], 1)
        self.assertEqual(result["rejected"], 1)
        self.assertEqual(result["candidates"][0]["fit_score"], 90.0)

    def test_start_and_get_generate_job(self):
        with patch.object(gen_mod, "get_question_by_id", return_value={"id": 1}), \
             patch.object(gen_mod, "generate_variants", return_value={"accepted": 0, "rejected": 0, "candidates": [], "token_usage": {}}):
            job = start_generate_job(1, count=1)
        job_id = job["job_id"]
        self.assertIn(job["status"], ("running", "done"))

        for _ in range(50):
            snap = get_generate_job(job_id)
            if snap and snap["status"] in ("done", "error"):
                break
            time.sleep(0.05)
        self.assertEqual(snap["status"], "done")
        self.assertEqual(snap["result"]["accepted"], 0)

        with patch.object(gen_mod, "get_question_by_id", return_value=None):
            with self.assertRaises(ValueError):
                start_generate_job(999)

        self.assertIsNone(get_generate_job("no-such-job"))


if __name__ == "__main__":
    unittest.main()
