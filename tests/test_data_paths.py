"""Request workspaces isolate mutable files and never inherit owner API keys."""

import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import anyio

from backend import data_paths, database, patterns, planner, settings


class WorkspaceIsolationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.owner = self.root / "owner"
        self.a = self.root / "visitor-a"
        self.b = self.root / "visitor-b"
        for directory in (self.owner, self.a, self.b):
            directory.mkdir()
        self.env_patch = patch.dict(os.environ, {"STUDY_AGENT_DATA_DIR": "", "STUDY_DEMO_AI_CONFIG": ""})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.patches = [
            patch.object(database, "DB_PATH", str(self.owner / "study_agent.db")),
            patch.object(patterns, "MASTERY_DB", str(self.owner / "mastery.db")),
            patch.object(patterns, "PATTERNS_YAML", str(self.owner / "patterns.yaml")),
            patch.object(planner, "CONFIG_PATH", str(self.owner / "board_order.yaml")),
            patch.object(settings, "SETTINGS_PATH", str(self.owner / "settings.json")),
            patch.object(settings, "_ENV_PATH", str(self.owner / ".env")),
            patch.object(settings, "_cache", {}),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_precedence_and_nested_context_restoration(self):
        legacy = "legacy/location.db"
        self.assertEqual(data_paths.data_path("study_agent.db", legacy), legacy)
        with patch.dict(os.environ, {"STUDY_AGENT_DATA_DIR": str(self.owner)}):
            self.assertEqual(data_paths.data_path("study_agent.db", legacy), str(self.owner / "study_agent.db"))
            with data_paths.workspace(self.a):
                self.assertEqual(data_paths.data_path("study_agent.db", legacy), str(self.a / "study_agent.db"))
                with data_paths.workspace(self.b):
                    self.assertEqual(data_paths.workspace_directory(), str(self.b))
                self.assertEqual(data_paths.workspace_directory(), str(self.a))
            self.assertEqual(data_paths.workspace_directory(), str(self.owner))
        self.assertIsNone(data_paths.workspace_directory())

    def _write_workspace(self, directory, label, count):
        with data_paths.workspace(directory):
            database.init_db()
            database.save_question(label, {})
            patterns.init_mastery_db()
            conn = patterns._get_conn()
            patterns._ensure_pattern_row(conn, "pattern-key", "数列", label)
            conn.commit()
            conn.close()
            patterns._save_yaml({label: {"key": label}})
            planner._save_config({"board_order": [{"category": "数列", "nodes": [count]}]})
            settings.save_settings({"limits": {"generate_count": count}})

    def test_database_yaml_and_settings_writes_are_separate(self):
        # Owner paths are deliberately monkeypatched as existing tests do.
        database.init_db()
        database.save_question("owner original", {})
        settings.save_settings({"limits": {"generate_count": 9}})
        self._write_workspace(self.a, "visitor A", 1)
        self._write_workspace(self.b, "visitor B", 2)

        for directory, label, count in ((self.a, "visitor A", 1), (self.b, "visitor B", 2)):
            with data_paths.workspace(directory):
                self.assertEqual([q["content"] for q in database.get_all_questions()], [label])
                conn = patterns._get_conn()
                try:
                    self.assertEqual(conn.execute("SELECT name FROM patterns").fetchone()[0], label)
                finally:
                    conn.close()
                self.assertEqual(patterns._load_yaml(), {label: {"key": label}})
                self.assertEqual(planner._load_config()["board_order"][0]["nodes"], [count])
                self.assertEqual(settings.get_limits()["generate_count"], count)
                for filename in ("study_agent.db", "mastery.db", "patterns.yaml", "settings.json", "board_order.yaml"):
                    self.assertTrue((directory / filename).exists(), filename)

        self.assertEqual([q["content"] for q in database.get_all_questions()], ["owner original"])
        self.assertEqual(settings.get_limits()["generate_count"], 9)
        self.assertFalse((self.owner / "patterns.yaml").exists())
        self.assertFalse((self.owner / "board_order.yaml").exists())
        self.assertFalse((self.owner / "mastery.db").exists())

    def test_settings_cache_isolated_even_when_timestamps_match(self):
        for directory, cap in ((self.a, 11), (self.b, 22)):
            path = directory / "settings.json"
            path.write_text(json.dumps({"scoring": {"cap": cap}}), encoding="utf-8")
            os.utime(path, ns=(1000000000, 1000000000))
        for directory, cap in ((self.a, 11), (self.b, 22), (self.a, 11)):
            with data_paths.workspace(directory):
                self.assertEqual(settings.get_scoring()["cap"], cap)

    def test_missing_workspace_files_never_fall_back_to_owner(self):
        (self.owner / "patterns.yaml").write_text("owner: data\n", encoding="utf-8")
        (self.owner / "board_order.yaml").write_text("board_order: [owner]\n", encoding="utf-8")
        (self.owner / ".env").write_text("DEEPSEEK_API_KEY=owner-file-key\n", encoding="utf-8")
        settings.save_settings({"api": {"deepseek": {"api_key": "owner-settings-key"}}})
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "owner-environment-key"}):
            with data_paths.workspace(self.a):
                self.assertEqual(settings.get_api_key("deepseek"), "")
                self.assertEqual(patterns._load_yaml(), {})
                self.assertEqual(planner._load_config(), {"board_order": []})
                patterns.delete_question_links(1)
                self.assertFalse((self.a / "mastery.db").exists())
                (self.a / ".env").write_text("DEEPSEEK_API_KEY=visitor-key\n", encoding="utf-8")
                self.assertEqual(settings.get_api_key("deepseek"), "visitor-key")
            self.assertEqual(settings.get_api_key("deepseek"), "owner-settings-key")

    def test_thread_pool_keeps_request_context(self):
        async def run():
            with data_paths.workspace(self.a):
                return await anyio.to_thread.run_sync(data_paths.data_path, "study_agent.db", database.DB_PATH)
        self.assertEqual(asyncio.run(run()), str(self.a / "study_agent.db"))

    def test_concurrent_request_tasks_keep_distinct_workspaces(self):
        async def request(directory, value):
            with data_paths.workspace(directory):
                await asyncio.sleep(0)
                await anyio.to_thread.run_sync(settings.save_settings, {"limits": {"generate_count": value}})
                await asyncio.sleep(0)
                return settings.get_limits()["generate_count"]

        async def run():
            return await asyncio.gather(request(self.a, 1), request(self.b, 2))

        self.assertEqual(asyncio.run(run()), [1, 2])
        self.assertIsNone(data_paths.workspace_directory())
        self.assertFalse((self.owner / "settings.json").exists())

    def _shared_snapshot(self):
        path = self.root / "administrator-ai.json"
        path.write_text(json.dumps({
            "api": {
                "deepseek": {"base_url": "https://trusted.example/v1", "api_key": "mock-shared-key"},
                "dashscope": {"base_url": "https://vision.example/v1", "api_key": "", "model": "trusted-vision"},
            },
            "teachers": {"liangliang": {"solver": {"model": "trusted-model"}}},
            "limits": {"api_max_tokens": 512, "generate_concurrency": 1},
            "scoring": {"cap": 999},
        }), encoding="utf-8")
        return path

    def test_shared_ai_uses_trusted_endpoints_keys_models_and_limits(self):
        shared_path = self._shared_snapshot()
        shared_bytes = shared_path.read_bytes()
        with patch.dict(os.environ, {"STUDY_DEMO_AI_CONFIG": str(shared_path), "DEEPSEEK_API_KEY": "mock-owner-key"}):
            with data_paths.workspace(self.a):
                (self.a / ".env").write_text("DEEPSEEK_API_KEY=mock-visitor-env-key\n", encoding="utf-8")
                settings.save_settings({
                    "api": {
                        "deepseek": {"base_url": "https://untrusted.example/v1", "api_key": "mock-visitor-key"},
                        "dashscope": {"base_url": "https://untrusted.example/vision", "api_key": "mock-visitor-vision-key"},
                    },
                    "teachers": {"liangliang": {"solver": {"model": "untrusted-model"}}},
                    "limits": {"api_max_tokens": 100000, "generate_concurrency": 99},
                    "scoring": {"cap": 7},
                })
                self.assertTrue(settings.shared_ai_enabled())
                self.assertEqual(settings.get_api_key("deepseek"), "mock-shared-key")
                self.assertEqual(settings.get_api_key("dashscope"), "")
                self.assertEqual(settings.get_api()["deepseek"]["base_url"], "https://trusted.example/v1")
                self.assertEqual(settings.get_api()["dashscope"]["base_url"], "https://vision.example/v1")
                self.assertEqual(settings.get_api()["dashscope"]["model"], "trusted-vision")
                self.assertEqual(settings.get_teacher_config("liangliang")["solver"]["model"], "trusted-model")
                self.assertEqual(settings.get_limits()["api_max_tokens"], 512)
                self.assertEqual(settings.get_limits()["generate_concurrency"], 1)
                self.assertEqual(settings.get_scoring()["cap"], 7)
                # Read-only shared credentials never enter visitor settings.
                self.assertNotIn("mock-shared-key", (self.a / "settings.json").read_text(encoding="utf-8"))
                self.assertNotIn("mock-shared-key", json.dumps(settings.get_settings()))
            self.assertFalse(settings.shared_ai_enabled())
            self.assertIsNone(data_paths.shared_ai_config_path())
            self.assertEqual(settings.get_api_key("deepseek"), "mock-owner-key")
        self.assertEqual(shared_path.read_bytes(), shared_bytes)

    def test_shared_configuration_is_ignored_for_owner_app(self):
        shared_path = self._shared_snapshot()
        settings.save_settings({"api": {"deepseek": {
            "base_url": "https://owner.example/v1", "api_key": "mock-owner-settings-key",
        }}, "limits": {"api_max_tokens": 1024}})
        with patch.dict(os.environ, {"STUDY_DEMO_AI_CONFIG": str(shared_path)}):
            self.assertFalse(settings.shared_ai_enabled())
            self.assertEqual(settings.get_api()["deepseek"]["base_url"], "https://owner.example/v1")
            self.assertEqual(settings.get_api_key("deepseek"), "mock-owner-settings-key")
            self.assertEqual(settings.get_limits()["api_max_tokens"], 1024)

    def test_missing_shared_configuration_disables_keys_without_fallback(self):
        with patch.dict(os.environ, {"STUDY_DEMO_AI_CONFIG": str(self.root / "missing.json"), "DEEPSEEK_API_KEY": "mock-owner-key"}):
            with data_paths.workspace(self.a):
                (self.a / ".env").write_text("DEEPSEEK_API_KEY=mock-visitor-key\n", encoding="utf-8")
                settings.save_settings({"api": {"deepseek": {
                    "api_key": "mock-visitor-settings-key", "base_url": "https://untrusted.example/v1",
                }}})
                self.assertFalse(settings.shared_ai_enabled())
                self.assertEqual(settings.get_api_key("deepseek"), "")
                self.assertEqual(settings.get_api()["deepseek"]["base_url"], settings.DEFAULTS["api"]["deepseek"]["base_url"])


if __name__ == "__main__":
    unittest.main()
