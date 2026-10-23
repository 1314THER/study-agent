"""Reusable matching/API/review contracts, entirely on simulated questions."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import routine_classification as rc
from backend import routine_matching as rm
from backend import routine_matching_api as api
from backend.data_paths import workspace
from backend.identity import identity_context
from scripts.review_routine_candidates import main as review_main
from tests.test_routine_classification import CONFIG, result


def novel(item):
    return result(item, rid=None, confidence="medium", suggested_routine={
        "name": "递推求通项：按矩阵特征分解迭代", "category": "数列",
        "signals": ["二元耦合线性递推，目标是同时求两列通项"],
        "retrieval_terms": ["耦合递推", "特征分解", "矩阵"],
        "key_steps": ["写成矩阵迭代", "求特征分解", "还原初值与通项"],
        "exclusions": ["能直接通过已有一阶递推构造辅助数列时优先使用已有套路"],
        "confusable_ids": ["SEQ-022"], "aliases": []},
        novelty_checks=[{"routine_id": "SEQ-022", "reason": "本草案采用矩阵特征分解，原目录采用特征根构造辅助数列；需人工判断是否确有方法差异"}])


class RoutineMatchingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = rc.load_catalog()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.item = rm.question_record("设两个数列满足耦合线性递推，求两列通项。", id=901,
                                      solution="写成矩阵迭代，进行特征分解并还原初值。", categories=["数列"], completeness="complete")
        self.store = rm.RoutineMatchingStore(self.directory / "store")

    def fake_novel(self, system, user, item):
        return novel(item)

    def entry(self):
        matched = rm.match_question(self.item, self.catalog, self.fake_novel)
        return rm.build_review_entry({"status": "classified", "item": self.item, **matched}, self.catalog)

    def decision(self, **changes):
        value = {"action": "create", "confirmed": True, "expected_catalog_hash": rc.digest(self.catalog),
                 "note": "模拟人工审核：确认方法边界及相近套路，保留为目录扩展"}
        value.update(changes)
        return value

    def client(self):
        app = FastAPI()
        app.include_router(api.router)
        app.dependency_overrides[api.get_store] = lambda: self.store
        return TestClient(app)

    def test_retrieval_miss_gets_full_catalog_audit_before_novelty(self):
        calls = []
        def fake(system, user, item):
            payload = json.loads(user)
            calls.append(payload)
            if payload["stage"] == "retrieved_match":
                return result(item, rid=None)
            self.assertIn("SEQ-022", {r["id"] for r in payload["catalog"]})
            self.assertTrue(all("key_steps" in r and "exclusions" in r for r in payload["catalog"]))
            return result(item, rid="SEQ-022")
        with patch.object(rc, "shortlist", return_value=[self.catalog["routines"][0]]):
            matched = rm.match_question(self.item, self.catalog, fake)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(calls[1]["catalog"]), len(self.catalog["routines"]))
        self.assertEqual(matched["classification"]["primary_routine_id"], "SEQ-022")
        self.assertTrue(matched["catalog_audited"])
        self.assertIsNone(rm.build_review_entry({"status": "classified", "item": self.item, **matched}, self.catalog))

    def test_high_confidence_match_does_not_pay_for_second_pass(self):
        matched = rm.match_question(self.item, self.catalog, lambda s,u,i: result(i, rid="SEQ-022"))
        self.assertEqual(matched["api_attempts"], 1)
        self.assertFalse(matched["catalog_audited"])

    def test_retriever_can_be_replaced_without_changing_rules_or_audit_contract(self):
        routine = next(r for r in self.catalog["routines"] if r["id"] == "SEQ-022")
        def custom_retriever(item, catalog):
            return [{**routine, "key_steps": ["检索器不能篡改这条规则"]}]
        def fake(system, user, item):
            choices = json.loads(user)["catalog"]
            self.assertEqual(len(choices), 1)
            self.assertEqual(choices[0]["key_steps"], routine["key_steps"])
            return result(item, rid="SEQ-022")
        matched = rm.match_question(self.item, self.catalog, fake, retriever=custom_retriever)
        self.assertEqual(matched["retrieved_ids"], ["SEQ-022"])
        with self.assertRaises(ValueError):
            rm.match_question(self.item, self.catalog, fake, retriever=lambda i,c: [{"id": "BAD-001"}])

    def test_novelty_has_complete_draft_evidence_and_nearest_comparisons(self):
        entry = self.entry()
        self.assertEqual(entry["kind"], "new_routine_candidate")
        self.assertTrue(entry["catalog_audited"])
        self.assertTrue(entry["classification"]["evidence"])
        self.assertTrue(entry["novelty_checks"])
        self.assertEqual(entry["status"], "pending")

    def test_repeated_matching_and_cache_restore_keep_one_stable_review(self):
        output = self.directory / "reports"
        rows, _ = rc.classify_items([self.item], self.catalog, output, CONFIG, self.fake_novel)
        first = rm.build_review_entry(rows[0], self.catalog)
        restored, _ = rc.classify_items([self.item], self.catalog, output, CONFIG, None)
        second = rm.build_review_entry(restored[0], self.catalog)
        self.assertEqual(first["review_id"], second["review_id"])
        self.assertEqual(first["classification"], second["classification"])
        second["classification"]["method_summary"] = "同题另一次模型措辞"
        self.store.enqueue(first)
        self.store.enqueue(second)
        self.assertEqual(len(self.store.read()["reviews"]), 1)

    def test_missing_information_never_claims_novelty(self):
        for item in (dict(self.item, solution=""), dict(self.item, completeness="deferred_graphic")):
            matched = rm.match_question(item, self.catalog, self.fake_novel)
            self.assertEqual(matched["api_attempts"], 1)
            entry = rm.build_review_entry({"status": "classified", "item": item, **matched}, self.catalog)
            self.assertEqual(entry["kind"], "insufficient_content")
            with self.assertRaises(ValueError):
                rm.apply_review_decision(self.catalog, entry, self.decision())

    def test_composite_or_unsubstantiated_draft_stays_ambiguous(self):
        for changes in ({"composite": True}, {"evidence": []}, {"novelty_checks": []},
                        {"suggested_routine": {"name": "草案", "category": "数列", "key_steps": ["待核对"]}}):
            matched = rm.match_question(self.item, self.catalog, lambda s,u,i: {**novel(i), **changes})
            entry = rm.build_review_entry({"status": "classified", "item": self.item, **matched}, self.catalog)
            self.assertEqual(entry["kind"], "ambiguous_match")
            with self.assertRaises(ValueError):
                rm.apply_review_decision(self.catalog, entry, self.decision())

    def test_invalid_novelty_comparisons_rejected(self):
        for checks in ([{"routine_id": "FAKE-001", "reason": "不同"}],
                       [{"routine_id": "SEQ-022", "reason": ""}],
                       [{"routine_id": "SEQ-022", "reason": "不同"}] * 2):
            with self.assertRaises(ValueError):
                rc.normalize_result({**novel(self.item), "novelty_checks": checks}, self.item, self.catalog)

    def test_interrupt_during_audit_resumes_only_audit_from_checkpoint(self):
        stages = []
        def interrupted(system, user, item):
            stage = json.loads(user)["stage"]
            stages.append(stage)
            if stage == "full_catalog_audit":
                raise KeyboardInterrupt()
            return novel(item)
        rows, manifest = rc.classify_items([self.item], self.catalog, self.directory / "reports", CONFIG, interrupted)
        self.assertTrue(manifest["interrupted"])
        self.assertEqual(rows[0]["status"], "matching")
        resumed = []
        def fake(system, user, item):
            resumed.append(json.loads(user)["stage"])
            return novel(item)
        rows, manifest = rc.classify_items([self.item], self.catalog, self.directory / "reports", CONFIG, fake)
        self.assertEqual(resumed, ["full_catalog_audit"])
        self.assertEqual(rows[0]["status"], "classified")
        self.assertEqual(manifest["api_attempts"], 1)

    def test_failed_audit_retries_independently_and_is_not_novel(self):
        def fake(system, user, item):
            if json.loads(user)["stage"] == "full_catalog_audit":
                raise TimeoutError("PRIVATE KEY")
            return novel(item)
        output = self.directory / "reports"
        rows, manifest = rc.classify_items([self.item], self.catalog, output, CONFIG, fake)
        self.assertEqual(manifest["api_attempts"], 3)
        self.assertEqual(rows[0]["status"], "error")
        self.assertEqual(rm.build_review_entry(rows[0], self.catalog)["kind"], "matching_incomplete")
        calls = []
        def resumed(system, user, item):
            calls.append(json.loads(user)["stage"])
            return novel(item)
        rc.classify_items([self.item], self.catalog, output, CONFIG, resumed)
        self.assertEqual(calls, [])
        rows, manifest = rc.classify_items([self.item], self.catalog, output, CONFIG, resumed, retry_failed=True)
        self.assertEqual(calls, ["full_catalog_audit"])
        self.assertEqual(rows[0]["status"], "classified")
        self.assertNotIn("PRIVATE KEY", "".join(p.read_text() for p in output.rglob("*.json")))

    def test_bad_audit_response_retries_that_stage_only(self):
        calls = []
        def fake(system, user, item):
            stage = json.loads(user)["stage"]
            calls.append(stage)
            return "broken" if len(calls) == 2 else novel(item)
        matched = rm.match_question(self.item, self.catalog, fake)
        self.assertEqual(calls, ["retrieved_match", "full_catalog_audit", "full_catalog_audit"])
        self.assertTrue(matched["catalog_audited"])

    def test_create_extends_catalog_without_changing_baseline(self):
        baseline = rc.DEFAULT_CATALOG.read_bytes()
        entry = self.entry()
        self.store.enqueue(entry)
        record = self.store.decide(entry["review_id"], self.decision())
        state = self.store.read()
        self.assertEqual(record["routine_id"], f"SEQ-{rc.CATEGORY_COUNTS['数列']+1:03d}")
        self.assertEqual(len(state["catalog"]["routines"]), len(self.catalog["routines"])+1)
        self.assertEqual(state["reviews"][entry["review_id"]]["status"], "create")
        self.assertEqual(state["decisions"][entry["review_id"]]["override"]["content_hash"], rc.digest(self.item))
        self.assertEqual(baseline, rc.DEFAULT_CATALOG.read_bytes())
        self.assertEqual(record, self.store.decide(entry["review_id"], self.decision()))

    def test_confirmation_and_catalog_content_conflicts_never_write(self):
        entry = self.entry()
        self.store.enqueue(entry)
        before = self.store.path.read_bytes()
        for decision in (self.decision(confirmed=False), self.decision(expected_catalog_hash="a" * 64),
                         self.decision(note=" "), self.decision(action="use_existing", routine_id="FAKE-001")):
            with self.assertRaises(ValueError):
                self.store.decide(entry["review_id"], decision)
        self.assertEqual(before, self.store.path.read_bytes())
        changed = deepcopy(entry)
        changed["item"]["version"] = 2
        with self.assertRaises(ValueError):
            rm.apply_review_decision(self.catalog, changed, self.decision())

    def test_human_can_use_existing_or_defer_reject_without_new_routine(self):
        for action in ("use_existing", "defer", "reject"):
            updated, record, override = rm.apply_review_decision(self.catalog, self.entry(),
                self.decision(action=action, routine_id="SEQ-022"))
            self.assertEqual(rc.digest(updated), rc.digest(self.catalog))
            self.assertEqual(override["primary_routine_id"], "SEQ-022" if action == "use_existing" else None)

    def test_deferred_review_remains_visible_and_can_be_confirmed_later(self):
        entry = self.entry()
        self.store.enqueue(entry)
        self.store.decide(entry["review_id"], self.decision(action="defer"))
        with self.client() as client, patch.object(api, "get_ai_caller", side_effect=AssertionError("暂缓后不重复调用 AI")):
            self.assertEqual(client.get("/routine-matching/reviews").json()["total"], 1)
            response = client.post("/routine-matching/match", json=self.item)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["review"]["review_id"], entry["review_id"])
        record = self.store.decide(entry["review_id"], self.decision())
        self.assertEqual(record["routine_id"], f"SEQ-{rc.CATEGORY_COUNTS['数列']+1:03d}")
        self.assertEqual([d["action"] for d in self.store.read()["history"]], ["defer", "create"])

    def test_human_can_edit_draft_and_matching_uses_the_extended_catalog(self):
        entry = self.entry()
        draft = deepcopy(entry["draft"])
        draft["name"] = "耦合递推求通项：矩阵分解并核对初值"
        updated, _, _ = rm.apply_review_decision(self.catalog, entry, self.decision(draft=draft))
        def fake(system, user, item):
            self.assertIn(f"SEQ-{rc.CATEGORY_COUNTS['数列']+1:03d}", {r["id"] for r in json.loads(user)["catalog"]})
            return result(item, rid=f"SEQ-{rc.CATEGORY_COUNTS['数列']+1:03d}")
        matched = rm.match_question(dict(self.item, id=999), updated, fake)
        self.assertEqual(matched["classification"]["primary_routine_id"], f"SEQ-{rc.CATEGORY_COUNTS['数列']+1:03d}")

    def test_duplicate_draft_and_old_catalog_cannot_be_created(self):
        entry = self.entry()
        draft = deepcopy(entry["draft"])
        draft["name"] = " " + self.catalog["routines"][0]["name"] + " "
        with self.assertRaises(ValueError):
            rm.apply_review_decision(self.catalog, entry, self.decision(draft=draft))
        updated, _, _ = rm.apply_review_decision(self.catalog, entry, self.decision())
        with self.assertRaises(ValueError):
            rm.apply_review_decision(updated, entry, self.decision(expected_catalog_hash=rc.digest(updated)))

    def test_concurrent_confirmation_allocates_once_and_rejects_other_decision(self):
        entry = self.entry()
        self.store.enqueue(entry)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: self.store.decide(entry["review_id"], self.decision()), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(len(self.store.read()["catalog"]["routines"]), len(self.catalog["routines"])+1)
        with self.assertRaises(ValueError):
            self.store.decide(entry["review_id"], self.decision(action="reject"))

    def test_extended_catalog_may_grow_past_300(self):
        catalog = deepcopy(self.catalog)
        for i in range(rc.CATEGORY_COUNTS["数列"]+1, rc.CATEGORY_COUNTS["数列"]+16):
            draft = deepcopy(novel(self.item)["suggested_routine"])
            draft.update(id=f"SEQ-{i:03d}", name=draft["name"] + str(i))
            catalog["routines"].append(draft)
        self.assertEqual(len(rc.validate_catalog(catalog)["routines"]), len(self.catalog["routines"])+15)

    def test_unmatched_report_separates_novelty_information_and_ambiguity(self):
        items = [self.item, dict(self.item, id=902, solution=""), dict(self.item, id=903)]
        def fake(system, user, item):
            return {**novel(item), "composite": item["id"] == 903}
        rows, manifest = rc.classify_items(items, self.catalog, self.directory / "reports", CONFIG, fake)
        rc.write_reports(self.directory / "reports", rows, self.catalog, manifest)
        queue = rc.read_json(self.directory / "reports" / "unmatched.json")
        self.assertEqual([e["kind"] for e in queue["entries"]],
                         ["new_routine_candidate", "insufficient_content", "ambiguous_match"])
        self.assertTrue((self.directory / "reports" / "unmatched.md").exists())

    def test_offline_human_preview_then_apply_retains_other_overrides(self):
        entry = self.entry()
        queue = self.directory / "unmatched.json"
        decision = self.directory / "human.json"
        previous = self.directory / "previous.json"
        rc.write_json(queue, {"schema_version": 1, "catalog_hash": rc.digest(self.catalog), "entries": [entry]})
        rc.write_json(decision, {"review_id": entry["review_id"], **self.decision()})
        rc.write_json(previous, [{"id": 123, "version": 1, "content_hash": "f" * 64, "primary_routine_id": "SET-001"}])
        output = self.directory / "approved"
        args = ["--queue", str(queue), "--decision", str(decision), "--overrides", str(previous), "--output", str(output)]
        with patch("sqlite3.connect", side_effect=AssertionError("禁止数据库")), patch.object(rc, "urlopen", side_effect=AssertionError("禁止网络")), redirect_stdout(io.StringIO()):
            self.assertEqual(review_main(args), 0)
            self.assertFalse(output.exists())
            self.assertEqual(review_main(args + ["--apply"]), 0)
        catalog = rc.load_catalog(output / "catalog.json")
        overrides = rc.load_overrides(output / "overrides.json", catalog)
        self.assertEqual(set(overrides), {123, 901})
        self.assertEqual(overrides[901]["primary_routine_id"], f"SEQ-{rc.CATEGORY_COUNTS['数列']+1:03d}")
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            review_main(args + ["--apply"])

    def test_api_retrieve_catalog_and_validation_no_ai_no_writes(self):
        with self.client() as client, patch("sqlite3.connect", side_effect=AssertionError("禁止数据库")), patch.object(api, "get_ai_caller", side_effect=AssertionError("禁止AI")):
            self.assertEqual(client.get("/routine-matching/catalog").status_code, 200)
            response = client.post("/routine-matching/retrieve", json=self.item)
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json()["ai_called"])
            for item in (dict(self.item, question=" "), dict(self.item, id=True), dict(self.item, categories=["BAD"]), dict(self.item, database_path="study_agent.db")):
                self.assertEqual(client.post("/routine-matching/retrieve", json=item).status_code, 422)
        self.assertFalse(self.store.directory.exists())

    def test_api_novel_match_review_confirm_and_reuse_across_features(self):
        with self.client() as client, patch("sqlite3.connect", side_effect=AssertionError("禁止题库连接")), patch.object(api, "get_ai_caller", return_value=self.fake_novel):
            response = client.post("/routine-matching/match", json=self.item)
            self.assertEqual(response.status_code, 200, response.text)
            matched = response.json()
            self.assertEqual(matched["api_attempts"], 2)
            review_id = matched["review"]["review_id"]
            self.assertTrue(matched["review_saved"])
            self.assertEqual(client.get("/routine-matching/reviews").json()["total"], 1)
            confirmed = client.post(f"/routine-matching/reviews/{review_id}/decision", json=self.decision())
            self.assertEqual(confirmed.status_code, 200, confirmed.text)
            self.assertFalse(confirmed.json()["formal_pattern_created"])
            self.assertEqual(client.get("/routine-matching/reviews").json()["total"], 0)
            self.assertEqual(len(client.get("/routine-matching/catalog").json()["catalog"]["routines"]), len(self.catalog["routines"])+1)
            with patch.object(api, "get_ai_caller", side_effect=AssertionError("人工确认后无需 AI")):
                again = client.post("/routine-matching/match", json=self.item)
            self.assertEqual(again.status_code, 200, again.text)
            self.assertTrue(again.json()["human_decision_applied"])
            self.assertEqual(again.json()["classification"]["primary_routine_id"], f"SEQ-{rc.CATEGORY_COUNTS['数列']+1:03d}")

    def test_api_pure_match_without_queue_writes_and_sanitized_failure(self):
        with self.client() as client, patch.object(api, "get_ai_caller", return_value=self.fake_novel):
            response = client.post("/routine-matching/match", json=dict(self.item, save_review=False))
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json()["review_saved"])
            self.assertFalse(self.store.directory.exists())
        def fail(*args):
            raise TimeoutError("SECRET")
        with self.client() as client, patch.object(api, "get_ai_caller", return_value=fail):
            response = client.post("/routine-matching/match", json=self.item)
            self.assertEqual(response.status_code, 502)
            self.assertNotIn("SECRET", response.text)

    def test_api_guest_cannot_create_and_approval_conflicts_are_409(self):
        entry = self.entry()
        self.store.enqueue(entry)
        before = self.store.path.read_bytes()
        with self.client() as client:
            with identity_context({"id": "other", "username": "other", "role": "user"}):
                response = client.post(f"/routine-matching/reviews/{entry['review_id']}/decision", json=self.decision())
            self.assertEqual(response.status_code, 403)
            response = client.post(f"/routine-matching/reviews/{entry['review_id']}/decision", json=self.decision(confirmed=False))
            self.assertEqual(response.status_code, 409)
            response = client.post("/routine-matching/reviews/missing/decision", json=self.decision())
            self.assertEqual(response.status_code, 404)
        self.assertEqual(before, self.store.path.read_bytes())

    def test_api_adapter_uses_system_configuration_and_provider_budget(self):
        from backend import settings
        from backend import jobs
        with patch("sqlite3.connect", side_effect=AssertionError("禁止数据库")), \
             patch.object(settings, "get_api", return_value={"deepseek": {"base_url": "https://api.example.test/v1"}}), \
             patch.object(settings, "get_limits", return_value={"api_max_tokens": 2048, "api_timeout_seconds": 60}), \
             patch.object(settings, "get_teacher_config", return_value={"solver": {"model": "chosen-model"}}), \
             patch.object(settings, "get_api_key", return_value="MOCK-ACCOUNT-KEY"), \
             patch.object(jobs, "provider_slot") as slot, \
             patch.object(jobs, "request_timeout", return_value=42) as timeout, \
             patch.object(rc, "make_http_caller", return_value=lambda s,u,i: result(i)) as adapter:
            caller = api.get_ai_caller()
            self.assertEqual(caller("system", "user", self.item)["primary_routine_id"], "SET-017")
        slot.assert_called_once_with("deepseek")
        timeout.assert_called_once_with(60)
        self.assertEqual(adapter.call_args.args[0]["model"], "chosen-model")
        self.assertEqual(adapter.call_args.args[0]["max_tokens"], 2048)
        self.assertEqual(adapter.call_args.kwargs["timeout"], 42)

    def test_pending_old_catalog_review_is_explicitly_marked_stale(self):
        first = self.entry()
        another = deepcopy(first)
        another["review_id"] = "review-another"
        self.store.enqueue(first)
        self.store.enqueue(another)
        self.store.decide(first["review_id"], self.decision())
        with self.client() as client:
            data = client.get("/routine-matching/reviews").json()
        self.assertEqual(data["total"], 1)
        self.assertTrue(data["entries"][0]["catalog_stale"])
        self.assertNotEqual(data["catalog_hash"], another["catalog_hash"])

    def test_store_resolution_isolated_by_workspace(self):
        with workspace(self.directory / "a"):
            store_a = api.get_store()
            store_a.enqueue(self.entry())
        with workspace(self.directory / "b"):
            store_b = api.get_store()
            self.assertFalse(store_b.directory.exists())
            self.assertEqual(store_b.read()["reviews"], {})
        self.assertNotEqual(store_a.directory, store_b.directory)

    def test_router_registered_in_system_before_static_mount_without_startup(self):
        source = (rc.ROOT / "backend" / "main.py").read_text(encoding="utf-8")
        self.assertLess(source.index("app.include_router(routine_matching_router)"), source.index('app.mount("/"'))
        # Exercise OpenAPI independently; do not import/start the bank-backed app.
        app = FastAPI()
        app.include_router(api.router)
        self.assertIn("/routine-matching/match", app.openapi()["paths"])


if __name__ == "__main__":
    unittest.main()
