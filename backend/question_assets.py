"""Private, workspace-scoped question images; never accept a client file path."""
import base64
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import os
import re
import uuid
from functools import lru_cache

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.data_paths import data_path

router = APIRouter()
_ID = re.compile(r"^[a-f0-9]{64}\.png$")


def asset_root():
    root = Path(data_path("question-assets", Path(__file__).resolve().parent.parent / ".runtime" / "question-assets"))
    if root.is_symlink():
        raise ValueError("题图目录不可用")
    return root


def store_image(data):
    """Normalize an image before the temporary upload is reclaimed."""
    from PIL import Image, ImageOps
    if len(data) > 32 * 1024 * 1024:
        raise ValueError("题图过大")
    with Image.open(BytesIO(data)) as image:
        if image.width * image.height > 30_000_000:
            raise ValueError("题图尺寸过大")
        image = ImageOps.exif_transpose(image)
        image.thumbnail((2400, 3200))
        output = BytesIO()
        if image.mode in ("RGBA", "LA") or "transparency" in image.info:
            rgba = image.convert("RGBA")
            background = Image.new("RGB", rgba.size, "white")
            background.paste(rgba, mask=rgba.getchannel("A"))
            image = background
        image.convert("RGB").save(output, format="PNG")
    content = output.getvalue()
    name = sha256(content).hexdigest() + ".png"
    from backend.storage.database import current_repository
    repo = current_repository()
    if repo is not None:
        from backend.identity import current_user_id
        from backend.storage import models as m
        from sqlalchemy import select
        import time
        with repo.db.transaction() as conn:
            existing = conn.execute(select(m.assets.c.id).where(repo.visible(m.assets), m.assets.c.sha256 == sha256(content).hexdigest())).scalar()
        if existing:
            return existing
        asset_id = str(uuid.uuid4())
        key = current_user_id() + "/" + asset_id + ".png"
        target = repo.asset_root / key
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with target.open("xb") as stream:
            target.chmod(0o600)
            stream.write(content)
        try:
            repo.save_asset(id=asset_id, owner_user_id=current_user_id(), storage_key=key,
                sha256=sha256(content).hexdigest(), filename=name, media_type="image/png", size=len(content), created_at=time.time())
            repo.alias("assets", name, asset_id)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return asset_id
    root = asset_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = root / name
    if target.is_symlink():
        raise ValueError("题图文件不可用")
    if not target.exists():
        temp = root / (uuid.uuid4().hex + ".tmp")
        try:
            with temp.open("xb") as stream:
                temp.chmod(0o600)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            temp.replace(target)
        finally:
            temp.unlink(missing_ok=True)
    return name


def resolve_asset(name):
    from backend.storage.database import current_repository
    repo = current_repository()
    if repo is not None:
        try:
            asset = repo.legacy_asset(name) if isinstance(name, str) and _ID.fullmatch(name) else repo.asset(str(uuid.UUID(name)))
            target = (repo.asset_root / asset["storage_key"]).resolve()
            if not target.is_relative_to(repo.asset_root.resolve()) or not target.is_file():
                raise ValueError("题图不存在")
            return target
        except (HTTPException, ValueError, TypeError, AttributeError):
            raise ValueError("题图不存在或无权访问")
    if not isinstance(name, str) or not _ID.fullmatch(name):
        raise ValueError("题图编号无效")
    target = asset_root() / name
    if target.is_symlink() or not target.is_file():
        raise ValueError("题图不存在或无权访问")
    return target


def validate_refs(refs):
    if refs is None:
        return []
    if not isinstance(refs, list) or len(refs) > 8:
        raise ValueError("每题最多关联 8 张题图")
    result = []
    for name in refs:
        resolve_asset(name)
        if name not in result:
            result.append(name)
    return result


def image_messages(refs):
    messages, size = [], 0
    for name in validate_refs(refs):
        path = resolve_asset(name)
        size += path.stat().st_size
        if size > 32 * 1024 * 1024:
            raise ValueError("关联题图总大小超过32 MiB")
        messages.append({"type":"image_url","image_url":{"url":"data:image/png;base64,"+
                        base64.b64encode(path.read_bytes()).decode("ascii"),"detail":"original"}})
    return messages


@lru_cache(maxsize=2048)
def _retain_source(path, mtime, size, destination, page=None):
    """Reuse normalized images and rendered pages, scoped to the private store."""
    if page is None:
        return store_image(Path(path).read_bytes())
    import fitz
    from backend.source_conversion import _PDF_LOCK
    from backend.multimodal import _pdf_render_scale
    with _PDF_LOCK, fitz.open(path) as doc:
        if not 1 <= page <= len(doc):
            raise ValueError("原卷页码不存在")
        source = doc[page - 1]
        # Some source PDFs use poster-sized page boxes. Bound pixel area as
        # well as the long edge before allocating the raster.
        scale = min(_pdf_render_scale(source, 150),
                    (29_000_000 / max(1, source.rect.width * source.rect.height)) ** .5)
        return store_image(source.get_pixmap(matrix=fitz.Matrix(scale, scale)).tobytes("png"))


def has_pool_graphics(item):
    from backend.pool_sources import _GRAPH_COMMAND, _GRAPH_DEPENDENCY
    return (item.get("completeness") == "deferred_graphic" or
            bool(_GRAPH_COMMAND.search(item.get("question", ""))) or
            bool(_GRAPH_DEPENDENCY.search(item.get("question", ""))) or
            any((o.get("raw") or {}).get("image_refs")
                for o in item.get("occurrences") or []))


def pool_asset_data(item):
    """Resolve original figures, preserving their order and option labels.

    A complete occurrence wins over incomplete duplicate provenance. Reading
    assets never changes the candidate's review or import state.
    """
    from backend.question_pool import files_directory, _source_file, source_asset_path
    root = files_directory().parent.resolve()
    best = {"asset_refs": [], "assets": [], "missing": [], "required": has_pool_graphics(item)}
    for origin in item.get("occurrences") or []:
        raw = origin.get("raw") or {}
        if not isinstance(raw, dict):
            continue
        assets, missing = [], []
        def retain(path, label, page=None, expected_hash=None):
            try:
                path = path.resolve()
                if not path.is_relative_to(root) or not path.is_file():
                    raise ValueError("原图文件缺失")
                if len(assets) >= 8:
                    raise ValueError("题图超过 8 张，请分题核对")
                stat = path.stat()
                if expected_hash:
                    from backend.source_conversion import file_hash
                    if file_hash(path) != expected_hash:
                        raise ValueError("原图哈希不符")
                ref = _retain_source(str(path), stat.st_mtime_ns, stat.st_size, str(asset_root()), page)
                try:
                    resolve_asset(ref)
                except ValueError:
                    _retain_source.cache_clear()
                    ref = _retain_source(str(path), stat.st_mtime_ns, stat.st_size, str(asset_root()), page)
                assets.append({"ref": ref, "label": label})
            except (ValueError, OSError) as exc:
                missing.append({"label": label, "reason": str(exc)})
        original = source_asset_path(raw["original_file"]) if isinstance(raw.get("original_file"), str) and raw["original_file"] else None
        # Directory sources use their preserved root; snapshots use the pinned
        # revision's directory. Neither path can escape this owner's pool.
        base = source_asset_path(raw["source_root"]) if isinstance(raw.get("source_root"), str) and raw["source_root"] else None
        if base is None and original:
            base = next((p for p in original.parents if p.parent.name == "snapshots" and p.is_relative_to(root)), None)
        refs = raw.get("image_refs") if isinstance(raw.get("image_refs"), list) else []
        downloaded = {a["path"]: a for a in raw.get("image_assets") or [] if isinstance(a, dict) and isinstance(a.get("path"), str)}
        for index, ref in enumerate(refs):
            if not isinstance(ref, dict):
                continue
            key = ref.get("repo_path") or ref.get("path")
            label = ref.get("label") or "题图 " + str(index + 1)
            if not base or not isinstance(key, str):
                missing.append({"label": label, "reason": "未保留原图定位"})
                continue
            if key.startswith("img_repaint/") and key.endswith(".tex"):
                key = "img/" + key[len("img_repaint/"):-4] + ".png"
            retain(base / key, label, expected_hash=downloaded.get(key, {}).get("sha256"))
        if not refs and original and original.suffix.lower() in (".png", ".jpg", ".jpeg"):
            retain(original, "原题图")
        graphic = raw.get("graphic_file") if isinstance(raw.get("graphic_file"), dict) else {}
        start, end = graphic.get("page_start", origin.get("page_start")), graphic.get("page_end", origin.get("page_end"))
        if not refs and type(start) is int and type(end) is int and 1 <= start <= end <= start + 7:
            try:
                source_path = original
                if not source_path or not source_path.is_file():
                    source_path, _ = _source_file(origin["source_id"])
                if source_path.suffix.lower() == ".pdf" and source_path.resolve().is_relative_to(root):
                    for page in range(start, end + 1):
                        retain(source_path, "原卷第 " + str(page) + " 页", page=page)
            except (HTTPException, ValueError, KeyError, OSError) as exc:
                missing.append({"label": "原卷题图", "reason": str(exc)})
        if assets and not missing:
            return {"asset_refs": list(dict.fromkeys(a["ref"] for a in assets)), "assets": assets,
                    "missing": [], "required": best["required"]}
        if len(assets) > len(best["assets"]) or (not best["missing"] and missing):
            best.update(asset_refs=list(dict.fromkeys(a["ref"] for a in assets)), assets=assets, missing=missing)
    if best["required"] and not best["assets"] and not best["missing"]:
        best["missing"] = [{"label": "原题图", "reason": "题源未提供可读取的图片或原卷页"}]
    return best


def pool_asset_refs(item, *, require_complete=False):
    data = pool_asset_data(item)
    if require_complete and data["required"] and data["missing"]:
        raise ValueError("题图缺失或不完整，请补齐原图后再准备解析")
    return data["asset_refs"]


def hydrate_pool_record(record, source_id=None):
    """Attach available original images without claiming OCR text is verified."""
    origin = {**record, "source_id": source_id}
    if not has_pool_graphics({**record, "occurrences": [origin]}):
        return record
    data = pool_asset_data({**record, "occurrences": [origin]})
    raw = dict(record.get("raw") or {})
    raw["question_assets"] = data
    record = {**record, "raw": raw}
    if record.get("completeness") == "deferred_graphic" and data["asset_refs"] and not data["missing"]:
        record["completeness"] = "needs_review"
        reason = record.get("reason", "").replace("题干引用图形信息，本阶段暂缓，保留出处", "原题图已加载，请核对题干与图形")
        reason = reason.replace("题干引用图形信息，等待加载原题图", "原题图已加载，请核对题干与图形")
        record["reason"] = reason if "已加载" in reason else reason + "；原题图已加载，请核对题干与图形"
    return record


@router.get("/question-pool/items/{item_id}/assets")
def get_pool_assets(item_id: int):
    from backend.question_pool import _require_owner, get_item
    _require_owner()
    return pool_asset_data(get_item(item_id))


@router.get("/question-assets/{asset_id}")
def get_asset(asset_id: str):
    try:
        path = resolve_asset(asset_id)
    except ValueError:
        raise HTTPException(404, "题图不存在或无权访问")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, no-store"})
