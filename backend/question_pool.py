"""Owner-only archival question pool. Nothing becomes curriculum until commit.

The pool is independent of study_agent/mastery/catalog databases. Source records
are immutable evidence; editable candidates and prepared AI answers live here.
"""
from __future__ import annotations

from contextlib import closing
from copy import deepcopy
from fractions import Fraction
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import unicodedata
import uuid
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from backend.categories import CATEGORIES
from backend.data_paths import data_path
from backend.identity import require_catalog_editor as _require_catalog_editor, current_identity
from backend.source_policy import MIN_YEAR, apply_year_policy, is_old, year_evidence, default_mock_years

ROOT = Path(__file__).resolve().parent.parent
COMPLETENESS = {"complete", "needs_review", "deferred_graphic", "failed"}
STATUSES = {"unreviewed", "reviewed", "preparing", "ready", "needs_review", "imported"}
ROLES = {"question", "mother", "variant1", "variant2", "variant3"}
QUESTION_TYPES = ["选择题", "多选题", "填空题", "大题", "未知"]
_LOCK = threading.RLock()


def _require_owner():
    _require_catalog_editor()
    # Legacy demo sessions predate account identities, but carry a lifetime
    # lease. They must not reach this owner capability through /jobs.
    from backend.data_paths import _BACKGROUND_LEASE
    if current_identity() is None and _BACKGROUND_LEASE.get() is not None:
        raise HTTPException(403, "原题池仅供主人维护。")


def storage_path():
    return Path(data_path("question_pool.db", ROOT / ".runtime" / "question_pool.db"))


def files_directory():
    return Path(data_path("question-pool", ROOT / ".runtime" / "question-pool")) / "files"


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load(value, default=None):
    try:
        return json.loads(value) if value else default
    except (TypeError, ValueError):
        return default


def _connection():
    _require_owner()
    path = storage_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS pool_sources (
          id INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL,
          name TEXT NOT NULL, kind TEXT NOT NULL, url TEXT DEFAULT '',
          revision TEXT DEFAULT '', license TEXT DEFAULT '', publication_allowed INTEGER DEFAULT 0,
          filename TEXT DEFAULT '', file_token TEXT DEFAULT '', options_json TEXT DEFAULT '{}',
          import_status TEXT DEFAULT 'ready', import_error TEXT DEFAULT '',
          created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS pool_items (
          id INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL, question TEXT NOT NULL,
          answer TEXT DEFAULT '', solution TEXT DEFAULT '', categories_json TEXT DEFAULT '[]',
          question_type TEXT DEFAULT '未知', year TEXT DEFAULT '', region TEXT DEFAULT '',
          completeness TEXT DEFAULT 'complete', reason TEXT DEFAULT '', status TEXT DEFAULT 'unreviewed',
          assignment_json TEXT DEFAULT '{"role":"question"}', version INTEGER DEFAULT 1,
          prepared_json TEXT, prepared_version INTEGER, answer_check_json TEXT,
          formal_question_id INTEGER, preparing_job_id TEXT, prepare_error TEXT DEFAULT '',
          created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS pool_categories (
          item_id INTEGER REFERENCES pool_items(id), category TEXT,
          PRIMARY KEY(item_id,category));
        CREATE INDEX IF NOT EXISTS idx_pool_category ON pool_categories(category,item_id);
        CREATE INDEX IF NOT EXISTS idx_pool_filter ON pool_items(completeness,status,question_type,year,id);
        CREATE TABLE IF NOT EXISTS pool_occurrences (
          id INTEGER PRIMARY KEY, item_id INTEGER REFERENCES pool_items(id),
          source_id INTEGER REFERENCES pool_sources(id), source_key TEXT NOT NULL,
          page_start INTEGER, page_end INTEGER, question_no TEXT DEFAULT '',
          original_question TEXT DEFAULT '', original_answer TEXT DEFAULT '', original_solution TEXT DEFAULT '',
          raw_json TEXT DEFAULT '{}', completeness TEXT, reason TEXT DEFAULT '', is_duplicate INTEGER DEFAULT 0,
          UNIQUE(source_id,source_key));
        CREATE INDEX IF NOT EXISTS idx_pool_occurrence_item ON pool_occurrences(item_id);
        CREATE TABLE IF NOT EXISTS pool_commits (
          request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result_json TEXT NOT NULL,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    """)
    # Add evidence per occurrence: a duplicate can have several exam years.
    migrations = {"pool_occurrences": {"year": "TEXT DEFAULT ''", "year_evidence_json": "TEXT DEFAULT '{}'"},
                  "pool_sources": {"import_report_json": "TEXT DEFAULT '{}'"}}
    for table, columns in migrations.items():
        present = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for column, definition in columns.items():
            if column not in present:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    conn.commit()
    path.chmod(0o600)
    return conn


def _text(value):
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return _dump(value)
    return str(value).strip()


def _canonical(text):
    # Do not remove internal whitespace inside mathematics or \text{}.
    return "\n".join(line.rstrip() for line in unicodedata.normalize("NFC", str(text)).replace("\r\n", "\n").splitlines()).strip()


def _record_fingerprint(question, source_id, key, raw):
    """Images are conditions too; identical text with different diagrams is distinct."""
    refs = (raw or {}).get("image_refs") or []
    images = [str(ref.get("sha256") or ref.get("url") or ref.get("path") or "")
              if isinstance(ref, dict) else str(ref) for ref in refs]
    value = question if question else f"missing:{source_id}:{key}"
    if images:
        value += "\nimage_refs:" + _dump(images)
    elif (raw or {}).get("graphic_file"):
        value += "\ngraphic_file:" + _dump(raw["graphic_file"])
    return sha256(value.encode()).hexdigest()


def _categories(values):
    if not isinstance(values, list) or any(not isinstance(v, str) or v not in CATEGORIES for v in values):
        raise HTTPException(400, "大板块必须取自项目现有分类。")
    return list(dict.fromkeys(values))


def _ids(values):
    if not isinstance(values, list) or not values or len(values) > 200 or any(type(v) is not int or v < 1 for v in values):
        raise HTTPException(400, "请选择 1 至 200 道原题。")
    return list(dict.fromkeys(values))


def _set_categories(conn, item_id, values):
    conn.execute("DELETE FROM pool_categories WHERE item_id=?", (item_id,))
    conn.executemany("INSERT INTO pool_categories VALUES (?,?)", [(item_id, value) for value in values])


def _source_stats(conn, source_id):
    rows = conn.execute("SELECT completeness,count(*) FROM pool_occurrences WHERE source_id=? GROUP BY completeness", (source_id,)).fetchall()
    counts = {r[0]: r[1] for r in rows}
    total, unique, duplicates = conn.execute("SELECT count(*),count(DISTINCT item_id),coalesce(sum(is_duplicate),0) FROM pool_occurrences WHERE source_id=?", (source_id,)).fetchone()
    return {"total": total, "unique": unique, "duplicates": duplicates, "collected": counts.get("complete", 0) + counts.get("needs_review", 0), **{v: counts.get(v, 0) for v in sorted(COMPLETENESS)}}


def _source_public(conn, row):
    source = dict(row)
    source.pop("fingerprint", None)
    source.pop("file_token", None)
    source["options"] = _load(source.pop("options_json"), {})
    source["import_report"] = _load(source.pop("import_report_json", "{}"), {})
    source["publication_allowed"] = bool(source["publication_allowed"])
    source["has_file"] = bool(row["file_token"])
    source["stats"] = _source_stats(conn, source["id"])
    return source


def create_source(source):
    _require_owner()
    name, kind = _text(source.get("name")), _text(source.get("kind"))
    if not name or not kind:
        raise HTTPException(400, "请填写来源名称和类型。")
    identity = {k: _text(source.get(k)) for k in ("name", "kind", "url", "revision", "file_token")}
    fingerprint = sha256(_dump(identity).encode()).hexdigest()
    with _LOCK, closing(_connection()) as conn, conn:
        conn.execute("""INSERT OR IGNORE INTO pool_sources
            (fingerprint,name,kind,url,revision,license,publication_allowed,filename,file_token,options_json)
            VALUES (?,?,?,?,?,?,?,?,?,?)""", (fingerprint, name, kind, identity["url"], identity["revision"],
            _text(source.get("license")), int(source.get("publication_allowed") is True), _text(source.get("filename")),
            identity["file_token"], _dump(source.get("options") or {})))
        return conn.execute("SELECT id FROM pool_sources WHERE fingerprint=?", (fingerprint,)).fetchone()[0]


def _retry_failed_record(conn, locator, record):
    """Repair extraction failures while retaining the failed attempt as evidence."""
    question = _canonical(_text(record.get("question")))
    if not question or record.get("completeness") == "failed":
        return False
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    old = conn.execute("SELECT * FROM pool_items WHERE id=?", (locator["item_id"],)).fetchone()
    fingerprint = _record_fingerprint(question, locator["source_id"], locator["source_key"], record.get("raw"))
    previous_raw = _load(locator["raw_json"], {}) or {}
    automatic_version = previous_raw.get("automatic_repair_version")
    if old["status"] != "unreviewed" or (old["version"] != 1 and automatic_version != old["version"]):
        return False  # Never replace the owner's corrections or prepared work.
    if (question == locator["original_question"] and _text(record.get("answer")) == locator["original_answer"]
            and _text(record.get("solution")) == locator["original_solution"] and record.get("completeness") == locator["completeness"]
            and previous_raw.get("conversion_pending_pages") == (record.get("raw") or {}).get("conversion_pending_pages")
            and fingerprint == old["fingerprint"]
            and previous_raw.get("image_refs") == (record.get("raw") or {}).get("image_refs")
            and previous_raw.get("image_assets") == (record.get("raw") or {}).get("image_assets")
            and previous_raw.get("conversion_parser") == (record.get("raw") or {}).get("conversion_parser")
            and record.get("question_type") == old["question_type"]):
        return False
    raw = deepcopy(record.get("raw") or {})
    raw["automatic_repair_version"] = old["version"] + 1
    raw["previous_extraction_attempts"] = _load(locator["raw_json"], {}).get("previous_extraction_attempts", []) + [{
        "question": locator["original_question"], "answer": locator["original_answer"], "solution": locator["original_solution"],
        "reason": locator["reason"], "raw": _load(locator["raw_json"], {}),
    }]
    values = list(dict.fromkeys(v for v in record.get("categories", []) if v in CATEGORIES))
    completeness = record.get("completeness", "needs_review")
    if completeness not in COMPLETENESS:
        completeness = "needs_review"
    match = conn.execute("SELECT id FROM pool_items WHERE fingerprint=?", (fingerprint,)).fetchone()
    sole = conn.execute("SELECT count(*) FROM pool_occurrences WHERE item_id=?", (old["id"],)).fetchone()[0] == 1
    fields = (fingerprint, question, _text(record.get("answer")), _text(record.get("solution")), _dump(values),
              record.get("question_type") if record.get("question_type") in QUESTION_TYPES else "未知",
              _text(record.get("year")), _text(record.get("region")), completeness, _text(record.get("reason")))
    if (not match and sole) or (match and match["id"] == old["id"]):
        target_id = old["id"]
        conn.execute("UPDATE pool_items SET fingerprint=?,question=?,answer=?,solution=?,categories_json=?,question_type=?,year=?,region=?,completeness=?,reason=?,version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=?", (*fields, target_id))
        _set_categories(conn, target_id, values)
    elif match:
        target_id = match["id"]
    else:
        target_id = conn.execute("INSERT INTO pool_items (fingerprint,question,answer,solution,categories_json,question_type,year,region,completeness,reason) VALUES (?,?,?,?,?,?,?,?,?,?)", fields).lastrowid
        _set_categories(conn, target_id, values)
    raw["automatic_repair_version"] = conn.execute("SELECT version FROM pool_items WHERE id=?", (target_id,)).fetchone()[0]
    conn.execute("""UPDATE pool_occurrences SET item_id=?,page_start=?,page_end=?,question_no=?,original_question=?,original_answer=?,original_solution=?,raw_json=?,completeness=?,reason=?,is_duplicate=?,year=?,year_evidence_json=? WHERE id=?""",
                 (target_id, record.get("page_start"), record.get("page_end"), _text(record.get("question_no")),
                  question, _text(record.get("answer")), _text(record.get("solution")), _dump(raw), completeness, _text(record.get("reason")),
                  int(bool(match and match["id"] != old["id"])), _text(record.get("year")),
                  _dump(record["raw"].get("year_evidence", {})), locator["id"]))
    if target_id != old["id"] and sole:
        conn.execute("DELETE FROM pool_categories WHERE item_id=?", (old["id"],))
        conn.execute("DELETE FROM pool_items WHERE id=?", (old["id"],))
    return True


def import_records(source, records, *, retry_failed=False):
    """Persist every source locator, including deferred/malformed records. Replay is a no-op."""
    _require_owner()
    source_id = create_source(source) if isinstance(source, dict) else int(source)
    with closing(_connection()) as conn:
        source_row = conn.execute("SELECT * FROM pool_sources WHERE id=?", (source_id,)).fetchone()
        if not source_row:
            raise HTTPException(404, "来源不存在。")
        conn.execute("UPDATE pool_sources SET import_status='running',import_error='' WHERE id=?", (source_id,))
        conn.commit()
        processed, recovered, skipped_old, unknown_year, total_read = 0, 0, 0, 0, 0
        def report():
            return {"minimum_year": MIN_YEAR, "total_read": total_read, "skipped_old": skipped_old, "unknown_year": unknown_year}
        def checkpoint():
            conn.execute("UPDATE pool_sources SET import_report_json=? WHERE id=?", (_dump(report()), source_id))
            conn.commit()
        try:
            for index, record in enumerate(records):
                if not isinstance(record, dict):
                    record = {"source_key": str(index), "completeness": "failed", "reason": "来源条目格式错误", "raw": {"value": _text(record)}}
                total_read += 1
                if is_old(record, dict(source_row)):
                    skipped_old += 1
                    continue
                record = apply_year_policy(record, dict(source_row))
                unknown_year += int(record["year"] is None)
                key = _text(record.get("source_key")) or str(index)
                locator = conn.execute("SELECT o.*,i.fingerprint AS item_fingerprint FROM pool_occurrences o JOIN pool_items i ON i.id=o.item_id WHERE o.source_id=? AND o.source_key=?", (source_id, key)).fetchone()
                raw = record.get("raw") or {}
                if not locator and raw.get("collector") and raw.get("paper_validation", {}).get("valid") and record.get("question_no"):
                    # Verified whole papers have unique question IDs even when
                    # OCR ordering or heading normalization changes a locator.
                    choices = conn.execute("SELECT o.*,i.fingerprint AS item_fingerprint FROM pool_occurrences o JOIN pool_items i ON i.id=o.item_id WHERE o.source_id=? AND o.question_no=?", (source_id, _text(record["question_no"]))).fetchall()
                    choices = [o for o in choices if _load(o["raw_json"], {}).get("collector") and _load(o["raw_json"], {}).get("file_sha256") == raw.get("file_sha256")]
                    if len(choices) == 1:
                        locator = choices[0]
                        key = locator["source_key"]
                if locator:
                    previous_raw = _load(locator["raw_json"], {}) or {}
                    raw = record.get("raw") or {}
                    waiting_scan = not locator["original_question"] and previous_raw.get("scan")
                    pending_pages = previous_raw.get("conversion_pending_pages")
                    image_identity_changed = raw.get("image_refs") and (_record_fingerprint(
                        _canonical(_text(record.get("question"))), source_id, key, raw) != locator["item_fingerprint"]
                        or raw.get("image_refs") != previous_raw.get("image_refs")
                        or raw.get("image_assets") != previous_raw.get("image_assets"))
                    conversion_changed = raw.get("collector") and (locator["original_question"] != _canonical(_text(record.get("question"))) or raw.get("conversion_parser") != previous_raw.get("conversion_parser"))
                    if retry_failed and (locator["completeness"] == "failed" or waiting_scan or pending_pages or image_identity_changed or conversion_changed):
                        recovered += int(_retry_failed_record(conn, locator, record))
                        if recovered % 250 == 0:
                            checkpoint()
                    continue
                question = _canonical(_text(record.get("question")))
                completeness = record.get("completeness", "complete")
                if completeness not in COMPLETENESS:
                    completeness = "needs_review"
                reason = _text(record.get("reason"))
                if not question and not (record.get("raw") or {}).get("scan"):
                    completeness, reason = "failed", reason or "缺少题干，保留来源条目待修正"
                values = [v for v in record.get("categories", []) if v in CATEGORIES]
                fingerprint = _record_fingerprint(question, source_id, key, record.get("raw"))
                answer, solution = _text(record.get("answer")), _text(record.get("solution"))
                previous = conn.execute("SELECT * FROM pool_items WHERE fingerprint=?", (fingerprint,)).fetchone()
                if previous:
                    item_id = previous["id"]
                    # Complement missing information only for unedited, unprepared candidates.
                    if previous["status"] == "unreviewed" and previous["version"] == 1:
                        merged = list(dict.fromkeys(_load(previous["categories_json"], []) + values))
                        conn.execute("UPDATE pool_items SET answer=CASE WHEN answer='' THEN ? ELSE answer END,solution=CASE WHEN solution='' THEN ? ELSE solution END,categories_json=? WHERE id=?", (answer, solution, _dump(merged), item_id))
                        _set_categories(conn, item_id, merged)
                        if answer and previous["answer"] and _compare_answers(previous["answer"], answer)["status"] != "match":
                            conn.execute("UPDATE pool_items SET completeness='needs_review',reason='不同来源的原答案不一致或尚未确认等价，请核对出处' WHERE id=?", (item_id,))
                else:
                    cursor = conn.execute("""INSERT INTO pool_items
                        (fingerprint,question,answer,solution,categories_json,question_type,year,region,completeness,reason)
                        VALUES (?,?,?,?,?,?,?,?,?,?)""", (fingerprint, question, answer, solution, _dump(values),
                        record.get("question_type") if record.get("question_type") in QUESTION_TYPES else "未知",
                        _text(record.get("year")), _text(record.get("region")), completeness, reason))
                    item_id = cursor.lastrowid
                    _set_categories(conn, item_id, values)
                conn.execute("""INSERT INTO pool_occurrences
                    (item_id,source_id,source_key,page_start,page_end,question_no,original_question,original_answer,original_solution,raw_json,completeness,reason,is_duplicate,year,year_evidence_json)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (item_id, source_id, key, record.get("page_start"), record.get("page_end"),
                    _text(record.get("question_no")), question, answer, solution, _dump(record.get("raw") or {}), completeness, reason, int(previous is not None),
                    _text(record.get("year")), _dump(record["raw"]["year_evidence"])))
                processed += 1
                if processed % 250 == 0:
                    checkpoint()
            conn.execute("UPDATE pool_sources SET import_status='done' WHERE id=?", (source_id,))
            checkpoint()
        except Exception as exc:
            checkpoint()  # Completed records remain available for an idempotent retry.
            conn.execute("UPDATE pool_sources SET import_status='error',import_error=? WHERE id=?", (str(exc)[:500], source_id))
            conn.commit()
            raise
        return {"source_id": source_id, "added_occurrences": processed, "recovered_occurrences": recovered,
                "report": report(), "stats": _source_stats(conn, source_id)}


def _occurrences(conn, ids):
    result = {value: [] for value in ids}
    if not ids:
        return result
    marks = ",".join("?" for _ in ids)
    for row in conn.execute(f"""SELECT o.*,s.name AS source_name,s.kind,s.url,s.revision,s.license,s.publication_allowed,s.filename
        FROM pool_occurrences o JOIN pool_sources s ON s.id=o.source_id WHERE o.item_id IN ({marks}) ORDER BY o.id""", ids):
        data = dict(row)
        data["raw"] = _load(data.pop("raw_json"), {})
        data["year_evidence"] = _load(data.pop("year_evidence_json", "{}"), {})
        data["publication_allowed"] = bool(data["publication_allowed"])
        result[data["item_id"]].append(data)
    return result


def _item_public(row, occurrences=None, full=True):
    item = dict(row)
    item.pop("fingerprint", None)
    item["categories"] = _load(item.pop("categories_json"), [])
    item["assignment"] = _load(item.pop("assignment_json"), {"role": "question"})
    prepared = item.pop("prepared_json")
    item["prepared"] = _load(prepared) if full else None
    item["has_prepared"] = bool(prepared)
    item["answer_check"] = _load(item.pop("answer_check_json"), {"status": "unverified", "detail": "尚未生成 AI 解析"})
    item["occurrences"] = occurrences or []
    item["year_status"] = "known" if item.get("year") else "unknown"
    if not full:
        item["solution"] = ""
        for occurrence in item["occurrences"]:
            occurrence.pop("raw", None)
            occurrence.pop("original_solution", None)
            occurrence.pop("original_question", None)
    return item


def get_item(item_id):
    with closing(_connection()) as conn:
        row = conn.execute("SELECT * FROM pool_items WHERE id=?", (item_id,)).fetchone()
        if not row:
            raise HTTPException(404, "原题不存在。")
        return _item_public(row, _occurrences(conn, [item_id])[item_id])


def list_items(*, category=None, source_id=None, year=None, region=None, question_type=None, keyword=None,
               completeness="text_only", status=None, has_answer=None, page=1, page_size=40):
    if type(page) is not int or page < 1 or type(page_size) is not int or not 1 <= page_size <= 100:
        raise HTTPException(400, "分页参数无效。")
    clauses, params = [], []
    if completeness == "text_only":
        clauses.append("i.completeness IN ('complete','needs_review')")
    elif completeness:
        if completeness not in COMPLETENESS:
            raise HTTPException(400, "完整性筛选无效。")
        clauses.append("i.completeness=?")
        params.append(completeness)
    for field, value in (("year", year), ("region", region), ("question_type", question_type), ("status", status)):
        if value:
            clauses.append(f"i.{field}=?")
            params.append(str(value))
    if category == "待分类":
        clauses.append("NOT EXISTS (SELECT 1 FROM pool_categories c WHERE c.item_id=i.id)")
    elif category:
        clauses.append("EXISTS (SELECT 1 FROM pool_categories c WHERE c.item_id=i.id AND c.category=?)")
        params.append(category)
    if source_id:
        clauses.append("EXISTS (SELECT 1 FROM pool_occurrences o WHERE o.item_id=i.id AND o.source_id=?)")
        params.append(source_id)
    if has_answer is not None:
        clauses.append("i.answer<>''" if has_answer else "i.answer=''")
    if keyword:
        for word in str(keyword).split()[:12]:
            clauses.append("(i.question LIKE ? ESCAPE '\\' OR i.answer LIKE ? ESCAPE '\\' OR EXISTS (SELECT 1 FROM pool_occurrences o JOIN pool_sources s ON s.id=o.source_id WHERE o.item_id=i.id AND (s.name LIKE ? ESCAPE '\\' OR o.source_key LIKE ? ESCAPE '\\')))")
            term = "%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            params.extend([term] * 4)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with closing(_connection()) as conn:
        total = conn.execute("SELECT count(*) FROM pool_items i" + where, params).fetchone()[0]
        rows = conn.execute("SELECT i.* FROM pool_items i" + where + " ORDER BY i.id LIMIT ? OFFSET ?", [*params, page_size, (page - 1) * page_size]).fetchall()
        occurrences = _occurrences(conn, [r["id"] for r in rows])
        return {"data": [_item_public(r, occurrences[r["id"]], full=False) for r in rows], "total": total, "page": page, "page_size": page_size}


def meta():
    with closing(_connection()) as conn:
        stats = {"total": conn.execute("SELECT count(*) FROM pool_items").fetchone()[0]}
        stats.update({r[0]: r[1] for r in conn.execute("SELECT completeness,count(*) FROM pool_items GROUP BY completeness")})
        stats["imported"] = conn.execute("SELECT count(*) FROM pool_items WHERE status='imported'").fetchone()[0]
        sources = [_source_public(conn, r) for r in conn.execute("SELECT * FROM pool_sources ORDER BY id")]
        coverage = [{"category": c, "candidates": conn.execute("SELECT count(*) FROM pool_categories pc JOIN pool_items i ON i.id=pc.item_id WHERE category=? AND completeness IN ('complete','needs_review')", (c,)).fetchone()[0]} for c in CATEGORIES]
        years = [r[0] for r in conn.execute("SELECT DISTINCT year FROM pool_items WHERE year<>'' ORDER BY year DESC")]
    from backend.patterns import get_patterns, _get_conn
    patterns = get_patterns()
    with closing(_get_conn()) as conn:
        roles = {}
        for pid, role in conn.execute("SELECT pattern_id,role FROM pattern_questions"):
            roles.setdefault(pid, set()).add(role)
    for row in coverage:
        current = [p for p in patterns if p["category"] == row["category"]]
        row.update(patterns=len(current), mothers=sum(bool(p.get("mother_id")) for p in current),
                   missing_mothers=sum(not p.get("mother_id") for p in current),
                   gaps=[{"pattern_id": p["id"], "name": p["name"], "mother_missing": not p.get("mother_id"),
                          "missing_roles": [role for role in ("variant1", "variant2", "variant3") if role not in roles.get(p["id"], set())]}
                         for p in current if not p.get("mother_id") or len(roles.get(p["id"], set())) < 4])
    return {"categories": list(CATEGORIES), "question_types": QUESTION_TYPES, "sources": sources, "stats": stats, "coverage": coverage, "years": years}


def _assignment(value):
    if not isinstance(value, dict) or value.get("role", "question") not in ROLES:
        raise HTTPException(400, "入库角色无效。")
    role = value.get("role", "question")
    if role == "question":
        return {"role": role}
    pid, new = value.get("pattern_id"), value.get("new_pattern")
    if pid is not None:
        if type(pid) is not int or pid < 1:
            raise HTTPException(400, "套路编号无效。")
        return {"role": role, "pattern_id": pid}
    if not isinstance(new, dict) or not _text(new.get("name")) or new.get("category") not in CATEGORIES:
        raise HTTPException(400, "请选择套路，或填写新套路名称和板块。")
    difficulty = new.get("difficulty", 1)
    if type(difficulty) is not int or difficulty not in range(4):
        raise HTTPException(400, "套路难度必须为 0 至 3。")
    return {"role": role, "new_pattern": {"name": _text(new["name"])[:150], "category": new["category"], "description": _text(new.get("description")), "difficulty": difficulty}}


def update_item(item_id, changes):
    _require_owner()
    if not isinstance(changes, dict):
        raise HTTPException(400, "修改内容无效。")
    allowed = {"question", "answer", "solution", "categories", "question_type", "completeness", "reason", "status", "assignment", "expected_version"}
    if set(changes) - allowed:
        raise HTTPException(400, "包含不可编辑字段。")
    with _LOCK, closing(_connection()) as conn, conn:
        row = conn.execute("SELECT * FROM pool_items WHERE id=?", (item_id,)).fetchone()
        if not row:
            raise HTTPException(404, "原题不存在。")
        if row["status"] == "imported":
            raise HTTPException(409, "已经入库，请在正式题库修改。")
        if changes.get("expected_version", row["version"]) != row["version"]:
            raise HTTPException(409, "原题已被修改，请刷新后再保存。")
        values = {}
        for field in ("question", "answer", "solution", "reason"):
            if field in changes:
                if not isinstance(changes[field], str) or len(changes[field]) > 200000:
                    raise HTTPException(400, "文字字段无效或过长。")
                values[field] = changes[field].strip()
        if "question" in values:
            if not values["question"]:
                raise HTTPException(400, "题干不能为空。")
            origin = conn.execute("SELECT source_id,source_key,raw_json FROM pool_occurrences WHERE item_id=? ORDER BY id LIMIT 1", (item_id,)).fetchone()
            fingerprint = _record_fingerprint(_canonical(values["question"]), origin["source_id"] if origin else "",
                                              origin["source_key"] if origin else "", _load(origin["raw_json"], {}) if origin else {})
            duplicate = conn.execute("SELECT id FROM pool_items WHERE fingerprint=? AND id<>?", (fingerprint, item_id)).fetchone()
            if duplicate:
                raise HTTPException(409, f"题干与原题 #{duplicate[0]} 相同，请使用已有原题。")
            values["fingerprint"] = fingerprint
        if "categories" in changes:
            categories = _categories(changes["categories"])
            values["categories_json"] = _dump(categories)
            _set_categories(conn, item_id, categories)
        for field, choices in (("question_type", QUESTION_TYPES), ("completeness", COMPLETENESS)):
            if field in changes:
                if changes[field] not in choices:
                    raise HTTPException(400, "题型或完整性状态无效。")
                values[field] = changes[field]
        if "status" in changes:
            if changes["status"] not in ("unreviewed", "reviewed"):
                raise HTTPException(400, "只能手动标记未处理或已查看。")
            values["status"] = changes["status"]
        if "assignment" in changes:
            values["assignment_json"] = _dump(_assignment(changes["assignment"]))
        invalidates = bool(set(changes) & {"question", "answer", "solution", "categories", "question_type", "completeness"})
        if invalidates:
            values.update(prepared_json=None, prepared_version=None, answer_check_json=None, status="reviewed", preparing_job_id=None, prepare_error="")
        if values:
            sets = ",".join(f"{field}=?" for field in values)
            # Assignment edits do not invalidate the generated mathematics.
            version_sql = ",version=version+1" if invalidates else ""
            conn.execute(f"UPDATE pool_items SET {sets}{version_sql},updated_at=CURRENT_TIMESTAMP WHERE id=?", [*values.values(), item_id])
    return get_item(item_id)


def _answer_normal(text):
    s = str(text or "").strip()
    s = re.sub(r"(?:正确)?(?:选项|答案)(?:为|是|：|:)?|故选|选择|选", "", s)
    s = s.replace("\\left", "").replace("\\right", "").replace("\\displaystyle", "")
    # Keep separators in coordinates, intervals and sets: (1,23) is not (12,3).
    s = re.sub(r"[\s$]", "", s).translate(str.maketrans({"，": ",", "；": ";", "：": ":", "．": "."}))
    if re.fullmatch(r"[A-H,、;。.]+", s):
        return re.sub(r"[,、;。.]", "", s)
    return s.rstrip("。.")


def _compare_answers(reference, generated):
    if not reference or not generated:
        return {"status": "unverified", "detail": "缺少原答案或 AI 答案，需要人工核对。"}
    a, b = _answer_normal(reference), _answer_normal(generated)
    if a and a == b:
        return {"status": "match", "detail": "原答案与 AI 答案文本一致。"}
    if re.fullmatch(r"[A-H]+", a) and re.fullmatch(r"[A-H]+", b):
        same = set(a) == set(b)
        return {"status": "match" if same else "conflict", "detail": "选项一致。" if same else "原答案与 AI 答案选项不同。"}
    # Numeric comparisons are conservative; algebraic/proof equivalence is manual.
    def number(value):
        value = re.sub(r"\\(?:d?frac)\{(-?\d+)\}\{(\d+)\}", r"\1/\2", str(value).replace("$", "").strip())
        return Fraction(value) if re.fullmatch(r"-?\d+(?:/\d+|\.\d+)?", value) else None
    try:
        na, nb = number(reference), number(generated)
        if na is not None and nb is not None:
            same = na == nb
            return {"status": "match" if same else "conflict", "detail": "数值一致。" if same else "原答案与 AI 答案数值不同。"}
    except (ValueError, ZeroDivisionError):
        pass
    return {"status": "unverified", "detail": "表达方式不同，未自动判断数学等价性；请对照原解析核对。"}


def _store_prepared(item_id, version, result):
    _require_owner()
    if not isinstance(result, dict) or not result.get("chunk_results") or result.get("error"):
        raise ValueError("AI 未返回可用的步骤解析。")
    chunks = result.get("chunk_results")
    if not isinstance(chunks, list) or not any(c.get("steps") for c in chunks if isinstance(c, dict)):
        raise ValueError("AI 解析缺少步骤。")
    with _LOCK, closing(_connection()) as conn, conn:
        row = conn.execute("SELECT * FROM pool_items WHERE id=?", (item_id,)).fetchone()
        if not row or row["version"] != version or row["status"] == "imported":
            raise HTTPException(409, "题目在解析期间已修改，本次结果未覆盖原题，请重新生成。")
        answer = result.get("final_answer") or next((c.get("final_answer") for c in chunks if c.get("final_answer")), "")
        check = _compare_answers(row["answer"], answer)
        conn.execute("UPDATE pool_items SET prepared_json=?,prepared_version=?,answer_check_json=?,status='ready',preparing_job_id=NULL,prepare_error='',updated_at=CURRENT_TIMESTAMP WHERE id=?", (_dump(result), version, _dump(check), item_id))
    return get_item(item_id)


def validate_prepare_args(args):
    _require_owner()
    args["item_ids"] = _ids(args.get("item_ids"))
    if args.get("teacher") is not None and not isinstance(args["teacher"], str):
        raise ValueError("老师选项无效")
    for item_id in args["item_ids"]:
        item = get_item(item_id)
        if is_old(item):
            raise ValueError(f"原题 #{item_id} 已确认早于 {MIN_YEAR} 年，不能准备入库。")
        if item["completeness"] != "complete" or not item["question"]:
            raise ValueError(f"原题 #{item_id} 请先核对题干并标记完整，图形题暂缓。")
        if item["status"] == "imported":
            raise ValueError(f"原题 #{item_id} 已入库。")
    return args


def prepare_items(args, ctx):
    from backend.jobs import _solve
    _require_owner()
    results = []
    for index, item_id in enumerate(_ids(args.get("item_ids"))):
        item = get_item(item_id)
        if is_old(item) or item["status"] == "imported" or item["completeness"] != "complete":
            results.append({"item_id": item_id, "status": "error", "error": "原题状态已改变，请重新选择。"})
            continue
        with _LOCK, closing(_connection()) as conn, conn:
            if conn.execute("SELECT status FROM pool_items WHERE id=?", (item_id,)).fetchone()[0] == "preparing":
                results.append({"item_id": item_id, "status": "error", "error": "此题已有解析任务。"})
                continue
            conn.execute("UPDATE pool_items SET status='preparing',preparing_job_id=?,prepare_error='' WHERE id=?", (getattr(ctx, "job_id", None), item_id))
        ctx.progress("pool_prepare", int(index * 100 / len(args["item_ids"])), f"正在准备第 {index + 1}/{len(args['item_ids'])} 道题")
        try:
            from backend.question_assets import pool_asset_refs
            outcome = _solve({"question": item["question"], "question_type": item["question_type"] if item["question_type"] != "未知" else None,
                              "teacher": args.get("teacher"), "save": False, "asset_refs": pool_asset_refs(item)}, ctx)
            result = outcome.value if hasattr(outcome, "value") else outcome
            _store_prepared(item_id, item["version"], result)
            results.append({"item_id": item_id, "status": "ready"})
        except Exception as exc:
            with _LOCK, closing(_connection()) as conn, conn:
                conn.execute("UPDATE pool_items SET status='needs_review',preparing_job_id=NULL,prepare_error=? WHERE id=? AND version=? AND status='preparing'", (str(exc)[:500], item_id, item["version"]))
            results.append({"item_id": item_id, "status": "error", "error": str(exc)[:500]})
    return {"items": results, "ready": sum(r["status"] == "ready" for r in results), "failed": sum(r["status"] == "error" for r in results)}


def _recover_preparation(item_id):
    item = get_item(item_id)
    if item["status"] == "preparing" and item.get("preparing_job_id"):
        from backend.jobs import get_job
        job = get_job(item["preparing_job_id"])
        if not job or job["status"] in ("done", "error", "interrupted"):
            with closing(_connection()) as conn, conn:
                conn.execute("UPDATE pool_items SET status='needs_review',preparing_job_id=NULL,prepare_error='解析任务已中断，可重新生成' WHERE id=? AND status='preparing'", (item_id,))


def _formal_id(question):
    from backend.database import get_connection, _normalize_choice_question_text, _ensure_multi_choice_marker
    variants = {question.strip(), _normalize_choice_question_text(question), _ensure_multi_choice_marker(_normalize_choice_question_text(question))}
    with closing(get_connection()) as conn:
        marks = ",".join("?" for _ in variants)
        row = conn.execute(f"SELECT id FROM questions WHERE content IN ({marks}) ORDER BY id LIMIT 1", list(variants)).fetchone()
        return row[0] if row else None


def _preview_one(item, pattern_conn):
    assignment = item["assignment"]
    role = assignment.get("role", "question")
    errors = []
    if is_old(item):
        errors.append(f"已确认早于 {MIN_YEAR} 年，禁止入库。")
    qid = item.get("formal_question_id") or _formal_id(item["question"])
    existing_answer, existing_check = "", None
    if qid:
        from backend.database import get_question_by_id
        formal = get_question_by_id(qid)
        if formal:
            saved = formal.get("answer_json") or {}
            existing_answer = saved.get("final_answer") or next((c.get("final_answer") for c in saved.get("chunk_results", []) if isinstance(c, dict) and c.get("final_answer")), "")
            existing_check = _compare_answers(item["answer"], existing_answer)
    pid = assignment.get("pattern_id")
    new = assignment.get("new_pattern")
    pattern = None
    if role != "question":
        if not any(o["publication_allowed"] for o in item["occurrences"]):
            errors.append("此题来源尚未确认允许公开；可先作为普通题保存，或在来源设置中确认选中题的发布范围。")
        if pid:
            pattern = pattern_conn.execute("SELECT * FROM patterns WHERE id=?", (pid,)).fetchone()
        elif new:
            pattern = pattern_conn.execute("SELECT * FROM patterns WHERE category=? AND name=?", (new["category"], new["name"])).fetchone()
            if pattern:
                pid = pattern["id"]
        else:
            errors.append("尚未指定套路。")
        if pid and not pattern:
            errors.append("指定套路不存在。")
        if pattern:
            slot = pattern_conn.execute("SELECT question_id FROM pattern_questions WHERE pattern_id=? AND role=?", (pid, role)).fetchone()
            if slot and slot[0] != qid:
                errors.append("该套路角色已占用，请选择其他角色或新套路；不会自动替换。")
        if qid:
            other = pattern_conn.execute("SELECT pattern_id FROM pattern_questions WHERE question_id=? AND role=?", (qid, role)).fetchone()
            if other and other[0] != pid:
                errors.append("这道题已在另一个套路占用相同角色。")
    imported = item["status"] == "imported"
    if not imported:
        if item["completeness"] != "complete":
            errors.append("请先修正并确认题干完整；依赖图形的题本阶段暂缓。")
        if not item["categories"]:
            errors.append("请确认至少一个大板块。")
        if not item["prepared"] or item.get("prepared_version") != item["version"]:
            errors.append("请先生成当前题干的 AI 步骤解析。")
    check = item["answer_check"]
    return {"item_id": item["id"], "question": item["question"], "role": role, "pattern_id": pid,
            "pattern_name": pattern["name"] if pattern else (new or {}).get("name", ""), "question_id": qid,
            "action": "already_imported" if imported else ("reuse" if qid else "create"), "version": item["version"],
            "can_commit": not errors, "blocking_errors": errors, "errors": errors,
            "needs_confirmation": not imported and (check.get("status") in ("conflict", "unverified") or bool(existing_check and existing_check.get("status") in ("conflict", "unverified"))),
            "answer_check": check, "existing_answer": existing_answer, "existing_answer_check": existing_check}


def preview_items(item_ids, confirmed_conflicts=None):
    from backend.patterns import _get_conn
    _require_owner()
    ids = _ids(item_ids)
    with closing(_get_conn()) as conn:
        rows = [_preview_one(get_item(item_id), conn) for item_id in ids]
    slots = {}
    for row in rows:
        if row["role"] == "question" or row["action"] == "already_imported":
            continue
        item = get_item(row["item_id"])
        new = item["assignment"].get("new_pattern") or {}
        slot = (row["pattern_id"] or (new.get("category"), new.get("name")), row["role"])
        if slot in slots:
            for conflicting in (row, slots[slot]):
                conflicting["blocking_errors"].append("本批多道题指定了同一套路角色，请调整后再入库。")
                conflicting["can_commit"] = False
        else:
            slots[slot] = row
    return {"items": rows, "can_commit": all(r["can_commit"] for r in rows)}


def _provenance(item):
    return [{**{k: occurrence.get(k) for k in ("source_name", "source_key", "kind", "url", "revision", "license", "publication_allowed", "question_no", "page_start", "page_end", "original_answer", "original_solution", "year", "year_evidence")},
             "paper": (occurrence.get("raw") or {}).get("paper", ""), "file": (occurrence.get("raw") or {}).get("file", "")}
            for occurrence in item["occurrences"]]


def _merge_provenance(question_id, item):
    from backend.database import get_connection
    with closing(get_connection()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT answer_json FROM questions WHERE id=?", (question_id,)).fetchone()
        if not row:
            raise ValueError("正式题目不存在")
        data = _load(row[0], {})
        provenance = data.get("provenance") if isinstance(data.get("provenance"), list) else []
        for origin in _provenance(item):
            if origin not in provenance:
                provenance.append(origin)
        data["provenance"] = provenance
        if "source_publication_pending" in data:
            data["source_publication_pending"] = not any(origin.get("publication_allowed") for origin in provenance)
        conn.execute("UPDATE questions SET answer_json=? WHERE id=?", (_dump(data), question_id))


def _resolve_pattern(assignment):
    from backend.patterns import _get_conn, _ensure_pattern_mastery, _recalc_category_mastery
    if assignment.get("pattern_id"):
        return assignment["pattern_id"]
    new = assignment["new_pattern"]
    # Only create; never edit an existing pattern's name, difficulty or description.
    with closing(_get_conn()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT OR IGNORE INTO patterns (yaml_key,category,name,description,difficulty) VALUES (?,?,?,?,?)", ("pat-" + uuid.uuid4().hex[:10], new["category"], new["name"], new.get("description", ""), new.get("difficulty", 1)))
        pid = conn.execute("SELECT id FROM patterns WHERE category=? AND name=?", (new["category"], new["name"])).fetchone()[0]
        _ensure_pattern_mastery(conn, pid)
        _recalc_category_mastery(conn, new["category"])
        return pid


def commit_items(item_ids, request_id, confirmed_conflicts=None):
    from backend.database import save_question
    from backend.patterns import link_question_to_pattern
    _require_owner()
    ids = _ids(item_ids)
    # Guard even a replay of a commit recorded before the year policy existed.
    if any(is_old(get_item(item_id)) for item_id in ids):
        raise HTTPException(400, f"已确认早于 {MIN_YEAR} 年的题目禁止入库。")
    if not isinstance(request_id, str) or not 8 <= len(request_id) <= 128:
        raise HTTPException(400, "入库请求编号无效。")
    confirmed = set(confirmed_conflicts or [])
    fingerprint = sha256(_dump({"ids": ids, "confirmed": sorted(confirmed)}).encode()).hexdigest()
    with _LOCK:
        with closing(_connection()) as conn:
            previous = conn.execute("SELECT * FROM pool_commits WHERE request_id=?", (request_id,)).fetchone()
            if previous:
                if previous["fingerprint"] != fingerprint:
                    raise HTTPException(409, "同一请求编号不能提交不同内容。")
                return _load(previous["result_json"])
        preview = preview_items(ids)
        results = []
        for row in preview["items"]:
            item_id = row["item_id"]
            if not row["can_commit"] or (row["needs_confirmation"] and item_id not in confirmed):
                results.append({"item_id": item_id, "status": "error", "error": "；".join(row["blocking_errors"]) or "请对照原答案和 AI 解析，并明确确认答案。"})
                continue
            if row["action"] == "already_imported":
                results.append({"item_id": item_id, "status": "imported", "question_id": row["question_id"], "reused": True})
                continue
            item = get_item(item_id)
            try:
                result = deepcopy(item["prepared"])
                primary = item["categories"][0]
                result["category"] = {"level1": primary, "level2": ""}
                for chunk in result.get("chunk_results", []):
                    chunk["category"] = {"level1": primary, "level2": ""}
                result["provenance"] = _provenance(item)
                result["source_solution"] = item["solution"]
                result["source_answer"] = item["answer"]
                result["source_publication_pending"] = not any(o["publication_allowed"] for o in item["occurrences"])
                result["pool_item_id"] = item_id
                origin = item["occurrences"][0] if item["occurrences"] else {}
                result["source_type"] = "高考题" if origin.get("kind") in ("compilation", "gaokao") else "模拟题"
                result["source_meta"] = {"paper": (origin.get("raw") or {}).get("paper") or origin.get("source_name", ""),
                                         "question_no": origin.get("question_no", ""), "year": item.get("year") or None,
                                         "region": item.get("region", ""), "year_status": item.get("year_status", "unknown")}
                qid = row["question_id"] or save_question(item["question"], result, overwrite_existing=False, match_existing=False)
                if not qid:
                    raise ValueError("题目保存失败")
                if row["role"] != "question":
                    pid = _resolve_pattern(item["assignment"])
                    link_question_to_pattern(pid, qid, row["role"], replace_existing=False)
                _merge_provenance(qid, item)
                with closing(_connection()) as conn, conn:
                    conn.execute("UPDATE pool_items SET status='imported',formal_question_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (qid, item_id))
                results.append({"item_id": item_id, "status": "imported", "question_id": qid, "reused": row["action"] == "reuse"})
            except Exception as exc:
                results.append({"item_id": item_id, "status": "error", "error": str(exc)[:500]})
        response = {"items": results, "imported": sum(r["status"] == "imported" for r in results), "failed": sum(r["status"] == "error" for r in results)}
        with closing(_connection()) as conn, conn:
            conn.execute("INSERT INTO pool_commits VALUES (?,?,?,CURRENT_TIMESTAMP)", (request_id, fingerprint, _dump(response)))
        return response


def update_source(source_id, changes):
    _require_owner()
    if set(changes) - {"name", "license", "publication_allowed"}:
        raise HTTPException(400, "来源字段不可修改。")
    values = {}
    for key in ("name", "license"):
        if key in changes:
            if not isinstance(changes[key], str) or not changes[key].strip():
                raise HTTPException(400, "来源名称或许可说明不能为空。")
            values[key] = changes[key].strip()
    if "publication_allowed" in changes:
        if type(changes["publication_allowed"]) is not bool:
            raise HTTPException(400, "发布选项无效。")
        values["publication_allowed"] = int(changes["publication_allowed"])
    with _LOCK, closing(_connection()) as conn, conn:
        row = conn.execute("SELECT * FROM pool_sources WHERE id=?", (source_id,)).fetchone()
        if not row:
            raise HTTPException(404, "来源不存在。")
        if values:
            conn.execute("UPDATE pool_sources SET " + ",".join(f"{key}=?" for key in values) + " WHERE id=?", [*values.values(), source_id])
        return _source_public(conn, conn.execute("SELECT * FROM pool_sources WHERE id=?", (source_id,)).fetchone())


def _source_file(source_id):
    _require_owner()
    with closing(_connection()) as conn:
        row = conn.execute("SELECT * FROM pool_sources WHERE id=?", (source_id,)).fetchone()
    if not row or not row["file_token"]:
        raise HTTPException(404, "该来源没有保留的上传文件。")
    token = row["file_token"]
    if not re.fullmatch(r"[a-f0-9]{64}\.[a-z0-9]+", token):
        raise HTTPException(404, "原文件不可用。")
    base = files_directory().resolve()
    target = (base / token).resolve()
    if target.parent != base or not target.is_file():
        raise HTTPException(404, "原文件不存在。")
    return target, dict(row)


def validate_import_args(args):
    _require_owner()
    if type(args.get("source_id")) is not int or args["source_id"] < 1:
        raise ValueError("来源编号无效")
    _source_file(args["source_id"])
    validated = {"source_id": args["source_id"]}
    if args.get("item_ids"):
        validated["item_ids"] = _ids(args["item_ids"])
        for item_id in validated["item_ids"]:
            item = get_item(item_id)
            if not any(o["source_id"] == args["source_id"] for o in item["occurrences"]):
                raise ValueError("重试的题目不属于此来源")
    return validated


def import_source_job(args, ctx):
    from backend.pool_sources import iter_source_records
    _require_owner()
    path, source = _source_file(args["source_id"])
    options = _load(source.get("options_json"), {})
    options.update(filename=source.get("filename") or path.name, resume=True, retry_failed=True,
                   cache_dir=files_directory().parent / "conversion-cache")
    conversion_stats = {}
    options["stats"] = conversion_stats
    def page_progress(stats):
        done, total = stats.get("completed_pages", 0), stats.get("total_pages", 1)
        ctx.progress("pool_import", min(95, round(5 + 85 * done / max(1, total))),
                     f"完成页 {done}/{total} · 缓存命中 {stats.get('cache_hits', 0)} · 失败页 {stats.get('failed_pages', 0)}")
    options["progress"] = page_progress
    if source["kind"] == "pdf":
        with closing(_connection()) as conn:
            failures = conn.execute("SELECT item_id,page_start,page_end FROM pool_occurrences WHERE source_id=? AND completeness='failed'", (source["id"],)).fetchall()
        selected = set(args.get("item_ids") or [])
        pages = set()
        for failure in failures:
            if selected and failure["item_id"] not in selected:
                continue
            start, end = failure["page_start"], failure["page_end"]
            if isinstance(start, int) and start > 0:
                pages.update(range(start, max(start, end or start) + 1))
        # A whole-source retry also visits any unprocessed tail. Successful
        # pages are free cache hits; only an explicit selection restricts pages.
        if pages and selected:
            options["page_numbers"] = sorted(pages)
    ctx.progress("pool_import", 5, "正在读取原题与出处")
    def records():
        nonlocal seen_keys
        for index, record in enumerate(iter_source_records(path, source["kind"], options)):
            if source["kind"] != "pdf" and index % 20 == 0:
                ctx.progress("pool_import", min(95, 10 + index // 10), f"已读取 {index} 个来源条目")
            seen_keys.add(record["source_key"])
            yield record
    seen_keys = set()
    result = import_records(source["id"], records(), retry_failed=True)
    # A scan/failed-page placeholder may become an answer page or continuation,
    # producing no standalone OCR question. Remove only untouched empty items.
    if source["kind"] == "pdf":
        success_pages = set(conversion_stats.get("processed_page_numbers", [])) - set(conversion_stats.get("failed_page_numbers", []))
        with _LOCK, closing(_connection()) as conn, conn:
            placeholders = conn.execute("SELECT o.*,i.version,i.status FROM pool_occurrences o JOIN pool_items i ON i.id=o.item_id WHERE o.source_id=? AND o.original_question=''", (source["id"],)).fetchall()
            for placeholder in placeholders:
                if (placeholder["source_key"] not in seen_keys and placeholder["page_start"] in success_pages
                        and placeholder["version"] == 1 and placeholder["status"] == "unreviewed"):
                    iid = placeholder["item_id"]
                    conn.execute("DELETE FROM pool_occurrences WHERE id=?", (placeholder["id"],))
                    if not conn.execute("SELECT 1 FROM pool_occurrences WHERE item_id=?", (iid,)).fetchone():
                        conn.execute("DELETE FROM pool_categories WHERE item_id=?", (iid,))
                        conn.execute("DELETE FROM pool_items WHERE id=?", (iid,))
            result["stats"] = _source_stats(conn, source["id"])
    result["conversion"] = conversion_stats
    with closing(_connection()) as conn, conn:
        conn.execute("UPDATE pool_sources SET import_report_json=? WHERE id=?", (_dump({**result["report"], "conversion": conversion_stats}), source["id"]))
    ctx.progress("pool_import", 100, "来源采集完成，候选题尚未进入正式题库")
    return result


def validate_collect_args(args):
    _require_owner()
    years = args.get("years", default_mock_years())
    if not isinstance(years, list) or not 1 <= len(years) <= 10 or any(type(y) is not int or not 2016 <= y <= 2100 for y in years):
        raise ValueError("请选择 2016 年及以后的题源年份")
    concurrency = args.get("concurrency", 20)
    if type(concurrency) is not int or not 1 <= concurrency <= 20:
        raise ValueError("OCR 并发应为 1 至 20")
    return {"years": sorted(set(years)), "concurrency": concurrency, "max_pages": 32,
            "topics": args.get("topics", True) is True, "ocr": args.get("ocr", True) is True,
            "structured": True, "convert": True, "import_pool": True}


def collect_sources_job(args, ctx):
    from backend.question_source_collector import collect
    _require_owner()
    root = files_directory().parent / "collections"
    def progress(report):
        percentages = {"starting": 0, "structured": 5, "discover": 15, "download": 35, "ocr": 65, "convert": 85, "done": 100}
        value = percentages.get(report["stage"], 0)
        if report["stage"] in ("ocr", "convert"):
            value = 35 + int(60 * report["converted"] / max(report["downloaded"], 1))
        ctx.progress("pool_collect", value, report["message"])
    return collect(args, root, progress)


router = APIRouter(prefix="/question-pool", tags=["原题池"])


@router.get("/meta")
def api_meta():
    return meta()


@router.get("/items")
def api_items(category: str = "", source_id: Optional[int] = None, year: str = "", region: str = "", question_type: str = "", keyword: str = "",
              completeness: str = "text_only", status: str = "", has_answer: Optional[bool] = None, page: int = Query(1, ge=1), page_size: int = Query(40, ge=1, le=100)):
    return list_items(category=category, source_id=source_id, year=year, region=region, question_type=question_type, keyword=keyword,
                      completeness=completeness, status=status, has_answer=has_answer, page=page, page_size=page_size)


@router.get("/items/{item_id}")
def api_item(item_id: int):
    _recover_preparation(item_id)
    return get_item(item_id)


@router.patch("/items/{item_id}")
def api_update_item(item_id: int, changes: dict):
    return update_item(item_id, changes)


class SelectionRequest(BaseModel):
    item_ids: list[int] = Field(..., min_items=1, max_items=200)
    teacher: Optional[str] = None
    request_id: Optional[str] = None
    confirmed_conflicts: list[int] = Field(default_factory=list)


class CollectRequest(BaseModel):
    years: list[int] = Field(default_factory=default_mock_years)
    topics: bool = True
    ocr: bool = True
    concurrency: int = 20
    request_id: Optional[str] = None


@router.post("/collect", status_code=202)
def api_collect(req: CollectRequest):
    from backend.jobs import submit_job, _submission_error
    _require_owner()
    try:
        return submit_job("pool_collect", {"years": req.years, "topics": req.topics, "ocr": req.ocr, "concurrency": req.concurrency}, req.request_id or uuid.uuid4().hex)
    except (ValueError, RuntimeError) as exc:
        raise _submission_error(exc)


@router.get("/collection")
def api_collection():
    _require_owner()
    path = files_directory().parent / "collections/progress.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"stage": "idle", "message": "尚未运行在线找题"}


@router.post("/prepare", status_code=202)
def api_prepare(req: SelectionRequest):
    from backend.jobs import submit_job, _submission_error
    _require_owner()
    try:
        return submit_job("pool_prepare", {"item_ids": req.item_ids, "teacher": req.teacher}, req.request_id or uuid.uuid4().hex)
    except (ValueError, RuntimeError) as exc:
        raise _submission_error(exc)


@router.post("/preview")
def api_preview(req: SelectionRequest):
    return preview_items(req.item_ids, req.confirmed_conflicts)


@router.post("/commit")
def api_commit(req: SelectionRequest):
    return commit_items(req.item_ids, req.request_id or "", req.confirmed_conflicts)


@router.patch("/sources/{source_id}")
def api_source_update(source_id: int, changes: dict):
    return update_source(source_id, changes)


@router.get("/sources/{source_id}/file")
def api_source_file(source_id: int):
    path, source = _source_file(source_id)
    return FileResponse(str(path), filename=source["filename"] or path.name,
                        content_disposition_type="inline" if source["kind"] == "pdf" else "attachment",
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


class SourceRetryRequest(BaseModel):
    item_ids: list[int] = Field(default_factory=list, max_items=200)


@router.post("/sources/{source_id}/retry", status_code=202)
def api_source_retry(source_id: int, req: Optional[SourceRetryRequest] = None):
    from backend.jobs import submit_job, _submission_error
    _require_owner()
    try:
        args = {"source_id": source_id}
        if req and req.item_ids:
            args["item_ids"] = req.item_ids
        return submit_job("pool_import", args, uuid.uuid4().hex)
    except (ValueError, RuntimeError) as exc:
        raise _submission_error(exc)


@router.post("/uploads", status_code=202)
async def api_upload(file: UploadFile = File(...), source_name: str = Form(""), ocr: bool = Form(True)):
    from backend.jobs import submit_job, _submission_error
    _require_owner()
    name = Path(file.filename or "upload").name
    ext = Path(name).suffix.lower()
    kinds = {".pdf": "pdf", ".docx": "docx", ".jpg": "image", ".jpeg": "image", ".png": "image", ".txt": "txt", ".json": "jsonl", ".jsonl": "jsonl", ".tex": "compilation"}
    if ext not in kinds:
        await file.close()
        raise HTTPException(400, "支持 PDF、DOCX、图片、TXT、JSON/JSONL 和 TeX。")
    base = files_directory()
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = base / ("upload-" + uuid.uuid4().hex)
    digest = sha256()
    size = 0
    try:
        with temporary.open("xb") as stream:
            temporary.chmod(0o600)
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > 100 * 1024 * 1024:
                    raise HTTPException(413, "单个文件请控制在 100 MiB 以内。")
                digest.update(chunk)
                stream.write(chunk)
        if not size:
            raise HTTPException(400, "上传文件为空。")
        token = digest.hexdigest() + ext
        target = base / token
        if target.exists():
            temporary.unlink()
        else:
            temporary.replace(target)
        source_id = create_source({"name": source_name.strip() or name, "kind": kinds[ext], "revision": digest.hexdigest(), "filename": name,
                                   "file_token": token, "license": "私人教辅文件；选中题发布范围待确认", "publication_allowed": False, "options": {"ocr": ocr}})
        # Re-uploading the same immutable file with OCR enabled is an explicit
        # owner choice; it must not retain the earlier upload's disabled option.
        with closing(_connection()) as conn, conn:
            conn.execute("UPDATE pool_sources SET options_json=? WHERE id=?", (_dump({"ocr": ocr}), source_id))
        try:
            job = await run_in_threadpool(submit_job, "pool_import", {"source_id": source_id}, uuid.uuid4().hex)
        except (ValueError, RuntimeError) as exc:
            raise _submission_error(exc)
        return {**job, "source_id": source_id}
    finally:
        await file.close()
        if temporary.exists():
            temporary.unlink()
