"""Cloud entrypoint. Requires Alembic upgrade before production startup."""
from contextlib import asynccontextmanager
import os
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from backend.auth import AccountGateway, AuthError, ROOT
from backend.storage.database import Database, repository_context
from backend.storage.repository import Repository
from backend.storage.accounts import CloudAccountStore
from backend.native_auth import DeviceTokens, NativeGateway
from backend.cloud_jobs import CloudJobs
from backend.api_v1 import build_router


def build_cloud_app(*, database=None, store=None, root=None, initialize=False, secure_cookie=None, origin=None):
    database = database or Database()
    if initialize:
        database.create_schema()
    root = Path(root or os.environ.get("STUDY_CLOUD_ROOT") or ROOT / ".cloud").resolve()
    store = store or CloudAccountStore(database, root)
    repo = Repository(database)
    repo.asset_root = root / "assets"
    tokens = DeviceTokens(database, store)
    worker = CloudJobs(repo, root / "assets")

    @asynccontextmanager
    async def lifespan(app):
        worker.recover()
        yield
        worker.close()
        database.engine.dispose()

    core = FastAPI(title="Study Coach", version="1.0", lifespan=lifespan)
    @core.exception_handler(AuthError)
    async def account_error(request, exc):
        return JSONResponse({"error": exc.code, "detail": exc.detail}, status_code=exc.status, headers={"Cache-Control": "no-store"})
    core.state.repository, core.state.tokens, core.state.jobs, core.state.store = repo, tokens, worker, store
    core.include_router(build_router(repo, worker, tokens, root / "assets"))

    @core.middleware("http")
    async def private_responses(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @core.get("/home.html")
    def home():
        return FileResponse(ROOT / "frontend" / "cloud.html")

    # Compatibility routes share the same repository. UUIDs are used in cloud
    # pages; old bookmarks can be resolved using the migration alias registry.
    @core.get("/questions")
    def legacy_questions():
        return repo.questions(200)["items"]

    @core.get("/questions/{question_id}")
    def legacy_question(question_id: str):
        return repo.question(repo.alias("questions.questions", question_id) or question_id)

    @core.get("/teach/session/{session_id}")
    def legacy_session(session_id: str):
        return repo.teaching(repo.alias("jobs.teaching_sessions", session_id) or session_id)

    @core.get("/legacy/{resource}/{legacy_id}")
    def resolve_legacy(resource: str, legacy_id: str):
        mapped = repo.alias(resource, legacy_id)
        if not mapped:
            raise HTTPException(404, "旧记录不存在")
        return {"id": mapped}

    @core.get("/question-assets/{name}")
    def legacy_asset(name: str):
        asset = repo.legacy_asset(name)
        path = (root / "assets" / asset["storage_key"]).resolve()
        if not path.is_relative_to(root / "assets") or not path.is_file():
            raise HTTPException(404, "题图不存在")
        return FileResponse(path, media_type=asset["media_type"])

    @core.get("/health")
    def health():
        return {"ok": True, "mode": "cloud", "storage": database.engine.dialect.name}

    # Old student deep links enter the new shared-service workspace. The local
    # SQLite application keeps its complete existing page set.
    @core.get("/{page}.html")
    def page(page: str):
        if page in ("login", "deepseek-guide"):
            return FileResponse(ROOT / "frontend" / (page + ".html"))
        return RedirectResponse("/home.html", status_code=303)

    core.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend")
    if secure_cookie is None:
        secure_cookie = os.environ.get("STUDY_AUTH_COOKIE_SECURE", "1") != "0"
    from backend.body_limit import BodyLimit
    limited_core = BodyLimit(core)
    browser = AccountGateway(limited_core, store, secure_cookie=secure_cookie, origin=origin or os.environ.get("STUDY_AUTH_ORIGIN"))
    gateway = NativeGateway(browser, limited_core, store, repo, tokens)
    gateway.state = core.state
    return gateway


def create_app():
    return build_cloud_app()
