"""母题库数据层：patterns.yaml + mastery.db（独立于 study_agent.db）。"""

import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta

import yaml

from backend.categories import CATEGORIES
from backend.database import get_question_by_id, update_question_source

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATTERNS_YAML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "patterns.yaml")
MASTERY_DB = os.path.join(BASE_DIR, "mastery.db")

STATE_NEVER = "never"
STATE_FIRST_PASS = "first_pass"
STATE_SECOND_PASS = "second_pass"
STATE_THIRD_PASS = "third_pass"
STATE_AGAIN_WRONG = "again_wrong"

_YAML_HEADER = """# 母题库：一级标题与 backend/categories.yaml 保持一致
#
# 每个套路的结构：
#   套路名:
#     key: 稳定编号（删除/重排题库后不失效）
#     description: 套路说明
#     mother_id: 当前母题在 study_agent.db 中的题目 ID
#     variant_ids: [变式题 ID]

"""


def _get_conn():
    conn = sqlite3.connect(MASTERY_DB)
    conn.row_factory = sqlite3.Row
    return conn


def _load_yaml() -> dict:
    if not os.path.exists(PATTERNS_YAML):
        return {}
    with open(PATTERNS_YAML, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


def _save_yaml(data: dict) -> None:
    tmp = PATTERNS_YAML + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(_YAML_HEADER)
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    os.replace(tmp, PATTERNS_YAML)


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _future_str(days: int) -> str:
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def _ensure_pattern_row(conn, yaml_key: str, category: str, name: str, description: str = "") -> int:
    conn.execute(
        """INSERT INTO patterns (yaml_key, category, name, description)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(yaml_key) DO UPDATE SET
             category = excluded.category,
             name = excluded.name,
             description = excluded.description""",
        (yaml_key, category, name, description),
    )
    row = conn.execute("SELECT id FROM patterns WHERE yaml_key = ?", (yaml_key,)).fetchone()
    return row["id"]


def _ensure_pattern_mastery(conn, pattern_id: int) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO pattern_mastery
           (pattern_id, state, need_check, next_check_at, updated_at)
           VALUES (?, 'never', 0, NULL, CURRENT_TIMESTAMP)""",
        (pattern_id,),
    )


def _recalc_category_mastery(conn, category: str) -> None:
    rows = conn.execute("SELECT id FROM patterns WHERE category = ?", (category,)).fetchall()
    total = len(rows)
    mastered = 0
    for row in rows:
        m = conn.execute(
            "SELECT state FROM pattern_mastery WHERE pattern_id = ?",
            (row["id"],),
        ).fetchone()
        if m and m["state"] == STATE_THIRD_PASS:
            mastered += 1
    percent = round(mastered / total * 100, 1) if total else 0.0
    conn.execute(
        """INSERT INTO category_mastery (category, total_patterns, mastered_patterns, percent, updated_at)
           VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(category) DO UPDATE SET
             total_patterns = excluded.total_patterns,
             mastered_patterns = excluded.mastered_patterns,
             percent = excluded.percent,
             updated_at = CURRENT_TIMESTAMP""",
        (category, total, mastered, percent),
    )


def _link_question(conn, pattern_id: int, question_id: int, role: str) -> None:
    conn.execute(
        """INSERT INTO pattern_questions (pattern_id, question_id, role)
           VALUES (?, ?, ?)
           ON CONFLICT(pattern_id, role) DO UPDATE SET question_id = excluded.question_id""",
        (pattern_id, question_id, role),
    )


def init_mastery_db() -> None:
    conn = _get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                yaml_key TEXT UNIQUE NOT NULL,
                category TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(category, name)
            );

            CREATE TABLE IF NOT EXISTS pattern_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern_id INTEGER NOT NULL REFERENCES patterns(id),
                question_id INTEGER NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('mother','variant1','variant2','variant3')),
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(pattern_id, role),
                UNIQUE(question_id, role)
            );
            CREATE INDEX IF NOT EXISTS idx_pq_pattern ON pattern_questions(pattern_id);
            CREATE INDEX IF NOT EXISTS idx_pq_question ON pattern_questions(question_id);

            CREATE TABLE IF NOT EXISTS category_mastery (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL UNIQUE,
                total_patterns INTEGER NOT NULL DEFAULT 0,
                mastered_patterns INTEGER NOT NULL DEFAULT 0,
                percent REAL NOT NULL DEFAULT 0,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS pattern_mastery (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern_id INTEGER NOT NULL UNIQUE REFERENCES patterns(id),
                state TEXT NOT NULL DEFAULT 'never',
                need_check INTEGER NOT NULL DEFAULT 0,
                next_check_at TEXT,
                last_completed_at TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id INTEGER NOT NULL,
                pattern_id INTEGER,
                role TEXT,
                correct INTEGER NOT NULL CHECK(correct IN (0,1)),
                is_first_try INTEGER NOT NULL DEFAULT 0,
                duration_seconds INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_attempts_question ON attempts(question_id);
            CREATE INDEX IF NOT EXISTS idx_attempts_pattern ON attempts(pattern_id);
            CREATE INDEX IF NOT EXISTS idx_attempts_created ON attempts(created_at);
        """)
        conn.commit()
    finally:
        conn.close()


def load_patterns_yaml() -> dict:
    return _load_yaml()


def get_patterns() -> list:
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT id, yaml_key, category, name, description FROM patterns ORDER BY category, name"
        ).fetchall()
        qrows = conn.execute(
            "SELECT pattern_id, question_id, role FROM pattern_questions ORDER BY role"
        ).fetchall()
        mrows = conn.execute(
            "SELECT pattern_id, state, need_check, next_check_at, last_completed_at FROM pattern_mastery"
        ).fetchall()
        questions = {}
        for q in qrows:
            questions.setdefault(q["pattern_id"], []).append({
                "question_id": q["question_id"],
                "role": q["role"],
            })
        mastery = {m["pattern_id"]: dict(m) for m in mrows}
        result = []
        for row in rows:
            qlist = questions.get(row["id"], [])
            result.append({
                "id": row["id"],
                "yaml_key": row["yaml_key"],
                "category": row["category"],
                "name": row["name"],
                "description": row["description"],
                "mother_id": next((q["question_id"] for q in qlist if q["role"] == "mother"), None),
                "variant_ids": [q["question_id"] for q in qlist if q["role"].startswith("variant")],
                "mastery": mastery.get(row["id"], {"state": "never", "need_check": 0}),
            })
        return result
    finally:
        conn.close()


def add_mother_question(question_id: int, category: str, name: str,
                        key: str = None, description: str = "") -> dict:
    question = get_question_by_id(question_id)
    if not question:
        raise ValueError(f"题目不存在: {question_id}")
    if category not in CATEGORIES:
        raise ValueError(f"未知板块: {category}")
    name = name.strip()
    if not name:
        raise ValueError("套路名不能为空")

    init_mastery_db()
    conn = _get_conn()
    try:
        row = None
        if key:
            row = conn.execute("SELECT * FROM patterns WHERE yaml_key = ?", (key,)).fetchone()
        if not row:
            row = conn.execute(
                "SELECT * FROM patterns WHERE category = ? AND name = ?",
                (category, name),
            ).fetchone()
        if row:
            pattern_id = row["id"]
            yaml_key = row["yaml_key"]
            if description:
                conn.execute("UPDATE patterns SET description = ? WHERE id = ?", (description, pattern_id))
        else:
            yaml_key = key or f"pat-{uuid.uuid4().hex[:10]}"
            pattern_id = _ensure_pattern_row(conn, yaml_key, category, name, description)
        _ensure_pattern_mastery(conn, pattern_id)
        _link_question(conn, pattern_id, question_id, "mother")
        _recalc_category_mastery(conn, category)
        conn.commit()
    finally:
        conn.close()

    update_question_source(question_id, "精选母题", {
        "owner": "sqz",
        "mother_id": str(question_id),
        "category": category,
        "pattern": name,
    })
    return {
        "pattern_id": pattern_id,
        "yaml_key": yaml_key,
        "category": category,
        "name": name,
        "mother_id": question_id,
    }


def get_pattern(pattern_id: int) -> dict:
    patterns = get_patterns()
    return next((p for p in patterns if p["id"] == pattern_id), None)


def update_pattern(pattern_id: int, category: str = None, name: str = None,
                   description: str = None, key: str = None) -> dict:
    conn = _get_conn()
    try:
        row = conn.execute("SELECT * FROM patterns WHERE id = ?", (pattern_id,)).fetchone()
        if not row:
            raise ValueError(f"套路不存在: {pattern_id}")
        old_category = row["category"]
        new_category = category or row["category"]
        if new_category not in CATEGORIES:
            raise ValueError(f"未知板块: {new_category}")
        new_name = (name or row["name"]).strip()
        if not new_name:
            raise ValueError("套路名不能为空")
        new_desc = row["description"] if description is None else description
        new_key = row["yaml_key"] if key is None else key
        dup = conn.execute(
            "SELECT id FROM patterns WHERE category = ? AND name = ? AND id <> ?",
            (new_category, new_name, pattern_id),
        ).fetchone()
        if dup:
            raise ValueError("同一板块下已有同名套路")
        if key:
            dup_key = conn.execute(
                "SELECT id FROM patterns WHERE yaml_key = ? AND id <> ?",
                (key, pattern_id),
            ).fetchone()
            if dup_key:
                raise ValueError(f"套路编号已存在: {key}")
        conn.execute(
            """UPDATE patterns SET category = ?, name = ?, description = ?, yaml_key = ? WHERE id = ?""",
            (new_category, new_name, new_desc, new_key, pattern_id),
        )
        if old_category != new_category:
            _recalc_category_mastery(conn, old_category)
        _recalc_category_mastery(conn, new_category)
        conn.commit()
    finally:
        conn.close()
    return get_pattern(pattern_id)


def delete_pattern(pattern_id: int) -> bool:
    conn = _get_conn()
    try:
        row = conn.execute("SELECT category FROM patterns WHERE id = ?", (pattern_id,)).fetchone()
        if not row:
            return False
        conn.execute("DELETE FROM pattern_questions WHERE pattern_id = ?", (pattern_id,))
        conn.execute("DELETE FROM pattern_mastery WHERE pattern_id = ?", (pattern_id,))
        conn.execute("DELETE FROM attempts WHERE pattern_id = ?", (pattern_id,))
        conn.execute("DELETE FROM patterns WHERE id = ?", (pattern_id,))
        _recalc_category_mastery(conn, row["category"])
        conn.commit()
        return True
    finally:
        conn.close()


def link_question_to_pattern(pattern_id: int, question_id: int, role: str) -> dict:
    if role not in ("mother", "variant1", "variant2", "variant3"):
        raise ValueError("role 必须是 mother/variant1/variant2/variant3")
    question = get_question_by_id(question_id)
    if not question:
        raise ValueError(f"题目不存在: {question_id}")
    conn = _get_conn()
    try:
        pattern_row = conn.execute("SELECT * FROM patterns WHERE id = ?", (pattern_id,)).fetchone()
        if not pattern_row:
            raise ValueError(f"套路不存在: {pattern_id}")
        pattern = dict(pattern_row)
        _link_question(conn, pattern_id, question_id, role)
        conn.commit()
    finally:
        conn.close()
    if role == "mother":
        update_question_source(question_id, "精选母题", {
            "owner": "sqz",
            "mother_id": str(question_id),
            "category": pattern["category"],
            "pattern": pattern["name"],
        })
    return get_pattern(pattern_id)


def unlink_question_from_pattern(pattern_id: int, question_id: int, role: str = None) -> bool:
    conn = _get_conn()
    try:
        if role:
            cur = conn.execute(
                "DELETE FROM pattern_questions WHERE pattern_id = ? AND question_id = ? AND role = ?",
                (pattern_id, question_id, role),
            )
        else:
            cur = conn.execute(
                "DELETE FROM pattern_questions WHERE pattern_id = ? AND question_id = ?",
                (pattern_id, question_id),
            )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def export_patterns_yaml() -> dict:
    patterns = get_patterns()
    data = {}
    for p in patterns:
        data.setdefault(p["category"], {})[p["name"]] = {
            "key": p["yaml_key"],
            "description": p.get("description", ""),
            "mother_id": p.get("mother_id"),
            "variant_ids": p.get("variant_ids", []),
        }
    _save_yaml(data)
    return data


def add_variant_question(pattern_id: int, question_id: int, role: str) -> None:
    if role not in ("variant1", "variant2", "variant3"):
        raise ValueError("role 必须是 variant1/variant2/variant3")
    init_mastery_db()
    conn = _get_conn()
    try:
        _link_question(conn, pattern_id, question_id, role)
        conn.commit()
    finally:
        conn.close()


def complete_pattern_loop(pattern_id: int, passed: bool) -> dict:
    """母题循环结果回写。passed=False 表示循环中出错，一律回到 never。"""
    init_mastery_db()
    conn = _get_conn()
    try:
        row = conn.execute("SELECT * FROM pattern_mastery WHERE pattern_id = ?", (pattern_id,)).fetchone()
        state = row["state"] if row else STATE_NEVER
        if passed:
            next_state = {
                STATE_NEVER: STATE_FIRST_PASS,
                STATE_FIRST_PASS: STATE_SECOND_PASS,
                STATE_SECOND_PASS: STATE_THIRD_PASS,
                STATE_THIRD_PASS: STATE_THIRD_PASS,
                STATE_AGAIN_WRONG: STATE_SECOND_PASS,
            }.get(state, STATE_FIRST_PASS)
            if next_state == STATE_FIRST_PASS:
                next_check = _future_str(1)
            elif next_state == STATE_SECOND_PASS:
                next_check = _future_str(7)
            else:
                next_check = _future_str(30)
            need_check = 1
        else:
            next_state = STATE_NEVER
            next_check = _now_str()
            need_check = 1
        conn.execute(
            """INSERT INTO pattern_mastery
               (pattern_id, state, need_check, next_check_at, last_completed_at, updated_at)
               VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(pattern_id) DO UPDATE SET
                 state = excluded.state,
                 need_check = excluded.need_check,
                 next_check_at = excluded.next_check_at,
                 last_completed_at = excluded.last_completed_at,
                 updated_at = CURRENT_TIMESTAMP""",
            (pattern_id, next_state, need_check, next_check, _now_str()),
        )
        cat_row = conn.execute("SELECT category FROM patterns WHERE id = ?", (pattern_id,)).fetchone()
        if cat_row:
            _recalc_category_mastery(conn, cat_row["category"])
        conn.commit()
        return {
            "pattern_id": pattern_id,
            "state": next_state,
            "need_check": need_check,
            "next_check_at": next_check,
        }
    finally:
        conn.close()


def match_mother_for_wrong_question(question_id: int):
    """错题匹配母题接口，当前为预留实现，返回 None。"""
    return None


def delete_question_links(question_id: int) -> None:
    if not os.path.exists(MASTERY_DB):
        return
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM pattern_questions WHERE question_id = ?", (question_id,))
        conn.execute("DELETE FROM attempts WHERE question_id = ?", (question_id,))
        conn.commit()
    finally:
        conn.close()


def get_mastery_summary() -> dict:
    conn = _get_conn()
    try:
        categories = conn.execute("SELECT * FROM category_mastery ORDER BY category").fetchall()
        patterns = conn.execute(
            """SELECT pm.state, COUNT(*) AS count FROM pattern_mastery pm
               GROUP BY pm.state ORDER BY pm.state"""
        ).fetchall()
        return {
            "categories": [dict(c) for c in categories],
            "pattern_states": {p["state"]: p["count"] for p in patterns},
        }
    finally:
        conn.close()


def sync_mother_questions() -> dict:
    """把题库里 source_type=精选母题 的题目同步成母题看板上的套路。"""
    from backend.database import get_all_questions

    init_mastery_db()
    conn = _get_conn()
    synced = 0
    try:
        for question in get_all_questions():
            if question.get("source_type") != "精选母题":
                continue
            meta = question.get("source_meta") or {}
            if not isinstance(meta, dict):
                continue
            category = (meta.get("category") or "").strip()
            name = (meta.get("pattern") or "").strip()
            if category not in CATEGORIES or not name:
                continue
            existing = conn.execute(
                "SELECT id FROM patterns WHERE category = ? AND name = ?",
                (category, name),
            ).fetchone()
            if existing:
                pattern_id = existing["id"]
            else:
                pattern_id = _ensure_pattern_row(conn, f"pat-{uuid.uuid4().hex[:10]}", category, name)
            _ensure_pattern_mastery(conn, pattern_id)
            _link_question(conn, pattern_id, question["id"], "mother")
            _recalc_category_mastery(conn, category)
            synced += 1
        conn.commit()
    finally:
        conn.close()

    if synced:
        export_patterns_yaml()
    return {"synced": synced}
