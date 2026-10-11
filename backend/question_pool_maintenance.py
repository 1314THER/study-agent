"""Offline, backed-up pruning of provably old questions and their references.

Uses stdlib SQLite only: inspecting this module never initializes live databases.
Run against the active owner workspace while no imports/commits are in progress.
"""
from contextlib import closing
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from backend.source_policy import MIN_YEAR, is_old, year_evidence


def _json(text, default=None):
    try:
        return json.loads(text) if text else default
    except (TypeError, ValueError):
        return default


def _exists(conn, schema, table):
    return conn.execute(f"SELECT 1 FROM {schema}.sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def _rows(conn, schema, table):
    return [dict(r) for r in conn.execute(f'SELECT * FROM {schema}."{table}"')] if _exists(conn, schema, table) else []


def _formal_evidence(row):
    answer = _json(row.get("answer_json"), {}) or {}
    meta = _json(row.get("source_meta"), {}) or answer.get("source_meta") or {}
    origins = answer.get("provenance") or []
    if origins:
        evidence = [year_evidence({"year": o.get("year"), "raw": o}) for o in origins if isinstance(o, dict)]
    else:
        evidence = [year_evidence({"source_meta": meta})]
    return evidence


def _orphan_rows(conn):
    """Archive existing invalid references separately from year-based deletion."""
    result = {}
    for schema, tables in (("formal", ("mistakes", "practice_records", "step_errors", "question_steps", "question_list_members")),
                           ("mastery", ("pattern_questions", "attempts", "board_nodes"))):
        for table in tables:
            if _exists(conn, schema, table):
                rows = conn.execute(f"SELECT r.rowid AS _rowid,r.* FROM {schema}.{table} r LEFT JOIN formal.questions q ON r.question_id=q.id WHERE r.question_id IS NOT NULL AND q.id IS NULL ORDER BY r.rowid").fetchall()
                if rows:
                    result[schema + "." + table] = [dict(r) for r in rows]
    if _exists(conn, "mastery", "board_edges"):
        rows = conn.execute("SELECT r.rowid AS _rowid,r.* FROM mastery.board_edges r LEFT JOIN formal.questions a ON r.from_question_id=a.id LEFT JOIN formal.questions b ON r.to_question_id=b.id WHERE a.id IS NULL OR b.id IS NULL ORDER BY r.rowid").fetchall()
        if rows:
            result["mastery.board_edges"] = [dict(r) for r in rows]
    return result


def _plan(conn):
    sources = {r["id"]: r for r in _rows(conn, "main", "pool_sources")}
    items = _rows(conn, "main", "pool_items")
    all_occurrences = _rows(conn, "main", "pool_occurrences")
    by_item, old_occurrences = {}, []
    for row in all_occurrences:
        raw = _json(row.get("raw_json"), {}) or {}
        # Legacy occurrences did not carry a year column. Locate the original
        # paper/file first; don't transfer one duplicate's year to another.
        record = {"year": row.get("year"), "raw": raw}
        proof = year_evidence(record, sources.get(row["source_id"]))
        by_item.setdefault(row["item_id"], []).append((row, proof))
        if proof["year"] is not None and proof["year"] < MIN_YEAR:
            old_occurrences.append({"id": row["id"], "item_id": row["item_id"],
                                    "source_id": row["source_id"], "source_key": row["source_key"], "proof": proof})
    delete_items = []
    normalize_items = []
    for row in items:
        origins = by_item.get(row["id"], [])
        remaining = [(o, e) for o, e in origins if e["year"] is None or e["year"] >= MIN_YEAR]
        if (origins and not remaining) or (not origins and is_old(row)):
            delete_items.append({"id": row["id"], "fingerprint": row["fingerprint"],
                                 "year": row.get("year"), "formal_question_id": row.get("formal_question_id"),
                                 "proofs": [e for _, e in origins] or [year_evidence(row)]})
        elif is_old(row):
            years = {e["year"] for _, e in remaining}
            year = next(iter(years)) if len(years) == 1 and None not in years else None
            normalize_items.append({"id": row["id"], "year": str(year) if year else ""})
    formal = _rows(conn, "formal", "questions")
    delete_formal = []
    for row in formal:
        proofs = _formal_evidence(row)
        if proofs and all(p["year"] is not None and p["year"] < MIN_YEAR for p in proofs):
            delete_formal.append({"id": row["id"], "proofs": proofs})
    return {"minimum_year": MIN_YEAR, "before": {"pool_items": len(items), "pool_occurrences": len(all_occurrences), "formal_questions": len(formal)},
            "delete_items": delete_items, "delete_occurrences": old_occurrences,
            "delete_formal_questions": delete_formal, "normalize_items": normalize_items,
            "existing_orphan_references": _orphan_rows(conn)}


def _connect(pool, formal, mastery, *, readonly=False):
    pool = Path(pool).resolve()
    conn = sqlite3.connect(pool.as_uri() + ("?mode=ro" if readonly else "?mode=rw"), uri=True, timeout=60)
    conn.row_factory = sqlite3.Row
    for name, path in (("formal", formal), ("mastery", mastery)):
        if not Path(path).is_file():
            conn.close()
            raise FileNotFoundError(path)
        uri = Path(path).resolve().as_uri() + ("?mode=ro" if readonly else "?mode=rw")
        conn.execute(f"ATTACH DATABASE ? AS {name}", (uri,))
    return conn


def build_plan(pool, formal, mastery):
    with closing(_connect(pool, formal, mastery, readonly=True)) as conn:
        return _plan(conn)


def backup_databases(paths, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    entries = []
    for path in map(Path, paths):
        target = directory / path.name
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as source, closing(sqlite3.connect(target)) as dest:
            source.backup(dest)
            integrity = dest.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise ValueError(f"备份完整性检查失败：{path}")
        target.chmod(0o600)
        entries.append({"source": str(path.resolve()), "backup": str(target.resolve()), "sha256": sha256(target.read_bytes()).hexdigest(), "integrity": integrity})
    write_report(directory / "backup-manifest.json", {"databases": entries})
    return entries


def write_report(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def _delete_ids(conn, schema, table, column, ids):
    if not ids or not _exists(conn, schema, table):
        return 0
    total = 0
    for offset in range(0, len(ids), 500):
        batch = ids[offset:offset + 500]
        marks = ",".join("?" for _ in batch)
        total += conn.execute(f'DELETE FROM {schema}."{table}" WHERE "{column}" IN ({marks})', batch).rowcount
    return total


def audit_references(conn):
    queries = {
        "pool_categories": "SELECT count(*) FROM pool_categories c LEFT JOIN pool_items i ON c.item_id=i.id WHERE i.id IS NULL",
        "pool_occurrences": "SELECT count(*) FROM pool_occurrences o LEFT JOIN pool_items i ON o.item_id=i.id LEFT JOIN pool_sources s ON s.id=o.source_id WHERE i.id IS NULL OR s.id IS NULL",
        "pool_formal": "SELECT count(*) FROM pool_items i LEFT JOIN formal.questions q ON i.formal_question_id=q.id WHERE i.formal_question_id IS NOT NULL AND q.id IS NULL",
    }
    for table in ("mistakes", "practice_records", "step_errors", "question_steps", "question_list_members"):
        if _exists(conn, "formal", table):
            queries[table] = f"SELECT count(*) FROM formal.{table} r LEFT JOIN formal.questions q ON r.question_id=q.id WHERE q.id IS NULL"
    for table in ("pattern_questions", "attempts", "board_nodes"):
        if _exists(conn, "mastery", table):
            queries[table] = f"SELECT count(*) FROM mastery.{table} r LEFT JOIN formal.questions q ON r.question_id=q.id WHERE r.question_id IS NOT NULL AND q.id IS NULL"
    if _exists(conn, "mastery", "board_edges"):
        queries["board_edges"] = "SELECT count(*) FROM mastery.board_edges r LEFT JOIN formal.questions a ON r.from_question_id=a.id LEFT JOIN formal.questions b ON r.to_question_id=b.id WHERE a.id IS NULL OR b.id IS NULL"
    return {name: conn.execute(sql).fetchone()[0] for name, sql in queries.items()}


def apply_plan(pool, formal, mastery, plan):
    """Lock all three databases, reject stale manifests, then prune together."""
    with closing(_connect(pool, formal, mastery)) as conn:
        # SQLite's multi-database atomic commit requires rollback journals.
        modes = {name: conn.execute(f"PRAGMA {name}.journal_mode").fetchone()[0] for name in ("main", "formal", "mastery")}
        if any(mode.lower() != "delete" for mode in modes.values()):
            raise ValueError("清理需要三个数据库采用 DELETE 日志；请先停止写入并切换日志模式。")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("BEGIN IMMEDIATE")
        try:
            if _plan(conn) != plan:
                raise ValueError("数据在生成清单后已变化，请重新备份并生成清单。")
            before_audit = audit_references(conn)
            oids = [r["id"] for r in plan["delete_occurrences"]]
            ids = [r["id"] for r in plan["delete_items"]]
            qids = [r["id"] for r in plan["delete_formal_questions"]]
            deleted = {}
            orphan_repairs = {}
            for location, rows in plan["existing_orphan_references"].items():
                schema, table = location.split(".")
                orphan_repairs[location] = _delete_ids(conn, schema, table, "rowid", [r["_rowid"] for r in rows])
            for table in ("mistakes", "practice_records", "step_errors", "question_steps", "question_list_members"):
                deleted[table] = _delete_ids(conn, "formal", table, "question_id", qids)
            for table in ("pattern_questions", "attempts", "board_nodes"):
                deleted[table] = _delete_ids(conn, "mastery", table, "question_id", qids)
            deleted["board_edges"] = _delete_ids(conn, "mastery", "board_edges", "from_question_id", qids)
            deleted["board_edges"] += _delete_ids(conn, "mastery", "board_edges", "to_question_id", qids)
            # Invalidate rounds containing a deleted question; no stale queue or
            # replayed grading result may bring that question back.
            for row in _rows(conn, "mastery", "loop_rounds"):
                queue = _json(row["queue_json"], [])
                if any(i.get("question_id") in qids for i in queue if isinstance(i, dict)):
                    conn.execute("DELETE FROM mastery.loop_job_results WHERE round_id=?", (row["round_id"],))
                    conn.execute("DELETE FROM mastery.loop_rounds WHERE round_id=?", (row["round_id"],))
            deleted["formal_questions"] = _delete_ids(conn, "formal", "questions", "id", qids)
            deleted["pool_occurrences"] = _delete_ids(conn, "main", "pool_occurrences", "id", oids)
            deleted["pool_categories"] = _delete_ids(conn, "main", "pool_categories", "item_id", ids)
            deleted["pool_items"] = _delete_ids(conn, "main", "pool_items", "id", ids)
            for row in plan["normalize_items"]:
                conn.execute("UPDATE pool_items SET year=? WHERE id=?", (row["year"], row["id"]))
            for qid in qids:
                conn.execute("UPDATE pool_items SET formal_question_id=NULL,status='unreviewed',prepared_json=NULL,prepared_version=NULL WHERE formal_question_id=?", (qid,))
            for row in _rows(conn, "main", "pool_commits"):
                result = _json(row["result_json"], {})
                if any(i.get("item_id") in ids or i.get("question_id") in qids for i in result.get("items", [])):
                    conn.execute("DELETE FROM pool_commits WHERE request_id=?", (row["request_id"],))
            # Remove old citations from mixed-age formal questions while keeping
            # candidates supported by modern or unknown sources.
            for row in _rows(conn, "formal", "questions"):
                answer = _json(row.get("answer_json"), {}) or {}
                origins = answer.get("provenance")
                if isinstance(origins, list):
                    kept = [o for o in origins if not isinstance(o, dict) or not is_old({"year": o.get("year"), "raw": o})]
                    if kept != origins:
                        answer["provenance"] = kept
                        conn.execute("UPDATE formal.questions SET answer_json=? WHERE id=?", (json.dumps(answer, ensure_ascii=False), row["id"]))
            after_audit = audit_references(conn)
            if any(after_audit[k] > before_audit[k] for k in after_audit):
                raise ValueError("清理会新增悬空关联，已回滚。")
            remaining = _plan(conn)
            if remaining["delete_items"] or remaining["delete_occurrences"] or remaining["delete_formal_questions"]:
                raise ValueError("清理后仍有已确认旧题，已回滚。")
            conn.commit()
            return {"deleted": deleted, "orphan_reference_repairs": orphan_repairs, "before": plan["before"], "after": remaining["before"], "references_before": before_audit,
                    "references_after": after_audit, "second_run_deletions": 0, "finished_at": datetime.now().isoformat()}
        except BaseException:
            conn.rollback()
            raise
