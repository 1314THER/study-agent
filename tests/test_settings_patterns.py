"""settings.py 与 patterns.py 纯函数测试。"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

import backend.patterns as patterns_mod
import backend.settings as settings_mod
from backend.patterns import (
    _ensure_pattern_mastery,
    _ensure_pattern_row,
    _future_str,
    _link_question,
    _load_yaml,
    _now_str,
    _recalc_category_mastery,
    _save_yaml,
    get_pattern,
    get_patterns,
    init_mastery_db,
    set_pattern_schedule,
)
from backend.settings import (
    _deep_merge,
    _read_file_settings,
    get_api,
    get_api_key,
    get_limits,
    get_scoring,
    get_settings,
    get_teacher_config,
    get_teachers,
    mask_key,
    reset_settings,
    save_settings,
)


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings_path = os.path.join(self.tmp.name, "settings.json")
        self.env_path = os.path.join(self.tmp.name, ".env")
        self._patches = [
            patch.object(settings_mod, "SETTINGS_PATH", self.settings_path),
            patch.object(settings_mod, "_ENV_PATH", self.env_path),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)
        settings_mod._cache = {"mtime": None, "data": None}

    def test_deep_merge(self):
        merged = _deep_merge({"a": {"b": 1}}, {"a": {"c": 2}})
        self.assertEqual(merged["a"], {"b": 1, "c": 2})
        self.assertEqual(_deep_merge({"a": 1}, {"a": 2}), {"a": 2})

    def test_get_settings_defaults_and_reset(self):
        data = get_settings()
        self.assertEqual(data["scoring"]["cap"], 15)
        self.assertEqual(data["limits"]["generate_count"], 3)

        save_settings({"limits": {"generate_count": 5}})
        self.assertEqual(get_settings()["limits"]["generate_count"], 5)

        reset_settings()
        self.assertEqual(get_settings()["limits"]["generate_count"], 3)

    def test_getters(self):
        self.assertIn("weights", get_scoring())
        self.assertIn("liangliang", get_teachers())
        self.assertEqual(get_teacher_config("none")["solver"]["model"], get_teacher_config("liangliang")["solver"]["model"])
        self.assertIn("deepseek", get_api())
        self.assertIn("api_max_tokens", get_limits())

    def test_get_api_key_prefers_settings_then_env(self):
        save_settings({"api": {"deepseek": {"api_key": "file-key"}}})
        self.assertEqual(get_api_key("deepseek"), "file-key")

        save_settings({"api": {"deepseek": {"api_key": ""}}})
        with open(self.env_path, "w", encoding="utf-8") as f:
            f.write("DEEPSEEK_API_KEY=env-key\n")
        self.assertEqual(get_api_key("deepseek"), "env-key")

    def test_get_api_key_empty(self):
        save_settings({"api": {"deepseek": {"api_key": ""}}})
        self.assertEqual(get_api_key("deepseek"), "")

    def test_mask_key(self):
        self.assertEqual(mask_key(""), "")
        self.assertEqual(mask_key("abc"), "***")
        self.assertEqual(mask_key("1234567890"), "123****890")

    def test_read_file_settings_corrupted(self):
        with open(self.settings_path, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertEqual(_read_file_settings()["scoring"]["cap"], 15)

    def test_save_settings_returns_merged(self):
        result = save_settings({"limits": {"search_default_limit": 50}})
        self.assertEqual(result["limits"]["search_default_limit"], 50)


class PatternsHelperTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.mastery_db = os.path.join(self.tmp.name, "mastery.db")
        self.patterns_yaml = os.path.join(self.tmp.name, "patterns.yaml")
        self._patches = [
            patch.object(patterns_mod, "MASTERY_DB", self.mastery_db),
            patch.object(patterns_mod, "PATTERNS_YAML", self.patterns_yaml),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def test_yaml_roundtrip(self):
        _save_yaml({"套路": {"key": "k1", "category": "数列"}})
        self.assertEqual(_load_yaml()["套路"]["key"], "k1")

    def test_time_strings(self):
        self.assertRegex(_now_str(), r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
        self.assertRegex(_future_str(1), r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")

    def test_pattern_row_mastery_and_link(self):
        init_mastery_db()
        conn = patterns_mod._get_conn()
        pid = _ensure_pattern_row(conn, "k1", "数列", "套路甲")
        _ensure_pattern_mastery(conn, pid)
        _link_question(conn, pid, 101, "mother")
        _recalc_category_mastery(conn, "数列")
        conn.commit()
        conn.close()

        patterns = get_patterns()
        self.assertTrue(any(p["id"] == pid for p in patterns))
        self.assertIsNotNone(get_pattern(pid))

        set_pattern_schedule(pid, "2026-08-10 08:00:00", need_check=1)
        pattern = get_pattern(pid)
        self.assertEqual(pattern["mastery"]["need_check"], 1)

    def test_pattern_difficulty_default_and_roundtrip(self):
        init_mastery_db()
        conn = patterns_mod._get_conn()
        pid = _ensure_pattern_row(conn, "k1", "数列", "套路甲", difficulty=3)
        pid2 = _ensure_pattern_row(conn, "k2", "数列", "套路乙")
        conn.commit()
        conn.close()

        self.assertEqual(get_pattern(pid)["difficulty"], 3)
        self.assertEqual(get_pattern(pid2)["difficulty"], 1)

        updated = patterns_mod.update_pattern(pid, difficulty=0)
        self.assertEqual(updated["difficulty"], 0)


if __name__ == "__main__":
    unittest.main()
