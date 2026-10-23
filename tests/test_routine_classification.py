"""Offline contracts only: fake questions/providers, no application startup."""
from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from backend import routine_classification as rc
from scripts.classify_question_patterns import main


CONFIG = {"model": "test-model", "base_url": "https://api.example.test/v1",
          "temperature": 0.1, "max_tokens": 4096}


def result(item, rid="SET-017", **changes):
    value = {"primary_routine_id": rid, "secondary_routine_ids": [], "candidate_routine_ids": [],
             "confidence": "high", "composite": False, "needs_review": False,
             "review_reasons": [], "method_summary": "根据原解析先分空集，再比较端点",
             "evidence": [{"field": "solution" if item["solution"] else "question",
                           "quote": item["solution"][:25] if item["solution"] else item["question"][:25]}],
             "representative_score": 90, "variant_features": ["标准非空与空集两分支"],
             "suggested_routine": None}
    value.update(changes)
    return value


class RoutineClassificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = rc.load_catalog()
        cls.fixture = rc.ROOT / "tests" / "fixtures" / "routine_questions.jsonl"
        cls.items = rc.load_items(cls.fixture)
        cls.golden = rc.read_json(rc.ROOT / "tests" / "fixtures" / "routine_expected.json")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.output = self.directory / "reports"
        self.item = deepcopy(self.items[0])

    def run_items(self, items, caller, **options):
        return rc.classify_items(items, self.catalog, self.output, CONFIG, caller, **options)

    def test_catalog_exact_coverage_and_static_chapters(self):
        from collections import Counter
        self.assertEqual(len(self.catalog["routines"]), len(self.catalog["routines"]))
        self.assertEqual(Counter(r["category"] for r in self.catalog["routines"]), rc.CATEGORY_COUNTS)
        # Source is static YAML, never a runtime database.
        text = (rc.ROOT / "backend" / "categories.yaml").read_text(encoding="utf-8")
        for chapter in rc.CATEGORY_COUNTS:
            self.assertIn(chapter + ":", text)
        self.assertEqual(len({r["name"] for r in self.catalog["routines"]}), len(self.catalog["routines"]))

    def test_catalog_rejects_duplicate_and_dangling_references(self):
        for mutate in (lambda c: c["routines"][1].update(id=c["routines"][0]["id"]),
                       lambda c: c["routines"][0].update(confusable_ids=["BAD-999"]),
                       lambda c: c["routines"][0].update(key_steps=[])):
            catalog = deepcopy(self.catalog)
            mutate(catalog)
            path = self.directory / "bad.json"
            rc.write_json(path, catalog)
            with self.assertRaises(ValueError):
                rc.load_catalog(path)

    def test_explicit_jsonl_input_no_database_formats(self):
        with self.assertRaises(ValueError):
            rc.load_items(self.directory / "study_agent.db")
        for value in ([dict(self.item, id=True)], [dict(self.item, version=0)],
                      [dict(self.item, question="")], [self.item, self.item],
                      [dict(self.item, categories=["不存在的板块"])],
                      [dict(self.item, solution={"text": "wrong"})]):
            path = self.directory / "bad.jsonl"
            path.write_text("\n".join(json.dumps(r) for r in value), encoding="utf-8")
            with self.assertRaises(ValueError):
                rc.load_items(path)

    def test_input_ignores_arbitrary_export_fields(self):
        path = self.directory / "input.jsonl"
        path.write_text(json.dumps(dict(self.item, api_key="SECRET", original_raw={"private": "data"})), encoding="utf-8")
        loaded = rc.load_items(path)[0]
        self.assertNotIn("api_key", loaded)
        self.assertNotIn("original_raw", loaded)

    def test_shortlist_contains_golden_boundary_and_method_cases(self):
        for item in self.items:
            rid = self.golden[str(item["id"])]["primary_routine_id"]
            if rid:
                with self.subTest(id=item["id"], routine=rid):
                    self.assertIn(rid, {r["id"] for r in rc.shortlist(item, self.catalog)})
        choices = {r["id"] for r in rc.shortlist(self.item, self.catalog)}
        self.assertTrue({"SET-016", "SET-017", "SET-018", "SET-019"} <= choices)

    def test_no_retrieval_evidence_exposes_all_chapters(self):
        item = dict(self.item, question="ABCDEFG", solution="HIJKLMN", categories=[])
        self.assertEqual(len(rc.shortlist(item, self.catalog)), len(self.catalog["routines"]))

    def test_fake_provider_end_to_end_and_golden_groups(self):
        def fake(system, user, item):
            expected = self.golden[str(item["id"])]
            return result(item, **expected)
        rows, manifest = self.run_items(self.items, fake, limit=0)
        self.assertEqual(manifest["counts"], {"classified": len(self.items)})
        self.assertEqual(manifest["api_attempts"], len(self.items))
        by_id = {r["id"]: r for r in rows}
        self.assertEqual(by_id[101]["classification"]["primary_routine_id"], by_id[102]["classification"]["primary_routine_id"])
        self.assertNotEqual(by_id[103]["classification"]["primary_routine_id"], by_id[104]["classification"]["primary_routine_id"])
        self.assertNotEqual(by_id[106]["classification"]["primary_routine_id"], by_id[107]["classification"]["primary_routine_id"])
        for item_id in (113, 114, 115, 116):
            self.assertTrue(by_id[item_id]["classification"]["needs_review"])
        groups = rc.build_groups(rows, self.catalog)
        for group in groups:
            self.assertLessEqual(len(group["variant_candidate_ids"]), 3)
            self.assertFalse(set(group["review_ids"]) & {group["mother_candidate_id"], *group["variant_candidate_ids"]})
        rc.write_reports(self.output, rows, self.catalog, manifest)
        self.assertTrue(all((self.output / name).exists() for name in rc.REPORT_FILES))
        self.assertIn("补充目录草案", (self.output / "review.md").read_text(encoding="utf-8"))

    def test_model_cannot_override_missing_solution_or_completeness(self):
        for item in (dict(self.item, solution=""), dict(self.item, completeness="needs_review"),
                     dict(self.item, completeness="deferred_graphic"), dict(self.item, completeness="unknown")):
            normalized = rc.normalize_result(result(item), item, self.catalog)
            self.assertTrue(normalized["needs_review"])
            self.assertTrue(normalized["review_reasons"])

    def test_schema_and_exact_evidence_are_required(self):
        for changes in ({"primary_routine_id": "FAKE-001"}, {"evidence": []},
                        {"evidence": [{"field": "solution", "quote": "模型编造的原文"}]},
                        {"confidence": 0.99}, {"representative_score": float("nan")},
                        {"needs_review": "false"}, {"secondary_routine_ids": ["SET-017"]},
                        {"secondary_routine_ids": ["SET-018", "SET-018"]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                rc.normalize_result(result(self.item, **changes), self.item, self.catalog)
        with self.assertRaises(ValueError):
            rc.normalize_result(result(self.item), self.item, self.catalog, {"SET-018"})

    def test_fenced_json_and_unknown_routine_suggestion(self):
        raw = "```json\n" + json.dumps(result(self.item)) + "\n```"
        self.assertEqual(rc.normalize_result(raw, self.item, self.catalog)["primary_routine_id"], "SET-017")
        normalized = rc.normalize_result(result(self.item, primary_routine_id=None,
                     evidence=[], suggested_routine={"name": "新方法草案", "category": "数列", "key_steps": ["翻译规则", "检查边界"]}), self.item, self.catalog)
        self.assertTrue(normalized["needs_review"])
        self.assertEqual(normalized["suggested_routine"]["name"], "新方法草案")

    def test_numeric_duplicates_remain_reserves_variants_use_new_features(self):
        items = [dict(self.item, id=i) for i in range(1, 8)]
        def fake(system, user, item):
            features = ["基本条件"] if item["id"] < 4 else ["边界变化" + str(item["id"])]
            return result(item, representative_score=100-item["id"], variant_features=features)
        rows, _ = self.run_items(items, fake, limit=0)
        group = rc.build_groups(rows, self.catalog)[0]
        self.assertEqual(group["mother_candidate_id"], 1)
        self.assertEqual(group["variant_candidate_ids"], [4, 5, 6])
        self.assertEqual(group["reserve_ids"], [2, 3, 7])

    def test_limit_cache_and_restart_skip_successes(self):
        calls = []
        def fake(system, user, item):
            calls.append(item["id"])
            return result(item)
        rows, first = self.run_items(self.items[:2], fake, limit=1)
        self.assertEqual(first["counts"], {"classified": 1, "pending": 1})
        rows, second = self.run_items(self.items[:2], fake, limit=1)
        self.assertEqual(second["counts"], {"classified": 2})
        self.assertEqual(calls, [101, 102])
        self.assertEqual(second["api_attempts"], 1)

    def test_changed_item_catalog_prompt_model_invalidate_cache(self):
        key = rc.cache_key(self.item, self.catalog, CONFIG)
        for item in (dict(self.item, question=self.item["question"]+"新条件"),
                     dict(self.item, version=2), dict(self.item, solution="修改原解析")):
            self.assertNotEqual(key, rc.cache_key(item, self.catalog, CONFIG))
        catalog = dict(self.catalog, version="next")
        self.assertNotEqual(key, rc.cache_key(self.item, catalog, CONFIG))
        self.assertNotEqual(key, rc.cache_key(self.item, self.catalog, dict(CONFIG, model="other")))
        with patch.object(rc, "PROMPT_VERSION", "next"):
            self.assertNotEqual(key, rc.cache_key(self.item, self.catalog, CONFIG))

    def test_invalid_json_retries_then_saves_success(self):
        calls = []
        def fake(system, user, item):
            calls.append(1)
            return "not JSON" if len(calls) == 1 else result(item)
        rows, manifest = self.run_items([self.item], fake)
        self.assertEqual(rows[0]["status"], "classified")
        self.assertEqual(manifest["api_attempts"], 2)

    def test_failures_cached_and_retried_only_when_requested(self):
        def fail(system, user, item):
            raise TimeoutError("SECRET provider request key")
        rows, manifest = self.run_items([self.item], fail)
        self.assertEqual(manifest["api_attempts"], 2)
        self.assertEqual(rows[0]["status"], "error")
        def fake(system, user, item):
            return result(item)
        rows, manifest = self.run_items([self.item], fake)
        self.assertEqual(manifest["api_attempts"], 0)
        rows, manifest = self.run_items([self.item], fake, retry_failed=True)
        self.assertEqual(rows[0]["status"], "classified")
        self.assertEqual(manifest["api_attempts"], 1)
        self.assertNotIn("SECRET", "".join(p.read_text() for p in (self.output / "cache").glob("*.json")))

    def test_interrupt_preserves_completed_cache_and_next_run_resumes(self):
        def interrupted(system, user, item):
            if item["id"] == 102:
                raise KeyboardInterrupt()
            return result(item)
        rows, manifest = self.run_items(self.items[:2], interrupted)
        self.assertTrue(manifest["interrupted"])
        self.assertEqual([r["status"] for r in rows], ["classified", "pending"])
        calls = []
        def fake(system, user, item):
            calls.append(item["id"])
            return result(item)
        rows, manifest = self.run_items(self.items[:2], fake)
        self.assertEqual(calls, [102])
        self.assertFalse(manifest["interrupted"])

    def test_corrupt_cache_is_pending_and_not_trusted(self):
        key = rc.cache_key(self.item, self.catalog, CONFIG)
        path = self.output / "cache" / (key + ".json")
        rc.atomic_write(path, "invalid JSON")
        self.assertIsNone(rc.read_cache(self.output, key, self.item, self.catalog))

    def test_manual_override_preserved_reclassify_skips_it(self):
        overrides_path = self.output / "overrides.json"
        override = {"id": self.item["id"], "version": 1, "content_hash": rc.digest(self.item),
                    "primary_routine_id": "SET-018", "secondary_routine_ids": [], "note": "人工确认该题非空"}
        rc.write_json(overrides_path, [override])
        before = overrides_path.read_bytes()
        overrides = rc.load_overrides(overrides_path, self.catalog)
        def forbidden(*args):
            raise AssertionError("人工调整不应重新调用模型")
        rows, manifest = self.run_items([self.item], forbidden, overrides=overrides)
        self.assertEqual(manifest["api_attempts"], 0)
        self.assertEqual(rows[0]["classification"]["primary_routine_id"], "SET-018")
        rc.write_reports(self.output, rows, self.catalog, manifest)
        self.assertEqual(before, overrides_path.read_bytes())

    def test_stale_override_not_applied_or_recommended(self):
        override = {"id": self.item["id"], "version": 1, "content_hash": rc.digest(self.item),
                    "primary_routine_id": "SET-018"}
        newer = dict(self.item, version=2)
        rows, _ = self.run_items([newer], lambda s,u,i: result(i), overrides={101: override})
        self.assertEqual(rows[0]["override_status"], "stale")
        self.assertEqual(rows[0]["classification"]["primary_routine_id"], "SET-017")
        group = rc.build_groups(rows, self.catalog)[0]
        self.assertIsNone(group["mother_candidate_id"])
        self.assertEqual(group["review_ids"], [101])

    def test_report_only_no_network_and_dry_run_no_writes(self):
        with patch.object(rc, "urlopen", side_effect=AssertionError("禁止网络")), patch("sqlite3.connect", side_effect=AssertionError("禁止数据库")):
            preview = rc.plan_run(self.items, self.catalog, self.output, CONFIG)
            self.assertFalse(self.output.exists())
            self.assertEqual(preview["counts"], {"pending": len(self.items)})
            rows, manifest = self.run_items(self.items[:2], None)
            rc.write_reports(self.output, rows, self.catalog, manifest)
        self.assertEqual(manifest["api_attempts"], 0)

    def test_cli_defaults_to_preview_and_validation_without_provider(self):
        with patch.object(rc, "make_http_caller", side_effect=AssertionError("禁止 AI")), patch("sqlite3.connect", side_effect=AssertionError("禁止数据库")), redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--validate-catalog"]), 0)
            self.assertEqual(main(["--input", str(self.fixture), "--output", str(self.output)]), 0)
        self.assertFalse(self.output.exists())

    def test_cli_classify_with_fake_and_report_only(self):
        with patch("sqlite3.connect", side_effect=AssertionError("禁止数据库")), patch.object(rc, "urlopen", side_effect=AssertionError("禁止网络")), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            args = ["--input", str(self.fixture), "--output", str(self.output), "--limit", "1"]
            self.assertEqual(main(args + ["--classify"], caller=lambda s,u,i: result(i)), 0)
            self.assertEqual(main(args + ["--report-only"]), 0)
        manifest = rc.read_json(self.output / "manifest.json")
        self.assertEqual(manifest["api_attempts"], 0)
        self.assertEqual(manifest["counts"]["classified"], 1)

    def test_cli_input_output_collision_rejected(self):
        input_path = self.output / "assignments.jsonl"
        input_path.parent.mkdir()
        input_path.write_text(json.dumps(self.item), encoding="utf-8")
        before = input_path.read_bytes()
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
            main(["--input", str(input_path), "--output", str(self.output), "--report-only"])
        self.assertEqual(exc.exception.code, 2)
        self.assertEqual(before, input_path.read_bytes())

    def test_symlink_database_input_rejected_before_read(self):
        database = self.directory / "fake.db"
        database.write_text("must not be read", encoding="utf-8")
        disguised = self.directory / "disguised.jsonl"
        disguised.symlink_to(database)
        with self.assertRaises(ValueError):
            rc.load_items(disguised)

    def test_sources_inside_cache_rejected(self):
        catalog_path = self.output / "cache" / "catalog.json"
        rc.write_json(catalog_path, self.catalog)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(["--catalog", str(catalog_path), "--input", str(self.fixture),
                  "--output", str(self.output), "--report-only"])

    def test_cli_signal_between_requests_recovers_cache(self):
        original = rc.classify_items
        calls = []
        def interrupted(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                def progress(*ignored):
                    raise KeyboardInterrupt()
                kwargs["progress"] = progress
            return original(*args, **kwargs)
        with patch.object(rc, "classify_items", interrupted), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = main(["--input", str(self.fixture), "--output", str(self.output), "--classify"],
                        caller=lambda s,u,i: result(i))
        self.assertEqual(code, 130)
        manifest = rc.read_json(self.output / "manifest.json")
        self.assertTrue(manifest["interrupted"])
        self.assertEqual(manifest["counts"]["classified"], 1)
        self.assertEqual(manifest["counts"]["pending"], 15)

    def test_fresh_process_import_does_not_load_application_modules(self):
        code = "import sqlite3; sqlite3.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('database forbidden')); from backend import routine_classification as rc; rc.load_catalog(); import sys; assert not any(x in sys.modules for x in ['backend.main','backend.question_pool','backend.database','backend.patterns','backend.jobs','backend.auth','backend.settings'])"
        process = subprocess.run([sys.executable, "-c", code], cwd=rc.ROOT, text=True, capture_output=True)
        self.assertEqual(process.returncode, 0, process.stderr)

    def test_provider_adapter_payload_without_app_or_database(self):
        class Response(io.StringIO):
            def __enter__(self): return self
            def __exit__(self, *args): self.close()
        captured = []
        def fake(request, timeout):
            captured.append((request, timeout))
            return Response(json.dumps({"choices": [{"message": {"content": "{}"}}]}))
        with patch("sqlite3.connect", side_effect=AssertionError("禁止数据库")), patch.object(rc, "urlopen", fake):
            caller = rc.make_http_caller(CONFIG, api_key="MOCK-KEY")
            self.assertEqual(caller("system", "user", self.item), "{}")
        request, timeout = captured[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertTrue(request.full_url.endswith("/chat/completions"))
        self.assertEqual(json.loads(request.data)["model"], CONFIG["model"])
        with self.assertRaises(ValueError): rc.make_http_caller(CONFIG, api_key="")
        with self.assertRaises(ValueError): rc.make_http_caller(dict(CONFIG, base_url="http://localhost"), api_key="MOCK")

    def test_cache_prefix_identical_across_questions_stages_and_catalog_order(self):
        catalog=deepcopy(self.catalog)
        catalog['routines'].reverse()
        first=rc.make_prompt(self.item,self.catalog,cache_friendly=True)
        second=rc.make_prompt(self.items[1],catalog,full_catalog=True,previous=result(self.item),cache_friendly=True)
        self.assertEqual(first[0],second[0])
        self.assertNotIn(self.item['question'],first[0])
        rows=json.loads(first[0].split('\n')[-1])['routines']
        self.assertEqual(len(rows),len(self.catalog["routines"]))
        expected={r['id']:r for r in self.catalog['routines']}
        for rid,name,category,steps,exclusions,others in rows:
            self.assertEqual((steps,exclusions),(expected[rid]['key_steps'],expected[rid]['exclusions']))
        self.assertEqual(set(json.loads(second[1])['allowed_ids']),set(expected))
        self.assertNotIn('catalog',json.loads(first[1]))
        self.assertNotEqual(rc.cache_key(self.item,self.catalog,CONFIG),rc.cache_key(self.item,self.catalog,dict(CONFIG,prompt_profile=rc.CACHE_PROMPT_VERSION)))

    def test_compact_provider_disables_thinking_caps_stages_and_records_usage(self):
        payloads=[];observed=[]
        config=dict(CONFIG,thinking='disabled',json_output=True,max_tokens=1024,audit_max_tokens=2048)
        class Response(io.StringIO):
            def __enter__(self):return self
            def __exit__(self,*args):self.close()
        def fake(request,timeout):
            payloads.append(json.loads(request.data))
            return Response(json.dumps({'choices':[{'message':{'content':'{}','reasoning_content':''},'finish_reason':'stop'}],
                'usage':{'prompt_tokens':1000,'completion_tokens':120,'prompt_cache_hit_tokens':900,'prompt_cache_miss_tokens':100,'completion_tokens_details':{'reasoning_tokens':0}}}))
        with patch.object(rc,'urlopen',fake):
            caller=rc.make_http_caller(config,api_key='MOCK',usage_callback=lambda *args:observed.append(args))
            for stage in ('retrieved_match','full_catalog_audit'):
                self.assertEqual(caller('JSON',json.dumps({'stage':stage}),self.item),'{}')
        self.assertEqual([p['max_tokens'] for p in payloads],[1024,2048])
        self.assertTrue(all(p['thinking']=={'type':'disabled'} and p['response_format']=={'type':'json_object'} for p in payloads))
        self.assertEqual(observed[1][1],'full_catalog_audit')
        self.assertEqual(observed[1][2]['reasoning_tokens'],0)

    def test_truncated_response_usage_recorded_before_retry_and_missing_metrics_unknown(self):
        seen=[]
        class Response(io.StringIO):
            def __enter__(self):return self
            def __exit__(self,*args):self.close()
        payload={'choices':[{'message':{'content':'{"partial":'},'finish_reason':'length'}],'usage':{'completion_tokens':1024}}
        with patch.object(rc,'urlopen',return_value=Response(json.dumps(payload))):
            caller=rc.make_http_caller(CONFIG,api_key='MOCK',usage_callback=lambda *args:seen.append(args))
            with self.assertRaises(ValueError):caller('JSON','{}',self.item)
        self.assertEqual(seen[0][2]['completion_tokens'],1024)
        self.assertIsNone(seen[0][2]['reasoning_tokens'])
        self.assertIsNone(seen[0][2]['prompt_cache_hit_tokens'])


if __name__ == "__main__":
    unittest.main()
