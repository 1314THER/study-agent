"""database.py 全函数测试：纯函数 + 临时 SQLite 上的 CRUD。"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

import backend.database as dbmod
from backend.database import (
    _build_l3_to_l2_map,
    _build_steps_structure,
    _collect_step_knowledge_points,
    _ensure_multi_choice_marker,
    _infer_category_level2,
    _normalize_choice_question_text,
    _normalize_dimension_keys,
    _normalize_question,
    _plain_segments,
    _sanitize_category,
    _sanitize_difficulty,
    _sanitize_knowledge_points,
    add_practice_record,
    add_step_error,
    add_question_to_lists,
    ai_search_questions,
    create_question_list,
    delete_question,
    delete_question_list,
    delete_step_error,
    find_question,
    find_question_id,
    get_all_questions,
    get_list_questions,
    get_question_by_id,
    get_question_list_ids,
    get_question_lists,
    get_questions_with_errors,
    get_step_errors,
    get_wrong_questions,
    init_db,
    looks_like_choice_question,
    looks_like_multi_choice_question,
    remove_question_from_list,
    rename_question_list,
    replace_step_errors,
    restore_question_to_list,
    save_question,
    search_questions,
    update_question_source,
    update_question_source_type,
    update_question_time,
)


def _answer(category="集合与逻辑用语", with_steps=True, kps=None, chunk_type="选择题", steps=None):
    kps = kps or ["集合与元素"]
    steps = steps if steps is not None else [{
        "step_number": 1,
        "title": "判断",
        "standard_writing": "逐项判断",
        "detailed_writing": "逐项判断并排除",
        "knowledge_point": "集合与元素",
        "step_difficulty": {"level": "容易", "score": 1, "dimensions": {}},
    }]
    cr = {
        "chunk_id": 1,
        "chunk_type": chunk_type,
        "category": {"level1": category, "level2": ""},
        "final_answer": "A",
        "knowledge_points": kps,
        "steps": steps if with_steps else [],
    }
    return {
        "category": {"level1": category, "level2": ""},
        "chunk_results": [cr],
        "final_answer": "A",
        "knowledge_points": kps,
        "overall_difficulty": {"level": "容易", "score": 1, "dimensions": {}},
    }


class PureHelperTest(unittest.TestCase):
    def test_plain_segments(self):
        self.assertEqual(_plain_segments("前 $x$ 后"), ["前 ", "$x$", " 后"])
        self.assertEqual(_plain_segments("$$x$$"), ["$$x$$"])
        self.assertEqual(_plain_segments("无公式"), ["无公式"])

    def test_choice_detection(self):
        self.assertTrue(looks_like_choice_question("A. 1\nB. 2\nC. 3\nD. 4"))
        self.assertFalse(looks_like_choice_question("只有一个 A. 选项"))
        self.assertFalse(looks_like_choice_question(""))

    def test_multi_choice_detection(self):
        self.assertTrue(looks_like_multi_choice_question("（多选）题干", {}))
        self.assertTrue(looks_like_multi_choice_question("", {"final_answer": "选 AB"}))
        self.assertFalse(looks_like_multi_choice_question("题干", {"final_answer": "选 A"}))

    def test_normalize_choice_text(self):
        text = "A. 甲\nB. 乙\nC. 丙\nD. 丁"
        self.assertEqual(_normalize_choice_question_text(text), text)
        self.assertEqual(_normalize_choice_question_text(""), "")

    def test_ensure_multi_choice_marker(self):
        self.assertEqual(_ensure_multi_choice_marker("题干"), "（多选）题干")
        self.assertEqual(_ensure_multi_choice_marker("（多选）题干"), "（多选）题干")
        self.assertEqual(_ensure_multi_choice_marker(""), "")

    def test_collect_step_knowledge_points(self):
        crs = [{"steps": [{"knowledge_point": "集合与元素、集合与元素"}]}]
        self.assertEqual(_collect_step_knowledge_points(crs), ["集合与元素"])
        self.assertEqual(_collect_step_knowledge_points("bad"), [])

    def test_build_steps_structure(self):
        crs = [{
            "chunk_id": 1,
            "steps": [{"step_number": 1, "title": "判断", "step_difficulty": {"score": 2}}],
        }]
        data = json.loads(_build_steps_structure(crs))
        self.assertEqual(data[0]["difficulty_score"], 2)
        self.assertEqual(_build_steps_structure([]), "[]")

    def test_normalize_question(self):
        self.assertEqual(_normalize_question("a  b\n c"), "abc")

    def test_sanitize_category(self):
        self.assertEqual(_sanitize_category({"level1": "集合与逻辑用语", "level2": "集合与元素"}), ("集合与逻辑用语", "集合与元素"))
        self.assertEqual(_sanitize_category({"level1": "不存在的板块"}), (None, None))
        self.assertEqual(_sanitize_category(None), (None, None))

    def test_sanitize_difficulty(self):
        level, score, dims = _sanitize_difficulty({"level": "中等", "total_score": 3, "dimensions": {}})
        self.assertEqual(level, "中等")
        self.assertEqual(score, 3)
        self.assertEqual(json.loads(dims), {})

    def test_normalize_dimension_keys(self):
        self.assertEqual(_normalize_dimension_keys({}), {})

    def test_build_l3_to_l2_map(self):
        mapping = _build_l3_to_l2_map()
        self.assertIsInstance(mapping, dict)
        self.assertTrue(mapping)

    def test_sanitize_knowledge_points(self):
        self.assertEqual(_sanitize_knowledge_points("集合与逻辑用语", ["集合与元素"]), ["集合与元素"])
        self.assertEqual(_sanitize_knowledge_points("集合与逻辑用语", []), [])

    def test_infer_category_level2(self):
        self.assertEqual(_infer_category_level2("集合与逻辑用语", ["集合与元素", "集合间的基本关系"]), "集合与元素")
        self.assertEqual(_infer_category_level2("集合与逻辑用语", ["不存在的知识点"]), None)
        self.assertEqual(_infer_category_level2("", ["集合与元素"]), None)


class TempDbCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, "test.db")
        patcher = patch.object(dbmod, "DB_PATH", self.db_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        init_db()

    def seed(self, text="设集合 $A=\\{1,2\\}$，则子集个数是？", category="集合与逻辑用语", kps=None, chunk_type="选择题", steps=None):
        return save_question(text, _answer(category, kps=kps, chunk_type=chunk_type, steps=steps))


class CrudTest(TempDbCase):
    def test_save_get_list_search_delete(self):
        qid = self.seed()
        self.assertIsNotNone(qid)

        row = get_question_by_id(qid)
        self.assertEqual(row["category_level1"], "集合与逻辑用语")
        self.assertEqual(len(get_all_questions()), 1)
        self.assertEqual(len(search_questions(categories=["集合与逻辑用语"], limit=5)), 1)
        self.assertTrue(delete_question(qid))
        self.assertFalse(delete_question(qid))
        self.assertIsNone(get_question_by_id(qid))

    def test_save_backfills_category_level2(self):
        qid = self.seed(kps=["集合与元素"])
        row = dbmod.get_connection().execute(
            "SELECT category_level2, answer_json FROM questions WHERE id = ?", (qid,)
        ).fetchone()
        self.assertEqual(row["category_level2"], "集合与元素")
        aj = json.loads(row["answer_json"])
        self.assertEqual(aj["category"]["level2"], "集合与元素")

    def test_save_question_keeps_pattern_difficulty(self):
        aj = _answer(category="数列", chunk_type="大题", kps=["等差数列"])
        cr = aj["chunk_results"][0]
        cr["steps"] = [{
            "step_number": 1, "title": "判等差", "standard_writing": "d恒定",
            "detailed_writing": "d恒定", "knowledge_point": "等差数列",
            "step_difficulty": {"dimensions": {
                "计算量": 1, "非常规程度": 0, "分类讨论": 0, "知识广度": 0, "条件转化难度": 0,
            }},
        }]
        cr["difficulty"] = {"pattern_id": 7, "pattern_difficulty": 3}
        qid = save_question("某等差题", aj)
        row = get_question_by_id(qid)
        od = row["answer_json"]["overall_difficulty"]
        self.assertEqual(od["pattern_difficulty"], 3)
        self.assertEqual(od["pattern_id"], 7)
        self.assertEqual(od["level"], "极难")  # 套路难度 3 主导综合等级
        self.assertEqual(row["difficulty_level"], "极难")

    def test_search_knowledge_points_all_required(self):
        self.seed("只有集合元素", kps=["集合与元素"])
        both_id = self.seed("集合元素加基本关系", kps=["集合与元素", "集合间的基本关系"])

        single = search_questions(knowledge_points=["集合与元素"])
        self.assertEqual(len(single), 2)

        both = search_questions(knowledge_points=["集合与元素", "集合间的基本关系"])
        self.assertEqual([q["id"] for q in both], [both_id])

        result = get_list_questions(
            create_question_list("测试清单"),
            knowledge_points=["集合与元素", "集合间的基本关系"],
        )
        self.assertEqual(result["total"], 0)

    def test_search_steps_all_required(self):
        step_one = {
            "step_number": 1,
            "title": "证明线线平行关系",
            "step_level1": "中位线",
            "standard_writing": "取中点",
            "detailed_writing": "取中点后证明",
            "knowledge_point": "立体几何",
            "step_difficulty": {"level": "容易", "score": 1, "dimensions": {}},
        }
        step_two = {
            "step_number": 2,
            "title": "求平面的法向量",
            "step_level1": "求平面法向量的标准过程",
            "standard_writing": "设向量",
            "detailed_writing": "设向量后解方程",
            "knowledge_point": "立体几何",
            "step_difficulty": {"level": "容易", "score": 1, "dimensions": {}},
        }
        one_id = self.seed(
            "立体几何只有中位线",
            category="立体几何",
            kps=["空间向量与立体几何"],
            chunk_type="大题",
            steps=[step_one],
        )
        two_id = self.seed(
            "立体几何中位线加法向量",
            category="立体几何",
            kps=["空间向量与立体几何"],
            chunk_type="大题",
            steps=[step_one, step_two],
        )

        l1_result = search_questions(step_level1s=["证明线线平行关系"])
        self.assertEqual({q["id"] for q in l1_result}, {one_id, two_id})

        l1_both = search_questions(step_level1s=["证明线线平行关系", "求平面的法向量"])
        self.assertEqual([q["id"] for q in l1_both], [two_id])

        l2_both = search_questions(step_level2s=["中位线", "求平面法向量的标准过程"])
        self.assertEqual([q["id"] for q in l2_both], [two_id])

    def test_find_question_exact_and_normalized(self):
        qid = self.seed()
        row = get_question_by_id(qid)
        found = find_question(row["content"])
        self.assertIsNotNone(found)
        self.assertEqual(find_question_id(row["content"]), qid)
        self.assertEqual(find_question_id(row["content"].replace(" ", "")), qid)

    def test_update_question_time(self):
        qid = self.seed()
        update_question_time(qid, "last_viewed_at")
        row = get_question_by_id(qid)
        self.assertIsNotNone(row["last_viewed_at"])
        with self.assertRaises(ValueError):
            update_question_time(qid, "bad_field")

    def test_step_error_lifecycle(self):
        qid = self.seed()
        eid = add_step_error(qid, 1, 1, "计算错误", "符号错", "x=1")
        self.assertIsNotNone(eid)
        self.assertEqual(len(get_step_errors(qid)), 1)
        self.assertEqual(len(get_questions_with_errors()), 1)
        self.assertTrue(delete_step_error(eid, qid))
        self.assertEqual(len(get_step_errors(qid)), 0)

        add_step_error(qid, 1, 1, "计算错误", "符号错", "x=1")
        replaced = replace_step_errors(qid, [{"step_number": 1, "chunk_id": 1, "mistake_type": "思路错误"}])
        self.assertEqual(replaced, 1)
        self.assertEqual(len(get_step_errors(qid)), 1)

    def test_practice_record(self):
        qid = self.seed()
        rid = add_practice_record(qid, True, duration_seconds=60, source_type="首次")
        self.assertIsNotNone(rid)

    def test_question_lists_flow(self):
        qid = self.seed()
        lid = create_question_list("清单")
        self.assertNotIn(lid, get_question_list_ids(qid))

        result = add_question_to_lists(qid, [lid])
        self.assertEqual(result["added"], 1)
        self.assertIn(lid, get_question_list_ids(qid))
        self.assertEqual(get_list_questions(lid)["total"], 1)

        self.assertTrue(rename_question_list(lid, "新清单"))
        self.assertTrue(remove_question_from_list(qid, lid))
        self.assertEqual(get_list_questions(lid)["total"], 0)
        self.assertTrue(restore_question_to_list(qid, lid))
        self.assertEqual(get_list_questions(lid)["total"], 1)
        self.assertTrue(remove_question_from_list(qid, lid))
        self.assertTrue(delete_question_list(lid))

    def test_system_list_protection(self):
        lists = get_question_lists()
        system = next(l for l in lists if l["list_type"] == "system")
        self.assertFalse(delete_question_list(system["id"]))

    def test_wrong_questions(self):
        qid = self.seed()
        add_step_error(qid, 1, 1, "计算错误", "", "")
        result = get_wrong_questions()
        self.assertEqual(result["total"], 1)
        self.assertEqual(len(result["data"]), 1)

    def test_source_type_update(self):
        qid = self.seed()
        self.assertTrue(update_question_source_type(qid, "高考题"))
        self.assertTrue(update_question_source(qid, "高考题", {"paper": "卷"}))
        row = get_question_by_id(qid)
        self.assertEqual(row["source_type"], "高考题")

    def test_ai_search_placeholder(self):
        result = ai_search_questions("导数", 5)
        self.assertEqual(result["results"], [])
        self.assertEqual(result["total"], 0)


if __name__ == "__main__":
    unittest.main()
