"""Private, workspace-scoped question images; never accept a client file path."""
import base64
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import os
import re
import uuid

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
    from PIL import Image
    if len(data) > 32 * 1024 * 1024:
        raise ValueError("题图过大")
    with Image.open(BytesIO(data)) as image:
        if image.width * image.height > 30_000_000:
            raise ValueError("题图尺寸过大")
        image.thumbnail((2400, 3200))
        output = BytesIO()
        image.convert("RGB").save(output, format="PNG")
    content = output.getvalue()
    name = sha256(content).hexdigest() + ".png"
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


def pool_asset_refs(item):
    """Read preserved provenance only. Never change candidate/import state."""
    from backend.question_pool import files_directory, _source_file
    root = files_directory().parent.resolve()
    refs = []
    def retain(path):
        if len(refs) >= 8:
            return
        path = path.resolve()
        if not path.is_relative_to(root) or not path.is_file():
            return
        if path.suffix.lower() in (".png", ".jpg", ".jpeg"):
            if path.stat().st_size <= 32 * 1024 * 1024:
                try:
                    refs.append(store_image(path.read_bytes()))
                except (ValueError, OSError):
                    pass
    for origin in item.get("occurrences") or []:
        raw = origin.get("raw") or {}
        original = Path(raw["original_file"]) if raw.get("original_file") else None
        if original:
            retain(original)
            snapshot = next((p for p in original.parents if p.parent.name == "snapshots" and p.is_relative_to(root)), None)
            if snapshot:
                for asset in raw.get("image_assets") or []:
                    if isinstance(asset, dict) and isinstance(asset.get("path"), str):
                        retain(snapshot / asset["path"])
        graphic = raw.get("graphic_file") or {}
        start, end = graphic.get("page_start", origin.get("page_start")), graphic.get("page_end", origin.get("page_end"))
        if type(start) is int and type(end) is int and 1 <= start <= end <= start + 7:
            try:
                source_path = original
                if not source_path or not source_path.is_file():
                    source_path, _ = _source_file(origin["source_id"])
                if source_path.suffix.lower() == ".pdf" and source_path.resolve().is_relative_to(root):
                    import fitz
                    from backend.multimodal import _pdf_render_scale
                    with fitz.open(source_path) as doc:
                        for page in list(range(start - 1, min(end, len(doc))))[:8 - len(refs)]:
                            pix = doc[page].get_pixmap(matrix=fitz.Matrix(_pdf_render_scale(doc[page], 150), _pdf_render_scale(doc[page], 150)))
                            refs.append(store_image(pix.tobytes("png")))
            except (HTTPException, ValueError, KeyError, OSError):
                pass
        refs = list(dict.fromkeys(refs))[:8]
        if len(refs) >= 8:
            break
    return refs


@router.get("/question-pool/items/{item_id}/assets")
def get_pool_assets(item_id: int):
    from backend.question_pool import _require_owner, get_item
    _require_owner()
    return {"asset_refs": pool_asset_refs(get_item(item_id))}


@router.get("/question-assets/{asset_id}")
def get_asset(asset_id: str):
    try:
        path = resolve_asset(asset_id)
    except ValueError:
        raise HTTPException(404, "题图不存在或无权访问")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, no-store"})
