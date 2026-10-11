"""Web packet validation is tested locally; no model or browser is used."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.data_paths import workspace
from backend.identity import identity_context
from backend import question_pool as pool, routine_classification as rc, routine_review as rr
from backend.routine_web_review import archive_response, export_packet, import_packet


OWNER = {"id": "studyadmin", "username": "studyadmin", "role": "owner"}
CONFIG = {"engine": "deepseek", "model": "fixture", "prompt_profile": rc.CACHE_PROMPT_VERSION}


def result(item):
    return {"primary_routine_id": "SET-014", "secondary_routine_ids": [],
            "candidate_routine_ids": [], "confidence": "high", "composite": False,
            "needs_review": False, "review_reasons": [], "method_summary": "分别判断元素选择",
            "evidence": [{"field": "question", "quote": item["question"]}],
            "representative_score": 80, "variant_features": [], "suggested_routine": None,
            "novelty_checks": []}


class RoutineWebReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {"STUDY_AGENT_DATA_DIR": "", "STUDY_DEMO_AI_CONFIG": ""}))
        self.stack.enter_context(workspace(self.tmp.name))
        self.stack.enter_context(identity_context(OWNER))
        self.catalog = rc.load_catalog()
        self.store = rr.ReviewStore(Path(self.tmp.name) / "review.sqlite3")
        pool.import_records({"name": "web test", "kind": "json", "revision": "1"},
                            [self.source(i) for i in range(1, 5)])
        self.run = self.store.create("web-test-run", self.catalog, CONFIG, pool.storage_path())

    @staticmethod
    def source(n):
        return {"source_key": str(n), "question": f"集合 A={{1,{n + 1}}} 的子集数是多少？",
                "solution": "两个元素分别选择取或不取。", "answer": "4",
                "categories": ["集合与逻辑用语"], "completeness": "complete", "year": 2025, "raw": {}}

    def export(self, limit=3):
        return export_packet(self.store, self.run["run_id"], limit=limit)

    def response(self, packet, entries=None, *, packet_id=True):
        entries = entries if entries is not None else [
            {"id": row["id"], "classification": result(row["item"])}
            for row in packet["metadata"]["items"]]
        body = {"results": entries}
        if packet_id:
            body["packet_id"] = packet["packet_id"]
        return body

    def test_export_freezes_and_reuses_open_packet(self):
        packet = self.export(3)
        again = self.export(1)
        self.assertEqual(packet["packet_id"], again["packet_id"])
        self.assertTrue(again["reused"])
        self.assertEqual(len(packet["metadata"]["items"]), 3)
        self.assertEqual(packet["metadata"]["config_digest"], rc.digest(CONFIG))
        self.assertIn('"packet_id":"' + packet["packet_id"] + '"', packet["prompt"])
        self.assertIn('"results"', packet["prompt"])
        self.assertIn("固定参考目录", packet["prompt"])

    def test_evidence_tampering_keeps_packet_open_for_retry(self):
        packet = self.export(3)
        bad = self.response(packet)
        bad["results"][-1]["classification"]["evidence"][0]["quote"] = "not present in source"
        raw = json.dumps(bad, ensure_ascii=False)
        archive_response(self.store, packet["packet_id"], raw)
        archive_response(self.store, packet["packet_id"], raw)
        with self.assertRaisesRegex(ValueError, f"原题 {bad['results'][-1]['id']}："):
            import_packet(self.store, packet["packet_id"], bad)
        with self.store.connection() as conn:
            self.assertEqual(conn.execute("SELECT response_text FROM review_web_responses").fetchall()[0][0], raw)
            self.assertEqual(conn.execute("SELECT count(*) FROM review_web_responses").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT count(*) FROM review_items WHERE status='classified'").fetchone()[0], 0)
        good = self.response(packet)
        self.assertEqual(import_packet(self.store, packet["packet_id"], good)["imported"], 3)

    def test_unknown_duplicate_and_missing_ids_are_rejected(self):
        for mutate in ("unknown", "duplicate", "missing"):
            packet = self.export(3)
            entries = self.response(packet)["results"]
            if mutate == "unknown":
                entries[-1]["id"] = 999
            elif mutate == "duplicate":
                entries[-1]["id"] = entries[0]["id"]
            else:
                entries.pop()
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                import_packet(self.store, packet["packet_id"], {"packet_id": packet["packet_id"], "results": entries})
            # Each failed attempt leaves the same packet open and retryable.
            if mutate != "missing":
                pass
            else:
                self.assertEqual(import_packet(self.store, packet["packet_id"], self.response(packet))["imported"], 3)

    def test_wrong_packet_id_is_rejected(self):
        packet = self.export(1)
        with self.assertRaises(ValueError):
            import_packet(self.store, packet["packet_id"], {"packet_id": "other", "results": self.response(packet)["results"]})

    def test_stale_open_packet_is_invalidated_and_reexported(self):
        old = self.export(2)
        with self.store.connection() as conn:
            conn.execute("UPDATE review_runs SET config_json=? WHERE run_id=?",
                         (rr.rc_json({**CONFIG, "model": "web changed"}), self.run["run_id"]))
            conn.commit()
        fresh = self.export(2)
        self.assertNotEqual(old["packet_id"], fresh["packet_id"])
        self.assertNotEqual(old["metadata"]["config_digest"], fresh["metadata"]["config_digest"])
        with self.store.connection() as conn:
            state = conn.execute("SELECT status FROM review_web_packets WHERE packet_id=?", (old["packet_id"],)).fetchone()[0]
        self.assertEqual(state, "invalidated")

    def test_stale_question_open_packet_is_invalidated_and_reexported(self):
        old = self.export(1)
        item_id = old["metadata"]["items"][0]["id"]
        updated = pool.update_item(item_id, {"question": "更新后的原题题干"})
        item = {key: updated[key] for key in ("id", "version", "question", "solution", "answer", "categories", "completeness")}
        with self.store.connection() as conn:
            conn.execute("UPDATE review_items SET item_json=?,content_hash=? WHERE run_id=? AND item_id=?",
                         (rr.rc_json(item), rc.digest(item), self.run["run_id"], item_id))
            conn.commit()
        fresh = self.export(1)
        self.assertNotEqual(old["packet_id"], fresh["packet_id"])
        self.assertEqual(fresh["metadata"]["items"][0]["content_hash"], rc.digest(item))

    def test_stale_catalog_open_packet_is_invalidated_and_reexported(self):
        old = self.export(1)
        updated_catalog = {**self.catalog, "version": "changed-catalog-version"}
        with self.store.connection() as conn:
            conn.execute("UPDATE review_runs SET catalog_json=? WHERE run_id=?",
                         (rr.rc_json(updated_catalog), self.run["run_id"]))
            conn.commit()
        fresh = self.export(1)
        self.assertNotEqual(old["packet_id"], fresh["packet_id"])
        self.assertNotEqual(old["metadata"]["run_catalog_hash"], fresh["metadata"]["run_catalog_hash"])

    def test_stale_snapshot_content_catalog_and_config_are_rejected(self):
        stale_modes = ("catalog", "config", "source")
        for mode in stale_modes:
            packet = self.export(1)
            with self.store.connection() as conn:
                if mode == "item":
                    row = conn.execute("SELECT item_json FROM review_items WHERE run_id=? AND item_id=?",
                                       (self.run["run_id"], packet["metadata"]["items"][0]["id"])).fetchone()
                    item = json.loads(row[0]); item["question"] += " 已修改"
                    conn.execute("UPDATE review_items SET item_json=? WHERE run_id=? AND item_id=?",
                                 (rr.rc_json(item), self.run["run_id"], item["id"]))
                elif mode == "catalog":
                    conn.execute("UPDATE review_runs SET catalog_json=? WHERE run_id=?",
                                 (rr.rc_json({**self.catalog, "version": "changed"}), self.run["run_id"]))
                elif mode == "config":
                    conn.execute("UPDATE review_runs SET config_json=? WHERE run_id=?",
                                 (rr.rc_json({**CONFIG, "model": "changed"}), self.run["run_id"]))
                conn.commit()
            if mode == "source":
                pool.update_item(packet["metadata"]["items"][0]["id"], {"question": "题库中的题目也已改变"})
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                import_packet(self.store, packet["packet_id"], self.response(packet))

    def test_duplicate_import_is_idempotent_and_counts_one_call(self):
        packet = self.export(2)
        reply = self.response(packet)
        before = self.store.run(self.run["run_id"])["calls"]
        first = import_packet(self.store, packet["packet_id"], reply)
        second = import_packet(self.store, packet["packet_id"], reply)
        self.assertEqual(first["imported"], 2)
        self.assertFalse(first["idempotent"])
        self.assertTrue(second["idempotent"])
        self.assertEqual(self.store.run(self.run["run_id"])["calls"], before + 1)
        self.assertEqual(self.store.item(self.run["run_id"], packet["metadata"]["items"][0]["id"])["result"]["source"], "chatgpt_web")
        with self.store.connection() as conn:
            saved_response = conn.execute("SELECT response_json FROM review_web_packets WHERE packet_id=?",
                                          (packet["packet_id"],)).fetchone()[0]
        self.assertEqual(json.loads(saved_response), reply)
        with self.assertRaises(ValueError):
            import_packet(self.store, packet["packet_id"], {**reply, "extra": "different response"})

    def test_import_refuses_a_running_batch(self):
        packet = self.export(1)
        with self.store.connection() as conn:
            conn.execute("UPDATE review_runs SET status='running' WHERE run_id=?", (self.run["run_id"],))
            conn.commit()
        with self.assertRaisesRegex(ValueError, "正在运行"):
            import_packet(self.store, packet["packet_id"], self.response(packet))

    def test_manual_decision_wins_and_other_executor_result_conflicts(self):
        manual_packet = self.export(1)
        item_id = manual_packet["metadata"]["items"][0]["id"]
        decision = {"primary_routine_id": "SET-015", "secondary_routine_ids": [],
                    "review_status": "confirmed", "marks": [], "note": "manual",
                    "item_version": 1, "content_hash": manual_packet["metadata"]["items"][0]["content_hash"]}
        with self.store.connection() as conn:
            conn.execute("UPDATE review_items SET status='classified',primary_id='SET-015',review_status='confirmed',human_json=? WHERE run_id=? AND item_id=?",
                         (rr.rc_json(decision), self.run["run_id"], item_id))
            conn.commit()
        import_packet(self.store, manual_packet["packet_id"], self.response(manual_packet))
        row = self.store.item(self.run["run_id"], item_id)
        self.assertEqual(row["primary_id"], "SET-015")
        self.assertEqual(row["human"]["note"], "manual")

        conflict_packet = self.export(1)
        other_id = conflict_packet["metadata"]["items"][0]["id"]
        with self.store.connection() as conn:
            conn.execute("UPDATE review_items SET status='classified',result_json=? WHERE run_id=? AND item_id=?",
                         (rr.rc_json({"source": "codex_luna"}), self.run["run_id"], other_id))
            conn.commit()
        with self.assertRaisesRegex(ValueError, "其他执行器"):
            import_packet(self.store, conflict_packet["packet_id"], self.response(conflict_packet))

    def test_missing_tokens_are_not_fabricated(self):
        packet = self.export(1)
        import_packet(self.store, packet["packet_id"], self.response(packet))
        with self.store.connection() as conn:
            usage = conn.execute("SELECT count(*) FROM review_usage WHERE run_id=?", (self.run["run_id"],)).fetchone()[0]
        self.assertEqual(usage, 0)


if __name__ == "__main__":
    unittest.main()
