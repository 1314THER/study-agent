"""Optional local model hooks. A normal checkout contains no CLI implementation."""
from contextlib import contextmanager
from contextvars import ContextVar
import importlib.util
import os
from pathlib import Path
import threading

from fastapi import APIRouter, Depends, HTTPException, Request


ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / ".local-codex" / "provider.py"
UNAVAILABLE = "Codex CLI 仅限本地使用，云端暂不可用。"
_request_allowed = ContextVar("local_model_request_allowed", default=None)
_pipeline_caller = ContextVar("local_pipeline_caller", default=None)
_plugin = None
_load_lock = threading.Lock()


def enabled():
    return (os.environ.get("STUDY_LOCAL_CODEX") == "1"
            and not os.environ.get("STUDY_DEMO_ROOT")
            and PLUGIN.is_file() and _request_allowed.get() is not False)


def provider():
    if not enabled():
        raise HTTPException(503, UNAVAILABLE)
    global _plugin
    with _load_lock:
        if _plugin is None:
            spec = importlib.util.spec_from_file_location("study_local_model_provider", PLUGIN)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            _plugin = module
    return _plugin


@contextmanager
def request_context(request):
    host = request.url.hostname
    local = (request.client is not None
             and request.client.host in ("127.0.0.1", "::1", "testclient")
             and host in ("127.0.0.1", "localhost", "::1", "testserver")
             and not any(h in request.headers for h in ("forwarded", "x-forwarded-for", "x-study-demo-client")))
    token = _request_allowed.set(local)
    try:
        yield
    finally:
        _request_allowed.reset(token)


def validate_engine(engine):
    if engine not in ("deepseek", "codex_cli"):
        raise ValueError("解析方式无效。")
    if engine == "codex_cli":
        provider()
    return engine


@contextmanager
def pipeline(engine="deepseek"):
    validate_engine(engine)
    caller = provider().pipeline_caller() if engine == "codex_cli" else None
    token = _pipeline_caller.set(caller)
    try:
        yield
    finally:
        _pipeline_caller.reset(token)


def current_caller():
    return _pipeline_caller.get()


def call_teacher(system, user, *, model="gpt-6-astra", reasoning_effort="medium", image_content=None):
    """Use the installed private CLI adapter and the saved ChatGPT login."""
    from backend.identity import current_identity
    identity = current_identity()
    if identity and identity.get("role") != "owner":
        raise HTTPException(503, UNAVAILABLE)
    provider()  # Retain the local-only, non-proxied request boundary.
    try:
        from backend import routine_codex as codex
    except ImportError:
        raise HTTPException(503, UNAVAILABLE) from None
    from backend.jobs import ensure_active, provider_slot, request_timeout
    from backend.settings import get_limits
    if reasoning_effort not in ("low", "medium", "high", "xhigh"):
        raise ValueError("Codex 推理强度请选择低、中、高或极高")
    try:
        with provider_slot("codex"):
            return codex.run_prompt(
                system, user, task="数学老师", model=model, reasoning_effort=reasoning_effort,
                image_content=image_content,
                timeout=request_timeout(get_limits().get("api_timeout_seconds", 300)),
                ensure_active=ensure_active,
            )
    except codex.CodexUnavailable:
        raise HTTPException(503, "Codex CLI 暂不可用，请检查本机 ChatGPT 登录、模型权限及额度。") from None


def routine_config():
    return provider().routine_config()


def validate_routine_config(config):
    if config.get("engine") == "codex_luna":
        provider().validate_routine_config(config)


def _owner():
    from backend.question_pool import _require_owner
    _require_owner()


router = APIRouter(prefix="/local-models", tags=["本地模型"], dependencies=[Depends(_owner)])


@router.get("/status")
def status(request: Request):
    with request_context(request):
        available = enabled() and provider().available()
        return {"codex_cli": {"available": bool(available),
                              "detail": "本地 Codex CLI · 使用已登录账号额度" if available else UNAVAILABLE}}
