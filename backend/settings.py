"""运行时设置：评分公式 / 老师模型 / API 密钥。

设置保存在 backend/settings.json，保存后无需重启即热生效。
API 密钥为空时回退到环境变量或 .env。
"""

import json
import os


SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "settings.json")
_ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")

DEFAULTS = {
    "scoring": {
        "weights": [0, 1, 2, 4],  # 下标对应五维分值 0/1/2/3
        "cap": 15,
        "thresholds": [
            {"limit": 3, "level": "容易"},
            {"limit": 6, "level": "中等"},
            {"limit": 9, "level": "困难"},
        ],
    },
    "teachers": {
        "liangliang": {
            "solver": {"model": "deepseek-v4-flash", "reasoning_effort": None},
            "verifier": {"model": "deepseek-v4-flash", "reasoning_effort": "low"},
            "formatter": {"model": "deepseek-v4-flash", "reasoning_effort": "low"},
        },
        "taotao": {
            "solver": {"model": "deepseek-v4-pro", "reasoning_effort": "low"},
            "verifier": {"model": "deepseek-v4-flash", "reasoning_effort": "medium"},
            "formatter": {"model": "deepseek-v4-flash", "reasoning_effort": "low"},
        },
        "xuefeng": {
            "solver": {"model": "deepseek-v4-pro", "reasoning_effort": "high"},
            "verifier": {"model": "deepseek-v4-flash", "reasoning_effort": "medium"},
            "formatter": {"model": "deepseek-v4-flash", "reasoning_effort": "low"},
        },
        "ji": {
            "solver": {"model": "deepseek-v4-pro", "reasoning_effort": "high"},
            "verifier": {"model": "deepseek-v4-flash", "reasoning_effort": "high"},
            "formatter": {"model": "deepseek-v4-flash", "reasoning_effort": "high"},
        },
    },
    "api": {
        "deepseek": {
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "",
        },
        "dashscope": {
            "base_url": "https://ws-1b3ikgt2q6ybkzos.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
            "model": "qwen-vl-max",
            "api_key": "",
        },
    },
}

_ENV_KEYS = {
    "deepseek": "DEEPSEEK_API_KEY",
    "dashscope": "DASHSCOPE_API_KEY",
}

_cache = {"mtime": None, "data": None}


def _deep_merge(base, patch):
    if not isinstance(base, dict) or not isinstance(patch, dict):
        return patch
    out = dict(base)
    for key, value in patch.items():
        out[key] = _deep_merge(base.get(key), value) if isinstance(base.get(key), dict) and isinstance(value, dict) else value
    return out


def _read_file_settings():
    if not os.path.exists(SETTINGS_PATH):
        return DEFAULTS
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return _deep_merge(DEFAULTS, data) if isinstance(data, dict) else DEFAULTS
    except (json.JSONDecodeError, OSError):
        return DEFAULTS


def get_settings() -> dict:
    """读取当前设置（带 mtime 缓存，保存后自动重新加载）。"""
    mtime = os.path.getmtime(SETTINGS_PATH) if os.path.exists(SETTINGS_PATH) else 0
    if _cache["mtime"] == mtime and _cache["data"] is not None:
        return _cache["data"]
    data = _read_file_settings()
    _cache["mtime"] = mtime
    _cache["data"] = data
    return data


def _write_settings(data: dict) -> None:
    tmp_path = SETTINGS_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, SETTINGS_PATH)
    _cache["mtime"] = os.path.getmtime(SETTINGS_PATH)
    _cache["data"] = data


def save_settings(patch: dict) -> dict:
    """浅层深合并补丁并落盘，返回合并后的完整设置。"""
    merged = _deep_merge(get_settings(), patch or {})
    _write_settings(merged)
    return merged


def reset_settings() -> dict:
    """恢复默认设置并落盘。"""
    _write_settings(DEFAULTS)
    return DEFAULTS


def get_scoring() -> dict:
    return get_settings().get("scoring") or DEFAULTS["scoring"]


def get_teachers() -> dict:
    return get_settings().get("teachers") or DEFAULTS["teachers"]


def get_teacher_config(teacher: str) -> dict:
    teachers = get_teachers()
    cfg = teachers.get(teacher) if teacher else None
    return cfg or teachers.get("liangliang") or DEFAULTS["teachers"]["liangliang"]


def get_api() -> dict:
    return get_settings().get("api") or DEFAULTS["api"]


def _read_env_key(name: str) -> str:
    key = os.environ.get(name)
    if key:
        return key
    if os.path.exists(_ENV_PATH):
        try:
            with open(_ENV_PATH, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith(name + "="):
                        return line.split("=", 1)[1]
        except OSError:
            pass
    return ""


def get_api_key(provider: str) -> str:
    """取指定 API 的密钥：设置文件优先，其次环境变量 / .env。"""
    api = get_api()
    cfg = api.get(provider) or {}
    key = cfg.get("api_key") or ""
    if key:
        return key
    env_name = _ENV_KEYS.get(provider)
    return _read_env_key(env_name) if env_name else ""


def mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return key[:3] + "*" * (len(key) - 6) + key[-3:]
