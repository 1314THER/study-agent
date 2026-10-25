"""Audit public national-case recordings without making paid model requests."""
import importlib.util
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("record_showcase_cases", ROOT / "scripts/record_showcase_cases.py")
recorder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recorder)


class ShowcaseRecordingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((ROOT / "frontend/showcase/recordings.json").read_text())

    def test_inputs_are_fixed_constructed_national_cases(self):
        cases = self.data["cases"]
        self.assertEqual(len(cases), 6)
        self.assertEqual(len({c["id"] for c in cases}), 6)
        for case, expected in zip(cases, recorder.fixed_cases()):
            for field in ("id", "question", "student_answer", "history", "expected"):
                self.assertEqual(case[field], expected[field])
            self.assertTrue(case["constructed_student"])
            self.assertIn(case["example_id"], ("national-2023-q17", "national-2025-q16"))
            self.assertNotIn("上海", case["question"])

    def test_baseline_is_explicit_about_evidence_and_alternative_solutions(self):
        prompt = self.data["baseline_prompt"]
        for phrase in ("原文依据", "不同的正确解法", "证据不足", "不能由缺步", "提示后答对"):
            self.assertIn(phrase, prompt)

    def test_completed_outputs_retain_the_actual_model_text_and_hash(self):
        for case in self.data["cases"]:
            recorded_configs = []
            for condition in ("basic", "same_information", "system"):
                value = case[condition]
                self.assertIn(value["status"], ("recorded", "pending", "failed"))
                if value["status"] != "recorded":
                    self.assertEqual(value.get("content", ""), "")
                    continue
                self.assertTrue(value["calls"], (case["id"], condition))
                self.assertEqual(value["content"], value["calls"][-1]["content"])
                self.assertEqual(value["response_sha256"], recorder.digest(value["content"]))
                self.assertTrue(value["recorded_at"])
                recorded_configs.append(value["config"])
                self.assertEqual(value["calls"][-1]["temperature"], 0.2)
                self.assertEqual(value["model"], value["calls"][-1]["model"])
            if recorded_configs:
                self.assertTrue(all(c == recorded_configs[0] for c in recorded_configs))

    def test_common_and_same_information_conditions_have_auditable_inputs(self):
        for case in self.data["cases"]:
            common = case["basic"]
            full = case["same_information"]
            if common["status"] == "recorded":
                request = json.loads(common["calls"][-1]["user_prompt"])
                self.assertEqual(set(request), {"question", "student_answer"})
                self.assertEqual(request["student_answer"], case["student_answer"])
                self.assertEqual(common["input_sha256"], recorder.digest(request))
            if full["status"] == "recorded":
                request = json.loads(full["calls"][-1]["user_prompt"])
                self.assertEqual(request["history"], case["history"])
                self.assertTrue(request["reference_answer"]["chunk_results"])
                self.assertEqual(full["input_sha256"], recorder.digest(request))

    def test_public_export_has_no_credentials_or_personal_identifiers(self):
        serialized = json.dumps(self.data, ensure_ascii=False)
        self.assertNotRegex(serialized, r"sk-[a-zA-Z0-9]{16,}")
        for field in ("api_key", "access_token", "refresh_token", "password", "authorization"):
            self.assertNotRegex(serialized.lower(), r'"' + re.escape(field) + r'"\s*:')
        self.assertEqual(self.data["provenance"]["execution_origin"], "local_production_code")
        self.assertIn("不是真实学生研究数据", " ".join(self.data["provenance"]["notes"]))

    def test_pending_build_does_not_open_a_database_or_call_a_provider(self):
        with patch("sqlite3.connect", side_effect=AssertionError("Private database opened")), \
             patch("httpx.post", side_effect=AssertionError("Model provider called")):
            pending = recorder.build_pending()
        self.assertTrue(all(c[k]["status"] == "pending" for c in pending["cases"]
                            for k in ("basic", "same_information", "system")))

    def test_stale_pending_checkpoint_cannot_erase_a_completed_record(self):
        old = recorder.build_pending()
        newer = recorder.build_pending()
        newer["cases"][0]["basic"] = {"status": "recorded", "content": "actual saved output"}
        newer["teaching"] = {"status": "recorded", "frames": []}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recordings.json"
            recorder.save(path, newer)
            recorder.save(path, old)
            restored = json.loads(path.read_text())
        self.assertEqual(restored["cases"][0]["basic"]["content"], "actual saved output")
        self.assertEqual(restored["teaching"]["status"], "recorded")

    def test_generation_child_thread_trace_remains_in_the_parent_record(self):
        recorder.TRACE.set([])
        def provider(system, user, **kwargs):
            return "actual child-thread response", {"total_tokens": 2}
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(copy_context().run, recorder.trace_call, provider,
                        "public system", "public question", model="test-model").result()
        calls = recorder.trace_records()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["content"], "actual child-thread response")

    def test_teaching_and_generation_are_not_synthetic_successes(self):
        for name in ("teaching", "generation"):
            value = self.data[name]
            self.assertIn(value["status"], ("recorded", "failed", "pending"))
            if value["status"] == "recorded":
                self.assertTrue(value["calls"])
                self.assertEqual(value["execution_origin"], "local_production_code")
        teaching = self.data["teaching"]
        if teaching["status"] == "recorded":
            self.assertGreaterEqual(len(teaching["frames"]), 4)
            self.assertEqual(teaching["frames"][0]["structured"]["action"], "guide")
            self.assertIn("提示", teaching["frames"][2]["input"])
            for frame in teaching["frames"]:
                self.assertEqual(frame["output"], frame["structured"]["message"])
        generation = self.data["generation"]
        if generation["status"] == "recorded":
            result = generation["structured"]
            self.assertEqual(result["accepted"] + result["rejected"], len(result["candidates"]))
            if result["accepted"]:
                self.assertTrue(generation["answer_json"]["chunk_results"])
                self.assertTrue(generation["question"])


if __name__ == "__main__":
    unittest.main()
