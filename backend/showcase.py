"""Read-only project showcase, independent of teaching, AI and owner data.

Run this application on the demo service's existing loopback port. The only
state is the in-memory deployment drain flag; no visitor workspace is created.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import threading

from fastapi import FastAPI, Request
from starlette.datastructures import MutableHeaders
from starlette.responses import FileResponse, JSONResponse, RedirectResponse


FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
HOME_PATHS = {"/", "/home.html", "/demo-home.html", "/showcase/index.html"}
LEGACY_ANCHORS = {
    "/index.html": "solution", "/multimodal.html": "solution",
    "/teach.html": "teaching", "/grade.html": "diagnosis",
    "/routine-graph.html": "graph", "/routine-review.html": "pool",
    "/question-pool.html": "pool", "/mother.html": "research",
    "/loop.html": "research", "/level-editor.html": "research",
    "/history.html": "library", "/exam.html": "library",
    "/calendar.html": "library", "/board.html": "research",
    "/settings.html": "research", "/deepseek-guide.html": "research",
    "/login.html": "overview",
}
ASSET_PATHS = {
    "/showcase/style.css", "/showcase/app.js", "/showcase/data.json",
    "/showcase/assets/ellipse-question.svg", "/showcase/assets/ellipse-page.svg",
    "/showcase/assets/pyramid-question.svg", "/showcase/assets/pyramid-page.svg",
    "/showcase/assets/student-paper.pdf", "/showcase/assets/teacher-paper.pdf",
    "/style.css", "/routine-graph.css", "/dimchart.js", "/radar.js", "/launch-lettering.svg",
    "/geometry.js", "/geometry.css",
    "/vendor/katex/katex.min.js", "/vendor/katex/katex.min.css",
    "/vendor/three-0.180.0/build/three.module.min.js",
    "/vendor/three-0.180.0/build/three.core.min.js",
    "/vendor/three-0.180.0/examples/jsm/controls/OrbitControls.js",
    "/vendor/jsxgraph-1.11.1/distrib/jsxgraphcore.js",
    "/vendor/jsxgraph-1.11.1/distrib/jsxgraph.css",
}
ASSET_PATHS.update("/vendor/katex/fonts/KaTeX_" + name + ".woff2" for name in (
    "AMS-Regular", "Caligraphic-Bold", "Caligraphic-Regular", "Fraktur-Bold",
    "Fraktur-Regular", "Main-Bold", "Main-BoldItalic", "Main-Italic",
    "Main-Regular", "Math-BoldItalic", "Math-Italic", "SansSerif-Bold",
    "SansSerif-Italic", "SansSerif-Regular", "Script-Regular", "Size1-Regular",
    "Size2-Regular", "Size3-Regular", "Size4-Regular", "Typewriter-Regular",
))
MAX_DRAIN_BODY = 256


class ShowcaseBoundary:
    """Count requests through the last ASGI body send, including cancellation."""

    def __init__(self, app, *, state, lock):
        self.app = app
        self.state = state
        self.lock = lock

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        path = scope["path"]
        internal = path.startswith("/_internal/")
        if internal:
            forwarded = any(name == "forwarded" or name.startswith("x-forwarded-") or
                            name in ("x-study-demo-client", "x-real-ip") for name in request.headers)
            if not request.client or request.client.host not in ("127.0.0.1", "::1") or forwarded:
                await JSONResponse({"detail": "Not found"}, status_code=404)(scope, receive, send)
                return
        counted = not internal and path != "/health"
        if counted:
            with self.lock:
                self.state.active_requests += 1

        async def public_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
                headers["Cache-Control"] = "no-cache" if path in HOME_PATHS else "no-store"
            await send(message)

        try:
            await self.app(scope, receive, public_headers)
        finally:
            if counted:
                with self.lock:
                    self.state.active_requests -= 1


def create_app(frontend: Path = FRONTEND, *, draining: bool | None = None) -> FastAPI:
    app = FastAPI(title="登辉项目展示", docs_url=None, redoc_url=None, openapi_url=None)
    root = Path(frontend).resolve()
    lock = threading.Lock()
    app.state.active_requests = 0
    app.state.draining = os.environ.get("STUDY_DEPLOY_DRAIN", "0") == "1" if draining is None else draining
    app.add_middleware(ShowcaseBoundary, state=app.state, lock=lock)

    def status():
        with lock:
            return {"active_requests": app.state.active_requests, "active_jobs": 0,
                    "draining": app.state.draining, "mode": "demo", "demo_mode": "showcase"}

    @app.api_route("/health", methods=["GET", "HEAD"])
    async def health():
        return {"ok": True, "mode": "demo", "demo_mode": "showcase", "ai_enabled": False}

    @app.get("/_internal/deploy-status")
    async def deploy_status():
        return status()

    @app.post("/_internal/deploy-drain")
    async def deploy_drain(request: Request):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_DRAIN_BODY:
                return JSONResponse({"detail": "Invalid drain state"}, status_code=413)
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            return JSONResponse({"detail": "Invalid drain state"}, status_code=400)
        if not isinstance(payload, dict) or set(payload) != {"draining"} or type(payload["draining"]) is not bool:
            return JSONResponse({"detail": "Invalid drain state"}, status_code=400)
        with lock:
            app.state.draining = payload["draining"]
        return status()

    @app.api_route("/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT"])
    async def public(request: Request, path: str):
        if request.method not in ("GET", "HEAD"):
            return JSONResponse({"detail": "This showcase has no teaching or write API"}, status_code=404)
        url_path = "/" + path
        if url_path in LEGACY_ANCHORS:
            return RedirectResponse("/#" + LEGACY_ANCHORS[url_path], status_code=307)
        if url_path in HOME_PATHS:
            relative = Path("showcase/index.html")
        elif url_path in ASSET_PATHS:
            relative = Path(path)
        else:
            return JSONResponse({"detail": "Not found"}, status_code=404)
        target = root / relative
        # No symlinks, traversal or dynamic directory mounts can expose private
        # files even if a reviewed public asset is later replaced on disk.
        if any((root / Path(*relative.parts[:i])).is_symlink() for i in range(1, len(relative.parts) + 1)):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        try:
            target.resolve().relative_to(root)
        except ValueError:
            return JSONResponse({"detail": "Not found"}, status_code=404)
        if not target.is_file():
            return JSONResponse({"detail": "Not found"}, status_code=404)
        return FileResponse(target, method=request.method)

    return app


app = create_app()
