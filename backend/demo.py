"""Public demo gateway. Run separately from the owner's backend, with one worker.

Each browser receives a short-lived, opaque cookie and a separate directory.
Demo data is seeded from versioned examples. AI uses a private, read-only
configuration; credentials are never written to visitor workspaces.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import threading
import time

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.responses import HTMLResponse

from backend.data_paths import background_lease, workspace


ROOT = Path(__file__).resolve().parent.parent
COOKIE = "__Host-study_demo"
MAX_BODY = 1024 * 1024
MAX_WORKSPACE = 16 * 1024 * 1024
MAX_UPLOAD_BODY = 18 * 1024 * 1024

# Explicitly allow only local features. New endpoints are private until reviewed.
LOCAL_ROUTES = {
    "GET": [
        r"/agent/context", r"/categories", r"/steps", r"/questions",
        r"/questions/(?:search|errors|[0-9]+)", r"/questions/[0-9]+/lists",
        r"/question-lists", r"/question-lists/(?:[0-9]+|all|wrong)/questions",
        r"/patterns", r"/patterns/calendar(?:\.ics)?", r"/patterns/[0-9]+/loop",
        r"/boards", r"/planner/board-order", r"/settings",
        r"/jobs(?:/[a-f0-9-]+)?", r"/demo/presets",
    ],
    "POST": [
        r"/jobs", r"/jobs/uploads",
        r"/questions/save", r"/questions/[0-9]+/(?:exam-touch|step-error|lists)",
        r"/questions/[0-9]+/step-errors/batch", r"/question-lists",
        r"/patterns/(?:mother|sync|export-yaml|match-wrong|calendar)",
        r"/patterns/[0-9]+/(?:questions|wrong|attempt|complete)",
        r"/planner/(?:plan|apply)", r"/teach/find", r"/settings/reset",
    ],
    "PUT": [
        r"/questions/[0-9]+/source-type", r"/question-lists/[0-9]+",
        r"/patterns/[0-9]+", r"/boards/[0-9]+", r"/planner/board-order",
    ],
    "DELETE": [
        r"/questions/[0-9]+", r"/questions/[0-9]+/step-error/[0-9]+",
        r"/questions/[0-9]+/lists/[0-9]+", r"/question-lists/[0-9]+",
        r"/patterns/[0-9]+", r"/patterns/[0-9]+/questions/[0-9]+",
        r"/patterns/calendar/[0-9]+",
    ],
}
AI_PATHS = re.compile(
    r"/(?:solve(?:/.*)?|agent/act|teach/(?!find$).*|grade(?:/.*)?|"
    r"multimodal/parse|ocr/answer|generate-jobs/.*|questions/ai-search|"
    r"questions/[0-9]+/generate(?:/async)?|exam/ai-assemble|"
    r"patterns/[0-9]+/(?:check|ensure-variants))$"
)
AI_ROUTES = {
    "POST": [
        r"/solve/step[123]", r"/agent/act", r"/teach/(?:start|check|session/start)",
        r"/teach/session/[a-f0-9-]{32,36}/(?:chat|ack)", r"/grade(?:/text)?",
        r"/multimodal/parse", r"/ocr/answer", r"/questions/[0-9]+/generate(?:/async)?",
        r"/questions/ai-search", r"/exam/ai-assemble",
        r"/patterns/[0-9]+/(?:check|ensure-variants)", r"/settings/test",
    ],
    "GET": [r"/teach/session/[a-f0-9-]{32,36}", r"/generate-jobs/[a-f0-9]{32}"],
}


class DemoBusy(Exception):
    pass


@dataclass
class Session:
    token: str
    directory: Path
    expires: float
    active: int = 0
    requests: deque = field(default_factory=deque)
    request_lock: object = None

    def public(self, ai_enabled=False):
        return {
            "session_id": self.token,
            "expires_at": datetime.fromtimestamp(self.expires, timezone.utc).isoformat(),
            "ai_enabled": ai_enabled,
        }


class SessionStore:
    def __init__(self, root: Path, *, ttl=7200, max_sessions=40, seed=ROOT / "demo-data", clock=time.time):
        self.root = Path(root)
        self.seed = Path(seed)
        self.ttl = ttl
        self.max_sessions = max_sessions
        self.clock = clock
        self.sessions = {}
        self.created = {}
        self.lock = threading.RLock()
        self.initialized = False
        self.background_jobs = threading.BoundedSemaphore(2)

    def prepare(self):
        with self.lock:
            if self.initialized:
                return
            if self.root.resolve() in (ROOT.resolve(), ROOT.parent.resolve()):
                raise RuntimeError("游客目录不能设为项目目录或其父目录")
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            # Keep unexpired visitor data and completed jobs across a service restart.
            for child in self.root.iterdir():
                if re.fullmatch(r"session-[a-f0-9]{32}", child.name) and not child.is_symlink():
                    try:
                        meta = json.loads((child / "session.json").read_text())
                        expires = float(meta["expires"])
                        if expires > self.clock():
                            token = child.name.removeprefix("session-")
                            self.sessions[token] = Session(token, child, expires)
                            continue
                    except (OSError, ValueError, KeyError, TypeError):
                        pass
                    shutil.rmtree(child)
            self.initialized = True

    def cleanup(self):
        now = self.clock()
        expired = []
        with self.lock:
            for token, session in list(self.sessions.items()):
                if session.expires <= now and session.active == 0:
                    self.sessions.pop(token, None)
                    expired.append(session)
            for client, times in list(self.created.items()):
                while times and times[0] <= now - 3600:
                    times.popleft()
                if not times:
                    del self.created[client]
        # Do not hold the visitor registry lock while acquiring task/teaching
        # locks. A background lease prevents an in-use workspace reaching here.
        for session in expired:
            from backend.teach import forget_workspace as clear_teaching
            from backend.generate import forget_workspace as clear_jobs
            clear_teaching(str(session.directory))
            clear_jobs(str(session.directory))
            shutil.rmtree(session.directory, ignore_errors=True)

    def _seed(self, directory):
        directory.mkdir(mode=0o700)
        try:
            for name in ("study_agent.db", "mastery.db"):
                source = self.seed / name
                with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as src:
                    with sqlite3.connect(str(directory / name)) as dst:
                        src.backup(dst)
            # Leave the versioned example question library, but clear learning history.
            with sqlite3.connect(str(directory / "study_agent.db")) as conn:
                for table in ("practice_records", "mistakes", "step_errors"):
                    conn.execute("DELETE FROM " + table)
                # Keep the conceptual mother question without private names or
                # jokes from the local development seed.
                question = "判断下列对象能否构成集合，并说明是有限集、无限集还是空集：\n(1) 很大的整数；\n(2) 满足 x²=-1 的实数；\n(3) 大于 0 且小于 5 的整数；\n(4) 所有整数。"
                answer = {
                    "status": "可解", "final_answer": "(1) 不能构成集合；(2) 空集；(3) 有限集；(4) 无限集。",
                    "knowledge_points": ["集合元素的确定性", "有限集、无限集与空集"],
                    "category": {"level1": "集合与逻辑用语", "level2": "集合的概念与性质"},
                    "chunk_results": [{"chunk_id": 1, "chunk_type": "大题", "category": {"level1": "集合与逻辑用语", "level2": "集合的概念与性质"},
                        "knowledge_points": ["集合元素的确定性"], "final_answer": "(1) 不能；(2) 空集；(3) 有限集；(4) 无限集。",
                        "steps": [{"step_number": 1, "title": "检查条件是否明确", "standard_writing": "‘很大’没有明确标准，不能确定元素是否属于该对象，因而不能构成集合。", "detailed_writing": "集合中的元素必须是确定的。对于任意整数，应能明确判断它是否满足条件。"},
                                  {"step_number": 2, "title": "按元素个数分类", "standard_writing": "实数范围内 x²=-1 无解，构成空集；大于0且小于5的整数为1、2、3、4，构成有限集；整数有无限多个，构成无限集。", "detailed_writing": "条件明确但没有元素仍然是集合，即空集。有限和无限描述元素的个数。"}]}],
                }
                conn.execute("UPDATE questions SET content=?, answer_json=? WHERE lower(content) LIKE '%coco%'",
                             (question, json.dumps(answer, ensure_ascii=False)))
                from backend.database import _build_steps_structure, _index_question_steps
                for (question_id,) in conn.execute("SELECT id FROM questions WHERE content=?", (question,)).fetchall():
                    conn.execute("UPDATE questions SET steps_structure=? WHERE id=?",
                                 (_build_steps_structure(answer["chunk_results"]), question_id))
                    _index_question_steps(conn, question_id, chunk_results=answer["chunk_results"])
                # Example source provenance must not expose the local owner's name.
                for question_id, source_text, answer_text in conn.execute("SELECT id, source_meta, answer_json FROM questions").fetchall():
                    source = json.loads(source_text or "{}")
                    if isinstance(source, dict) and "owner" in source:
                        source.pop("owner", None)
                        conn.execute("UPDATE questions SET source_meta=? WHERE id=?",
                                     (json.dumps(source, ensure_ascii=False), question_id))
                    parsed = json.loads(answer_text or "{}")
                    changed = False
                    if isinstance(parsed, dict):
                        meta = parsed.get("source_meta")
                        if isinstance(meta, dict) and "owner" in meta:
                            meta.pop("owner", None)
                            changed = True
                        for chunk in parsed.get("chunk_results", []) or []:
                            meta = chunk.get("source_meta") if isinstance(chunk, dict) else None
                            if isinstance(meta, dict) and "owner" in meta:
                                meta.pop("owner", None)
                                changed = True
                    if changed:
                        conn.execute("UPDATE questions SET answer_json=? WHERE id=?",
                                     (json.dumps(parsed, ensure_ascii=False), question_id))
            with sqlite3.connect(str(directory / "mastery.db")) as conn:
                conn.execute("DELETE FROM attempts")
                for table in ("loop_rounds", "loop_job_results"):
                    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                        conn.execute("DELETE FROM " + table)
                conn.execute("UPDATE pattern_mastery SET state='never', need_check=0, "
                             "next_check_at=NULL, last_completed_at=NULL")
                conn.execute("UPDATE category_mastery SET mastered_patterns=0, percent=0")
                conn.execute("UPDATE patterns SET name='集合关系拓展示例' WHERE name='1'")
                conn.execute("UPDATE patterns SET name='集合运算拓展示例' WHERE name='123'")
            # DB rows contain the example patterns. Never copy mutable owner YAML.
            (directory / "patterns.yaml").write_text("{}\n", encoding="utf-8")
            (directory / "board_order.yaml").write_text("board_order: []\n", encoding="utf-8")
            (directory / "settings.json").write_text("{}\n", encoding="utf-8")
            with workspace(directory):
                from backend.database import init_db
                from backend.patterns import init_mastery_db, export_patterns_yaml
                init_db()
                init_mastery_db()
                export_patterns_yaml()
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise

    def acquire(self, token, client, *, create=False):
        self.prepare()
        self.cleanup()
        now = self.clock()
        with self.lock:
            session = self.sessions.get(token or "")
            if session is None or session.expires <= now:
                if not create:
                    return None, False
                if sum(s.expires > now for s in self.sessions.values()) >= self.max_sessions:
                    raise DemoBusy("体验人数已达上限，请稍后再试。")
                times = self.created.setdefault(client, deque())
                if len(times) >= 10:
                    raise DemoBusy("新建体验过于频繁，请稍后再试。")
                token = secrets.token_hex(16)
                session = Session(token, self.root / ("session-" + token), now + self.ttl)
                self._seed(session.directory)
                (session.directory / "session.json").write_text(json.dumps({"expires": session.expires}), encoding="utf-8")
                self.sessions[token] = session
                times.append(now)
                fresh = True
            else:
                fresh = False
            while session.requests and session.requests[0] <= now - 60:
                session.requests.popleft()
            if len(session.requests) >= 120:
                raise DemoBusy("操作过于频繁，请稍等一分钟。")
            session.requests.append(now)
            session.active += 1
            return session, fresh

    def release(self, session):
        with self.lock:
            session.active -= 1
        self.cleanup()

    def expire(self, session):
        with self.lock:
            session.expires = 0
            (session.directory / "session.json").write_text('{"expires":0}', encoding="utf-8")

    def borrow(self, session):
        # The common job executor limits running work. A lease only retains data.
        with self.lock:
            session.active += 1
        done = False

        def release():
            nonlocal done
            if not done:
                done = True
                self.release(session)
        return release


class DemoGateway:
    def __init__(self, application, store, *, ai_enabled=False, local_preview=False):
        self.application = application
        self.store = store
        self.ai_enabled = ai_enabled
        self.local_preview = local_preview
        self.ai_requests = threading.BoundedSemaphore(2)

    def cookie_options(self, request):
        local_http = self.local_preview and request.url.hostname in ("localhost", "127.0.0.1", "::1") and request.url.scheme == "http"
        return ("study_demo_local", False) if local_http else (COOKIE, True)

    def ai_route(self, method, path):
        return self.ai_enabled and any(re.fullmatch(p, path) for p in AI_ROUTES.get(method, []))

    @staticmethod
    def error(code, detail, status=403):
        return JSONResponse({"error": code, "detail": detail}, status_code=status,
                            headers={"Cache-Control": "no-store"})

    def static(self, path):
        # Static files are served only from the frontend directory, with no traversal.
        candidate = (ROOT / "frontend" / path.lstrip("/")).resolve()
        return candidate.is_relative_to((ROOT / "frontend").resolve()) and candidate.is_file()

    def allowed(self, method, path):
        if method in ("GET", "HEAD") and (path == "/" or self.static(path)):
            return True
        if method == "HEAD":
            method = "GET"
        return self.ai_route(method, path) or any(re.fullmatch(pattern, path) for pattern in LOCAL_ROUTES.get(method, []))

    async def __call__(self, scope, receive, send):
        heavy = scope["type"] == "http" and scope["method"] == "POST" and self.ai_route(scope["method"], scope["path"])
        if heavy and not self.ai_requests.acquire(blocking=False):
            await self.error("demo_busy", "当前 AI 正在处理其他请求，请稍后再试。", 429)(scope, receive, send)
            return
        try:
            await self.handle_request(scope, receive, send)
        finally:
            if heavy:
                self.ai_requests.release()

    async def handle_request(self, scope, receive, send):
        if scope["type"] == "lifespan":
            await self.lifespan(scope, receive, send)
            return
        if scope["type"] != "http":
            await send({"type": "websocket.close", "code": 1008})
            return
        request = Request(scope, receive)
        path = scope["path"]
        if path == "/health" and request.method == "GET":
            await JSONResponse({"mode": "demo", "ai_enabled": self.ai_enabled})(scope, receive, send)
            return
        if path.startswith("/_internal/"):
            with workspace(self.store.root / "bootstrap"):
                await self.application(scope, receive, send)
            return
        reset = path == "/demo/reset" and request.method == "POST"
        if path in ("/jobs", "/jobs/uploads") and request.method == "POST" and not self.ai_enabled:
            await self.error("demo_ai_disabled", "游客 AI 暂未开放。")(scope, receive, send)
            return
        if not reset and not self.allowed(request.method, path):
            if AI_PATHS.fullmatch(path):
                response = self.error("demo_ai_disabled", "游客体验暂未开放付费 AI。可以查看已有解析、编辑题库和组卷。")
            elif path.startswith("/settings"):
                response = self.error("demo_settings_locked", "游客不能更改服务商或 API 密钥；你的体验题库可以自由编辑。")
            else:
                response = self.error("demo_unavailable", "此功能暂未开放游客体验。")
            await response(scope, receive, send)
            return
        if request.method not in ("GET", "HEAD"):
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                await self.error("demo_origin_invalid", "请在游客体验页面内操作。")(scope, receive, send)
                return
        body = bytearray()
        max_body = MAX_UPLOAD_BODY if path in ("/multimodal/parse", "/ocr/answer", "/jobs/uploads") else MAX_BODY
        if request.method not in ("GET", "HEAD"):
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > max_body:
                    await self.error("demo_body_too_large", "上传文件请控制在 16 MB 内，文字提交请控制在 1 MB 内。", 413)(scope, receive, send)
                    return
        delivered = False

        async def replay_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        html = request.method == "GET" and (path == "/" or path.endswith(".html"))
        static = request.method in ("GET", "HEAD") and self.static(path) and not path.endswith(".html")
        if static:
            with workspace(self.store.root / "bootstrap"):
                await self.application(scope, receive, send)
            return
        client = request.headers.get("x-study-demo-client") or (request.client.host if request.client else "local")
        cookie_name, cookie_secure = self.cookie_options(request)
        try:
            session, fresh = await asyncio.to_thread(self.store.acquire, request.cookies.get(cookie_name), client, create=html)
        except DemoBusy as exc:
            await self.error("demo_busy", str(exc), 429)(scope, receive, send)
            return
        if session is None:
            code = "demo_session_expired" if request.cookies.get(cookie_name) else "demo_session_required"
            await self.error(code, "体验已结束，请返回游客首页重新开始。", 401)(scope, receive, send)
            return
        try:
            expected = request.headers.get("x-demo-session")
            if expected and expected != session.token:
                await self.error("demo_session_expired", "体验已在其他标签页重置，请刷新本页。", 401)(scope, receive, send)
                return
            # asyncio.Lock must be constructed on the event loop (Python 3.9).
            if session.request_lock is None:
                session.request_lock = asyncio.Lock()
            async with session.request_lock:
                if session.expires <= self.store.clock():
                    await self.error("demo_session_expired", "本次体验已结束或已在其他页面重置，请重新进入。", 401)(scope, receive, send)
                    return
                if reset:
                    self.store.expire(session)
                    try:
                        new, _ = await asyncio.to_thread(self.store.acquire, None, client, create=True)
                    except DemoBusy as exc:
                        await self.error("demo_busy", str(exc), 429)(scope, receive, send)
                        return
                    response = JSONResponse({"reset": True}, headers={"Cache-Control": "no-store"})
                    self.set_cookie(response, new, cookie_name, cookie_secure)
                    self.store.release(new)
                    await response(scope, receive, send)
                    return
                if request.method not in ("GET", "HEAD") and sum(p.stat().st_size for p in session.directory.rglob('*') if p.is_file()) > MAX_WORKSPACE:
                    await self.error("demo_storage_full", "体验数据已达上限，请重置体验。", 413)(scope, receive, send)
                    return
                await self.forward(scope, replay_receive, send, session, fresh, cookie_name, cookie_secure)
        finally:
            self.store.release(session)

    @staticmethod
    def set_cookie(response, session, name=COOKIE, secure=True):
        response.set_cookie(name, session.token, max_age=max(1, int(session.expires - time.time())),
                            secure=secure, httponly=True, samesite="strict", path="/")

    async def forward(self, scope, receive, send, session, fresh, cookie_name=COOKIE, cookie_secure=True):
        start = None
        chunks = []
        is_html = False

        async def wrapped_send(message):
            nonlocal start, is_html
            if message["type"] == "http.response.start":
                start = dict(message)
                headers = [(k, v) for k, v in start["headers"] if k.lower() not in (b"cache-control", b"etag", b"last-modified")]
                headers.append((b"cache-control", b"no-store"))
                if fresh:
                    cookie_response = JSONResponse({})
                    self.set_cookie(cookie_response, session, cookie_name, cookie_secure)
                    headers.extend((k, v) for k, v in cookie_response.raw_headers if k == b"set-cookie")
                start["headers"] = headers
                is_html = scope["method"] == "GET" and any(k == b"content-type" and b"text/html" in v for k, v in headers)
                if not is_html:
                    await send(start)
            elif message["type"] == "http.response.body" and is_html:
                chunks.append(message.get("body", b""))
                if not message.get("more_body", False):
                    data = b"".join(chunks)
                    boot = ('<script>window.STUDY_DEMO=' + json.dumps(session.public(self.ai_enabled), ensure_ascii=True) +
                            ';</script><script src="/demo-session.js?v=20261009a"></script>').encode()
                    data = re.sub(br"(<head\b[^>]*>)", lambda match: match.group(1) + boot, data, count=1, flags=re.I)
                    start["headers"] = [(k, v) for k, v in start["headers"] if k != b"content-length"]
                    start["headers"].append((b"content-length", str(len(data)).encode()))
                    await send(start)
                    await send({"type": "http.response.body", "body": data})
            else:
                await send(message)

        with workspace(session.directory), background_lease(lambda: self.store.borrow(session)):
            unfinished = {
                "/grade.html": ("AI 改卷", "计划对照解题步骤检查学生作答，给出评分和错因反馈。"),
                "/mother.html": ("母题看板", "计划把代表性题目和知识套路组织成可浏览的学习地图。"),
                "/loop.html": ("套路循环", "计划通过母题、变式和定期复习巩固同一类解题方法。"),
                "/level-editor.html": ("关卡编辑", "计划支持教师编排关卡、关联套路和设置练习顺序。"),
            }
            if scope["method"] in ("GET", "HEAD") and scope["path"] in ("/", "/home.html", "/demo-home.html"):
                page = (ROOT / "frontend" / "demo-home.html").read_text(encoding="utf-8")
                response = HTMLResponse(page)
                if scope["method"] == "HEAD":
                    response.body = b""
                await response(scope, receive, wrapped_send)
            elif scope["method"] == "GET" and scope["path"] in unfinished:
                title, description = unfinished[scope["path"]]
                page = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><script src="/jobs.js?v=20261009a"></script><link rel="stylesheet" href="/style.css"></head><body class="demo-unfinished"><main style="max-width:720px;margin:100px auto;padding:28px"><a href="/home.html">返回首页</a><h1>{title}</h1><h2>暂未开发完成</h2><p>{description}</p><p><a href="/multimodal.html">体验多模态解答</a> · <a href="/history.html">个人题库</a> · <a href="/exam.html">组卷</a> · <a href="/board.html">集合闯关</a></p></main><script src="/nav.js"></script></body></html>'''
                await HTMLResponse(page)(scope, receive, wrapped_send)
            else:
                await self.application(scope, receive, wrapped_send)

    async def lifespan(self, scope, receive, send):
        self.store.prepare()
        bootstrap = self.store.root / "bootstrap"
        bootstrap.mkdir(exist_ok=True, mode=0o700)
        cleanup_task = None

        async def housekeeping():
            while True:
                await asyncio.sleep(60)
                await asyncio.to_thread(self.store.cleanup)

        async def lifespan_send(message):
            nonlocal cleanup_task
            if message["type"] == "lifespan.startup.complete":
                cleanup_task = asyncio.create_task(housekeeping())
            await send(message)

        try:
            with workspace(bootstrap):
                await self.application(scope, receive, lifespan_send)
        finally:
            if cleanup_task is not None:
                cleanup_task.cancel()
                try:
                    await cleanup_task
                except asyncio.CancelledError:
                    pass


def create_app(directory=None, *, ai_enabled=None, local_preview=None, **store_options):
    # Import after environment is established, so the demo has its own log path.
    root = directory or os.environ.get("STUDY_DEMO_ROOT", str(ROOT / ".demo-sessions"))
    os.environ.setdefault("STUDY_AGENT_LOG_DIR", str(Path(root) / "logs"))
    from backend.main import app as main_app
    if ai_enabled is None:
        ai_enabled = os.environ.get("STUDY_DEMO_AI_ENABLED", "1") == "1"
    if local_preview is None:
        local_preview = os.environ.get("STUDY_DEMO_LOCAL_PREVIEW", "0") == "1"
    return DemoGateway(main_app, SessionStore(Path(root), **store_options), ai_enabled=ai_enabled, local_preview=local_preview)


app = create_app()
