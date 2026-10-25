"""
多模态解答：按所选老师调用模型，处理文件解析、图片理解与切题
支持 PDF / JPG / PNG / docx / txt
"""

import os
import re
import json
import base64
import io
import logging
import httpx
from typing import Optional

import backend.settings as runtime_settings

logger = logging.getLogger(__name__)

# ---------- API ----------
MAX_IMAGE_BYTES = 32 * 1024 * 1024
GLM46V_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_SIDE = 8192
MAX_REQUEST_BYTES = 48 * 1024 * 1024


def resolve_multimodal_model(teacher=None, stage="solver", has_image=False):
    """Resolve the selected teacher's model, including Liang's vision fallback."""
    teacher_config = runtime_settings.get_teacher_config(teacher)
    stage_config = teacher_config.get(stage) or teacher_config.get("solver") or {}
    model = stage_config.get("model") or runtime_settings.DEFAULTS["teachers"]["liangliang"]["solver"]["model"]
    effort = stage_config.get("reasoning_effort") or "medium"
    if has_image and model == "glm-4.7-flash":
        model = "glm-4.6v-flash"
    return model, effort


# ---------- 文件解析 ----------
def file_to_base64(file_path: str) -> str:
    with open(file_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _pdf_render_scale(page, dpi):
    scale = dpi / 72
    rect = getattr(page, "rect", None)
    if rect is not None and max(rect.width, rect.height) > 0:
        scale = min(scale, MAX_IMAGE_SIDE / max(rect.width, rect.height))
    return scale


def pdf_to_images(file_path: str, dpi: int = 200) -> list:
    """将 PDF 每页转为 PNG base64"""
    import fitz
    doc = fitz.open(file_path)
    images = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        scale = _pdf_render_scale(page, dpi)
        mat = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("png")
        images.append(base64.b64encode(img_bytes).decode("utf-8"))
    doc.close()
    return images


def iter_pdf_images(file_path: str, dpi: int = 200):
    """Render one page at a time instead of retaining the whole PDF in RAM."""
    import fitz
    with fitz.open(file_path) as doc:
        total = len(doc)
        for page_num in range(total):
            page = doc[page_num]
            scale = _pdf_render_scale(page, dpi)
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
            data = pix.tobytes("png")
            del pix
            yield page_num + 1, total, base64.b64encode(data).decode("utf-8")
            del data


def image_to_base64(file_path: str) -> str:
    """Normalize camera orientation and fit the documented image size limit.

    Preserve the whole image and its aspect ratio; never crop away questions.
    All image inputs are re-encoded as PNG so the data URL matches the bytes.
    """
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        with Image.open(file_path) as image:
            image = ImageOps.exif_transpose(image)
            image.load()
            image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), Image.Resampling.LANCZOS)
            if image.mode not in ("RGB", "RGBA", "L", "LA"):
                image = image.convert("RGB")
            output = io.BytesIO()
            image.save(output, format="PNG", optimize=True)
            data = output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("无法读取图片，请上传完整的 JPG/PNG 文件") from exc
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("图片超过单张 32 MiB 限制，请降低图片分辨率")
    return base64.b64encode(data).decode("utf-8")


def docx_to_text(file_path: str) -> str:
    from docx import Document
    doc = Document(file_path)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paragraphs)


# ---------- 按老师选择模型进行多模态理解 ----------
_PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")


def _read_extraction_prompt() -> str:
    """从 extraction.md 读取提取 prompt"""
    path = os.path.join(_PROMPTS_DIR, "extraction.md")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    # 兜底：返回基础 prompt
    return "你是一个数学题目提取专家。提取图片或文本中的所有数学题目，输出为 JSON 数组。"


_EXTRACTION_PROMPT = _read_extraction_prompt()

_ANSWER_OCR_PROMPT = (
    "你是一个数学手写作答识别助手。请把图片中的手写数学过程和答案完整识别出来。\n"
    "要求：\n"
    "1. 保留数学符号与公式，可用 LaTeX 表示，例如 $x^2$、$\\frac{1}{2}$。\n"
    "2. 中文按原文保留，明显的错别字按上下文修正。\n"
    "3. 只输出识别出的作答文本，不要解释，不要加标题。"
)


def _fit_glm46v_image(encoded: str) -> tuple[str, str]:
    """Keep GLM-4.6V image payloads below the provider's per-image limit."""
    raw = base64.b64decode(encoded, validate=True)
    from PIL import Image, ImageOps
    try:
        with Image.open(io.BytesIO(raw)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            width, height = image.size
            if len(raw) <= GLM46V_IMAGE_BYTES and max(width, height) <= 6000 and source.format in ("PNG", "JPEG"):
                mime = "image/jpeg" if source.format == "JPEG" else "image/png"
                image.close()
                return encoded, mime
            if max(width, height) > 6000:
                scale = 6000 / max(width, height)
                width, height = max(1, int(width * scale)), max(1, int(height * scale))
            while max(width, height) >= 320:
                resized = image.resize((width, height), Image.Resampling.LANCZOS) if image.size != (width, height) else image
                for quality in (92, 86, 80, 74):
                    output = io.BytesIO()
                    resized.save(output, format="JPEG", quality=quality, optimize=True)
                    payload = output.getvalue()
                    if len(payload) <= GLM46V_IMAGE_BYTES:
                        result = base64.b64encode(payload).decode("ascii")
                        if resized is not image:
                            resized.close()
                        image.close()
                        return result, "image/jpeg"
                if resized is not image:
                    resized.close()
                width, height = int(width * 0.85), int(height * 0.85)
            image.close()
    except (OSError, ValueError) as exc:
        raise ValueError("图片过大，无法压缩到 GLM-4.6V-Flash 的上传限制") from exc
    raise ValueError("图片过大，压缩后仍超过 GLM-4.6V-Flash 的单张图片限制")


def _call_multimodal_model(image_base64: Optional[str] = None, text: Optional[str] = None,
                           teacher: Optional[str] = None, stage: str = "solver") -> str:
    """Call the selected teacher model for text and image recognition."""
    limits = runtime_settings.get_limits()
    model, reasoning_effort = resolve_multimodal_model(teacher, stage, has_image=bool(image_base64))
    image_content = []

    image_mime = "image/png"
    if image_base64:
        try:
            image_bytes = base64.b64decode(image_base64, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise ValueError("图片编码无效") from exc
        if len(image_bytes) > MAX_IMAGE_BYTES:
            raise ValueError("图片超过单张 32 MiB 限制")
        if model == "glm-4.6v-flash":
            image_base64, image_mime = _fit_glm46v_image(image_base64)
        image_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{image_mime};base64,{image_base64}", "detail": "original"},
        })

    prompt = text or _EXTRACTION_PROMPT
    request_body = {"model": model, "prompt": prompt, "images": image_content}
    if len(json.dumps(request_body, ensure_ascii=False).encode("utf-8")) > MAX_REQUEST_BYTES:
        raise ValueError("图片请求超过 48 MiB 请求体限制")

    try:
        from backend.solver import call_deepseek
        result = call_deepseek(
            "你是一个数学题目识别助手。请遵守用户给出的识别要求。",
            prompt,
            model=model,
            reasoning_effort=reasoning_effort,
            image_content=image_content or None,
            max_tokens=limits.get("multimodal_max_tokens", 16384),
            timeout_seconds=limits.get("multimodal_timeout_seconds", 180),
        )
        content = result[0] if isinstance(result, tuple) else result
        usage = result[1] if isinstance(result, tuple) and len(result) > 1 else {}
        if not isinstance(content, str) or not content.strip():
            raise ValueError("所选老师的模型未返回识别文本")
        if isinstance(usage, dict) and usage.get("finish_reason") == "length":
            raise ValueError("图片识别结果超出输出长度，请拆分页面或提高识别输出上限")
        return content
    except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPError):
        raise
    except (KeyError, json.JSONDecodeError, IndexError, TypeError) as e:
        raise Exception("多模态模型响应解析失败") from e


def _parse_questions(raw: str) -> list:
    """从 LLM 回复中提取 JSON 题目列表"""
    # 尝试提取 JSON 代码块
    m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', raw, re.DOTALL)
    if m:
        raw = m.group(1).strip()
    
    # 尝试找第一个 [ 和最后一个 ]
    first = raw.find("[")
    last = raw.rfind("]")
    if first >= 0 and last > first:
        raw = raw[first:last + 1]
    
    try:
        items = json.loads(raw)
        if not isinstance(items, list):
            raise ValueError("响应不是数组")
        return items
    except (json.JSONDecodeError, ValueError) as e:
        # 尝试逐行解析兜底
        logger.warning("JSON 解析失败，尝试兜底解析: %s", e)
        return _fallback_parse(raw)


def _fallback_parse(text: str) -> list:
    """兜底解析：逐行查找题目模式"""
    questions = []
    lines = text.split("\n")
    current_q = None
    question_text = ""
    
    for line in lines:
        m = re.match(r'(?:^|\s*)(?:第\s*)?(\d+)[.、)\s]\s*(.*)', line)
        if m:
            if current_q is not None and question_text.strip():
                questions.append(current_q)
            idx = int(m.group(1))
            content = m.group(2).strip()
            current_q = {"index": idx, "latex": content, "difficulty": "中等"}
            question_text = content
        elif current_q is not None:
            current_q["latex"] += "\n" + line.strip()
    
    if current_q is not None and question_text.strip():
        questions.append(current_q)
    
    return questions if questions else [{"index": 1, "latex": text, "difficulty": "中等"}]


def _post_process(questions: list) -> list:
    """统一后处理：确保每道题有 index / latex / difficulty"""
    result = []
    for i, q in enumerate(questions):
        if not isinstance(q, dict):
            continue
        latex = q.get("latex", q.get("content", q.get("text", "")))
        difficulty = q.get("difficulty", "中等")
        if difficulty in ("简单", "容易"):
            difficulty = "容易"
        if difficulty not in ("容易", "中等", "困难"):
            difficulty = "中等"
        teacher_map = {"容易": "liangliang", "中等": "liangliang", "困难": "taotao"}
        question_type = q.get("type", q.get("question_type", ""))
        if question_type not in ("选择题", "多选题", "填空题", "大题"):
            question_type = ""
        result.append({
            "index": q.get("index", i + 1),
            "latex": latex.strip(),
            "difficulty": difficulty,
            "recommended_teacher": teacher_map.get(difficulty, "liangliang"),
            "question_type": question_type,
            "asset_refs": q.get("asset_refs", []),
        })
    return result


def _image_mime(ext: str) -> str:
    return {"jpg": "jpeg", "jpeg": "jpeg", "png": "png"}.get(ext.lower(), "png")


def _retain_preview(encoded):
    # Image retention must never discard a successfully extracted text question.
    from backend.question_assets import store_image
    try:
        return [store_image(base64.b64decode(encoded, validate=True))]
    except (ValueError, OSError):
        logger.warning("题图留存失败，继续交付文字题干")
        return []


# ---------- 主入口 ----------
def parse_file(file_path: str, original_filename: str = "", progress=None,
               teacher: Optional[str] = "liangliang") -> list:
    """解析文件，返回 [{index, latex, difficulty, recommended_teacher}]"""
    ext = os.path.splitext(file_path)[1].lower()
    
    # PDF → 每页转图 → 逐页切题
    if ext == ".pdf":
        all_questions = []
        for page_num, total, page_b64 in iter_pdf_images(file_path):
            if progress:
                progress(page_num, total)
            raw = _call_multimodal_model(image_base64=page_b64, text=_EXTRACTION_PROMPT, teacher=teacher)
            page_qs = _parse_questions(raw)
            refs = _retain_preview(page_b64)
            for q in page_qs:
                if isinstance(q, dict):
                    q["asset_refs"] = refs
            all_questions.extend(page_qs)
            del page_b64
        return _post_process(all_questions)
    
    # 图片 → 直接调 vision API
    elif ext in (".jpg", ".jpeg", ".png"):
        if progress:
            progress(1, 1)
        b64 = image_to_base64(file_path)
        raw = _call_multimodal_model(image_base64=b64, text=_EXTRACTION_PROMPT, teacher=teacher)
        questions = _parse_questions(raw)
        refs = _retain_preview(b64)
        for q in questions:
            if isinstance(q, dict):
                q["asset_refs"] = refs
        return _post_process(questions)
    
    # docx / txt → 文本提取 → 调 text-only API
    elif ext == ".docx":
        if progress:
            progress(1, 1)
        text = docx_to_text(file_path)
        raw = _call_multimodal_model(text=_EXTRACTION_PROMPT + "\n\n文本内容：\n" + text, teacher=teacher)
        questions = _parse_questions(raw)
        return _post_process(questions)
    
    elif ext == ".txt":
        if progress:
            progress(1, 1)
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        raw = _call_multimodal_model(text=_EXTRACTION_PROMPT + "\n\n文本内容：\n" + text, teacher=teacher)
        questions = _parse_questions(raw)
        return _post_process(questions)
    
    else:
        raise ValueError(f"不支持的文件格式: {ext}")


def get_supported_extensions() -> list:
    return [".pdf", ".jpg", ".jpeg", ".png", ".docx", ".txt"]


def recognize_answer_image(file_path: str, teacher: Optional[str] = "liangliang", stage: str = "grade") -> dict:
    """识别手写作答图片，返回 {text, confidence}"""
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png"):
        raise ValueError("仅支持 JPG/PNG 图片")
    b64 = image_to_base64(file_path)
    raw = _call_multimodal_model(image_base64=b64, text=_ANSWER_OCR_PROMPT, teacher=teacher, stage=stage)
    text = (raw or "").strip()
    has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in text)
    if len(text) >= 10 and has_cjk:
        confidence = "high"
    elif len(text) >= 2:
        confidence = "medium"
    else:
        confidence = "low"
    return {"text": text, "confidence": confidence}
