"""运行时设置：评分公式 / 老师模型 / API 密钥。

设置保存在 backend/settings.json，保存后无需重启即热生效。
注册账号的 API 密钥保存在中央账户库中；普通用户不继承主人的密钥。
游客启用共享 AI 时，仅使用管理员指定的只读配置，不继承主人的环境。
"""

import json
import os
from copy import deepcopy

from backend.data_paths import data_path, shared_ai_config_path, workspace_directory


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
            "solver": {"model": "deepseek-flash", "reasoning_effort": None},
            "verifier": {"model": "deepseek-flash", "reasoning_effort": "low"},
            "formatter": {"model": "deepseek-flash", "reasoning_effort": "low"},
            "grade": {"model": "deepseek-flash", "reasoning_effort": "low"},
        },
        "taotao": {
            "solver": {"model": "deepseek-v4-pro", "reasoning_effort": "low"},
            "verifier": {"model": "deepseek-flash", "reasoning_effort": "medium"},
            "formatter": {"model": "deepseek-flash", "reasoning_effort": "low"},
            "grade": {"model": "deepseek-flash", "reasoning_effort": "medium"},
        },
        "xuefeng": {
            "solver": {"model": "deepseek-v4-pro", "reasoning_effort": "high"},
            "verifier": {"model": "deepseek-flash", "reasoning_effort": "medium"},
            "formatter": {"model": "deepseek-flash", "reasoning_effort": "low"},
            "grade": {"model": "deepseek-flash", "reasoning_effort": "medium"},
        },
        "ji": {
            "solver": {"model": "deepseek-v4-pro", "reasoning_effort": "high"},
            "verifier": {"model": "deepseek-flash", "reasoning_effort": "high"},
            "formatter": {"model": "deepseek-flash", "reasoning_effort": "high"},
            "grade": {"model": "deepseek-flash", "reasoning_effort": "high"},
        },
    },
    "api": {
        "deepseek": {
            "base_url": "https://api.deepseek.com/v1",
            "vision_model": "deepseek-flash",
            "api_key": "",
        },
    },
    "limits": {
        "api_max_tokens": 32000,
        "api_timeout_seconds": 300,
        "multimodal_max_tokens": 16384,
        "multimodal_timeout_seconds": 180,
        "multimodal_concurrency": 7,
        "generate_concurrency": 5,
        "generate_count": 3,
        "pattern_default_max_time_seconds": 120,
        "search_default_limit": 200,
        "ai_search_limit": 20,
    },
}

_ENV_KEYS = {
    "deepseek": "DEEPSEEK_API_KEY",
}

# Indexed by the resolved file; visitors may have identically timestamped files.
_cache = {}


def _deep_merge(base, patch):
    if not isinstance(base, dict) or not isinstance(patch, dict):
        return patch
    out = dict(base)
    for key, value in patch.items():
        out[key] = _deep_merge(base.get(key), value) if isinstance(base.get(key), dict) and isinstance(value, dict) else value
    return out


def _current_identity():
    from backend.identity import current_identity
    return current_identity()


def _account_api_key():
    from backend.auth import current_account_api_key
    return current_account_api_key()


def _migrate_settings(data):
    """Drop the retired provider and use the current Flash model name.

    This operates on a copy. Reading legacy settings never exposes or copies
    a DashScope credential into another provider or workspace.
    """
    data = deepcopy(data)
    api = data.get("api")
    if isinstance(api, dict):
        data["api"] = {"deepseek": api.get("deepseek", {})}
        cfg = data["api"]["deepseek"]
        if isinstance(cfg, dict):
            cfg.pop("model", None)
            if cfg.get("vision_model") in ("deepseek-v4-flash", "deepseek-v4-flash-vision-exp") or str(cfg.get("vision_model", "")).lower().startswith("qwen"):
                cfg["vision_model"] = "deepseek-flash"
    for cfg in (data.get("teachers") or {}).values():
        if not isinstance(cfg, dict):
            continue
        for stage in cfg.values():
            if isinstance(stage, dict) and (stage.get("model") in ("deepseek-v4-flash", "deepseek-v4-flash-vision-exp") or str(stage.get("model", "")).lower().startswith("qwen")):
                stage["model"] = "deepseek-flash"
    return data


def _read_shared_ai_settings():
    """Read trusted AI configuration without caching or copying its secrets.

    Only a server environment variable selects this file. Visitor settings
    cannot select it, change shared endpoints, or write back to it.
    """
    identity = _current_identity()
    if identity and identity.get("role") in ("owner", "user"):
        return None
    path = shared_ai_config_path()
    if path is None:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        # A configured but missing/invalid snapshot disables shared credentials;
        # it must not silently switch to visitor-selected endpoints and keys.
        return {}
    if not isinstance(data, dict) or not isinstance(data.get("api"), dict):
        return {}
    return _migrate_settings({
        section: deepcopy(data[section])
        for section in ("api", "teachers", "limits")
        if isinstance(data.get(section), dict)
    })


def _shared_api(shared: dict) -> dict:
    """Use trusted provider values exclusively, including their endpoints."""
    api = deepcopy(DEFAULTS["api"])
    for provider, defaults in api.items():
        cfg = shared.get("api", {}).get(provider)
        if isinstance(cfg, dict):
            api[provider] = _deep_merge(defaults, cfg)
    return api


def shared_ai_enabled() -> bool:
    """Whether this workspace can use at least one administrator AI key."""
    identity = _current_identity()
    if identity and identity.get("role") in ("owner", "user"):
        return False
    shared = _read_shared_ai_settings()
    if shared is None:
        return False
    return any(
        isinstance(cfg.get("api_key"), str) and bool(cfg["api_key"].strip())
        for cfg in _shared_api(shared).values()
    )


def _read_file_settings(path=None):
    path = path if path is not None else data_path("settings.json", SETTINGS_PATH)
    defaults = deepcopy(DEFAULTS)
    if not os.path.exists(path):
        return defaults
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return _deep_merge(defaults, _migrate_settings(data)) if isinstance(data, dict) else defaults
    except (json.JSONDecodeError, OSError):
        return defaults


def get_settings() -> dict:
    """读取当前设置（带 mtime 缓存，保存后自动重新加载）。"""
    path = os.path.abspath(data_path("settings.json", SETTINGS_PATH))
    mtime = os.stat(path).st_mtime_ns if os.path.exists(path) else None
    cached = _cache.get(path)
    if cached and cached["mtime"] == mtime:
        return cached["data"]
    data = _read_file_settings(path)
    _cache[path] = {"mtime": mtime, "data": data}
    # Expired demo workspaces must not accumulate an unlimited settings cache.
    if len(_cache) > 128:
        _cache.pop(next(iter(_cache)))
    return data


def _write_settings(data: dict) -> None:
    path = os.path.abspath(data_path("settings.json", SETTINGS_PATH))
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)
    _cache[path] = {"mtime": os.stat(path).st_mtime_ns, "data": data}


def save_settings(patch: dict) -> dict:
    """浅层深合并补丁并落盘，返回合并后的完整设置。"""
    patch = _migrate_settings(patch or {})
    identity = _current_identity()
    if identity and identity.get("role") in ("owner", "user"):
        cfg = (patch.get("api") or {}).get("deepseek") or {}
        key = cfg.pop("api_key", None)
        if isinstance(key, str) and key.strip():
            from backend.auth import set_current_account_api_key
            set_current_account_api_key(key.strip())
    merged = _migrate_settings(_deep_merge(get_settings(), patch))
    if identity and identity.get("role") in ("owner", "user"):
        merged["api"]["deepseek"]["api_key"] = ""
    _write_settings(merged)
    return merged


def reset_settings() -> dict:
    """恢复默认设置并落盘。"""
    defaults = deepcopy(DEFAULTS)
    _write_settings(defaults)
    return defaults


def get_scoring() -> dict:
    return get_settings().get("scoring") or DEFAULTS["scoring"]


def get_teachers() -> dict:
    identity = _current_identity()
    shared = None if identity and identity.get("role") in ("owner", "user") else _read_shared_ai_settings()
    if shared is not None:
        return _deep_merge(deepcopy(DEFAULTS["teachers"]), shared.get("teachers", {}))
    return get_settings().get("teachers") or DEFAULTS["teachers"]


def get_teacher_config(teacher: str) -> dict:
    teachers = get_teachers()
    cfg = teachers.get(teacher) if teacher else None
    return cfg or teachers.get("liangliang") or DEFAULTS["teachers"]["liangliang"]


def get_api() -> dict:
    identity = _current_identity()
    if identity and identity.get("role") == "user":
        # Account keys are sent only to the official, server-controlled endpoint.
        return deepcopy(DEFAULTS["api"])
    shared = None if identity and identity.get("role") == "owner" else _read_shared_ai_settings()
    if shared is not None:
        return _shared_api(shared)
    return get_settings().get("api") or DEFAULTS["api"]


def get_limits() -> dict:
    identity = _current_identity()
    shared = None if identity and identity.get("role") in ("owner", "user") else _read_shared_ai_settings()
    if shared is not None:
        # Shared AI budgets and concurrency remain controlled by the owner.
        return _deep_merge(deepcopy(DEFAULTS["limits"]), shared.get("limits", {}))
    return get_settings().get("limits") or DEFAULTS["limits"]


def _read_env_key(name: str) -> str:
    # Only the authenticated owner or private legacy process may use its env.
    identity = _current_identity()
    if (identity and identity.get("role") == "owner") or workspace_directory() is None:
        key = os.environ.get(name)
        if key:
            return key
    env_path = data_path(".env", _ENV_PATH)
    if os.path.exists(env_path):
        try:
            with open(env_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith(name + "="):
                        return line.split("=", 1)[1]
        except OSError:
            pass
    return ""


def get_api_key(provider: str) -> str:
    """Account keys take precedence; users never fall back to shared secrets."""
    if provider != "deepseek":
        return ""
    identity = _current_identity()
    if identity and identity.get("role") in ("owner", "user"):
        key = _account_api_key()
        if key or identity.get("role") == "user":
            return key
    shared = None if identity and identity.get("role") == "owner" else _read_shared_ai_settings()
    if shared is not None:
        key = (_shared_api(shared).get(provider) or {}).get("api_key")
        return key.strip() if isinstance(key, str) else ""
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
