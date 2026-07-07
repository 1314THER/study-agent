"""
多模态解答：文件解析 + 通义千问 Qwen-VL-Plus 切题
支持 PDF / JPG / PNG / docx / txt
"""

import os
import re
import json
import base64
import httpx
from typing import Optional

# ---------- API ----------
DASHSCOPE_BASE = "https://ws-1b3ikgt2q6ybkzos.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
MODEL = "qwen3.6-flash"


def _get_api_key() -> str:
    key = os.environ.get("DASHSCOPE_API_KEY")
    if key:
        return key
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("DASHSCOPE_API_KEY="):
                    return line.split("=", 1)[1]
    raise ValueError("未找到 DASHSCOPE_API_KEY，请在 .env 中设置")


# ---------- 文件解析 ----------
def file_to_base64(file_path: str) -> str:
    with open(file_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def pdf_to_images(file_path: str, dpi: int = 200) -> list:
    """将 PDF 每页转为 PNG base64"""
    import fitz
    doc = fitz.open(file_path)
    images = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("png")
        images.append(base64.b64encode(img_bytes).decode("utf-8"))
    doc.close()
    return images


def image_to_base64(file_path: str) -> str:
    return file_to_base64(file_path)


def docx_to_text(file_path: str) -> str:
    from docx import Document
    doc = Document(file_path)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paragraphs)


# ---------- Qwen-VL 调用 ----------
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


def _call_qwen_vl(image_base64: Optional[str] = None, text: Optional[str] = None) -> str:
    """调用 Qwen-VL-Plus，返回原始回复文本"""""
    api_key = _get_api_key()
    messages = [{"role": "user", "content": []}]
    
    if image_base64:
        messages[0]["content"].append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{image_base64}"}
        })
    
    messages[0]["content"].append({
        "type": "text",
        "text": text or _EXTRACTION_PROMPT
    })
    
    body = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": 16384,
    }
    
    try:
        resp = httpx.post(
            f"{DASHSCOPE_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json=body,
            timeout=180,
        )
        if resp.status_code != 200:
            raise Exception(f"Qwen API 错误 {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return content
    except httpx.TimeoutException:
        raise Exception("Qwen API 请求超时（180s）")
    except httpx.ConnectError:
        raise Exception("无法连接到 Qwen API 服务器")
    except (KeyError, json.JSONDecodeError, IndexError) as e:
        raise Exception(f"Qwen API 响应解析失败: {str(e)[:200]}")


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
        print(f"[Warn] JSON 解析失败，尝试兜底解析: {e}")
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
        if difficulty not in ("简单", "中等", "困难"):
            difficulty = "中等"
        teacher_map = {"简单": "liangliang", "中等": "liangliang", "困难": "taotao"}
        question_type = q.get("type", q.get("question_type", ""))
        if question_type not in ("选择题", "填空题", "大题"):
            question_type = ""
        result.append({
            "index": q.get("index", i + 1),
            "latex": latex.strip(),
            "difficulty": difficulty,
            "recommended_teacher": teacher_map.get(difficulty, "liangliang"),
            "question_type": question_type,
        })
    return result


def _image_mime(ext: str) -> str:
    return {"jpg": "jpeg", "jpeg": "jpeg", "png": "png"}.get(ext.lower(), "png")


# ---------- 主入口 ----------
def parse_file(file_path: str, original_filename: str = "") -> list:
    """解析文件，返回 [{index, latex, difficulty, recommended_teacher}]"""
    ext = os.path.splitext(file_path)[1].lower()
    
    # PDF → 每页转图 → 逐页切题
    if ext == ".pdf":
        images = pdf_to_images(file_path)
        all_questions = []
        for page_b64 in images:
            raw = _call_qwen_vl(image_base64=page_b64, text=_EXTRACTION_PROMPT)
            page_qs = _parse_questions(raw)
            all_questions.extend(page_qs)
        return _post_process(all_questions)
    
    # 图片 → 直接调 vision API
    elif ext in (".jpg", ".jpeg", ".png"):
        b64 = image_to_base64(file_path)
        raw = _call_qwen_vl(image_base64=b64, text=_EXTRACTION_PROMPT)
        questions = _parse_questions(raw)
        return _post_process(questions)
    
    # docx / txt → 文本提取 → 调 text-only API
    elif ext == ".docx":
        text = docx_to_text(file_path)
        raw = _call_qwen_vl(text=_EXTRACTION_PROMPT + "\n\n文本内容：\n" + text)
        questions = _parse_questions(raw)
        return _post_process(questions)
    
    elif ext == ".txt":
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        raw = _call_qwen_vl(text=_EXTRACTION_PROMPT + "\n\n文本内容：\n" + text)
        questions = _parse_questions(raw)
        return _post_process(questions)
    
    else:
        raise ValueError(f"不支持的文件格式: {ext}")


def get_supported_extensions() -> list:
    return [".pdf", ".jpg", ".jpeg", ".png", ".docx", ".txt"]
