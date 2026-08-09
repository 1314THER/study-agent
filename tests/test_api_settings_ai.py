"""系统设置、AI 仿题、语义搜索 API 测试。"""

import unittest
from unittest.mock import patch

from tests.api_base import ApiTestCase


class SettingsApiTest(ApiTestCase):
    def test_get_settings_masks_key(self):
        resp = self.client.get("/settings")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("api", resp.json())
        api = resp.json()["api"]["deepseek"]
        self.assertIn("has_key", api)

    def test_update_settings_sanitizes(self):
        resp = self.client.put("/settings", json={
            "scoring": {"weights": [99, -1, 3, 4], "cap": 999},
            "limits": {"generate_count": 100, "bad_key": 1},
            "api": {"deepseek": {"base_url": "https://example.com/v1"}},
        })
        self.assertEqual(resp.status_code, 200)
        scoring = resp.json()["scoring"]
        self.assertEqual(scoring["weights"][0], 50)
        self.assertEqual(scoring["cap"], 50)
        self.assertEqual(resp.json()["limits"]["generate_count"], 10)

    def test_reset_settings(self):
        resp = self.client.post("/settings/reset")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["scoring"]["cap"], 15)

    def test_settings_test_without_key(self):
        with patch("backend.settings.get_api_key", return_value=""):
            resp = self.client.post("/settings/test", json={"provider": "deepseek"})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["ok"])

    def test_settings_test_unknown_provider(self):
        resp = self.client.post("/settings/test", json={"provider": "unknown"})
        self.assertFalse(resp.json()["ok"])


class GenerateApiTest(ApiTestCase):
    def test_generate_variants(self):
        fixture = {"candidates": [{"status": "accepted", "question_id": 2}]}
        with patch("backend.generate.generate_variants", return_value=fixture) as mock:
            resp = self.client.post("/questions/1/generate", json={"count": 2, "teacher": "taotao"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["candidates"][0]["question_id"], 2)
        mock.assert_called_once_with(1, count=2, teacher="taotao")

        with patch("backend.generate.generate_variants", side_effect=ValueError("no question")):
            resp = self.client.post("/questions/999/generate", json={})
        self.assertEqual(resp.status_code, 404)

    def test_generate_variants_async(self):
        with patch("backend.generate.start_generate_job", return_value={"job_id": "j1"}) as mock:
            resp = self.client.post("/questions/1/generate/async", json={"teacher": "liangliang"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["job_id"], "j1")
        mock.assert_called_once_with(1, count=None, teacher="liangliang")

        with patch("backend.generate.start_generate_job", side_effect=ValueError("no")):
            resp = self.client.post("/questions/999/generate/async", json={})
        self.assertEqual(resp.status_code, 404)

    def test_get_generate_job(self):
        with patch("backend.generate.get_generate_job", return_value={"job_id": "j1", "status": "done"}):
            resp = self.client.get("/generate-jobs/j1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "done")

        with patch("backend.generate.get_generate_job", return_value=None):
            resp = self.client.get("/generate-jobs/nope")
        self.assertEqual(resp.status_code, 404)


class AiSearchApiTest(ApiTestCase):
    def test_ai_search(self):
        with patch("backend.database.ai_search_questions", return_value=[{"id": 1}]) as mock:
            resp = self.client.post("/questions/ai-search", json={"query": "导数", "limit": 5})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()[0]["id"], 1)
        mock.assert_called_once_with("导数", 5)


if __name__ == "__main__":
    unittest.main()
