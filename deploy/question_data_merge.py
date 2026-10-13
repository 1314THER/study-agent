"""Prepare an ID-preserving, additive question/review import in a new directory.

This deliberately refuses ID collisions instead of rewriting frozen review
hashes. It never changes either input and never copies accounts or AI settings.
The deployment wrapper must drain/stop writers and rerun preparation before
installing the candidate; preparing against a live site is only a preflight.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, closing
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import stat


PATHS = {"pool": ".runtime/question_pool.db", "review": ".runtime/routine-review.sqlite3"}
KEYS = {
    "pool_sources": ("id",), "pool_items": ("id",),
    "pool_categories": ("item_id", "category"), "pool_occurrences": ("id",),
    "pool_commits": ("request_id",),
    "review_runs": ("run_id",), "review_items": ("run_id", "item_id"),
    "review_cache": ("cache_key",), "review_humans": ("item_id", "content_hash"),
    "review_history": ("id",), "review_usage": ("id",), "review_configs": ("id",),
    "review_batch_responses": ("id",), "review_web_packets": ("packet_id",),
    "review_web_responses": ("packet_id", "response_digest"),
}
POOL_TABLES = tuple(name for name in KEYS if name.startswith("pool_"))
REVIEW_TABLES = tuple(name for name in KEYS if name.startswith("review_"))
OPTIONAL = {"review_web_packets", "review_web_responses"}
HASH = re.compile(r"[0-9a-f]{64}\Z")


class MergeConflict(ValueError):
    """A safe-to-display diagnostic containing identifiers, never row text."""


def _fail(table, key, detail):
    # Keys can include arbitrary source labels. Only integer/opaque identifiers
    # are printable; no question, file path, response, or credential is echoed.
    identifiers = [str(value) for value in key if type(value) is int]
    suffix = " #" + "/".join(identifiers) if identifiers else ""
    raise MergeConflict(f"{table}{suffix}: {detail}")


def _digest(value):
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def _json(value, table, key, column, expected=None):
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError):
        _fail(table, key, column + " 不是有效 JSON")
    if expected is not None and not isinstance(parsed, expected):
        _fail(table, key, column + " 结构无效")
    return parsed


def _equal(left, right, column):
    if column.endswith("_json") and left is not None and right is not None:
        try:
            return json.loads(left) == json.loads(right)
        except (ValueError, TypeError):
            return False
    return left == right


def _path(root, relative):
    path = root
    for part in Path(relative).parts:
        path /= part
        if path.is_symlink():
            raise MergeConflict("数据库路径含符号链接")
    if path.exists() and not stat.S_ISREG(path.stat().st_mode):
        raise MergeConflict("数据库路径不是普通文件")
    return path


def _open_readonly(path):
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _tables(conn):
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def _columns(conn, table):
    return [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]


def _field_definitions(conn, table):
    # ALTER TABLE adds a column at the end; a freshly initialized database can
    # place that same column elsewhere. Inserts and comparisons use names.
    return {row[1]: (row[2].upper(), row[3], row[4], row[5])
            for row in conn.execute(f'PRAGMA table_info("{table}")')}


def _schema(conn, family):
    expected = POOL_TABLES if family == "pool" else REVIEW_TABLES
    tables = _tables(conn)
    if tables - set(expected) or set(expected) - OPTIONAL - tables:
        raise MergeConflict(f"{family}: 数据库表结构不受支持，请先升级后重试")
    for table in tables:
        info = list(conn.execute(f'PRAGMA table_info("{table}")'))
        keys = tuple(row[1] for row in sorted(info, key=lambda row: row[5]) if row[5])
        if keys != KEYS[table]:
            _fail(table, (), "主键结构不受支持")
    if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise MergeConflict(f"{family}: SQLite 完整性校验失败")
    if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise MergeConflict(f"{family}: SQLite 外键校验失败")


def _rows(conn, table):
    return conn.execute(f'SELECT * FROM "{table}"')


def _ensure_schema(source, candidate, family):
    expected = POOL_TABLES if family == "pool" else REVIEW_TABLES
    present = _tables(candidate)
    for table in expected:
        if table not in _tables(source):
            continue
        if table not in present:
            sql = source.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()[0]
            candidate.execute(sql)
            for (index_sql,) in source.execute("SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL", (table,)):
                candidate.execute(index_sql)
        elif _field_definitions(candidate, table) != _field_definitions(source, table):
            _fail(table, (), "字段结构不同，请先在服务器完成数据库升级")


def _row_key(row, table):
    return tuple(row[column] for column in KEYS[table])


def _existing(candidate, table, key):
    condition = " AND ".join(f'"{column}"=?' for column in KEYS[table])
    return candidate.execute(f'SELECT * FROM "{table}" WHERE {condition}', key).fetchone()


def _match_rows(table, incoming, existing):
    key = _row_key(incoming, table)
    if table == "review_runs":
        compare = ("request_id", "catalog_json", "config_json")
    elif table == "review_items":
        compare = ("item_json", "provenance_json", "content_hash")
    elif table == "review_web_packets":
        compare = ("run_id", "snapshot_json", "prompt_text")
    elif table in {"review_cache", "review_humans"}:
        # The same exact cache identity or version-bound human decision already
        # present on the server takes precedence over the imported observation.
        compare = ()
    elif table in {"pool_sources", "pool_items", "pool_commits"}:
        compare = tuple(column for column in incoming.keys() if column not in {"created_at", "updated_at"})
    else:
        compare = tuple(incoming.keys())
    for column in compare:
        if not _equal(incoming[column], existing[column], column):
            _fail(table, key, "已有主键的 " + column + " 不同；为保留服务器数据，已拒绝导入")


def _merge_table(source, candidate, table):
    if table not in _tables(source):
        return 0
    columns = _columns(source, table)
    quoted = ",".join('"' + column + '"' for column in columns)
    insert = f'INSERT INTO "{table}" ({quoted}) VALUES ({",".join("?" for _ in columns)})'
    added = 0
    for row in _rows(source, table):
        key = _row_key(row, table)
        old = _existing(candidate, table, key)
        if old is not None:
            _match_rows(table, row, old)
            continue
        natural = None
        if table in {"pool_sources", "pool_items"}:
            natural = candidate.execute(f'SELECT id FROM "{table}" WHERE fingerprint=?', (row["fingerprint"],)).fetchone()
        elif table == "pool_occurrences":
            natural = candidate.execute("SELECT id FROM pool_occurrences WHERE source_id=? AND source_key=?", (row["source_id"], row["source_key"])).fetchone()
        elif table == "review_runs":
            natural = candidate.execute("SELECT run_id FROM review_runs WHERE request_id=?", (row["request_id"],)).fetchone()
        if natural is not None:
            _fail(table, key, "自然键已使用不同编号；需单独映射，不能直接导入")
        try:
            candidate.execute(insert, tuple(row[column] for column in columns))
        except sqlite3.IntegrityError:
            _fail(table, key, "插入违反唯一约束或外键约束")
        added += 1
    return added


def _validate_pool(conn, source=False):
    sources = {row[0] for row in conn.execute("SELECT id FROM pool_sources")}
    items = {row[0] for row in conn.execute("SELECT id FROM pool_items")}
    categories = {}
    for row in _rows(conn, "pool_categories"):
        if row["item_id"] not in items:
            _fail("pool_categories", (row["item_id"],), "引用不存在的题目")
        categories.setdefault(row["item_id"], set()).add(row["category"])
    for row in _rows(conn, "pool_sources"):
        for column in ("options_json", "import_report_json"):
            if column in row.keys():
                _json(row[column], "pool_sources", (row["id"],), column, dict)
    for row in _rows(conn, "pool_items"):
        key = (row["id"],)
        values = _json(row["categories_json"], "pool_items", key, "categories_json", list)
        if any(not isinstance(value, str) for value in values) or set(values) != categories.get(row["id"], set()):
            _fail("pool_items", key, "categories_json 与分类表不一致")
        assignment = _json(row["assignment_json"], "pool_items", key, "assignment_json", dict)
        for column in ("prepared_json", "answer_check_json"):
            if row[column] is not None:
                _json(row[column], "pool_items", key, column, dict)
        if source and (row["formal_question_id"] is not None or assignment.get("role", "question") != "question" or assignment.get("pattern_id") or assignment.get("new_pattern")):
            _fail("pool_items", key, "包含正式题库或套路学习依赖，当前定向题池包不支持")
        if source and (row["status"] == "preparing" or row["preparing_job_id"]):
            _fail("pool_items", key, "仍引用解析任务，请先完成或中断任务再导出")
    if source and conn.execute("SELECT count(*) FROM pool_commits").fetchone()[0]:
        raise MergeConflict("pool_commits: 包含正式题库提交记录，需另做完整关系迁移")
    for row in _rows(conn, "pool_occurrences"):
        key = (row["id"],)
        if row["item_id"] not in items or row["source_id"] not in sources:
            _fail("pool_occurrences", key, "引用不存在的题目或来源")
        _json(row["raw_json"], "pool_occurrences", key, "raw_json", dict)
        if "year_evidence_json" in row.keys():
            _json(row["year_evidence_json"], "pool_occurrences", key, "year_evidence_json", dict)
    for row in _rows(conn, "pool_commits"):
        _json(row["result_json"], "pool_commits", (), "result_json", dict)


def _validate_review(review, pool):
    pool_ids = {row[0] for row in pool.execute("SELECT id FROM pool_items")}
    occurrences = {(row[0], row[1]): row[2] for row in pool.execute("SELECT source_id,source_key,item_id FROM pool_occurrences")}
    runs = {row[0] for row in review.execute("SELECT run_id FROM review_runs")}
    active = [row[0] for row in review.execute("SELECT run_id FROM review_runs WHERE status!='archived'")]
    if len(active) > 1:
        raise MergeConflict("review_runs: 已有多个非归档批次，需先在网站中处理")
    for row in _rows(review, "review_runs"):
        _json(row["catalog_json"], "review_runs", (), "catalog_json", dict)
        _json(row["config_json"], "review_runs", (), "config_json", dict)
    review_ids = set()
    for row in _rows(review, "review_items"):
        key = (row["item_id"],)
        if row["run_id"] not in runs or row["item_id"] not in pool_ids:
            _fail("review_items", key, "引用不存在的批次或原题")
        item = _json(row["item_json"], "review_items", key, "item_json", dict)
        if type(item.get("id")) is not int or item["id"] != row["item_id"] or _digest(item) != row["content_hash"]:
            _fail("review_items", key, "快照编号或内容哈希无效")
        origins = _json(row["provenance_json"], "review_items", key, "provenance_json", list)
        for origin in origins:
            if not isinstance(origin, dict) or occurrences.get((origin.get("source_id"), origin.get("source_key"))) != row["item_id"]:
                _fail("review_items", key, "出处快照引用不一致")
        for column in ("result_json", "human_json", "catalog_json"):
            if row[column] is not None:
                _json(row[column], "review_items", key, column, dict)
        for column in ("secondary_json", "marks_json"):
            _json(row[column], "review_items", key, column, list)
        review_ids.add((row["run_id"], row["item_id"]))
    for row in _rows(review, "review_cache"):
        _json(row["result_json"], "review_cache", (), "result_json", dict)
    for row in _rows(review, "review_humans"):
        if row["item_id"] not in pool_ids or not HASH.fullmatch(row["content_hash"]):
            _fail("review_humans", (row["item_id"],), "原题引用或内容哈希无效")
        _json(row["decision_json"], "review_humans", (row["item_id"],), "decision_json", dict)
    for table, column in (("review_history", "decision_json"), ("review_usage", "usage_json")):
        for row in _rows(review, table):
            if (row["run_id"], row["item_id"]) not in review_ids:
                _fail(table, (row["id"],), "引用不存在的审核题目")
            _json(row[column], table, (row["id"],), column, dict)
    for row in _rows(review, "review_configs"):
        if row["run_id"] not in runs:
            _fail("review_configs", (row["id"],), "引用不存在的批次")
        _json(row["config_json"], "review_configs", (row["id"],), "config_json", dict)
    for row in _rows(review, "review_batch_responses"):
        ids = _json(row["item_ids_json"], "review_batch_responses", (row["id"],), "item_ids_json", list)
        if row["run_id"] not in runs or any(type(item_id) is not int or (row["run_id"], item_id) not in review_ids for item_id in ids):
            _fail("review_batch_responses", (row["id"],), "引用不存在的审核题目")
        # Batch matching records an object keyed by attempted item IDs. Older
        # diagnostics can contain a list; neither is an authoritative FK.
        _json(row["validation_errors_json"], "review_batch_responses", (row["id"],), "validation_errors_json", (dict, list))
    if "review_web_packets" not in _tables(review):
        return
    packets = set()
    for row in _rows(review, "review_web_packets"):
        snapshot = _json(row["snapshot_json"], "review_web_packets", (), "snapshot_json", dict)
        if row["run_id"] not in runs or snapshot.get("run_id") != row["run_id"] or snapshot.get("packet_id") != row["packet_id"] or not isinstance(snapshot.get("items"), list):
            _fail("review_web_packets", (), "网页审核包批次引用无效")
        for frozen in snapshot["items"]:
            if not isinstance(frozen, dict) or not isinstance(frozen.get("item"), dict):
                _fail("review_web_packets", (), "网页审核包题目结构无效")
            item_id = frozen.get("id")
            if type(item_id) is not int or (row["run_id"], item_id) not in review_ids or frozen["item"].get("id") != item_id or _digest(frozen["item"]) != frozen.get("content_hash"):
                _fail("review_web_packets", (), "网页审核包题目引用或内容哈希无效")
        if "response_json" in row.keys() and row["response_json"] is not None:
            response = _json(row["response_json"], "review_web_packets", (), "response_json", dict)
            if response.get("packet_id") != row["packet_id"]:
                _fail("review_web_packets", (), "网页回复包编号不一致")
        packets.add(row["packet_id"])
    if "review_web_responses" in _tables(review):
        for row in _rows(review, "review_web_responses"):
            if row["packet_id"] not in packets:
                _fail("review_web_responses", (), "引用不存在的网页审核包")


def merge(source_root, target_root, candidate_root):
    """Return added/total table counts; raise MergeConflict without live writes."""
    source_root, target_root, candidate_root = map(lambda path: Path(path).absolute(), (source_root, target_root, candidate_root))
    if any(root.is_symlink() or not root.is_dir() for root in (source_root, target_root, candidate_root)):
        raise MergeConflict("源、服务器和候选目录必须是独立的普通目录")
    if any(candidate_root.resolve() == root.resolve() or root.resolve().is_relative_to(candidate_root.resolve()) for root in (source_root, target_root)) or any(candidate_root.iterdir()):
        raise MergeConflict("候选目录必须为空，且不能覆盖任一输入目录")
    created = candidate_root / ".runtime"
    counts = {}
    try:
        with ExitStack() as stack:
            incoming, candidates = {}, {}
            for family, relative in PATHS.items():
                source_path, target_path = _path(source_root, relative), _path(target_root, relative)
                if not source_path.is_file():
                    raise MergeConflict(f"{family}: 导入包缺少数据库")
                source = stack.enter_context(closing(_open_readonly(source_path)))
                _schema(source, family)
                incoming[family] = source
                destination = _path(candidate_root, relative)
                destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                saved = stack.enter_context(closing(sqlite3.connect(destination, timeout=30)))
                saved.row_factory = sqlite3.Row
                if target_path.is_file():
                    target = stack.enter_context(closing(_open_readonly(target_path)))
                    _schema(target, family)
                    target.backup(saved)
                else:
                    # Clone only the trusted schema, not rows: every insertion
                    # still passes through the same collision checks.
                    _ensure_schema(source, saved, family)
                saved.execute("PRAGMA journal_mode=DELETE")
                saved.commit()
                saved.execute("PRAGMA foreign_keys=ON")
                saved.execute("BEGIN IMMEDIATE")
                _ensure_schema(source, saved, family)
                candidates[family] = saved
                destination.chmod(0o600)
            _validate_pool(incoming["pool"], source=True)
            _validate_review(incoming["review"], incoming["pool"])
            active_source = {row[0] for row in incoming["review"].execute("SELECT run_id FROM review_runs WHERE status!='archived'")}
            active_target = {row[0] for row in candidates["review"].execute("SELECT run_id FROM review_runs WHERE status!='archived'")}
            if active_target and active_source and active_target != active_source:
                raise MergeConflict("review_runs: 服务器已有不同的非归档审核批次，已拒绝导入")
            for family, tables in (("pool", POOL_TABLES), ("review", REVIEW_TABLES)):
                for table in tables:
                    counts[table] = {"added": _merge_table(incoming[family], candidates[family], table)}
                    if table in _tables(candidates[family]):
                        counts[table]["total"] = candidates[family].execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
                    else:
                        counts[table]["total"] = 0
            _validate_pool(candidates["pool"])
            _validate_review(candidates["review"], candidates["pool"])
            candidates["review"].execute("UPDATE review_runs SET status=CASE WHEN status IN ('running','queued') THEN 'paused' ELSE status END, stop=CASE WHEN status IN ('running','queued') THEN 1 ELSE stop END, reason=CASE WHEN status IN ('running','queued') THEN '数据迁移后任务已暂停，可检查后继续' ELSE reason END, worker_pid=NULL, job_id=NULL")
            for family, candidate in candidates.items():
                if candidate.execute("PRAGMA foreign_key_check").fetchone() is not None or candidate.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise MergeConflict(f"{family}: 合并后完整性校验失败")
            for candidate in candidates.values():
                candidate.commit()
        return {"version": 1, "tables": counts}
    except (sqlite3.Error, KeyError, TypeError) as exc:
        if created.exists():
            shutil.rmtree(created)
        raise MergeConflict("数据库字段或 JSON 引用结构无效；未修改服务器数据") from exc
    except BaseException:
        if created.exists():
            shutil.rmtree(created)
        raise


def main():
    parser = argparse.ArgumentParser(description="生成保留编号的题池/审核增量候选，绝不修改输入")
    parser.add_argument("source_root", type=Path)
    parser.add_argument("target_root", type=Path)
    parser.add_argument("candidate_root", type=Path)
    args = parser.parse_args()
    print(json.dumps(merge(args.source_root, args.target_root, args.candidate_root), ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (MergeConflict, OSError) as exc:
        raise SystemExit(str(exc)) from None
