"""The student API contract, shared by web and all Apple clients."""
import hashlib
from pathlib import Path
import time
from uuid import UUID
from fastapi import APIRouter, UploadFile, File, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, update
from backend.auth import current_account_api_key, set_current_account_api_key
from backend.identity import current_identity, current_user_id, require_catalog_editor
from backend.storage import models as m
from backend.storage.repository import uid, rowdict


class QuestionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=100000)
    answer_json: dict = Field(default_factory=dict)
    public: bool = False
    expected_revision: int | None = None


class JobInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str
    args: dict = Field(default_factory=dict)
    request_id: str = Field(min_length=8, max_length=128)


class KeyInput(BaseModel):
    api_key: str


class AdminRecordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(max_length=80, pattern=r"^(pool|review|templates)\.[a-z_]+$")
    external_id: str = Field(min_length=1, max_length=512)
    data: dict


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)
    status: str = Field(pattern="^(confirmed|deferred|rejected)$")


def build_router(repo, jobs, tokens, asset_root):
    router = APIRouter(prefix="/api/v1")
    root = Path(asset_root).resolve()

    @router.get("/auth/me")
    def me():
        return {"authenticated": True, "user": current_identity()}

    @router.get("/auth/devices")
    def devices():
        return {"items": tokens.sessions()}

    @router.delete("/auth/devices/{device_id}")
    def revoke(device_id: UUID):
        tokens.revoke(str(device_id))
        return {"revoked": True}

    @router.put("/auth/api-key")
    def api_key(body: KeyInput):
        set_current_account_api_key(body.api_key)
        return {"api_key_configured": True}

    @router.get("/questions")
    def questions(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), q: str = Query("", max_length=500), wrong: bool = False):
        return repo.questions(limit, offset, q, wrong)

    @router.post("/questions", status_code=201)
    def save_question(body: QuestionInput):
        return repo.save_question(body.content, body.answer_json, public=body.public)

    @router.get("/questions/{question_id}")
    def question(question_id: UUID):
        return repo.question(str(question_id))

    @router.get("/questions/{question_id}/versions/{revision}")
    def historical_question(question_id: UUID, revision: int):
        if revision < 1:
            raise HTTPException(422, "题目版本号无效")
        return repo.question_version(str(question_id), revision)

    @router.put("/questions/{question_id}")
    def update_question(question_id: UUID, body: QuestionInput):
        if body.expected_revision is None:
            raise HTTPException(422, "修改题目必须携带版本号")
        return repo.save_question(body.content, body.answer_json, question_id=str(question_id), expected_revision=body.expected_revision)

    @router.delete("/questions/{question_id}")
    def withdraw(question_id: UUID):
        repo.withdraw_question(str(question_id))
        return {"withdrawn": True}

    @router.get("/attempts")
    def attempts(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
        return repo.attempts(limit, offset)

    @router.get("/progress")
    def progress():
        return repo.progress()

    @router.get("/teaching")
    def teaching_list(limit: int = Query(50, ge=1, le=200)):
        with repo.db.transaction() as c:
            rows = c.execute(select(m.teaching_sessions).where(m.teaching_sessions.c.user_id == current_user_id()).order_by(m.teaching_sessions.c.updated_at.desc()).limit(limit))
            return {"items": [{**r.state_json, "revision": r.revision, "pending_job": r.pending_job} for r in rows]}

    @router.get("/teaching/{session_id}")
    def teaching(session_id: UUID):
        return repo.teaching(str(session_id))

    @router.get("/jobs")
    def job_list(limit: int = Query(50, ge=1, le=200)):
        with repo.db.transaction() as c:
            ids = c.scalars(select(m.jobs.c.id).where(m.jobs.c.user_id == current_user_id()).order_by(m.jobs.c.created_at.desc()).limit(limit)).all()
            return {"items": [repo.job(i) for i in ids]}

    @router.post("/jobs", status_code=202)
    def submit(body: JobInput):
        return jobs.submit(body.kind, body.args, body.request_id)

    @router.get("/jobs/{job_id}")
    def job(job_id: UUID):
        return repo.job(str(job_id))

    @router.post("/assets", status_code=201)
    async def upload(file: UploadFile = File(...)):
        content = await file.read(32 * 1024 * 1024 + 1)
        await file.close()
        if not content or len(content) > 32 * 1024 * 1024:
            raise HTTPException(413, "附件须在 32 MB 内")
        name = Path(file.filename or "upload").name[:200]
        ext = Path(name).suffix.lower()
        types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".heic": "image/heic",
                 ".pdf": "application/pdf", ".drawing": "application/vnd.apple.pencilkit"}
        if ext not in types:
            raise HTTPException(415, "支持图片、PDF 和笔迹文件")
        if ext == ".pdf" and not content.startswith(b"%PDF-"):
            raise HTTPException(415, "PDF 文件无效")
        if ext in {".png", ".jpg", ".jpeg"}:
            from io import BytesIO
            from PIL import Image
            try:
                with Image.open(BytesIO(content)) as image:
                    if image.width * image.height > 30_000_000:
                        raise ValueError()
                    image.verify()
            except Exception:
                raise HTTPException(415, "图片文件无效")
        asset_id = uid()
        key = current_user_id() + "/" + asset_id + ext
        target = (root / key).resolve()
        if not target.is_relative_to(root):
            raise HTTPException(400, "附件路径无效")
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            with target.open("xb") as f:
                target.chmod(0o600)
                f.write(content)
            asset = repo.save_asset(id=asset_id, owner_user_id=current_user_id(), storage_key=key,
                filename=name, media_type=types[ext], size=len(content), sha256=hashlib.sha256(content).hexdigest(), created_at=time.time())
        except Exception:
            target.unlink(missing_ok=True)
            raise
        asset.pop("storage_key")
        return asset

    @router.get("/assets/{asset_id}")
    def download(asset_id: UUID):
        asset = repo.asset(str(asset_id))
        target = (root / asset["storage_key"]).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise HTTPException(404, "附件文件不存在")
        return FileResponse(target, media_type=asset["media_type"], filename=asset["filename"], headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})

    @router.get("/legacy-assets/{name}")
    def legacy_asset(name: str):
        asset = repo.legacy_asset(name)
        target = (root / asset["storage_key"]).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise HTTPException(404, "附件不存在")
        return FileResponse(target, media_type=asset["media_type"])

    @router.get("/patterns")
    def patterns():
        with repo.db.transaction() as c:
            return {"items": [{"id": r.id, "revision": r.revision, **r.data} for r in c.execute(select(m.patterns).where(m.patterns.c.active.is_(True)))]}

    @router.get("/admin/records")
    def admin_records(kind: str, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
        return {"items": repo.records(kind, admin=True, offset=offset, limit=limit)}

    @router.post("/admin/records", status_code=201)
    def import_admin_record(body: AdminRecordInput):
        require_catalog_editor()
        from backend.storage.migration import stable
        record_id = stable("cloud-import:" + body.kind + ":" + body.external_id)
        with repo.db.transaction() as c:
            previous = c.execute(select(m.admin_records).where(m.admin_records.c.id == record_id)).first()
            if previous:
                if previous.data.get("imported_payload") != body.data:
                    raise HTTPException(409, "同一来源编号已有不同数据，请审核后修改")
                return {"id": record_id, "already_imported": True}
            c.execute(m.admin_records.insert().values(id=record_id, kind=body.kind,
                data={**body.data, "imported_payload": body.data, "_revision": 0}, created_at=time.time()))
        return {"id": record_id, "already_imported": False}

    @router.put("/admin/records/{record_id}/review")
    def review(record_id: UUID, body: ReviewInput):
        require_catalog_editor()
        with repo.db.transaction() as c:
            row = c.execute(select(m.admin_records).where(m.admin_records.c.id == str(record_id)).with_for_update()).first()
            if row is None:
                raise HTTPException(404, "审核记录不存在")
            if row.data.get("_revision", 0) != body.expected_revision:
                raise HTTPException(409, "记录已更新，请刷新后重试")
            data = {**row.data, "status": body.status, "_revision": body.expected_revision + 1}
            c.execute(update(m.admin_records).where(m.admin_records.c.id == str(record_id)).values(data=data))
        return {"id": str(record_id), "data": data}

    @router.post("/admin/records/{record_id}/publish")
    def publish(record_id: UUID, body: QuestionInput):
        require_catalog_editor()
        with repo.db.transaction() as c:
            row = c.execute(select(m.admin_records).where(m.admin_records.c.id == str(record_id), m.admin_records.c.kind == "pool.pool_items").with_for_update()).first()
            if not row:
                raise HTTPException(404, "原题记录不存在")
            if row.data.get("published_question_id"):
                return repo.question(row.data["published_question_id"], conn=c)
            if row.data.get("status") != "confirmed" or row.data.get("_revision", 0) != body.expected_revision:
                raise HTTPException(409, "请先确认最新原题记录")
            prepared = row.data.get("prepared_json") or body.answer_json
            if not prepared or not (prepared.get("chunk_results") or prepared.get("final_answer")):
                raise HTTPException(422, "发布前需要可用的标准解析")
            question = repo.save_question(row.data.get("question") or body.content, prepared, public=True, conn=c)
            c.execute(update(m.admin_records).where(m.admin_records.c.id == str(record_id)).values(data={**row.data, "published_question_id": question["id"], "_revision": body.expected_revision + 1}))
            return question

    @router.get("/learning/records")
    def learning_records(kind: str, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
        return {"items": repo.records(kind, offset=offset, limit=limit)}

    return router
