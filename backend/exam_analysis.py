"""Whole-exam extraction, review, solving and blueprint scoring."""
from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import time
import uuid

from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile

from backend.categories import CATEGORIES
from backend.data_paths import data_path, workspace_directory
from backend.identity import can_edit_catalog, current_identity, require_catalog_editor

router = APIRouter(prefix="/exam", tags=["整卷分析"])
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / ".runtime" / "exam-analyses.sqlite3"
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_IMAGE_FILES = 30
MAX_PDF_PAGES = 80

ATTRIBUTES = [
    {"id": "direct_application", "name": "直接应用型", "description": "定义、公式或常规方法直接使用"},
    {"id": "thinking", "name": "思考型", "description": "思路选择、条件转化或非直接推理"},
    {"id": "calculation", "name": "计算型", "description": "计算负担构成主要任务"},
    {"id": "case_analysis", "name": "分类讨论型", "description": "需要区分情形完成解答"},
    {"id": "transfer", "name": "综合迁移型", "description": "实际结合多个板块或迁移已有方法"},
    {"id": "construction", "name": "构造型", "description": "关键步骤需要构造函数、对象或辅助条件"},
]
ATTRIBUTE_BY_ID = {item["id"]: item for item in ATTRIBUTES}
MOCK_DIFFICULTY = [2, 2, 2, 2, 2, 5, 5, 8, 2, 5, 8, 5, 5, 8, 2, 2, 5, 8, 12]
MOCK_KNOWLEDGE = [
    ("集合与逻辑用语", "集合的基本运算"),
    ("函数与导数", "函数的单调性"),
    ("函数与导数", "导数在函数中的综合应用"),
    ("三角函数", "三角恒等变换"),
    ("三角函数", "解三角形"),
    ("平面向量", "平面向量的数量积"),
    ("复数", "复数运算"),
    ("立体几何", "点、直线、平面之间的位置关系"),
    ("数列", "数列求和"),
    ("解析几何", "直线与圆锥曲线的位置关系"),
    ("概率统计", "随机事件的概率"),
    ("概率统计", "离散型随机变量及其分布列"),
]
MOCK_ATTRIBUTE_RANGES = [
    ("direct_application", 4, 10), ("thinking", 3, 6), ("calculation", 3, 8),
    ("case_analysis", 1, 3), ("transfer", 2, 4), ("construction", 0, 2),
]


def storage_path():
    return Path(data_path("exam-analyses.sqlite3", DEFAULT_DB))


def template_storage_path():
    identity = current_identity()
    if identity:
        if identity.get("role") == "owner":
            directory = workspace_directory() or os.environ.get("STUDY_OWNER_DATA_DIR") or os.environ.get("STUDY_AGENT_DATA_DIR") or ROOT
        else:
            directory = os.environ.get("STUDY_OWNER_DATA_DIR") or os.environ.get("STUDY_AGENT_DATA_DIR") or ROOT
        return Path(directory) / "exam-templates.sqlite3"
    return storage_path()


def upload_root():
    path = Path(data_path("exam-uploads", DEFAULT_DB.parent / "exam-uploads"))
    if path.is_symlink():
        raise ValueError("整卷文件目录不可用")
    return path


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def knowledge_id(level1, level2):
    return f"{level1}/{level2}"


def _knowledge_catalog():
    output = []
    for level1, points in CATEGORIES.items():
        for level2 in points:
            output.append({"id": knowledge_id(level1, level2), "level1": level1,
                           "level2": level2, "name": f"{level1} / {level2}"})
    return output


_KNOWLEDGE_BY_ID = {item["id"]: item for item in _knowledge_catalog()}
_CHILD_KNOWLEDGE = {}
for _l1, _children in __import__("yaml").safe_load((ROOT / "backend" / "categories.yaml").read_text(encoding="utf-8")).items():
    for _l2, _subs in (_children or {}).items():
        for _sub in _subs or []:
            _CHILD_KNOWLEDGE.setdefault((_l1, _sub), knowledge_id(_l1, _l2))


def _kp_target(level1, level2, minimum=1, maximum=3):
    return {"id": knowledge_id(level1, level2), "level1": level1, "level2": level2,
            "min": minimum, "max": maximum, "weight": 2}


def _attribute_target(attr_id, minimum, maximum):
    return {"id": attr_id, "name": ATTRIBUTE_BY_ID[attr_id]["name"],
            "min": minimum, "max": maximum, "weight": 1}


def default_templates():
    return [
        {"id": "balanced-mock", "name": "均衡模拟卷", "exam_type": "mock", "builtin": True,
         "expected_question_numbers": list(range(1, 20)),
         "difficulty_targets": [{"question_no": i, "target": score} for i, score in enumerate(MOCK_DIFFICULTY, 1)],
         "knowledge_targets": [_kp_target(a, b) for a, b in MOCK_KNOWLEDGE], "knowledge_policy": None,
         "attribute_targets": [_attribute_target(*item) for item in MOCK_ATTRIBUTE_RANGES],
         "difficulty_rule": None, "scoring": {"difficulty_max": 15}},
        {"id": "lesson-concept", "name": "新课概念入门", "exam_type": "lesson", "builtin": True,
         "expected_question_numbers": [], "difficulty_targets": [],
         "knowledge_targets": [], "knowledge_policy": {"min": 1, "max": 2, "weight": 2},
         "attribute_targets": [_attribute_target("direct_application", 2, 10),
                               _attribute_target("thinking", 0, 1),
                               _attribute_target("case_analysis", 0, 1),
                               _attribute_target("transfer", 0, 1),
                               _attribute_target("construction", 0, 0)],
         "difficulty_rule": {"min": 1, "max": 5}, "scoring": {"difficulty_max": 15}},
        {"id": "lesson-transfer", "name": "新课变式迁移", "exam_type": "lesson", "builtin": True,
         "expected_question_numbers": [], "difficulty_targets": [],
         "knowledge_targets": [], "knowledge_policy": {"min": 2, "max": 4, "weight": 2},
         "attribute_targets": [_attribute_target("direct_application", 1, 10),
                               _attribute_target("thinking", 1, 3),
                               _attribute_target("calculation", 1, 10),
                               _attribute_target("case_analysis", 0, 2),
                               _attribute_target("transfer", 1, 3),
                               _attribute_target("construction", 0, 1)],
         "difficulty_rule": {"min": 2, "max": 8}, "scoring": {"difficulty_max": 15}},
    ]


def _connect():
    path = storage_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError("整卷分析数据库不可用")
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS exam_analyses (analysis_id TEXT PRIMARY KEY, created_at REAL NOT NULL, "
                 "updated_at REAL NOT NULL, title TEXT NOT NULL, exam_type TEXT NOT NULL, template_id TEXT NOT NULL, "
                 "template_version INTEGER NOT NULL, template_json TEXT NOT NULL, scoring_json TEXT NOT NULL, "
                 "teacher TEXT NOT NULL, status TEXT NOT NULL, review_confirmed INTEGER NOT NULL DEFAULT 0, "
                 "source_files_json TEXT NOT NULL, questions_json TEXT NOT NULL, report_json TEXT, current_job_id TEXT, "
                 "report_versions_json TEXT NOT NULL DEFAULT '[]', error TEXT)")
    conn.commit()
    os.chmod(path, 0o600)
    return conn


def _template_connect():
    path = template_storage_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError("整卷分析模板数据库不可用")
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS exam_templates (template_id TEXT PRIMARY KEY, name TEXT NOT NULL, "
                 "exam_type TEXT NOT NULL, version INTEGER NOT NULL, data_json TEXT NOT NULL, builtin INTEGER NOT NULL, "
                 "updated_at REAL NOT NULL)")
    for template in default_templates():
        conn.execute("INSERT OR IGNORE INTO exam_templates VALUES (?,?,?,?,?,?,?)",
                     (template["id"], template["name"], template["exam_type"], 1,
                      _dump(template), int(template["builtin"]), time.time()))
    conn.commit()
    os.chmod(path, 0o600)
    return conn


class _Database:
    """Close a connection after the usual sqlite context-manager commit."""
    def __enter__(self):
        self.conn = _connect()
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        try:
            self.conn.rollback() if exc_type else self.conn.commit()
        finally:
            self.conn.close()


def _db():
    return _Database()


class _TemplateDatabase:
    def __enter__(self):
        self.conn = _template_connect()
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        try:
            self.conn.rollback() if exc_type else self.conn.commit()
        finally:
            self.conn.close()


def _tdb():
    return _TemplateDatabase()


def _read_template(conn, template_id):
    row = conn.execute("SELECT * FROM exam_templates WHERE template_id=?", (template_id,)).fetchone()
    if not row:
        return None
    result = json.loads(row["data_json"])
    result.update(id=row["template_id"], name=row["name"], exam_type=row["exam_type"],
                  version=row["version"], builtin=bool(row["builtin"]))
    return result


def _template_list():
    with _tdb() as conn:
        rows = conn.execute("SELECT template_id FROM exam_templates ORDER BY builtin DESC, name").fetchall()
        return [_read_template(conn, row["template_id"]) for row in rows]


def _validate_template(template_id, data):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,63}", template_id or ""):
        raise ValueError("模板编号只能使用小写字母、数字和连字符")
    if not isinstance(data, dict):
        raise ValueError("模板内容必须是对象")
    name = str(data.get("name") or "").strip()
    exam_type = data.get("exam_type")
    if not name or len(name) > 100 or exam_type not in ("mock", "lesson"):
        raise ValueError("模板名称或试卷类型无效")
    expected = data.get("expected_question_numbers") or []
    if not isinstance(expected, list) or len(expected) > 100 or any(type(x) is not int or not 1 <= x <= 999 for x in expected):
        raise ValueError("预期题号列表无效")
    if len(expected) != len(set(expected)):
        raise ValueError("预期题号不能重复")
    if exam_type == "mock" and not expected:
        raise ValueError("模拟卷模板必须设置预期题号")
    if exam_type == "lesson" and expected:
        raise ValueError("新课模板不应固定试卷题号")
    targets = data.get("knowledge_targets") or []
    if not isinstance(targets, list) or len(targets) > 300:
        raise ValueError("知识点目标列表无效")
    for item in targets:
        if not isinstance(item, dict) or item.get("id") not in _KNOWLEDGE_BY_ID:
            raise ValueError("知识点目标必须来自现有二级知识点目录")
        _validate_range(item)
    policy = data.get("knowledge_policy")
    if exam_type == "lesson":
        if not isinstance(policy, dict):
            raise ValueError("新课模板需要配置知识点题数范围")
        _validate_range(policy)
    attrs = data.get("attribute_targets") or []
    if not isinstance(attrs, list) or len(attrs) > len(ATTRIBUTES):
        raise ValueError("属性目标列表无效")
    seen = set()
    for item in attrs:
        if not isinstance(item, dict) or item.get("id") not in ATTRIBUTE_BY_ID or item["id"] in seen:
            raise ValueError("属性目标无效或重复")
        seen.add(item["id"])
        _validate_range(item)
    explicit = data.get("difficulty_targets") or []
    if not isinstance(explicit, list) or len(explicit) > 100:
        raise ValueError("逐题难度目标无效")
    for item in explicit:
        if not isinstance(item, dict) or type(item.get("question_no")) is not int or type(item.get("target")) is not int or not 0 <= item["target"] <= 15:
            raise ValueError("逐题难度目标必须是题号及 0–15 整数")
    rule = data.get("difficulty_rule")
    if rule is not None:
        if not isinstance(rule, dict) or type(rule.get("min")) is not int or type(rule.get("max")) is not int or not 0 <= rule["min"] <= rule["max"] <= 15:
            raise ValueError("递进难度范围必须在 0–15 内")
    return copy.deepcopy(data)


def _validate_range(item):
    lo, hi, weight = item.get("min"), item.get("max"), item.get("weight", 1)
    if type(lo) is not int or type(hi) is not int or not 0 <= lo <= hi <= 100:
        raise ValueError("目标题数必须为 0–100 的整数范围")
    if type(weight) not in (int, float) or not math.isfinite(weight) or not 0 <= weight <= 100:
        raise ValueError("目标权重必须在 0–100 范围内")


def _lesson_snapshot(template, selected_ids):
    snapshot = copy.deepcopy(template)
    if template["exam_type"] != "lesson":
        return snapshot
    selected_ids = list(dict.fromkeys(selected_ids or []))
    if not selected_ids:
        raise ValueError("新课模板请至少选择一个本课二级知识点")
    policy = template.get("knowledge_policy") or {"min": 1, "max": 2, "weight": 2}
    snapshot["knowledge_targets"] = []
    for kid in selected_ids:
        item = _KNOWLEDGE_BY_ID.get(kid)
        if not item:
            raise ValueError("所选知识点不在当前分类目录中")
        snapshot["knowledge_targets"].append(_kp_target(item["level1"], item["level2"],
                                                        policy["min"], policy["max"]))
        snapshot["knowledge_targets"][-1]["weight"] = policy.get("weight", 2)
    return snapshot


@router.get("/templates")
def api_templates():
    import backend.settings as settings
    return {"templates": _template_list(), "knowledge_catalog": _knowledge_catalog(),
            "attributes": ATTRIBUTES, "teachers": list(settings.get_teachers().keys()),
            "can_edit": can_edit_catalog()}


@router.put("/templates/{template_id}")
def api_update_template(template_id: str, payload: dict = Body(...)):
    require_catalog_editor()
    try:
        data = _validate_template(template_id, payload)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    now = time.time()
    with _tdb() as conn:
        old = conn.execute("SELECT version,builtin FROM exam_templates WHERE template_id=?", (template_id,)).fetchone()
        version = (old["version"] + 1) if old else 1
        builtin = old["builtin"] if old else 0
        conn.execute("INSERT INTO exam_templates VALUES (?,?,?,?,?,?,?) ON CONFLICT(template_id) DO UPDATE SET "
                     "name=excluded.name, exam_type=excluded.exam_type, version=excluded.version, "
                     "data_json=excluded.data_json, updated_at=excluded.updated_at",
                     (template_id, data["name"], data["exam_type"], version, _dump(data), builtin, now))
        conn.commit()
    data.update(id=template_id, version=version, builtin=bool(builtin))
    return data


def _get_row(analysis_id, conn=None):
    owns = conn is None
    conn = conn or _connect()
    try:
        row = conn.execute("SELECT * FROM exam_analyses WHERE analysis_id=?", (analysis_id,)).fetchone()
        return dict(row) if row else None
    finally:
        if owns:
            conn.close()


def _save_row(analysis_id, **updates):
    allowed = {"updated_at", "title", "status", "review_confirmed", "questions_json", "report_json",
               "current_job_id", "report_versions_json", "error", "template_id", "template_version",
               "template_json", "scoring_json", "teacher"}
    if set(updates) - allowed:
        raise ValueError("不支持的整卷字段")
    if not updates:
        return
    updates.setdefault("updated_at", time.time())
    sql = ",".join(f"{key}=?" for key in updates)
    with _db() as conn:
        conn.execute(f"UPDATE exam_analyses SET {sql} WHERE analysis_id=?",
                     (*updates.values(), analysis_id))
        conn.commit()


def _public_analysis(row):
    if not row:
        return None
    files = json.loads(row["source_files_json"])
    status = row["status"]
    error_value = row["error"]
    job = None
    if row["current_job_id"]:
        try:
            from backend.jobs import get_job
            job = get_job(row["current_job_id"])
        except Exception:
            job = None
    if job and status in ("extracting", "solving") and job.get("status") in ("error", "interrupted", "cancelled"):
        if job["kind"] == "exam_extract":
            status = "extract_interrupted" if job["status"] == "interrupted" else "extract_error"
        else:
            status = "cancelled" if job["status"] == "cancelled" else "interrupted" if job["status"] == "interrupted" else "partial"
        job_error = job.get("error")
        error_value = (job_error.get("detail") if isinstance(job_error, dict) else job_error) or job.get("detail")
        _save_row(row["analysis_id"], status=status, error=error_value)
    result = {"id": row["analysis_id"], "title": row["title"], "exam_type": row["exam_type"],
              "template_id": row["template_id"], "template_version": row["template_version"],
              "template": json.loads(row["template_json"]), "scoring": json.loads(row["scoring_json"]),
              "teacher": row["teacher"], "status": status,
              "review_confirmed": bool(row["review_confirmed"]), "created_at": row["created_at"],
              "updated_at": row["updated_at"], "source_files": [
                  {k: f.get(k) for k in ("filename", "size", "sha256", "kind")} for f in files],
              "questions": json.loads(row["questions_json"]), "report": json.loads(row["report_json"]) if row["report_json"] else None,
              "current_job_id": row["current_job_id"], "error": error_value,
              "report_versions": json.loads(row["report_versions_json"] or "[]")}
    result["job"] = job
    if status in ("solving", "partial", "cancelled", "interrupted", "complete") and result["questions"]:
        result["report"] = build_report(row)
    return result


@router.get("/analyses")
def api_list_analyses(limit: int = 50):
    limit = max(1, min(100, int(limit)))
    with _db() as conn:
        rows = conn.execute("SELECT * FROM exam_analyses ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return {"analyses": [_public_analysis(dict(row)) for row in rows]}


@router.get("/analyses/{analysis_id}")
def api_get_analysis(analysis_id: str):
    row = _get_row(analysis_id)
    if not row:
        raise HTTPException(404, "整卷分析记录不存在")
    return _public_analysis(row)


async def _persist_upload(file: UploadFile, directory: Path, index: int):
    filename = Path(file.filename or "upload").name[:200]
    ext = Path(filename).suffix.lower()
    if ext not in (".pdf", ".jpg", ".jpeg", ".png"):
        raise HTTPException(400, f"不支持的文件类型：{ext or '未知'}")
    target = directory / f"{index:03d}{ext}"
    digest = hashlib.sha256()
    size = 0
    with target.open("xb") as stream:
        os.chmod(target, 0o600)
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_FILE_BYTES:
                raise HTTPException(413, "单个文件最多 16 MiB")
            stream.write(chunk)
            digest.update(chunk)
    if not size:
        raise HTTPException(400, "上传文件为空")
    return {"filename": filename, "size": size, "sha256": digest.hexdigest(),
            "kind": "pdf" if ext == ".pdf" else "image", "path": str(target)}


@router.post("/analyses", status_code=202)
async def api_create_analysis(files: list[UploadFile] = File(...), template_id: str = Form("balanced-mock"),
                              title: str = Form(""), teacher: str = Form("liangliang"),
                              selected_knowledge_ids: str = Form("[]")):
    if not files or len(files) > MAX_IMAGE_FILES:
        raise HTTPException(400, f"请选择 1 至 {MAX_IMAGE_FILES} 个文件")
    try:
        selected = json.loads(selected_knowledge_ids or "[]")
    except json.JSONDecodeError:
        raise HTTPException(400, "知识点选择格式无效") from None
    if not isinstance(selected, list) or any(not isinstance(x, str) for x in selected):
        raise HTTPException(400, "知识点选择格式无效")
    with _tdb() as conn:
        template = _read_template(conn, template_id)
    if not template:
        raise HTTPException(404, "分析模板不存在")
    import backend.settings as settings
    if teacher not in settings.get_teachers():
        teacher = "liangliang"
    try:
        template = _lesson_snapshot(template, selected)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    kinds = [Path(file.filename or "").suffix.lower() for file in files]
    pdf_count = kinds.count(".pdf")
    if pdf_count and (pdf_count != 1 or len(files) != 1):
        raise HTTPException(400, "请上传一份 PDF，或按页顺序上传多张图片，不要混合 PDF 和图片")
    if not pdf_count and any(ext not in (".jpg", ".jpeg", ".png") for ext in kinds):
        raise HTTPException(400, "多文件上传仅支持 JPG/PNG 图片")
    analysis_id = uuid.uuid4().hex
    directory = upload_root() / analysis_id
    directory.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if directory.parent.is_symlink():
        raise HTTPException(500, "整卷文件目录不可用")
    directory.mkdir(mode=0o700)
    sources = []
    total = 0
    try:
        for index, file in enumerate(files):
            item = await _persist_upload(file, directory, index)
            total += item["size"]
            if total > MAX_TOTAL_BYTES:
                raise HTTPException(413, "本次上传最多 64 MiB")
            sources.append(item)
        now = time.time()
        default_title = Path(sources[0]["filename"]).stem if sources else "整卷分析"
        title = (title.strip() or default_title or "整卷分析")[:150]
        scoring = {"difficulty_max": 15, "knowledge_weight": 2, "attribute_weight": 1,
                   "difficulty_formula": "15 - sqrt(mean((actual-target)^2))",
                   "coverage_formula": "max(0, sum(weight*min^2) - sum(weight*outside_range^2))"}
        with _db() as conn:
            conn.execute("INSERT INTO exam_analyses (analysis_id,created_at,updated_at,title,exam_type,template_id,"
                         "template_version,template_json,scoring_json,teacher,status,review_confirmed,source_files_json,"
                         "questions_json,report_json,current_job_id,report_versions_json,error) "
                         "VALUES (?,?,?,?,?,?,?,?,?,?,'extracting',0,?,'[]',NULL,NULL,'[]',NULL)",
                         (analysis_id, now, now, title, template["exam_type"], template_id, template["version"],
                          _dump(template), _dump(scoring), teacher, _dump(sources)))
            conn.commit()
        from backend.jobs import submit_job
        job = await asyncio.to_thread(submit_job, "exam_extract", {"analysis_id": analysis_id},
                                      "exam-extract-" + analysis_id)
        _save_row(analysis_id, current_job_id=job["job_id"])
        return _public_analysis(_get_row(analysis_id))
    except HTTPException:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    except (ValueError, RuntimeError) as exc:
        shutil.rmtree(directory, ignore_errors=True)
        with _db() as conn:
            conn.execute("DELETE FROM exam_analyses WHERE analysis_id=?", (analysis_id,))
            conn.commit()
        from backend.jobs import JobBusy, JobConflict
        if isinstance(exc, (JobBusy, JobConflict)):
            raise HTTPException(429 if isinstance(exc, JobBusy) else 409, str(exc)) from None
        raise HTTPException(400, str(exc)) from None
    finally:
        for file in files:
            await file.close()


def _ordered_questions(questions):
    return sorted(questions or [], key=lambda q: (q.get("question_no") is None,
                                                   q.get("question_no") if q.get("question_no") is not None else 10**9,
                                                   q.get("source_pages", [10**9])[0]))


def _target_difficulty(template, question_no, position, total):
    explicit = {item["question_no"]: item["target"] for item in template.get("difficulty_targets") or []}
    if question_no in explicit:
        return explicit[question_no]
    rule = template.get("difficulty_rule")
    if not rule:
        return None
    start, end = rule["min"], rule["max"]
    if total <= 1:
        return start
    # Round half up so evenly spaced targets are independent of Python's bankers rounding.
    return int(math.floor(start + (end - start) * position / (total - 1) + 0.5))


def _difficulty_score(q):
    result = q.get("answer_result") or {}
    value = result.get("overall_difficulty") or result.get("difficulty") or {}
    score = value.get("total_score") if isinstance(value, dict) else None
    if type(score) is not int:
        return None
    return max(0, min(15, score))


def score_difficulty(questions, template):
    ordered = _ordered_questions(questions)
    total = len(ordered)
    rows, errors, missing = [], [], []
    for position, question in enumerate(ordered):
        number = question.get("question_no")
        target = _target_difficulty(template, number, position, total)
        actual = _difficulty_score(question)
        row = {"question_no": number, "target": target, "actual": actual,
               "difference": (actual - target) if actual is not None and target is not None else None,
               "direction": ("偏难" if actual > target else "偏易" if actual < target else "匹配")
               if actual is not None and target is not None else "待完成",
               "squared_error": ((actual - target) ** 2) if actual is not None and target is not None else None,
               "subquestions": []}
        for idx, chunk in enumerate((question.get("answer_result") or {}).get("chunk_results") or [], 1):
            difficulty = chunk.get("difficulty") or {}
            row["subquestions"].append({"label": chunk.get("chunk_type") or f"小问 {idx}",
                                         "actual": difficulty.get("total_score")
                                         if type(difficulty.get("total_score")) is int else None})
        if row["squared_error"] is not None:
            errors.append(row["squared_error"])
        else:
            missing.append(number)
        rows.append(row)
    rmse = math.sqrt(sum(errors) / total) if total and len(errors) == total else None
    return {"score": round(max(0.0, 15.0 - rmse), 2) if rmse is not None else None,
            "rmse": round(rmse, 3) if rmse is not None else None, "maximum": 15,
            "ready": bool(total and len(errors) == total), "question_count": total,
            "missing_question_numbers": missing, "questions": rows}


def _coverage_counts(questions, key):
    counts = {}
    for question in questions:
        number = question.get("question_no")
        tags = question.get(key) or []
        if number is None:
            continue
        for tag in {tag for tag in tags if isinstance(tag, str)}:
            counts.setdefault(tag, set()).add(number)
    return counts


def _effective_range(target, total):
    lo = min(total, max(0, int(target.get("min", 0))))
    hi = min(total, max(lo, int(target.get("max", total))))
    return lo, hi


def score_coverage(questions, template):
    ordered = _ordered_questions(questions)
    total = len(ordered)
    knowledge_counts = _coverage_counts(ordered, "knowledge_core")
    attribute_counts = _coverage_counts(ordered, "attributes")
    unresolved = []
    for q in ordered:
        unresolved.extend(q.get("unmapped_knowledge") or [])
    solves_complete = bool(ordered) and all(q.get("solve_status") == "done" for q in ordered)
    provisional = bool(unresolved) or not solves_complete
    penalty, budget = 0.0, 0.0

    def rows_for(targets, counts, kind):
        nonlocal penalty, budget
        rows = []
        for target in targets or []:
            tag_id = target.get("id")
            lo, hi = _effective_range(target, total)
            weight = float(target.get("weight", 1))
            numbers = sorted(counts.get(tag_id, set()))
            count = len(numbers)
            lower_gap, upper_gap = max(0, lo - count), max(0, count - hi)
            gap = upper_gap if upper_gap else lower_gap
            uncertain = bool(provisional and lower_gap)
            charge = upper_gap if upper_gap else (0 if uncertain else lower_gap)
            row_penalty = weight * charge * charge
            budget += weight * lo * lo
            penalty += row_penalty
            rows.append({"id": tag_id, "name": target.get("name") or target.get("level2") or
                         ATTRIBUTE_BY_ID.get(tag_id, {}).get("name", tag_id),
                         "level1": target.get("level1"), "level2": target.get("level2"),
                         "minimum": lo, "maximum": hi, "weight": weight,
                         "actual_count": count, "question_numbers": numbers,
                         "gap": gap, "gap_type": "超出" if upper_gap else "不足" if lower_gap else "符合",
                         "pending_review": uncertain, "penalty": row_penalty, "kind": kind})
        return rows

    knowledge_rows = rows_for(template.get("knowledge_targets"), knowledge_counts, "knowledge")
    attribute_rows = rows_for(template.get("attribute_targets"), attribute_counts, "attribute")
    score = max(0.0, budget - penalty)
    return {"score": None if provisional else round(score, 2), "score_preview": round(score, 2),
            "maximum": round(budget, 2), "penalty": round(penalty, 2), "ready": not provisional,
            "provisional_reason": ("仍有题目知识点待核对，未将目标计作确定缺失。" if unresolved else
                                   "仍有题目未完成解答，覆盖结果暂为部分统计。" if not solves_complete else None),
            "knowledge": knowledge_rows, "attributes": attribute_rows,
            "unmapped_knowledge": unresolved}


def build_report(analysis):
    questions = json.loads(analysis["questions_json"])
    template = json.loads(analysis["template_json"])
    prior = json.loads(analysis["report_json"]) if analysis.get("report_json") else {}
    return {"analysis_id": analysis["analysis_id"], "template_id": analysis["template_id"],
            "template_version": analysis["template_version"], "difficulty_fit": score_difficulty(questions, template),
            "coverage": score_coverage(questions, template), "question_count": len(questions),
            "completed_questions": sum(q.get("solve_status") == "done" for q in questions),
            "failed_questions": [q.get("question_no") for q in questions if q.get("solve_status") == "error"],
            **({"extraction_issues": prior["extraction_issues"]} if prior.get("extraction_issues") else {})}


def _save_report(analysis_id, *, version_label=None):
    analysis = _get_row(analysis_id)
    if not analysis:
        return None
    report = build_report(analysis)
    versions = json.loads(analysis["report_versions_json"] or "[]")
    version = len(versions) + 1
    versions.append({"version": version, "created_at": time.time(), "template_id": analysis["template_id"],
                     "template_version": analysis["template_version"], "label": version_label,
                     "template": json.loads(analysis["template_json"]), "scoring": json.loads(analysis["scoring_json"]),
                     "report": report})
    _save_row(analysis_id, report_json=_dump(report), report_versions_json=_dump(versions))
    return report


def _validate_question_numbers(questions, template):
    missing_number = [q.get("id") for q in questions if type(q.get("question_no")) is not int or q.get("question_no") < 1]
    if missing_number:
        raise HTTPException(409, {"message": "请先为每题确认有效原题号。", "question_ids": missing_number})
    seen, duplicate = set(), []
    for q in questions:
        number = q["question_no"]
        if number in seen:
            duplicate.append(number)
        seen.add(number)
    if duplicate:
        raise HTTPException(409, {"message": "题号有重复，请核对后再开始。", "duplicates": sorted(set(duplicate))})
    expected = set(template.get("expected_question_numbers") or [])
    if expected and seen != expected:
        raise HTTPException(409, {"message": "题号范围与模板不一致，请核对漏题、重题或题号。",
                                  "missing": sorted(expected - seen), "unexpected": sorted(seen - expected)})
    empty = [q.get("question_no") for q in questions if not (q.get("latex") or "").strip()]
    if empty:
        raise HTTPException(409, {"message": "存在空题干，请补全后再开始。", "question_numbers": empty})


def _submit_analysis_job(analysis_id, kind):
    from backend.jobs import submit_job
    request_id = f"{kind}-{analysis_id}-{uuid.uuid4().hex[:12]}"
    job = submit_job(kind, {"analysis_id": analysis_id}, request_id)
    _save_row(analysis_id, current_job_id=job["job_id"])
    return job


@router.post("/analyses/{analysis_id}/start", status_code=202)
def api_start_analysis(analysis_id: str, payload: dict = Body(default_factory=dict)):
    analysis = _get_row(analysis_id)
    if not analysis:
        raise HTTPException(404, "整卷分析记录不存在")
    questions = json.loads(analysis["questions_json"])
    if analysis["status"] not in ("awaiting_review", "cancelled", "partial", "error", "interrupted"):
        raise HTTPException(409, "当前状态不能开始解题")
    if not payload.get("confirm_review"):
        raise HTTPException(422, "请确认已核对原题号、跨页合并和题目完整性。")
    template = json.loads(analysis["template_json"])
    _validate_question_numbers(questions, template)
    incomplete = [q.get("question_no") for q in questions if not q.get("is_complete", True)]
    if incomplete:
        raise HTTPException(409, {"message": "请先确认或补全不完整题目。", "question_numbers": incomplete})
    for q in questions:
        if q.get("solve_status") != "done":
            q["solve_status"] = "pending"
    _save_row(analysis_id, status="solving", review_confirmed=1, questions_json=_dump(questions), error=None)
    try:
        job = _submit_analysis_job(analysis_id, "exam_solve")
    except Exception as exc:
        _save_row(analysis_id, status="awaiting_review", error=str(exc)[:300])
        raise HTTPException(429, str(exc)) from None
    return {"analysis_id": analysis_id, "job": job}


class QuestionPatchError(ValueError):
    pass


@router.patch("/analyses/{analysis_id}/questions")
def api_patch_questions(analysis_id: str, payload: dict = Body(...)):
    analysis = _get_row(analysis_id)
    if not analysis:
        raise HTTPException(404, "整卷分析记录不存在")
    patches = payload.get("questions")
    if not isinstance(patches, list) or len(patches) > 100:
        raise HTTPException(422, "questions 必须是题目修改列表")
    questions = json.loads(analysis["questions_json"])
    if analysis["status"] in ("extracting", "solving"):
        raise HTTPException(409, "处理中的试卷不能修改，请先停止任务。")
    by_id = {q["id"]: q for q in questions}
    try:
        for patch in patches:
            if not isinstance(patch, dict) or patch.get("id") not in by_id:
                raise QuestionPatchError("题目编号无效")
            question = by_id[patch["id"]]
            label_fields = {"knowledge_core", "knowledge_prerequisites", "attributes"}
            requested_labels = label_fields.intersection(patch)
            if requested_labels and requested_labels != label_fields:
                raise QuestionPatchError("人工确认标签时，请同时提交核心知识、前置知识和属性三组标签。")
            previous_labels = {"knowledge_core": list(question.get("knowledge_core") or []),
                               "knowledge_prerequisites": list(question.get("knowledge_prerequisites") or []),
                               "attributes": list(question.get("attributes") or [])}
            if "question_no" in patch:
                number = patch["question_no"]
                if type(number) is not int or not 1 <= number <= 999:
                    raise QuestionPatchError("原题号必须为 1–999 的整数")
                question["question_no"] = number
            if "latex" in patch:
                text = patch["latex"]
                if not isinstance(text, str) or len(text) > 50000:
                    raise QuestionPatchError("题干内容无效或过长")
                if text != question.get("latex"):
                    question["latex"] = text
                    question["answer_result"] = None
                    question["solve_status"] = "pending"
                    question["knowledge_core"] = []
                    question["knowledge_prerequisites"] = []
                    question["attributes"] = []
                    question["unmapped_knowledge"] = []
                    question["labels_source"] = "candidate"
                    question["labels_reviewed"] = False
                    question["attribute_evidence"] = {}
            if "is_complete" in patch:
                if type(patch["is_complete"]) is not bool:
                    raise QuestionPatchError("题目完整性必须是布尔值")
                question["is_complete"] = patch["is_complete"]
                question["needs_review"] = not patch["is_complete"]
            for field in ("knowledge_core", "knowledge_prerequisites"):
                if field in patch:
                    values = patch[field]
                    if not isinstance(values, list) or any(v not in _KNOWLEDGE_BY_ID for v in values):
                        raise QuestionPatchError("知识点必须来自当前二级分类目录")
                    question[field] = list(dict.fromkeys(values))
            if "attributes" in patch:
                values = patch["attributes"]
                if not isinstance(values, list) or any(v not in ATTRIBUTE_BY_ID for v in values):
                    raise QuestionPatchError("属性标签无效")
                question["attributes"] = list(dict.fromkeys(values))
            if any(k in patch for k in ("knowledge_core", "knowledge_prerequisites", "attributes")):
                from backend.identity import current_user_id
                history = question.setdefault("label_revision_history", [])
                history.append({"at": time.time(), "editor_id": current_user_id(), "source": "manual_correction",
                                "previous": previous_labels,
                                "current": {"knowledge_core": list(question.get("knowledge_core") or []),
                                            "knowledge_prerequisites": list(question.get("knowledge_prerequisites") or []),
                                            "attributes": list(question.get("attributes") or [])}})
                question["labels_source"] = "manual"
                question["labels_reviewed"] = True
                question["unmapped_knowledge"] = []
    except QuestionPatchError as exc:
        raise HTTPException(422, str(exc)) from None
    versions = json.loads(analysis["report_versions_json"] or "[]")
    if analysis["report_json"]:
        old_report = json.loads(analysis["report_json"])
        versions.append({"version": len(versions) + 1, "created_at": time.time(), "template_id": analysis["template_id"],
                         "template_version": analysis["template_version"], "label": "修正前报告",
                         "template": json.loads(analysis["template_json"]),
                         "scoring": json.loads(analysis["scoring_json"]), "report": old_report})
    _save_row(analysis_id, questions_json=_dump(questions), report_json=None,
              report_versions_json=_dump(versions),
              status="awaiting_review" if not analysis["review_confirmed"] else "partial")
    return _public_analysis(_get_row(analysis_id))


def _retry_extract(analysis_id):
    _save_row(analysis_id, status="extracting", error=None)
    try:
        return _submit_analysis_job(analysis_id, "exam_extract")
    except Exception as exc:
        _save_row(analysis_id, status="extract_error", error=str(exc)[:300])
        raise HTTPException(429, str(exc)) from None


@router.post("/analyses/{analysis_id}/retry", status_code=202)
def api_retry_analysis(analysis_id: str, payload: dict = Body(default_factory=dict)):
    analysis = _get_row(analysis_id)
    if not analysis:
        raise HTTPException(404, "整卷分析记录不存在")
    questions = json.loads(analysis["questions_json"])
    if not questions or analysis["status"] in ("extract_error", "extract_interrupted"):
        job = _retry_extract(analysis_id)
        return {"analysis_id": analysis_id, "job": job}
    if not analysis["review_confirmed"]:
        raise HTTPException(409, "请先核对并确认题号与题目完整性。")
    _validate_question_numbers(questions, json.loads(analysis["template_json"]))
    selected = payload.get("question_ids")
    if selected is not None and (not isinstance(selected, list) or any(not isinstance(v, str) for v in selected)):
        raise HTTPException(422, "question_ids 必须是题目编号列表")
    for q in questions:
        if (selected is None or q["id"] in selected) and (q.get("solve_status") != "done" or _difficulty_score(q) is None):
            q["solve_status"] = "pending"
            q["error"] = None
    if selected is not None and any(qid not in {q["id"] for q in questions} for qid in selected):
        raise HTTPException(422, "题目编号列表包含无效项")
    if not any(q.get("solve_status") == "pending" for q in questions):
        raise HTTPException(409, "没有需要重试的題目")
    _save_row(analysis_id, status="solving", questions_json=_dump(questions), error=None)
    try:
        return {"analysis_id": analysis_id, "job": _submit_analysis_job(analysis_id, "exam_solve")}
    except Exception as exc:
        _save_row(analysis_id, status="partial", error=str(exc)[:300])
        raise HTTPException(429, str(exc)) from None


@router.post("/analyses/{analysis_id}/cancel")
def api_cancel_analysis(analysis_id: str):
    analysis = _get_row(analysis_id)
    if not analysis:
        raise HTTPException(404, "整卷分析记录不存在")
    if analysis["status"] not in ("extracting", "solving"):
        raise HTTPException(409, "当前分析没有运行中的任务")
    from backend.jobs import cancel_job
    if analysis.get("current_job_id") and not cancel_job(analysis["current_job_id"]):
        raise HTTPException(409, "后台任务已经结束")
    _save_row(analysis_id, status="cancelled", error="用户已停止当前处理。")
    return _public_analysis(_get_row(analysis_id))


@router.post("/analyses/{analysis_id}/rescore")
def api_rescore_analysis(analysis_id: str, payload: dict = Body(default_factory=dict)):
    analysis = _get_row(analysis_id)
    if not analysis:
        raise HTTPException(404, "整卷分析记录不存在")
    template_id = payload.get("template_id") or analysis["template_id"]
    with _tdb() as conn:
        template = _read_template(conn, template_id)
    if not template:
        raise HTTPException(404, "分析模板不存在")
    if template["exam_type"] != analysis["exam_type"]:
        raise HTTPException(422, "模板类型与试卷类型不一致")
    if template["exam_type"] == "lesson":
        selected = [item["id"] for item in json.loads(analysis["template_json"]).get("knowledge_targets", [])]
        template = _lesson_snapshot(template, selected)
    _save_row(analysis_id, template_id=template_id, template_version=template["version"],
              template_json=_dump(template))
    report = _save_report(analysis_id, version_label="重新评分")
    return {"analysis": _public_analysis(_get_row(analysis_id)), "report": report}


@router.post("/analyses/{analysis_id}/add-to-bank")
def api_add_to_bank(analysis_id: str, payload: dict = Body(...)):
    analysis = _get_row(analysis_id)
    if not analysis:
        raise HTTPException(404, "整卷分析记录不存在")
    numbers = payload.get("question_numbers")
    if not isinstance(numbers, list) or not numbers or any(type(n) is not int for n in numbers):
        raise HTTPException(422, "请选择要入库的题号")
    questions = json.loads(analysis["questions_json"])
    selected = [q for q in questions if q.get("question_no") in set(numbers)]
    if len(selected) != len(set(numbers)):
        raise HTTPException(422, "所选题号不存在")
    if any(q.get("solve_status") != "done" or not q.get("answer_result") for q in selected):
        raise HTTPException(409, "只有已完成解答的题目可以入库")
    from backend.database import save_question
    saved = []
    for q in selected:
        answer = copy.deepcopy(q["answer_result"])
        answer["source_type"] = "模拟题" if analysis["exam_type"] == "mock" else "ai生成"
        answer["source_meta"] = ({"paper": analysis["title"], "question_no": str(q["question_no"])}
                                  if analysis["exam_type"] == "mock" else
                                  {"reference_id": f"exam:{analysis_id}:{q['question_no']}"})
        saved.append({"question_no": q["question_no"], "id": save_question(q["latex"], answer)})
    return {"saved": saved}


def _extract_prompt(page_no, page_total):
    return ("你正在识别一张数学试卷的单页。请逐题提取本页可见题目，必须保留卷面上的原题号，不能按页重编号。\n"
            f"这是第 {page_no}/{page_total} 页。\n"
            "若题目从上一页延续，请沿用原题号；若题目延续到下一页，注明 continues_to_next=true。题目只截到一半时"
            "注明 is_complete=false；不确定编号时 index=null，不得猜题号。保留题干、所有选项、小问、图表可辨信息和公式，"
            "不要作答。只输出合法 JSON 数组，每项包含 index（原题号整数或 null）、latex（该页片段）、type、"
            "continues_from_previous、continues_to_next、is_complete、confidence（0 到 1）。")


def _parse_exam_response(raw):
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.S | re.I)
    if fenced:
        text = fenced.group(1)
    decoder = json.JSONDecoder()
    cursor = 0
    while True:
        start = text.find("[", cursor)
        if start < 0:
            return []
        try:
            data, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            cursor = start + 1
            continue
        if isinstance(data, list):
            return data
        cursor = start + 1


def _iter_exam_pdf_images(file_path, mm):
    """Render bounded exam pages so large PDF page boxes do not exhaust memory."""
    import fitz
    with fitz.open(file_path) as doc:
        total = len(doc)
        for index in range(total):
            page = doc[index]
            width, height = page.rect.width, page.rect.height
            area = max(1.0, width * height)
            scale = min(mm._pdf_render_scale(page, 180), math.sqrt(12_000_000 / area))
            data = None
            while scale >= 0.1:
                pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
                data = pix.tobytes("png")
                del pix
                if len(data) <= mm.MAX_IMAGE_BYTES:
                    break
                del data
                data = None
                scale *= 0.75
            if data is None:
                raise ValueError(f"PDF 第 {index + 1} 页图片过大，无法安全识别")
            yield index + 1, total, base64.b64encode(data).decode("ascii")
            del data


def _merge_page_questions(pages, expected_numbers):
    questions, duplicates, unassigned = [], [], []
    by_number = {}
    last_question = None
    for page in pages:
        page_no = page["page_no"]
        for item in page["items"]:
            if not isinstance(item, dict):
                continue
            latex = str(item.get("latex") or item.get("content") or item.get("text") or "").strip()
            if not latex:
                continue
            number = item.get("index", item.get("question_number", item.get("original_number")))
            if type(number) is not int or number < 1 or number > 999:
                number = None
            if number is None and item.get("continues_from_previous") and last_question:
                number = last_question["question_no"]
            type_name = item.get("type") or item.get("question_type") or ""
            allowed_types = ("选择题", "多选题", "填空题", "大题")
            if type_name not in allowed_types:
                type_name = ""
            try:
                confidence = float(item.get("confidence", 0.75))
            except (TypeError, ValueError):
                confidence = 0.5
            complete = item.get("is_complete") is not False and "【原图此处截断】" not in latex
            continuation = bool(item.get("continues_from_previous"))
            previous = by_number.get(number) if number is not None else None
            can_merge = bool(previous and page_no != previous["source_pages"][-1] and page_no == previous["source_pages"][-1] + 1
                             and (continuation or not previous["is_complete"] or previous.get("continues_to_next")))
            page_detail = {"page_no": page_no, "filename": page.get("filename"),
                           "file_page": page.get("file_page"), "asset_refs": page["asset_refs"][:8]}
            if can_merge:
                previous["latex"] = (previous["latex"].rstrip() + "\n" + latex).strip()
                previous["source_pages"].append(page_no)
                previous["source_page_details"].append(page_detail)
                previous["asset_refs"] = list(dict.fromkeys(previous["asset_refs"] + page["asset_refs"]))[:8]
                previous["is_complete"] = complete
                previous["continues_to_next"] = bool(item.get("continues_to_next"))
                previous["confidence"] = min(previous["confidence"], confidence)
                last_question = previous
                continue
            q = {"id": uuid.uuid4().hex, "question_no": number, "latex": latex,
                 "question_type": type_name, "source_pages": [page_no], "asset_refs": page["asset_refs"][:8],
                 "source_page_details": [page_detail],
                 "is_complete": complete, "continues_to_next": bool(item.get("continues_to_next")),
                 "confidence": max(0, min(1, confidence)), "needs_review": (number is None or not complete or confidence < 0.5),
                 "solve_status": "pending", "answer_result": None, "knowledge_core": [],
                 "knowledge_prerequisites": [], "attributes": [], "labels_source": "candidate",
                 "labels_reviewed": False, "unmapped_knowledge": []}
            if number is None:
                unassigned.append(q["id"])
            elif number in by_number:
                duplicates.append(number)
            else:
                by_number[number] = q
            questions.append(q)
            last_question = q
    expected = set(expected_numbers or [])
    found = {q["question_no"] for q in questions if q.get("question_no") is not None}
    issues = {"missing_question_numbers": sorted(expected - found),
              "duplicate_question_numbers": sorted(set(duplicates)), "unassigned_question_ids": unassigned,
              "incomplete_question_numbers": sorted(q["question_no"] for q in questions
                                                    if q.get("question_no") is not None and not q.get("is_complete"))}
    return questions, issues


def extract_analysis(analysis_id, ctx):
    analysis = _get_row(analysis_id)
    if not analysis:
        raise RuntimeError("整卷分析记录不存在")
    from backend.jobs import JobStopped, ensure_active
    sources = json.loads(analysis["source_files_json"])
    template = json.loads(analysis["template_json"])
    pages = []
    from backend import multimodal as mm
    page_total = 0
    try:
        for source_index, source in enumerate(sources):
            path = source["path"]
            ext = Path(path).suffix.lower()
            if ext == ".pdf":
                import fitz
                with fitz.open(path) as doc:
                    page_count = len(doc)
                if not 1 <= page_count <= MAX_PDF_PAGES:
                    raise ValueError(f"PDF 页数必须在 1–{MAX_PDF_PAGES} 页")
                iterator = _iter_exam_pdf_images(path, mm)
                for local_page, total, encoded in iterator:
                    page_total += 1
                    ctx.progress("recognizing", min(45, 3 + round(42 * page_total / max(page_count, 1))),
                                 f"多模态识别 PDF 第 {local_page}/{total} 页")
                    raw = mm._call_multimodal_model(image_base64=encoded,
                                                   text=_extract_prompt(local_page, total),
                                                   teacher=analysis.get("teacher"))
                    ensure_active()
                    refs = mm._retain_preview(encoded)
                    pages.append({"page_no": page_total, "items": _parse_exam_response(raw), "asset_refs": refs,
                                  "filename": source["filename"], "file_page": local_page})
                    del encoded
            else:
                page_total += 1
                encoded = mm.image_to_base64(path)
                ctx.progress("recognizing", min(45, 3 + round(42 * page_total / max(len(sources), 1))),
                             f"多模态识别第 {page_total} 张图片")
                raw = mm._call_multimodal_model(image_base64=encoded,
                                               text=_extract_prompt(page_total, len(sources)),
                                               teacher=analysis.get("teacher"))
                ensure_active()
                refs = mm._retain_preview(encoded)
                pages.append({"page_no": page_total, "items": _parse_exam_response(raw), "asset_refs": refs,
                              "filename": source["filename"], "file_page": 1})
                del encoded
        expected = template.get("expected_question_numbers") or []
        questions, issues = _merge_page_questions(pages, expected)
        if not questions:
            raise ValueError("未能识别出题目，请检查文件清晰度后重试。")
        ensure_active()
        _save_row(analysis_id, status="awaiting_review", questions_json=_dump(questions),
                  report_json=_dump({"extraction_issues": issues}), error=None)
        ctx.progress("review", 100, "切题完成，请核对原题号与跨页题目")
        return {"analysis_id": analysis_id, "question_count": len(questions), "issues": issues}
    except JobStopped:
        _save_row(analysis_id, status="cancelled", error="用户已停止当前扫描。")
        raise
    except Exception as exc:
        _save_row(analysis_id, status="extract_error", error=str(exc)[:300])
        raise


_TRIGGERS = {
    "thinking": re.compile(r"转化|观察|不妨|设法|关键在于|由此可得|逆向|反设"),
    "calculation": re.compile(r"计算|求值|化简|解方程|运算"),
    "case_analysis": re.compile(r"分类讨论|分情况|分别讨论|当.{0,12}时|否则"),
    "construction": re.compile(r"构造|辅助线|构造函数|设.{0,8}函数|作.{0,8}(?:垂线|中点|辅助)"),
}


def _find_knowledge(level1, label):
    if not isinstance(label, str):
        return None
    text = label.strip()
    if not text:
        return None
    if level1 and text in CATEGORIES.get(level1, []):
        return knowledge_id(level1, text)
    if level1 and (level1, text) in _CHILD_KNOWLEDGE:
        return _CHILD_KNOWLEDGE[(level1, text)]
    matches = [item["id"] for item in _knowledge_catalog() if item["level2"] == text]
    if len(matches) == 1:
        return matches[0]
    child_matches = [kid for (parent, child), kid in _CHILD_KNOWLEDGE.items() if child == text and (not level1 or parent == level1)]
    return child_matches[0] if len(child_matches) == 1 else None


def _analyze_labels(question, result):
    chunks = result.get("chunk_results") or []
    core, prerequisites, unmapped, all_text, categories = set(), set(), [], [], set()
    dimension_max = {"非常规程度": 0, "计算量": 0, "分类讨论": 0, "知识广度": 0, "条件转化难度": 0}
    pattern_difficulties = []
    for chunk in chunks:
        try:
            pattern_value = (chunk.get("difficulty") or {}).get("pattern_difficulty")
            if pattern_value is not None:
                pattern_difficulties.append(int(pattern_value))
        except (TypeError, ValueError):
            pass
        category = chunk.get("category") or {}
        if isinstance(category, str):
            level1, level2 = category, ""
        else:
            level1, level2 = category.get("level1", ""), category.get("level2", "")
        if level1:
            categories.add(level1)
        if level2:
            found = _find_knowledge(level1, level2)
            if found:
                core.add(found)
            else:
                unmapped.append({"text": level2, "source": "category"})
        labels = chunk.get("knowledge_points") or []
        if isinstance(labels, str):
            labels = [labels]
        for label in labels:
            found = _find_knowledge(level1, label)
            if found:
                core.add(found)
            elif isinstance(label, str) and label.strip():
                unmapped.append({"text": label.strip(), "source": "knowledge_points"})
        for step in chunk.get("steps") or []:
            step_text = " ".join(str(step.get(k) or "") for k in ("title", "standard_writing", "detailed_writing", "knowledge_point"))
            all_text.append(step_text)
            step_label = step.get("knowledge_point")
            if isinstance(step_label, str) and step_label.strip():
                found = _find_knowledge(level1, step_label)
                if found:
                    (prerequisites if "前置" in step_text[:16] or "准备知识" in step_text[:16] else core).add(found)
                elif not any(step_label.strip() == item["text"] for item in unmapped):
                    unmapped.append({"text": step_label.strip(), "source": "step"})
            dims = ((step.get("step_difficulty") or {}).get("dimensions") or {})
            for key in dimension_max:
                try:
                    dimension_max[key] = max(dimension_max[key], int(dims.get(key, 0)))
                except (TypeError, ValueError):
                    pass
    text = " ".join(all_text)
    if not core and not prerequisites and not unmapped:
        unmapped.append({"text": "未识别到二级知识点", "source": "classification_missing"})
    attributes = set()
    evidence = {}
    step_count = sum(len(chunk.get("steps") or []) for chunk in chunks)
    if step_count and step_count <= 3 and max(dimension_max.values() or [0]) <= 1 and not any(pattern_difficulties):
        attributes.add("direct_application")
        evidence["direct_application"] = "解答步骤较少，五维步骤评分未显示明显复杂环节。"
    for attr, pattern in _TRIGGERS.items():
        match = pattern.search(text)
        dim_signal = ((attr == "thinking" and (dimension_max["非常规程度"] >= 1 or dimension_max["条件转化难度"] >= 2 or max(pattern_difficulties or [0]) >= 2))
                      or (attr == "calculation" and dimension_max["计算量"] >= 2)
                      or (attr == "case_analysis" and dimension_max["分类讨论"] >= 1))
        if match or dim_signal:
            attributes.add(attr)
            evidence[attr] = match.group(0) if match else "步骤五维评分显示此类任务。"
    if len(categories) >= 2:
        attributes.add("transfer")
        evidence["transfer"] = "解析板块涉及：" + "、".join(sorted(categories))
    if len(core) >= 2 and "transfer" not in attributes:
        attrs = set(attributes)
        attrs.add("transfer")
        attributes = attrs
        evidence["transfer"] = "解析标注了多个核心知识点。"
    return {"knowledge_core": sorted(core), "knowledge_prerequisites": sorted(prerequisites),
            "unmapped_knowledge": list({(x["text"], x["source"]): x for x in unmapped}.values()),
            "attributes": sorted(attributes), "attribute_evidence": evidence,
            "attribute_review": {"source": "candidate", "reviewed": False}}


def solve_analysis(analysis_id, ctx):
    analysis = _get_row(analysis_id)
    if not analysis:
        raise RuntimeError("整卷分析记录不存在")
    questions = json.loads(analysis["questions_json"])
    teacher = analysis["teacher"]
    pending = [q for q in questions if q.get("solve_status") != "done" or _difficulty_score(q) is None]
    if not pending:
        pending = [q for q in questions if q.get("solve_status") == "pending"]
    total = len(pending)
    from backend.jobs import _solve, ensure_active
    errors = []
    for position, q in enumerate(pending, 1):
        ensure_active()
        q["solve_status"] = "solving"
        q["error"] = None
        _save_row(analysis_id, questions_json=_dump(questions), status="solving")
        ctx.progress("exam_solve", max(2, round(100 * (position - 1) / max(total, 1))),
                     f"正在解答第 {q.get('question_no') or '?'} 题（{position}/{total}）")
        args = {"question": q["latex"], "teacher": teacher, "question_type": q.get("question_type") or None,
                "asset_refs": q.get("asset_refs") or [], "save": False}
        try:
            outcome = _solve(args, ctx)
            ensure_active()
            result = outcome.value
            if result.get("error") and not result.get("chunk_results"):
                raise RuntimeError(result.get("detail") or result.get("error"))
            labels = _analyze_labels(q, result)
            q.update(labels)
            q["answer_result"] = result
            q["solve_status"] = "done" if _difficulty_score({**q, "answer_result": result}) is not None else "needs_review"
            if q["solve_status"] == "needs_review":
                q["error"] = "解析已完成，但没有可用的 0–15 难度分。"
        except Exception as exc:
            q["solve_status"] = "error"
            q["error"] = str(exc)[:300]
            errors.append(q.get("question_no"))
        _save_row(analysis_id, questions_json=_dump(questions))
        try:
            ctx.manager.partial(ctx, {"analysis_id": analysis_id, "done": position, "total": total,
                                      "failed_question_numbers": errors})
        except Exception:
            pass
    analysis = _get_row(analysis_id)
    latest = json.loads(analysis["questions_json"])
    all_done = bool(latest) and all(q.get("solve_status") == "done" and _difficulty_score(q) is not None for q in latest)
    has_error = any(q.get("solve_status") in ("error", "needs_review") for q in latest)
    status = "complete" if all_done else "partial" if has_error or total else "complete"
    _save_row(analysis_id, status=status, error=None if status == "complete" else "部分题目未完成或缺少难度分，可单独重试。")
    report = _save_report(analysis_id)
    ctx.progress("report", 100, "整卷分析报告已生成" if status == "complete" else "已生成部分报告，仍有题目待补")
    return {"analysis_id": analysis_id, "status": status, "report": report}


def run_extract_job(args, ctx):
    return extract_analysis(args["analysis_id"], ctx)


def run_solve_job(args, ctx):
    return solve_analysis(args["analysis_id"], ctx)
