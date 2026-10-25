"""Workspace-private exam response records and evidence-grounded reports."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import threading
import time
import uuid
import datetime

from fastapi import APIRouter, Body, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from backend.data_paths import data_path
from backend.identity import current_identity
from backend.student_analysis_types import (
    AnswerExtractor, AssessmentSpec, DiagnosticEngine, DiagnosticFinding, Grader, RecommendationBuilder,
    ResponseEvidence, TimingEvidence,
)

router = APIRouter(prefix="/student-analysis", tags=["学生学情分析"])
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / ".runtime" / "student-analysis.sqlite3"
MAX_IMAGE_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES, MAX_PDF_PAGES = 30, 16 * 1024 * 1024, 64 * 1024 * 1024, 80
DEFAULT_REPORT_WINDOW, REPEAT_MIN_EXAMS, REPEAT_MIN_QUESTIONS = 5, 2, 2
_LOCK = threading.RLock()
_REVIEW_STATES = {"pending", "confirmed", "blank", "unrecognized"}
_QUESTIONNAIRE_FIELDS = {
    "completion": {"completed", "not_completed", "unknown"},
    "stuck_period": {"early", "middle", "late", "unknown", "none"},
    "stuck_duration_range": {"under_5m", "5_15m", "15_30m", "over_30m", "unknown", "none"},
    "skipped_and_returned": {"yes", "no", "unknown"}, "checked_work": {"yes", "no", "unknown"},
    "confidence": {"mostly_sure", "mixed", "mostly_unsure", "unknown"},
    "condition": {"calm", "tense", "tired", "distracted", "other", "unknown"},
}
_ERROR_TYPES = {"符号错误", "计算错误", "公式记错", "知识性错误", "审题错误", "思路错误", "其他"}


class _VisionAnswerExtractor:
    def extract_page(self, image_base64, prompt, *, teacher=None):
        from backend.multimodal import _call_multimodal_model
        return _call_multimodal_model(image_base64=image_base64, text=prompt, teacher=teacher, stage="grade")


class _SharedGrader:
    def grade(self, assessment, response, *, full_score, rubric, objective_rule, teacher):
        from backend.grade import grade_prepared
        return grade_prepared(assessment.question, assessment.answer_result, response.reviewed_text,
            question_type=assessment.question_type, full_score=full_score, teacher=teacher,
            scoring_rubric=rubric or None, objective_rule=objective_rule,
            input_type="ocr" if response.source == "ocr" else "text")


class _RulesDiagnosticEngine:
    def analyze(self, attempts):
        return build_report(attempts)


class _StructuredRecommendationBuilder:
    def build(self, findings, *, max_items=3):
        return [{"finding_id": finding["id"], "title": finding["title"],
                 "recommendation": finding["recommendation"],
                 "validation_target": finding["validation_target"],
                 "evidence_level": finding["evidence_level"]}
                for finding in findings[:max_items]]


ANSWER_EXTRACTOR: AnswerExtractor = _VisionAnswerExtractor()
GRADER: Grader = _SharedGrader()
DIAGNOSTIC_ENGINE: DiagnosticEngine = _RulesDiagnosticEngine()
RECOMMENDATION_BUILDER: RecommendationBuilder = _StructuredRecommendationBuilder()


def storage_path():
    return Path(data_path("student-analysis.sqlite3", DEFAULT_DB))


def upload_root():
    return Path(data_path("student-analysis-uploads", DEFAULT_DB.parent / "student-analysis-uploads"))


def _dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _connect():
    path = storage_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError("学情数据库路径不可用")
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS student_attempts (
            attempt_id TEXT PRIMARY KEY, created_at REAL NOT NULL, updated_at REAL NOT NULL,
            revision INTEGER NOT NULL, status TEXT NOT NULL, data_json TEXT NOT NULL,
            pages_json TEXT NOT NULL, questions_json TEXT NOT NULL, questionnaire_json TEXT NOT NULL,
            report_cache_json TEXT, current_job_id TEXT, error TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_student_attempts_date ON student_attempts(updated_at DESC);
        CREATE TABLE IF NOT EXISTS student_reports (
            report_id TEXT PRIMARY KEY, created_at REAL NOT NULL, data_json TEXT NOT NULL
        );
    """)
    conn.commit()
    os.chmod(path, 0o600)
    return conn


def _row_to_attempt(row):
    if not row:
        return None
    data = json.loads(row["data_json"])
    return {"id": row["attempt_id"], "created_at": row["created_at"],
            "updated_at": row["updated_at"], "revision": row["revision"],
            "status": row["status"], **data, "pages": json.loads(row["pages_json"]),
            "questions": json.loads(row["questions_json"]),
            "questionnaire": json.loads(row["questionnaire_json"]),
            "report": json.loads(row["report_cache_json"]) if row["report_cache_json"] else None,
            "current_job_id": row["current_job_id"], "error": row["error"]}


def _public_attempt(attempt):
    """Return an attempt without exposing private filesystem paths."""
    public = json.loads(_dump(attempt))
    for page in public.get("pages", []):
        page.pop("image_path", None)
    return public


def _get_row(attempt_id, conn=None):
    owns = conn is None
    conn = conn or _connect()
    try:
        row = conn.execute("SELECT * FROM student_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
        return _row_to_attempt(dict(row) if row else None)
    finally:
        if owns:
            conn.close()


def _write_attempt(attempt, *, expected_revision=None, bump_revision=True):
    """Persist a checked snapshot and reject stale task writes."""
    with _LOCK, _connect() as conn:
        row = conn.execute("SELECT revision FROM student_attempts WHERE attempt_id=?", (attempt["id"],)).fetchone()
        if not row:
            raise ValueError("考试记录不存在")
        if expected_revision is not None and row["revision"] != expected_revision:
            return False
        attempt["revision"] = row["revision"] + (1 if bump_revision else 0)
        attempt["updated_at"] = time.time()
        core = {k: v for k, v in attempt.items() if k not in {
            "id", "created_at", "updated_at", "revision", "status", "pages", "questions",
            "questionnaire", "report", "current_job_id", "error"}}
        conn.execute("UPDATE student_attempts SET updated_at=?,revision=?,status=?,data_json=?,pages_json=?,"
                     "questions_json=?,questionnaire_json=?,report_cache_json=NULL,current_job_id=?,error=? WHERE attempt_id=?",
                     (attempt["updated_at"], attempt["revision"], attempt["status"], _dump(core),
                      _dump(attempt["pages"]), _dump(attempt["questions"]), _dump(attempt["questionnaire"]),
                      attempt.get("current_job_id"), attempt.get("error"), attempt["id"]))
        conn.commit()
    return True


def _require_attempt(attempt_id):
    attempt = _get_row(attempt_id)
    if not attempt:
        raise HTTPException(404, "考试记录不存在")
    return attempt


def _analysis_source(analysis_id):
    from backend.exam_analysis import _get_row as get_exam_row
    row = get_exam_row(analysis_id)
    if not row:
        raise HTTPException(404, "整卷分析记录不存在")
    if row["status"] != "complete" or not row["review_confirmed"]:
        raise HTTPException(409, "请先完成试卷识别核对和整卷分析。")
    questions = json.loads(row["questions_json"])
    if not questions or any(q.get("solve_status") != "done" or not q.get("answer_result") for q in questions):
        raise HTTPException(409, "试卷中仍有题目缺少可用参考解答。")
    snapshots = []
    for source in questions:
        content = str(source.get("latex") or "").strip()
        answer = source.get("answer_result") or {}
        key = hashlib.sha256(re.sub(r"\s+", "", content).encode()).hexdigest()
        snapshots.append({
            "id": source["id"], "question_no": source.get("question_no"), "question": content,
            "question_type": source.get("question_type") or answer.get("question_type"),
            "answer_result": answer,
            "difficulty": answer.get("overall_difficulty") or answer.get("difficulty") or {},
            "knowledge_core": sorted(set(source.get("knowledge_core") or [])),
            "labels_reviewed": bool(source.get("labels_reviewed")),
            "knowledge_links_reviewed": bool(source.get("labels_reviewed")),
            "routines": list(source.get("confirmed_routines") or []) if source.get("labels_reviewed") else [],
            "basic_item": (answer.get("overall_difficulty") or answer.get("difficulty") or {}).get("level") == "容易",
            "canonical_question_id": key,
            "response": {"student_answer": "", "ocr_fragments": [], "source_pages": [], "source": None,
                         "review_status": "pending", "ocr_confidence": None, "manual_error_evidence": []},
            "full_score": None, "rubric": [], "rubric_confirmed": False,
            "objective_rule": None,
            "earned_score": None, "grade_result": None, "grade_status": "pending",
            "grade_review_status": "pending", "paper_quality": "valid", "paper_note": "",
            "score_source": None, "revision_history": [],
        })
    return row, snapshots


def _validate_questionnaire(value):
    if not isinstance(value, dict):
        raise HTTPException(422, "考后问卷格式无效。")
    clean = {}
    for key, allowed in _QUESTIONNAIRE_FIELDS.items():
        answer = value.get(key, "unknown")
        if answer not in allowed:
            raise HTTPException(422, f"问卷字段 {key} 的选项无效。")
        clean[key] = answer
    numbers = value.get("stuck_question_numbers", [])
    if not isinstance(numbers, list) or len(numbers) > 100 or any(type(x) is not int or x < 1 for x in numbers):
        raise HTTPException(422, "卡题题号格式无效。")
    clean.update(stuck_question_numbers=sorted(set(numbers)), note=str(value.get("note") or "")[:1000],
                 timing_source="self_report", recorded_at=time.time())
    return clean


def _validate_rubric(question, full_score, rubric, confirmed):
    try:
        score = float(full_score) if full_score is not None else None
    except (TypeError, ValueError):
        raise HTTPException(422, "题目满分格式无效。") from None
    if score is not None and (not math.isfinite(score) or score < 0 or score > 1000):
        raise HTTPException(422, "题目满分须为 0–1000。")
    if not isinstance(rubric, list) or len(rubric) > 100:
        raise HTTPException(422, "评分点格式无效。")
    from backend.grade import _collect_steps
    valid = {step["id"] for step in _collect_steps(question["answer_result"])}
    seen, clean = set(), []
    for item in rubric:
        if not isinstance(item, dict) or item.get("step_id") not in valid or item["step_id"] in seen:
            raise HTTPException(422, "评分点引用的参考步骤无效或重复。")
        try:
            points = float(item.get("max_points"))
        except (TypeError, ValueError):
            raise HTTPException(422, "评分点分值无效。") from None
        if not math.isfinite(points) or points < 0 or points > (score if score is not None else 1000):
            raise HTTPException(422, "评分点分值超出范围。")
        seen.add(item["step_id"])
        clean.append({"step_id": item["step_id"], "max_points": round(points, 2)})
    if clean and (score is None or abs(sum(x["max_points"] for x in clean) - score) > .01):
        raise HTTPException(422, "各评分点分值之和须等于题目满分。")
    if confirmed and clean and not question["answer_result"].get("chunk_results"):
        raise HTTPException(422, "试题没有分步参考答案，无法确认步骤评分点。")
    return score, clean, bool(confirmed)


def _validate_objective_rule(question, value):
    if value in (None, {}):
        return None
    if question.get("question_type") != "多选题" or not isinstance(value, dict):
        raise HTTPException(422, "仅多选题支持自定义计分规则。")
    mode = value.get("mode")
    if mode not in ("all_or_nothing", "per_option"):
        raise HTTPException(422, "多选题计分规则无效。")
    try:
        penalty = float(value.get("wrong_option_penalty", 0))
    except (TypeError, ValueError):
        raise HTTPException(422, "错选扣分格式无效。") from None
    if not math.isfinite(penalty) or penalty < 0 or penalty > 1000:
        raise HTTPException(422, "错选扣分须在 0–1000 之间。")
    return {"mode": mode, "wrong_option_penalty": round(penalty, 3)}


@router.get("/profile")
def api_profile():
    identity = current_identity() or {}
    return {"id": str(identity.get("id") or "self"), "name": identity.get("username") or "当前学生",
            "scope": "current_workspace"}


@router.get("/attempts")
def api_list_attempts(limit: int = Query(50, ge=1, le=100)):
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM student_attempts ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
    return {"attempts": [_public_attempt(_row_to_attempt(dict(row))) for row in rows]}


@router.post("/attempts", status_code=201)
def api_create_attempt(payload: dict = Body(...)):
    analysis_id = payload.get("exam_analysis_id")
    if not isinstance(analysis_id, str) or not re.fullmatch(r"[a-f0-9]{32}", analysis_id):
        raise HTTPException(422, "请从已核对的整卷分析中选择试卷。")
    source, questions = _analysis_source(analysis_id)
    attempt_type = payload.get("attempt_type", "first")
    if attempt_type not in ("first", "retake"):
        raise HTTPException(422, "考试类型无效。")
    exam_date = payload.get("exam_date") or time.strftime("%Y-%m-%d")
    if not isinstance(exam_date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", exam_date):
        raise HTTPException(422, "考试日期请使用 YYYY-MM-DD。")
    try:
        import datetime
        datetime.date.fromisoformat(exam_date)
    except ValueError:
        raise HTTPException(422, "考试日期无效。") from None
    minutes = payload.get("time_limit_minutes")
    if minutes is not None and (type(minutes) is not int or not 1 <= minutes <= 1000):
        raise HTTPException(422, "考试限时须为 1–1000 分钟。")
    now, attempt_id = time.time(), uuid.uuid4().hex
    attempt = {"id": attempt_id, "created_at": now, "updated_at": now, "revision": 1,
               "status": "created", "title": str(payload.get("title") or source["title"])[:150],
               "exam_analysis_id": analysis_id, "exam_title": source["title"], "exam_date": exam_date,
               "time_limit_minutes": minutes, "attempt_type": attempt_type,
               "viewed_answer": bool(payload.get("viewed_answer", False)), "teacher": source["teacher"],
               "exam_question_count": len(questions), "pages": [], "questions": questions,
               "questionnaire_confirmed": False,
               "questionnaire": {}, "report": None, "current_job_id": None, "error": None}
    core = {k: v for k, v in attempt.items() if k not in {
        "id", "created_at", "updated_at", "revision", "status", "pages", "questions",
        "questionnaire", "report", "current_job_id", "error"}}
    with _connect() as conn:
        conn.execute("INSERT INTO student_attempts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (attempt_id, now, now, 1, "created", _dump(core), "[]", _dump(questions), "{}", None, None, None))
        conn.commit()
    return _public_attempt(attempt)


@router.get("/attempts/{attempt_id}")
def api_get_attempt(attempt_id: str):
    return _public_attempt(_require_attempt(attempt_id))


def _safe_attempt_dir(attempt_id, revision):
    root = upload_root()
    if root.is_symlink():
        raise ValueError("作答文件目录不可用")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory = root / attempt_id / f"r{revision}"
    if directory.exists() and directory.is_symlink():
        raise ValueError("作答文件目录不可用")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return directory


async def _copy_upload(file, target):
    total, digest = 0, hashlib.sha256()
    with target.open("xb") as stream:
        os.chmod(target, 0o600)
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_FILE_BYTES:
                raise HTTPException(413, "单个文件最多 16 MiB。")
            stream.write(chunk)
            digest.update(chunk)
    if not total:
        raise HTTPException(400, "上传文件为空。")
    return total, digest.hexdigest()


def _save_page_image(raw, directory, index, filename, local_page):
    if len(raw) > 32 * 1024 * 1024:
        raise HTTPException(413, "答卷页面图片超过 32 MiB。")
    target = directory / f"page-{index + 1:03d}.png"
    with target.open("xb") as stream:
        os.chmod(target, 0o600)
        stream.write(raw)
    return {"page_no": index + 1, "source_filename": filename, "source_page": local_page,
            "image_path": str(target), "sha256": hashlib.sha256(raw).hexdigest(),
            "status": "pending", "fragments": [], "unmatched_fragments": [], "error": None}


def _render_pages(sources, directory):
    import fitz
    from PIL import Image, ImageOps
    from io import BytesIO
    from backend.multimodal import _pdf_render_scale
    pages, index, max_pages = [], 0, MAX_IMAGE_FILES
    for source in sources:
        if Path(source["path"]).suffix.lower() == ".pdf":
            max_pages = MAX_PDF_PAGES
            with fitz.open(source["path"]) as doc:
                if not 1 <= len(doc) <= MAX_PDF_PAGES:
                    raise HTTPException(422, f"PDF 页数须为 1–{MAX_PDF_PAGES} 页。")
                for local_page, page in enumerate(doc, 1):
                    scale = min(_pdf_render_scale(page, 180),
                                math.sqrt(12_000_000 / max(1, page.rect.width * page.rect.height)))
                    raw = page.get_pixmap(matrix=fitz.Matrix(scale, scale)).tobytes("png")
                    pages.append(_save_page_image(raw, directory, index, source["filename"], local_page))
                    index += 1
        else:
            try:
                with Image.open(source["path"]) as image:
                    image = ImageOps.exif_transpose(image)
                    image.thumbnail((8192, 8192))
                    if image.mode not in ("RGB", "RGBA", "L", "LA"):
                        image = image.convert("RGB")
                    buffer = BytesIO()
                    image.save(buffer, format="PNG", optimize=True)
                    raw = buffer.getvalue()
            except Exception as exc:
                raise HTTPException(422, "无法读取答卷图片，请检查文件格式。") from exc
            pages.append(_save_page_image(raw, directory, index, source["filename"], 1))
            index += 1
    if not pages or len(pages) > max_pages:
        raise HTTPException(422, f"答卷最多 {max_pages} 页；请按题分页上传。")
    return pages


@router.post("/attempts/{attempt_id}/answers", status_code=202)
async def api_upload_answers(attempt_id: str, files: list[UploadFile] = File(...)):
    attempt = _require_attempt(attempt_id)
    if attempt["status"] in ("extracting", "grading"):
        raise HTTPException(409, "当前任务仍在运行，请停止任务或等待完成后再更换答卷。")
    if not files or len(files) > MAX_IMAGE_FILES:
        raise HTTPException(400, f"请选择 1 至 {MAX_IMAGE_FILES} 个文件。")
    kinds = [Path(file.filename or "").suffix.lower() for file in files]
    if any(ext not in (".pdf", ".jpg", ".jpeg", ".png") for ext in kinds):
        raise HTTPException(400, "答卷仅支持 PDF、JPG 和 PNG。")
    if ".pdf" in kinds and len(files) != 1:
        raise HTTPException(400, "PDF 请单独上传；多文件上传时请按页顺序选择图片。")
    revision = attempt["revision"] + 1
    directory = _safe_attempt_dir(attempt_id, revision)
    total, sources, persisted = 0, [], False
    try:
        for index, file in enumerate(files):
            filename = Path(file.filename or "answer").name[:200]
            ext = Path(filename).suffix.lower()
            size, digest = await _copy_upload(file, directory / f"source-{index + 1:03d}{ext}")
            total += size
            if total > MAX_TOTAL_BYTES:
                raise HTTPException(413, "整份答卷最多 64 MiB。")
            sources.append({"filename": filename, "path": str(directory / f"source-{index + 1:03d}{ext}"),
                            "size": size, "sha256": digest})
        pages = await asyncio.to_thread(_render_pages, sources, directory)
        attempt["sources"] = [{k: v for k, v in source.items() if k != "path"} for source in sources]
        attempt["pages"] = pages
        for question in attempt["questions"]:
            question["response"] = {"student_answer": "", "ocr_fragments": [], "source_pages": [],
                                     "source": None, "review_status": "pending", "ocr_confidence": None,
                                     "manual_error_evidence": []}
            question["grade_result"], question["grade_status"], question["grade_review_status"] = None, "pending", "pending"
        attempt["questionnaire"], attempt["status"], attempt["error"], attempt["report"] = {}, "extracting", None, None
        if not _write_attempt(attempt, expected_revision=attempt["revision"]):
            raise HTTPException(409, "考试记录已变更，请刷新后重新上传。")
        persisted = True
        return _submit_extract(attempt_id)
    except HTTPException:
        if not persisted:
            shutil.rmtree(directory, ignore_errors=True)
        raise
    except Exception as exc:
        if not persisted:
            shutil.rmtree(directory, ignore_errors=True)
        current = _get_row(attempt_id)
        if current and current["revision"] == attempt["revision"]:
            current["status"], current["error"] = "error", str(exc)[:300]
            _write_attempt(current, expected_revision=current["revision"])
        raise HTTPException(400, str(exc)[:200]) from None
    finally:
        for file in files:
            await file.close()


def _json_from_vision(raw):
    text = str(raw or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.S | re.I)
    if fenced:
        text = fenced.group(1).strip()
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "[{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                return [value]
        except json.JSONDecodeError:
            continue
    raise ValueError("手写识别未返回可核对的结构化结果")


def _student_ocr_prompt(attempt):
    numbers = [q.get("question_no") for q in attempt["questions"]]
    return (
        "识别这页数学考试答卷，不要解题、订正、补全或推测缺失内容。按可见内容分段，尽量读取卷面题号和小问。"
        "逐字保留学生实际写错的符号、运算和结论，公式用 LaTeX；看不清的片段原样写【无法辨认】。"
        "没有看到作答不能判断学生是否留白。confidence 只表示文字识别清晰度，不表示解答正确。"
        f"试卷题号：{numbers}。只输出 JSON 数组，每项字段 question_no(整数或 null)、part(可空字符串)、"
        "text(原文)、confidence(high/medium/low)、explicitly_blank(仅当卷面明确空白时 true)。"
    )


def _normalize_fragments(items, known_numbers):
    fragments = []
    for index, item in enumerate(items[:100]):
        if not isinstance(item, dict):
            continue
        number = item.get("question_no")
        if type(number) is not int or number not in known_numbers:
            number = None
        text = str(item.get("text") or "").strip()[:12000]
        confidence = item.get("confidence") if item.get("confidence") in ("high", "medium", "low") else "low"
        blank = item.get("explicitly_blank") is True
        if not text and not blank:
            continue
        fragment_id = uuid.uuid5(uuid.NAMESPACE_URL, f"{number}:{item.get('part')}:{text}:{index}").hex
        fragments.append({"id": fragment_id, "question_no": number,
                          "part": str(item.get("part") or "")[:80], "text": text,
                          "confidence": confidence, "explicitly_blank": blank})
    return fragments


def _store_ocr_page(attempt_id, revision, page_no, expected_hash, fragments, error=None):
    with _LOCK:
        attempt = _get_row(attempt_id)
        if not attempt or attempt["revision"] != revision:
            return False
        page = next((p for p in attempt["pages"] if p["page_no"] == page_no), None)
        if not page or page.get("sha256") != expected_hash:
            return False
        page["status"], page["error"] = ("error", str(error)[:300]) if error else ("done", None)
        page["fragments"] = fragments or []
        page["unmatched_fragments"] = [f for f in (fragments or []) if f.get("question_no") is None]
        for question in attempt["questions"]:
            matched = [f for f in (fragments or []) if f.get("question_no") == question.get("question_no")]
            if not matched:
                continue
            response = question["response"]
            response["ocr_fragments"] = [f for f in response["ocr_fragments"] if f.get("page_no") != page_no]
            response["ocr_fragments"].extend({**fragment, "page_no": page_no} for fragment in matched)
            response["ocr_fragments"].sort(key=lambda f: (f["page_no"], f["id"]))
            response["source_pages"] = sorted({f["page_no"] for f in response["ocr_fragments"]})
            response["student_answer"] = "\n".join(f["text"] for f in response["ocr_fragments"] if f["text"])
            levels = [f["confidence"] for f in response["ocr_fragments"]]
            response["ocr_confidence"] = "low" if "low" in levels else "medium" if "medium" in levels else "high"
            response["source"], response["review_status"] = "ocr", "pending"
        if all(p["status"] == "done" for p in attempt["pages"]):
            attempt["status"], attempt["error"] = "awaiting_review", None
        elif all(p["status"] in ("done", "error") for p in attempt["pages"]):
            attempt["status"], attempt["error"] = "extract_partial", "部分页面识别失败，可以重试或手动录入。"
        return _write_attempt(attempt, expected_revision=revision, bump_revision=False)


def run_extract_job(args, ctx):
    attempt_id, revision = args["attempt_id"], args["revision"]
    attempt = _get_row(attempt_id)
    if not attempt or attempt["revision"] != revision:
        raise RuntimeError("考试记录已更新，这次识别结果已过期。")
    from backend.jobs import ensure_active
    known_numbers = {q.get("question_no") for q in attempt["questions"]}
    pending = [p for p in attempt["pages"] if p["status"] != "done"]
    results, failed = [], []
    for index, page in enumerate(pending, 1):
        ensure_active()
        attempt = _get_row(attempt_id)
        if not attempt or attempt["revision"] != revision:
            raise RuntimeError("考试记录已更新，停止过期识别。")
        ctx.progress("student_ocr", round(90 * (index - 1) / max(len(pending), 1)),
                     f"正在识别答卷第 {page['page_no']} 页（{index}/{len(pending)}）")
        try:
            encoded = base64.b64encode(Path(page["image_path"]).read_bytes()).decode("ascii")
            raw = ANSWER_EXTRACTOR.extract_page(encoded, _student_ocr_prompt(attempt), teacher=attempt.get("teacher"))
            fragments = _normalize_fragments(_json_from_vision(raw), known_numbers)
            if not _store_ocr_page(attempt_id, revision, page["page_no"], page["sha256"], fragments):
                raise RuntimeError("考试记录已变更，识别结果未保存。")
            results.append({"page_no": page["page_no"], "status": "done", "fragment_count": len(fragments)})
        except Exception as exc:
            _store_ocr_page(attempt_id, revision, page["page_no"], page["sha256"], [], str(exc))
            failed.append({"page_no": page["page_no"], "detail": str(exc)[:200]})
            results.append({"page_no": page["page_no"], "status": "error"})
        ensure_active()
        ctx.manager.partial(ctx, {"pages": results, "total": len(pending), "failed": len(failed)})
    ctx.progress("student_ocr", 100, "答卷识别完成，请核对题号与原文")
    return {"attempt_id": attempt_id, "pages": results, "failed": failed}


def _submit_extract(attempt_id):
    attempt = _require_attempt(attempt_id)
    from backend.jobs import submit_job
    try:
        job = submit_job("student_extract", {"attempt_id": attempt_id, "revision": attempt["revision"]},
                         f"student-extract-{attempt_id}-{attempt['revision']}")
    except Exception as exc:
        attempt["status"], attempt["error"] = "extract_partial", str(exc)[:200]
        _write_attempt(attempt, expected_revision=attempt["revision"])
        raise HTTPException(429, str(exc)[:200]) from None
    attempt["current_job_id"] = job["job_id"]
    _write_attempt(attempt, expected_revision=attempt["revision"], bump_revision=False)
    return {"attempt": _public_attempt(_get_row(attempt_id)), "job": job}


@router.post("/attempts/{attempt_id}/retry", status_code=202)
def api_retry_attempt(attempt_id: str):
    attempt = _require_attempt(attempt_id)
    retryable = [p for p in attempt["pages"] if p["status"] == "error"]
    if not retryable:
        raise HTTPException(409, "没有失败的识别页面需要重试。")
    for page in retryable:
        page["status"], page["error"] = "pending", None
    attempt["status"], attempt["error"] = "extracting", None
    if not _write_attempt(attempt, expected_revision=attempt["revision"]):
        raise HTTPException(409, "考试记录已更新，请刷新后重试。")
    return _submit_extract(attempt_id)


@router.patch("/attempts/{attempt_id}/unmatched")
def api_assign_unmatched(attempt_id: str, payload: dict = Body(...)):
    attempt = _require_attempt(attempt_id)
    if attempt["status"] in ("extracting", "grading"):
        raise HTTPException(409, "识别或批改任务运行中，暂不能修改题号关联。")
    mappings = payload.get("mappings")
    if not isinstance(mappings, list) or len(mappings) > 100:
        raise HTTPException(422, "题号关联内容无效。")
    q_by_id = {q["id"]: q for q in attempt["questions"]}
    for mapping in mappings:
        if not isinstance(mapping, dict) or mapping.get("question_id") not in q_by_id:
            raise HTTPException(422, "关联的试卷题目不存在。")
        page = next((p for p in attempt["pages"] if p["page_no"] == mapping.get("page_no")), None)
        if not page:
            raise HTTPException(422, "作答页不存在。")
        fragment = next((f for f in page["unmatched_fragments"] if f["id"] == mapping.get("fragment_id")), None)
        if not fragment:
            raise HTTPException(422, "未匹配的作答片段不存在。")
        question = q_by_id[mapping["question_id"]]
        assigned = {**fragment, "question_no": question["question_no"],
                    "page_no": page["page_no"], "manually_matched": True}
        response = question["response"]
        response["ocr_fragments"].append(assigned)
        response["source_pages"] = sorted(set(response["source_pages"] + [page["page_no"]]))
        response["student_answer"] = "\n".join(x["text"] for x in response["ocr_fragments"] if x.get("text"))
        response["source"], response["review_status"] = "ocr", "pending"
        page["unmatched_fragments"].remove(fragment)
    if not _write_attempt(attempt, expected_revision=attempt["revision"]):
        raise HTTPException(409, "考试记录已更新，请刷新后重新关联。")
    return _public_attempt(_require_attempt(attempt_id))


@router.patch("/attempts/{attempt_id}/questions/{question_id}")
def api_patch_question(attempt_id: str, question_id: str, payload: dict = Body(...)):
    attempt = _require_attempt(attempt_id)
    if attempt["status"] in ("extracting", "grading"):
        raise HTTPException(409, "识别或批改任务运行中，请先停止任务再修改作答。")
    question = next((q for q in attempt["questions"] if q["id"] == question_id), None)
    if not question:
        raise HTTPException(404, "考试题目不存在。")
    allowed = {"student_answer", "review_status", "full_score", "rubric", "rubric_confirmed", "objective_rule",
               "earned_score", "paper_quality", "paper_note", "manual_error_evidence", "grade_review_status",
               "basic_item"}
    if set(payload) - allowed:
        raise HTTPException(422, "请求中包含不支持的字段。")
    response_changed = any(k in payload for k in ("student_answer", "review_status", "full_score", "rubric", "rubric_confirmed", "objective_rule"))
    audited_change = any(k in payload for k in ("student_answer", "review_status", "full_score", "rubric",
        "rubric_confirmed", "objective_rule", "earned_score", "paper_quality", "paper_note", "manual_error_evidence",
        "basic_item"))
    if audited_change:
        question["revision_history"].append({"at": time.time(), "revision": attempt["revision"],
            "response": dict(question["response"]), "full_score": question["full_score"],
            "rubric": question["rubric"], "earned_score": question["earned_score"],
            "objective_rule": question.get("objective_rule"),
            "basic_item": question.get("basic_item"),
            "score_source": question.get("score_source"), "paper_quality": question.get("paper_quality"),
            "paper_note": question.get("paper_note"),
            "manual_error_evidence": question["response"].get("manual_error_evidence", []),
            "grade_result": question["grade_result"]})
        question["revision_history"] = question["revision_history"][-20:]
    if response_changed:
        question["grade_result"], question["grade_status"], question["grade_review_status"] = None, "pending", "pending"
        question["earned_score"], question["score_source"] = None, None
        if attempt["status"] in ("complete", "awaiting_questionnaire", "awaiting_grade_review"):
            attempt["status"] = "awaiting_review"
    response = question["response"]
    if "student_answer" in payload:
        answer = payload["student_answer"]
        if not isinstance(answer, str) or len(answer) > 20000:
            raise HTTPException(422, "作答文本过长或格式无效。")
        response["student_answer"], response["source"] = answer.strip(), "manual"
    if "review_status" in payload:
        if payload["review_status"] not in _REVIEW_STATES - {"pending"}:
            raise HTTPException(422, "作答核对状态无效。")
        if payload["review_status"] == "blank" and response["student_answer"].strip():
            raise HTTPException(422, "存在作答内容，不能同时确认为空白。")
        if payload["review_status"] == "confirmed" and not response["student_answer"].strip():
            raise HTTPException(422, "作答为空时请明确选择确认空白。")
        response["review_status"] = payload["review_status"]
    if any(k in payload for k in ("full_score", "rubric", "rubric_confirmed")):
        full, rubric, confirmed = _validate_rubric(question, payload.get("full_score", question["full_score"]),
            payload.get("rubric", question["rubric"]), payload.get("rubric_confirmed", question["rubric_confirmed"]))
        question["full_score"], question["rubric"], question["rubric_confirmed"] = full, rubric, confirmed
    if "objective_rule" in payload:
        question["objective_rule"] = _validate_objective_rule(question, payload["objective_rule"])
    if "earned_score" in payload:
        earned = payload["earned_score"]
        if earned is not None:
            if response.get("review_status") not in ("confirmed", "blank"):
                raise HTTPException(422, "请先确认作答内容或明确确认为空白，再录入实得分。")
            try:
                earned = float(earned)
            except (TypeError, ValueError):
                raise HTTPException(422, "实得分格式无效。") from None
            if not math.isfinite(earned) or question["full_score"] is None or not 0 <= earned <= question["full_score"]:
                raise HTTPException(422, "实得分须在已设置的题目满分范围内。")
        question["earned_score"] = earned
        question["score_source"] = "manual" if earned is not None else None
        if earned is not None:
            question["grade_status"], question["grade_review_status"] = "manual", "confirmed"
            question["grade_result"] = {"mode": "manual_score", "earned_score": earned,
                "full_score": question["full_score"], "is_correct": earned >= question["full_score"],
                "review_required": False, "score_basis": "manual"}
    if "paper_quality" in payload:
        if payload["paper_quality"] not in ("valid", "problem", "pending"):
            raise HTTPException(422, "题目质量状态无效。")
        question["paper_quality"] = payload["paper_quality"]
    if "paper_note" in payload:
        question["paper_note"] = str(payload["paper_note"] or "")[:1000]
    if "basic_item" in payload:
        if type(payload["basic_item"]) is not bool:
            raise HTTPException(422, "基础题标记格式无效。")
        question["basic_item"] = payload["basic_item"]
    if "manual_error_evidence" in payload:
        rows = payload["manual_error_evidence"]
        if not isinstance(rows, list) or len(rows) > 30:
            raise HTTPException(422, "人工错因记录格式无效。")
        from backend.grade import _collect_steps
        clean = []
        valid_step_ids = {step["id"] for step in _collect_steps(question["answer_result"])}
        for item in rows:
            if not isinstance(item, dict) or item.get("mistake_type") not in _ERROR_TYPES:
                raise HTTPException(422, "人工错因类型无效。")
            step_id = str(item.get("step_id") or "").strip()
            if step_id and step_id not in valid_step_ids:
                raise HTTPException(422, "人工错因引用了不存在的标准步骤。")
            clean.append({"mistake_type": item["mistake_type"], "detail": str(item.get("detail") or "")[:500],
                "answer_evidence": str(item.get("answer_evidence") or "")[:1000],
                "step_id": step_id[:100] or None,
                "source": "manual", "depends_on_error": bool(item.get("depends_on_error"))})
        response["manual_error_evidence"] = clean
    if "grade_review_status" in payload:
        if payload["grade_review_status"] not in ("confirmed", "pending"):
            raise HTTPException(422, "批改核对状态无效。")
        if payload["grade_review_status"] == "confirmed" and question["grade_status"] in ("pending", "error"):
            raise HTTPException(422, "请先批改或手动录入分数。")
        question["grade_review_status"] = payload["grade_review_status"]
    if "grade_review_status" not in payload and response_changed and question["grade_status"] not in ("pending", "error"):
        question["grade_review_status"] = "pending"
    attempt["report"] = None
    _check_attempt_completion(attempt)
    if not _write_attempt(attempt, expected_revision=attempt["revision"]):
        raise HTTPException(409, "考试记录已更新，请刷新后修改。")
    return _public_attempt(_require_attempt(attempt_id))


@router.patch("/attempts/{attempt_id}/questionnaire")
def api_patch_questionnaire(attempt_id: str, payload: dict = Body(...)):
    attempt = _require_attempt(attempt_id)
    if attempt["status"] in ("extracting", "grading"):
        raise HTTPException(409, "识别或批改任务运行中，请完成后再保存考后回顾。")
    attempt["questionnaire"] = _validate_questionnaire(payload)
    attempt["questionnaire_confirmed"] = True
    attempt["report"] = None
    if attempt["status"] in ("awaiting_grade_review", "awaiting_questionnaire", "complete"):
        _check_attempt_completion(attempt)
    if not _write_attempt(attempt, expected_revision=attempt["revision"]):
        raise HTTPException(409, "考试记录已更新，请刷新后再保存问卷。")
    return _public_attempt(_require_attempt(attempt_id))


@router.post("/attempts/{attempt_id}/grade", status_code=202)
def api_start_grade(attempt_id: str):
    attempt = _require_attempt(attempt_id)
    if attempt["status"] == "grading":
        raise HTTPException(409, "批改任务正在运行。")
    if any(q["response"]["review_status"] in ("pending", "unrecognized") for q in attempt["questions"]):
        raise HTTPException(409, "请逐题核对识别结果；空白题也需要明确确认。")
    if any(q["rubric"] and not q["rubric_confirmed"] for q in attempt["questions"]):
        raise HTTPException(409, "请先确认 AI 建议的评分点，或清除评分点后按总分暂定批改。")
    attempt["questionnaire"] = attempt["questionnaire"] or _validate_questionnaire({})
    for question in attempt["questions"]:
        if question["grade_status"] not in ("done", "manual"):
            question["grade_status"] = "pending"
    attempt["status"], attempt["error"] = "grading", None
    if not _write_attempt(attempt, expected_revision=attempt["revision"]):
        raise HTTPException(409, "考试记录已更新，请刷新后再批改。")
    return _submit_grade(attempt_id, _require_attempt(attempt_id)["revision"])


def _submit_grade(attempt_id, revision):
    from backend.jobs import submit_job
    attempt = _require_attempt(attempt_id)
    try:
        job = submit_job("student_grade", {"attempt_id": attempt_id, "revision": revision},
                         f"student-grade-{attempt_id}-{revision}")
    except Exception as exc:
        attempt["status"], attempt["error"] = "awaiting_grade_review", str(exc)[:200]
        _write_attempt(attempt, expected_revision=revision, bump_revision=False)
        raise HTTPException(429, str(exc)[:200]) from None
    attempt["current_job_id"] = job["job_id"]
    _write_attempt(attempt, expected_revision=revision, bump_revision=False)
    return {"attempt": _public_attempt(_require_attempt(attempt_id)), "job": job}


def _step_knowledge_links(question):
    from backend.grade import _collect_steps
    from backend.exam_analysis import _find_knowledge
    if not question.get("knowledge_links_reviewed"):
        return {}
    chunks = question["answer_result"].get("chunk_results") or []
    output = {}
    for step in _collect_steps(question["answer_result"]):
        chunk = next((x for x in chunks if x.get("chunk_id", 1) == step["chunk_id"]), {})
        category = chunk.get("category") or {}
        level1 = category.get("level1") if isinstance(category, dict) else category
        matched = _find_knowledge(level1, step.get("knowledge_point")) if step.get("knowledge_point") else None
        if matched:
            output[step["id"]] = [matched]
    return output


def _check_attempt_completion(attempt):
    if all(q["response"].get("review_status") in ("confirmed", "blank") and
           q["grade_status"] in ("done", "manual", "skipped") and
           q["grade_review_status"] == "confirmed" for q in attempt["questions"]):
        attempt["status"] = "complete" if attempt.get("questionnaire_confirmed") else "awaiting_questionnaire"
    else:
        attempt["status"] = "awaiting_grade_review"


def _persist_grade(attempt_id, revision, question_id, result=None, error=None):
    with _LOCK:
        attempt = _get_row(attempt_id)
        if not attempt or attempt["revision"] != revision:
            return False
        question = next((q for q in attempt["questions"] if q["id"] == question_id), None)
        if not question:
            return False
        question["grade_result"], question["grade_status"] = result, "error" if error else "done"
        question["grade_error"] = str(error)[:300] if error else None
        if error:
            question["grade_review_status"] = "pending"
        else:
            deterministic = result.get("mode") in ("answer_match", "confirmed_blank", "excluded_item")
            high_confidence = result.get("grading_confidence") == "high"
            question["grade_review_status"] = "confirmed" if not result.get("review_required") and (deterministic or high_confidence) else "pending"
        question["earned_score"] = result.get("earned_score") if result else None
        question["score_source"] = result.get("score_basis") if result else None
        _check_attempt_completion(attempt)
        return _write_attempt(attempt, expected_revision=revision, bump_revision=False)


def run_grade_job(args, ctx):
    attempt_id, revision = args["attempt_id"], args["revision"]
    attempt = _get_row(attempt_id)
    if not attempt or attempt["revision"] != revision or attempt["status"] != "grading":
        raise RuntimeError("考试记录已更新，取消过期批改。")
    from backend.jobs import ensure_active
    questions = [q for q in attempt["questions"] if q["grade_status"] not in ("done", "manual")]
    completed, failed = [], []
    for index, question in enumerate(questions, 1):
        ensure_active()
        attempt = _get_row(attempt_id)
        if not attempt or attempt["revision"] != revision or attempt["status"] != "grading":
            raise RuntimeError("考试记录已更新，停止过期批改。")
        response = question["response"]
        if response["review_status"] == "blank":
            result = {"mode": "confirmed_blank", "student_answer": "", "is_correct": False,
                "result_matched": False, "earned_score": 0.0 if question["full_score"] is not None else None,
                "full_score": question["full_score"], "error_suggestions": [], "review_required": False,
                "score_basis": "confirmed_blank"}
            _persist_grade(attempt_id, revision, question["id"], result)
        elif response["review_status"] != "confirmed" or not response["student_answer"].strip():
            detail = "作答尚未核对，未批改。"
            _persist_grade(attempt_id, revision, question["id"], error=detail)
            failed.append({"question_id": question["id"], "detail": detail})
        elif question["paper_quality"] == "problem":
            result = {"mode": "excluded_item", "student_answer": response["student_answer"],
                "is_correct": None, "earned_score": None, "full_score": question["full_score"],
                "review_required": False, "score_basis": "paper_issue"}
            _persist_grade(attempt_id, revision, question["id"], result)
        else:
            ctx.progress("grading", round(90 * (index - 1) / max(len(questions), 1)),
                         f"正在批改第 {question.get('question_no') or '?'} 题（{index}/{len(questions)}）")
            assessment = AssessmentSpec(question_id=question["id"],
                question_no=int(question.get("question_no") or 0), question=question["question"],
                question_type=question.get("question_type"), answer_result=question["answer_result"],
                difficulty=question.get("difficulty") or {},
                knowledge_tags=tuple(question.get("knowledge_core") or []),
                tags_confirmed=bool(question.get("labels_reviewed")),
                routines=tuple(question.get("routines") or []))
            original_text = "\n".join(fragment.get("text", "") for fragment in response.get("ocr_fragments", []))
            evidence = ResponseEvidence(source=response.get("source"), original_text=original_text,
                reviewed_text=response["student_answer"], review_status=response["review_status"],
                source_pages=tuple(response.get("source_pages") or []),
                ocr_confidence=response.get("ocr_confidence"),
                error_evidence=tuple(response.get("manual_error_evidence") or []))
            result = GRADER.grade(assessment, evidence, full_score=question.get("full_score"),
                rubric=question.get("rubric") if question.get("rubric_confirmed") else [],
                objective_rule=question.get("objective_rule"), teacher=attempt.get("teacher"))
            if result.get("error"):
                detail = result.get("detail") or result["error"]
                _persist_grade(attempt_id, revision, question["id"], error=detail)
                failed.append({"question_id": question["id"], "detail": detail})
            else:
                result["knowledge_links"] = _step_knowledge_links(question)
                result["question_id"] = question["id"]
                result["review_required"] = bool(result.get("review_required")) or response.get("ocr_confidence") in ("low", "medium")
                _persist_grade(attempt_id, revision, question["id"], result)
        completed.append(question["id"])
        ensure_active()
        ctx.manager.partial(ctx, {"completed": completed, "total": len(questions), "failed": len(failed)})
    attempt = _get_row(attempt_id)
    if attempt and attempt["revision"] == revision:
        if failed:
            attempt["status"], attempt["error"] = "awaiting_grade_review", f"{len(failed)} 道题未批改，请手动录分或重试。"
        else:
            attempt["error"] = None
            _check_attempt_completion(attempt)
        _write_attempt(attempt, expected_revision=revision, bump_revision=False)
    return {"attempt_id": attempt_id, "completed": len(completed), "failed": failed}


@router.post("/attempts/{attempt_id}/cancel")
def api_cancel_attempt(attempt_id: str):
    attempt = _require_attempt(attempt_id)
    if attempt["status"] not in ("extracting", "grading") or not attempt.get("current_job_id"):
        raise HTTPException(409, "当前没有运行中的任务。")
    from backend.jobs import cancel_job
    if not cancel_job(attempt["current_job_id"]):
        raise HTTPException(409, "任务已结束或中断。")
    if any(q["grade_status"] in ("done", "manual") for q in attempt["questions"]):
        attempt["status"] = "awaiting_grade_review"
    else:
        attempt["status"] = "extract_partial" if any(p["status"] != "done" for p in attempt["pages"]) else "awaiting_review"
    attempt["error"] = "任务已停止；已保存的结果仍可继续使用。"
    _write_attempt(attempt, expected_revision=attempt["revision"])
    return _public_attempt(_require_attempt(attempt_id))


@router.get("/attempts/{attempt_id}/pages/{page_no}/image")
def api_get_attempt_page_image(attempt_id: str, page_no: int):
    attempt = _require_attempt(attempt_id)
    page = next((row for row in attempt["pages"] if row.get("page_no") == page_no), None)
    if not page:
        raise HTTPException(404, "作答页面不存在。")
    path, root = Path(page.get("image_path") or ""), upload_root().resolve()
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
        raise HTTPException(404, "作答页面文件不存在。")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, no-store"})


def _first_independent_questions(attempts):
    seen, independent, practice = set(), [], []
    for attempt in attempts:
        if attempt["attempt_type"] != "first" or attempt["viewed_answer"]:
            practice.extend((attempt, question) for question in attempt["questions"])
            continue
        for question in attempt["questions"]:
            key = question["canonical_question_id"]
            if key in seen:
                practice.append((attempt, question))
            else:
                seen.add(key)
                independent.append((attempt, question))
    return independent, practice


def build_report(attempts, *, rules_version="1"):
    confirmed = [a for a in attempts if a["status"] == "complete"]
    confirmed.sort(key=lambda a: (a["exam_date"], a["created_at"]))
    independent, practice = _first_independent_questions(confirmed)
    knowledge_errors, routine_rows = {}, {}
    basic_groups = {}
    timing, item_issues, timeline = [], [], []
    for attempt in confirmed:
        max_points = earned_points = 0.0
        scored = blank_count = 0
        blank_question_numbers, partial_score_numbers = [], []
        for question in attempt["questions"]:
            full = question.get("full_score")
            earned = question.get("earned_score")
            lost_points = round(max(0.0, float(full) - float(earned)), 2) \
                if full is not None and earned is not None else None
            qref = {"attempt_id": attempt["id"], "attempt_title": attempt["title"],
                    "exam_date": attempt["exam_date"], "question_id": question["id"],
                    "question_no": question.get("question_no"), "question": question["question"],
                    "full_score": full, "earned_score": earned, "lost_points": lost_points}
            if question.get("paper_quality") == "problem":
                item_issues.append({**qref, "note": question.get("paper_note") or "题目被标记为需要复核。"})
                continue
            full, earned = question.get("full_score"), question.get("earned_score")
            if question["response"].get("review_status") == "blank":
                blank_count += 1
                blank_question_numbers.append(question.get("question_no"))
            if (question.get("full_score") is not None and question.get("earned_score") is not None
                    and 0 < question["earned_score"] < question["full_score"]):
                partial_score_numbers.append(question.get("question_no"))
            if (question.get("paper_quality") == "valid" and full is not None and earned is not None
                    and question.get("grade_status") in ("done", "manual")):
                max_points += full
                earned_points += earned
                scored += 1
            if question.get("paper_quality") == "pending":
                item_issues.append({**qref, "note": question.get("paper_note") or "试题质量尚未确认。",
                                    "needs_review": True})
        timeline.append({"attempt_id": attempt["id"], "title": attempt["title"], "exam_date": attempt["exam_date"],
            "attempt_type": attempt["attempt_type"], "score": round(earned_points, 2) if scored else None,
            "full_score": round(max_points, 2) if scored else None, "scored_questions": scored,
            "confirmed_blank_questions": blank_count, "time_limit_minutes": attempt.get("time_limit_minutes"),
            "questionnaire": attempt.get("questionnaire") or {}})
        questionnaire = attempt.get("questionnaire") or {}
        if blank_question_numbers or questionnaire.get("completion") == "not_completed" or \
                questionnaire.get("stuck_period") not in (None, "unknown", "none") or \
                questionnaire.get("stuck_duration_range") not in (None, "unknown", "none") or \
                questionnaire.get("skipped_and_returned") not in (None, "unknown") or \
                questionnaire.get("checked_work") not in (None, "unknown"):
            timing.append(TimingEvidence(source=questionnaire.get("timing_source", "self_report"),
                scope="exam", response_signals=({"confirmed_blank_question_numbers": blank_question_numbers,
                    "partial_score_question_numbers": partial_score_numbers},),
                self_report={"attempt_id": attempt["id"], "exam_date": attempt["exam_date"],
                    "stuck_period": questionnaire.get("stuck_period"),
                    "stuck_duration_range": questionnaire.get("stuck_duration_range"),
                    "stuck_question_numbers": questionnaire.get("stuck_question_numbers", []),
                    "skipped_and_returned": questionnaire.get("skipped_and_returned"),
                    "checked_work": questionnaire.get("checked_work"),
                    "completion": questionnaire.get("completion"),
                    "condition": questionnaire.get("condition")} ).to_dict())

    for attempt, question in independent:
        response, grade = question["response"], question.get("grade_result") or {}
        if response.get("review_status") != "confirmed" or question.get("paper_quality") != "valid":
            continue
        full_score = question.get("full_score")
        earned_score = question.get("earned_score")
        question_lost_points = round(max(0.0, float(full_score) - float(earned_score)), 2) \
            if full_score is not None and earned_score is not None else None
        evidence = response.get("manual_error_evidence") or grade.get("error_suggestions") or []
        knowledge_links = (grade.get("knowledge_links") or {}) if question.get("knowledge_links_reviewed") else {}
        for step in grade.get("step_results") or []:
            if step.get("status") != "correct":
                continue
            for knowledge_id in knowledge_links.get(step.get("id"), []):
                bucket = knowledge_errors.setdefault(knowledge_id, {
                    "evidence": [], "counter_evidence": [], "attempts": set(), "questions": set(), "mistakes": {}})
                bucket["counter_evidence"].append({"attempt_id": attempt["id"],
                    "question_id": question["id"], "question_no": question.get("question_no"),
                    "exam_date": attempt["exam_date"], "step_id": step.get("id"),
                    "answer_evidence": step.get("answer_evidence") or step.get("comment"),
                    "student_answer": response.get("student_answer")})
        previous_errors = set()
        for error in evidence:
            step_id = error.get("step_id")
            if step_id in previous_errors or error.get("depends_on_error"):
                continue
            if step_id:
                previous_errors.add(step_id)
            links = knowledge_links.get(step_id, []) if step_id else []
            # Question-level AI labels never get fanned out to every error on a
            # composite question. Only a confirmed step-to-knowledge link counts.
            for knowledge_id in links:
                bucket = knowledge_errors.setdefault(knowledge_id, {
                    "evidence": [], "counter_evidence": [], "attempts": set(), "questions": set(), "mistakes": {}})
                bucket["evidence"].append({"attempt_id": attempt["id"], "question_id": question["id"],
                    "question_no": question.get("question_no"), "exam_date": attempt["exam_date"],
                    "step_id": step_id, "step_number": error.get("step_number"),
                    "mistake_type": error.get("mistake_type"), "detail": error.get("mistake_detail") or error.get("detail"),
                    "answer_evidence": error.get("answer_evidence"), "student_answer": response.get("student_answer"),
                    "question": question.get("question"), "full_score": full_score,
                    "earned_score": earned_score, "lost_points": question_lost_points})
                bucket["attempts"].add(attempt["id"])
                bucket["questions"].add(question["canonical_question_id"])
                mistake = error.get("mistake_type") or "原因待核"
                bucket["mistakes"][mistake] = bucket["mistakes"].get(mistake, 0) + 1

        difficulty = question.get("difficulty") or {}
        basic_item = question.get("basic_item", difficulty.get("level") == "容易")
        if basic_item and question.get("labels_reviewed"):
            confirmed_labels = sorted(set(str(x).strip() for x in question.get("knowledge_core") or [] if str(x).strip()))
            confirmed_methods = sorted(set(str(x.get("id") or x.get("name") or "").strip()
                                           for x in question.get("routines") or []
                                           if str(x.get("id") or x.get("name") or "").strip()))
            comparable = [("知识点", label) for label in confirmed_labels]
            comparable.extend(("方法", label) for label in confirmed_methods)
            for axis, label in comparable:
                group_id = f"{difficulty.get('level') or '容易'}:{axis}:{label}"
                group = basic_groups.setdefault(group_id, {"axis": axis, "label": label, "level": difficulty.get("level") or "容易",
                    "incorrect": [], "correct": []})
                row = {"attempt_id": attempt["id"], "attempt_title": attempt.get("title"),
                    "question_id": question["id"], "question_no": question.get("question_no"),
                    "canonical_question_id": question.get("canonical_question_id"),
                    "exam_date": attempt["exam_date"], "question": question.get("question"),
                    "difficulty": group["level"], "full_score": full_score, "earned_score": earned_score,
                    "lost_points": question_lost_points,
                    "error_types": sorted(set(x.get("mistake_type") for x in evidence if x.get("mistake_type"))),
                    "student_answer": response.get("student_answer"),
                    "correct": grade.get("is_correct") is True}
                if grade.get("is_correct") is True:
                    group["correct"].append(row)
                elif grade.get("is_correct") is False:
                    group["incorrect"].append(row)
        for routine in question.get("routines") or []:
            routine_id = str(routine.get("id") or routine.get("name") or "").strip()
            if not question.get("labels_reviewed") or not routine_id:
                continue
            row = routine_rows.setdefault(routine_id, {"name": routine.get("name") or routine_id,
                "correct": 0, "incorrect": 0, "attempts": set(), "questions": set(), "evidence": [], "counter_evidence": []})
            row["attempts"].add(attempt["id"])
            row["questions"].add(question["canonical_question_id"])
            if grade.get("is_correct") is True:
                row["correct"] += 1
                row["counter_evidence"].append({"attempt_id": attempt["id"], "question_id": question["id"],
                    "question_no": question.get("question_no"), "exam_date": attempt["exam_date"],
                    "observation": "已确认在该方法题中完成作答。"})
            elif grade.get("is_correct") is False:
                row["incorrect"] += 1
                row["evidence"].append({"attempt_id": attempt["id"], "question_id": question["id"],
                                        "question_no": question.get("question_no"), "exam_date": attempt["exam_date"],
                                        "question": question.get("question"), "full_score": question.get("full_score"),
                                        "earned_score": question.get("earned_score"), "lost_points": lost_points})

    findings = []
    for knowledge_id, row in knowledge_errors.items():
        if not row["evidence"]:
            continue
        repeated = len(row["attempts"]) >= REPEAT_MIN_EXAMS and len(row["questions"]) >= REPEAT_MIN_QUESTIONS
        findings.append({"id": "knowledge:" + hashlib.sha256(knowledge_id.encode()).hexdigest()[:12],
            "kind": "knowledge", "title": knowledge_id,
            "observation": f"在 {len(row['attempts'])} 次独立考试、{len(row['questions'])} 道不同题中，出现关联到该步骤的错误。",
            "evidence_level": "repeated" if repeated else "initial", "supporting_evidence": row["evidence"],
            "counter_evidence": row["counter_evidence"], "possible_causes": sorted(row["mistakes"].items(), key=lambda x: -x[1]),
            "cause_confirmed": False,
            "recommendation": "先做一组不看答案的基础变式题，逐题核对该知识环节，再安排间隔复测。",
            "validation_target": "能否在未练过的新题和间隔复测中独立完成该步骤。"})
    for group_id, row in basic_groups.items():
        if not row["incorrect"]:
            continue
        repeated = (len({x["attempt_id"] for x in row["incorrect"]}) >= REPEAT_MIN_EXAMS and
                    len({x.get("canonical_question_id") or x["question_id"]
                         for x in row["incorrect"]}) >= REPEAT_MIN_QUESTIONS)
        mixed = bool(row["correct"])
        findings.append({"id": "basic:" + hashlib.sha256(group_id.encode()).hexdigest()[:12],
            "kind": "basic_performance", "title": f"基础题发挥 · {row['axis']} {row['label']}",
            "observation": f"同为{row['level']}、关联同一{row['axis']}的基础题中，{len(row['incorrect'])} 道答错、{len(row['correct'])} 道答对。" +
                ("正确与错误表现并存，稳定性仍需观察。" if mixed else "重复错误仍需用新题补测确认。"),
            "evidence_level": "repeated" if repeated else "initial",
            "supporting_evidence": row["incorrect"], "counter_evidence": row["correct"],
            "possible_causes": ["知识掌握、计算、审题、状态和时间策略仍需通过相近题补测区分。"],
            "cause_confirmed": False,
            "recommendation": "各做一组同难度不限时题和限时题，并标记检查过程与错误位置。",
            "validation_target": "下一次新基础题中记录正确情况、错误类型，以及限时与不限时的差异。"})
    for routine_id, row in routine_rows.items():
        if not row["incorrect"]:
            continue
        repeated = len(row["attempts"]) >= REPEAT_MIN_EXAMS and len(row["questions"]) >= REPEAT_MIN_QUESTIONS
        findings.append({"id": "routine:" + hashlib.sha256(routine_id.encode()).hexdigest()[:12],
            "kind": "routine", "title": row["name"],
            "observation": f"该已确认方法中，{row['incorrect']} 次作答未完整完成，{row['correct']} 次完成。",
            "evidence_level": "repeated" if repeated else "initial", "supporting_evidence": row["evidence"],
            "counter_evidence": row["counter_evidence"], "possible_causes": ["方法选择与步骤熟练度仍需通过变式题区分。"],
            "cause_confirmed": False, "recommendation": "先口述方法选择条件，再独立完成母题与变式题。",
            "validation_target": "能否在不同题面中识别并独立完成相同方法。"})
    if timing:
        findings.append({"id": "timing:self-report", "kind": "timing", "title": "考试时间分配",
            "observation": "结合已确认空白或部分得分作答与学生自述的卡题、跳题、检查情况，出现时间分配风险线索；现有数据不能定位具体用时或单独证明失分原因。",
            "evidence_level": "initial", "supporting_evidence": timing, "counter_evidence": [],
            "possible_causes": ["可能存在卡题停留或检查时间安排问题。"], "cause_confirmed": False,
            "recommendation": "练习分段计时、先跳过卡题再返回，并记录下次实际用时。",
            "validation_target": "下一次考试的完成情况、回做情况与实际用时。"})
    if item_issues:
        findings.append({"id": "paper:review", "kind": "paper_quality", "title": "试题与评分复核",
            "observation": f"{len(item_issues)} 道题被标记为需要复核，已从确定能力判断中排除。",
            "evidence_level": "initial", "supporting_evidence": item_issues, "counter_evidence": [],
            "possible_causes": [], "cause_confirmed": False,
            "recommendation": "核对原题条件、参考答案和评分标准，再决定是否恢复相关作答证据。",
            "validation_target": "人工确认题面与标准答案后，更新对应试题状态。"})
    for attempt in confirmed:
        for followup in attempt.get("followups", []):
            finding = next((f for f in findings if f["id"] == followup.get("finding_id")), None)
            if finding:
                finding["supporting_evidence"].append({**followup, "evidence_type": "independent_followup"})
                finding["evidence_level"] = "followup"
                finding["observation"] += " 已关联一条新题独立复测记录。"
    def priority_key(finding):
        category = {"paper_quality": 5, "basic_performance": 4, "knowledge": 3,
                    "routine": 2, "timing": 1}.get(finding["kind"], 0)
        evidence_strength = {"followup": 3, "repeated": 2, "initial": 1}.get(finding["evidence_level"], 0)
        feasibility = 1 if finding["recommendation"] else 0
        lost_points = sum(float(row.get("lost_points") or 0) for row in finding["supporting_evidence"])
        recent = 0
        for row in finding["supporting_evidence"]:
            try:
                recent = max(recent, datetime.date.fromisoformat(str(row.get("exam_date"))).toordinal())
            except (TypeError, ValueError):
                continue
        return (-category, -evidence_strength, -len(finding["supporting_evidence"]),
                -feasibility, -lost_points, -recent, finding["title"])
    findings.sort(key=priority_key)
    findings = [DiagnosticFinding(id=row["id"], kind=row["kind"], title=row["title"],
        observation=row["observation"], supporting_evidence=tuple(row["supporting_evidence"]),
        counter_evidence=tuple(row["counter_evidence"]), evidence_level=row["evidence_level"],
        possible_causes=tuple(row["possible_causes"]), recommendation=row["recommendation"],
        validation_target=row["validation_target"], cause_confirmed=row["cause_confirmed"]).to_dict()
        for row in findings]
    return {"rules_version": rules_version, "window_exam_count": len(confirmed),
        "attempt_ids": [a["id"] for a in confirmed], "timeline": timeline,
        "independent_question_count": len(independent), "practice_attempt_question_count": len(practice),
        "findings": findings, "priority_recommendations": RECOMMENDATION_BUILDER.build(findings, max_items=3),
        "time_evidence": timing, "paper_issues": item_issues,
        "score_note": "只汇总已确认有效且分数已知的题目；未知分数不补零。"}


def _report_stale(snapshot):
    attempts = {aid: _get_row(aid) for aid in snapshot.get("source_revisions", {})}
    return any(not attempts[aid] or attempts[aid]["revision"] != revision
               for aid, revision in snapshot.get("source_revisions", {}).items())


def _report_source_snapshot(attempts):
    fields = ("id", "question_no", "question", "question_type", "answer_result", "difficulty", "canonical_question_id",
              "knowledge_core", "labels_reviewed", "knowledge_links_reviewed", "routines",
              "basic_item",
              "response", "full_score", "rubric", "rubric_confirmed", "objective_rule",
              "earned_score", "score_source", "grade_result", "grade_status", "grade_review_status",
              "paper_quality", "paper_note", "revision_history")
    return {attempt["id"]: {"revision": attempt["revision"], "exam_analysis_id": attempt["exam_analysis_id"],
            "exam_title": attempt["exam_title"], "exam_date": attempt["exam_date"],
            "attempt_type": attempt["attempt_type"], "viewed_answer": attempt["viewed_answer"],
            "questions": [{field: question.get(field) for field in fields} for question in attempt["questions"]]}
            for attempt in attempts}


def _new_report_snapshot(attempts, *, report_type):
    return {"id": uuid.uuid4().hex, "created_at": time.time(), "report_type": report_type,
        "source_revisions": {a["id"]: a["revision"] for a in attempts},
        "rules_snapshot": {"version": "1", "default_window": DEFAULT_REPORT_WINDOW,
            "repeat_min_exams": REPEAT_MIN_EXAMS, "repeat_min_questions": REPEAT_MIN_QUESTIONS},
        "source_snapshot": _report_source_snapshot(attempts),
        "data": DIAGNOSTIC_ENGINE.analyze(attempts)}


def _save_report(snapshot):
    with _connect() as conn:
        conn.execute("INSERT INTO student_reports VALUES (?,?,?)",
                     (snapshot["id"], snapshot["created_at"], _dump(snapshot)))
        conn.commit()
    return snapshot


@router.post("/attempts/{attempt_id}/report", status_code=201)
def api_create_single_report(attempt_id: str):
    attempt = _require_attempt(attempt_id)
    if attempt["status"] != "complete":
        raise HTTPException(409, "请先完成本次考试的作答核对和批改复核。")
    return _save_report(_new_report_snapshot([attempt], report_type="single"))


@router.post("/reports", status_code=201)
def api_create_report(payload: dict = Body(default_factory=dict)):
    limit = payload.get("limit", DEFAULT_REPORT_WINDOW)
    if type(limit) is not int or not 1 <= limit <= 50:
        raise HTTPException(422, "报告范围须为 1–50 套试卷。")
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM student_attempts WHERE status='complete'").fetchall()
    attempts = [_row_to_attempt(dict(row)) for row in rows]
    attempts.sort(key=lambda a: (a["exam_date"], a["created_at"]))
    requested = payload.get("attempt_ids")
    if requested is not None:
        if not isinstance(requested, list) or any(not isinstance(x, str) for x in requested):
            raise HTTPException(422, "试卷范围格式无效。")
        if len(requested) != len(set(requested)):
            raise HTTPException(422, "比较范围不能重复选择同一场考试。")
        by_id = {a["id"]: a for a in attempts}
        if any(x not in by_id for x in requested):
            raise HTTPException(422, "所选试卷尚未完成核对或不存在。")
        attempts = [by_id[x] for x in requested]
    else:
        attempts = attempts[-limit:]
    if not attempts:
        raise HTTPException(409, "当前没有已确认的考试记录可用于生成报告。")
    return _save_report(_new_report_snapshot(attempts, report_type="multi"))


@router.get("/reports")
def api_list_reports(limit: int = Query(20, ge=1, le=100)):
    with _connect() as conn:
        rows = conn.execute("SELECT data_json FROM student_reports ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    reports = []
    for row in rows:
        snap = json.loads(row[0])
        reports.append({"id": snap["id"], "created_at": snap["created_at"],
            "report_type": snap.get("report_type", "multi"),
            "window_exam_count": snap["data"]["window_exam_count"],
            "finding_count": len(snap["data"]["findings"]), "stale": _report_stale(snap)})
    return {"reports": reports}


@router.get("/reports/{report_id}")
def api_get_report(report_id: str):
    with _connect() as conn:
        row = conn.execute("SELECT data_json FROM student_reports WHERE report_id=?", (report_id,)).fetchone()
    if not row:
        raise HTTPException(404, "学情报告不存在。")
    report = json.loads(row[0])
    report["stale"] = _report_stale(report)
    return report


@router.post("/attempts/{attempt_id}/questions/{question_id}/followup")
def api_link_followup(attempt_id: str, question_id: str, payload: dict = Body(...)):
    attempt = _require_attempt(attempt_id)
    question = next((q for q in attempt["questions"] if q["id"] == question_id), None)
    if not question:
        raise HTTPException(404, "考试题目不存在。")
    practice_id = payload.get("practice_record_id")
    if type(practice_id) is not int or practice_id < 1:
        raise HTTPException(422, "请提供有效的单题练习记录编号。")
    from backend.database import get_connection
    conn = get_connection()
    try:
        row = conn.execute("SELECT pr.correct,pr.student_answer,pr.id,q.content FROM practice_records pr "
                           "JOIN questions q ON q.id=pr.question_id WHERE pr.id=?", (practice_id,)).fetchone()
        if not row:
            raise HTTPException(404, "单题练习记录不存在。")
        record = dict(row)
    finally:
        conn.close()
    key = hashlib.sha256(re.sub(r"\s+", "", record["content"]).encode()).hexdigest()
    if key == question["canonical_question_id"]:
        raise HTTPException(422, "复测题须为新题或变式题，原题重做单独保留。")
    attempt.setdefault("followups", []).append({"id": uuid.uuid4().hex, "finding_id": payload.get("finding_id"),
        "question_id": question_id, "practice_record_id": practice_id, "correct": bool(record["correct"]),
        "student_answer": record["student_answer"], "question": record["content"],
        "linked_at": time.time(), "source": "practice_record"})
    if not _write_attempt(attempt, expected_revision=attempt["revision"]):
        raise HTTPException(409, "考试记录已更新，请刷新后再关联。")
    return _public_attempt(_require_attempt(attempt_id))
