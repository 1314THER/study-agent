"""母题库数据层：patterns.yaml + mastery.db（独立于 study_agent.db）。"""

import json
import os
import re
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

            CREATE TABLE IF NOT EXISTS boards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL UNIQUE,
                name TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS board_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                board_id INTEGER NOT NULL REFERENCES boards(id),
                question_id INTEGER NOT NULL,
                x REAL NOT NULL DEFAULT 0,
                y REAL NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(board_id, question_id)
            );
            CREATE INDEX IF NOT EXISTS idx_board_nodes_board ON board_nodes(board_id);

            CREATE TABLE IF NOT EXISTS board_edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                board_id INTEGER NOT NULL REFERENCES boards(id),
                from_question_id INTEGER NOT NULL,
                to_question_id INTEGER NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(board_id, from_question_id, to_question_id)
            );
            CREATE INDEX IF NOT EXISTS idx_board_edges_board ON board_edges(board_id);
        """)
        conn.commit()
        # 迁移：patterns 增加 max_time_seconds
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(patterns)").fetchall()]
        if "max_time_seconds" not in cols:
            conn.execute("ALTER TABLE patterns ADD COLUMN max_time_seconds INTEGER NOT NULL DEFAULT 120")
            conn.commit()
    finally:
        conn.close()


def load_patterns_yaml() -> dict:
    return _load_yaml()


def get_patterns() -> list:
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT id, yaml_key, category, name, description, max_time_seconds FROM patterns ORDER BY category, name"
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
                "max_time_seconds": row["max_time_seconds"] or 120,
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
                   description: str = None, key: str = None,
                   max_time_seconds: int = None) -> dict:
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
        new_max_time = max_time_seconds if max_time_seconds is not None else (row["max_time_seconds"] or 120)
        new_max_time = max(10, int(new_max_time))
        conn.execute(
            """UPDATE patterns SET category = ?, name = ?, description = ?, yaml_key = ?, max_time_seconds = ? WHERE id = ?""",
            (new_category, new_name, new_desc, new_key, new_max_time, pattern_id),
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


def get_pattern_loop(pattern_id: int) -> dict:
    """返回套路循环页所需的题目、答案、限时与掌握状态。"""
    pattern = get_pattern(pattern_id)
    if not pattern:
        raise ValueError(f"套路不存在: {pattern_id}")
    roles = ["mother", "variant1", "variant2", "variant3"]
    variants = pattern.get("variant_ids") or []
    def _variant_qid(i):
        return variants[i] if i < len(variants) else None
    qids = {
        "mother": pattern.get("mother_id"),
        "variant1": _variant_qid(0),
        "variant2": _variant_qid(1),
        "variant3": _variant_qid(2),
    }
    questions = []
    for role in roles:
        qid = qids.get(role)
        if not qid:
            questions.append({"role": role, "question_id": None, "content": "", "answer": "", "question_type": ""})
            continue
        q = get_question_by_id(qid)
        if not q:
            questions.append({"role": role, "question_id": qid, "content": "", "answer": "", "question_type": ""})
            continue
        aj = q.get("answer_json") or {}
        answer = aj.get("final_answer") or ""
        if not answer and aj.get("chunk_results"):
            answer = " | ".join(cr.get("final_answer", "") for cr in aj["chunk_results"] if cr.get("final_answer"))
        if not answer:
            for cr in aj.get("chunk_results", []) or []:
                if not isinstance(cr, dict):
                    continue
                for step in cr.get("steps", []) or []:
                    if not isinstance(step, dict):
                        continue
                    text = str(step.get("detailed_writing") or "") + "\n" + str(step.get("standard_writing") or "")
                    m = re.search(r"最终答案\s*[：:]\s*(.+)$", text, re.M)
                    if m:
                        answer = m.group(1).strip()
                        break
                    m2 = re.search(r"选\s*[A-H][、,，]?[A-H]*", text)
                    if m2:
                        answer = m2.group(0).strip()
                        break
                if answer:
                    break
        questions.append({
            "role": role,
            "question_id": qid,
            "content": q.get("content", ""),
            "answer": answer,
            "question_type": q.get("question_type", ""),
        })
    return {
        "pattern": pattern,
        "questions": questions,
        "has_all_variants": all(q["question_id"] for q in questions if q["role"] != "mother"),
    }


def record_attempt(pattern_id: int, question_id: int, role: str,
                   correct: bool, is_first_try: bool = False,
                   duration_seconds: int = 0) -> int:
    """记录一次套路循环尝试。"""
    init_mastery_db()
    conn = _get_conn()
    try:
        cur = conn.execute(
            """INSERT INTO attempts
               (question_id, pattern_id, role, correct, is_first_try, duration_seconds)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (question_id, pattern_id, role, 1 if correct else 0, 1 if is_first_try else 0, int(duration_seconds or 0)),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def ensure_variants(pattern_id: int, teacher: str = "liangliang") -> dict:
    """变式1/2/3 为空时调用 AI 生成并持久化。"""
    pattern = get_pattern(pattern_id)
    if not pattern:
        raise ValueError(f"套路不存在: {pattern_id}")
    mother_id = pattern.get("mother_id")
    if not mother_id:
        raise ValueError("该套路还没有母题")
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT role, question_id FROM pattern_questions WHERE pattern_id = ? AND role LIKE 'variant%'",
            (pattern_id,),
        ).fetchall()
    finally:
        conn.close()
    existing = {r["role"]: r["question_id"] for r in rows}
    missing_roles = [f"variant{i}" for i in (1, 2, 3) if f"variant{i}" not in existing]
    if not missing_roles:
        return {"generated": 0, "variants": [existing[f"variant{i}"] for i in (1, 2, 3)]}

    from backend.generate import generate_variants
    result = generate_variants(mother_id, count=len(missing_roles), teacher=teacher)
    accepted = [c for c in result.get("candidates", []) if c.get("status") == "accepted" and c.get("question_id")]
    linked = []
    for role, cand in zip(missing_roles, accepted):
        add_variant_question(pattern_id, cand["question_id"], role)
        linked.append({"role": role, "question_id": cand["question_id"]})
    return {
        "generated": len(linked),
        "variants": [x["question_id"] for x in linked],
        "linked": linked,
        "result": result,
    }


def get_boards() -> list:
    """返回所有板块地图：节点、连线、题目摘要与掌握状态。"""
    init_mastery_db()
    conn = _get_conn()
    try:
        for cat in CATEGORIES:
            conn.execute(
                """INSERT OR IGNORE INTO boards (category, name) VALUES (?, ?)""",
                (cat, cat),
            )
        conn.commit()
        board_rows = conn.execute("SELECT * FROM boards ORDER BY category").fetchall()
        node_rows = conn.execute("SELECT * FROM board_nodes ORDER BY id").fetchall()
        edge_rows = conn.execute("SELECT * FROM board_edges ORDER BY id").fetchall()
        pq_rows = conn.execute(
            "SELECT pattern_id, question_id, role FROM pattern_questions"
        ).fetchall()
        mrows = conn.execute(
            "SELECT pattern_id, state, need_check, next_check_at, last_completed_at FROM pattern_mastery"
        ).fetchall()
    finally:
        conn.close()

    mastery = {m["pattern_id"]: dict(m) for m in mrows}
    pq_by_qid = {}
    for pq in pq_rows:
        pq_by_qid.setdefault(pq["question_id"], []).append(dict(pq))

    boards = []
    for b in board_rows:
        nodes = []
        for n in node_rows:
            if n["board_id"] != b["id"]:
                continue
            q = get_question_by_id(n["question_id"])
            links = pq_by_qid.get(n["question_id"], [])
            pattern_id = next((l["pattern_id"] for l in links if l["role"] == "mother"), None)
            state = "never"
            if pattern_id and mastery.get(pattern_id):
                state = mastery[pattern_id].get("state", "never")
            nodes.append({
                "node_id": n["id"],
                "question_id": n["question_id"],
                "x": n["x"],
                "y": n["y"],
                "content": (q.get("content", "") if q else "")[:120],
                "question_type": (q.get("question_type", "") if q else ""),
                "pattern_id": pattern_id,
                "state": state,
            })
        edges = [
            {"from_question_id": e["from_question_id"], "to_question_id": e["to_question_id"]}
            for e in edge_rows if e["board_id"] == b["id"]
        ]
        boards.append({
            "id": b["id"],
            "category": b["category"],
            "name": b["name"],
            "nodes": nodes,
            "edges": edges,
        })
    return boards


def save_board_layout(board_id: int, nodes: list, edges: list) -> dict:
    """整体替换某板块地图的节点与连线。nodes 含 question_id/x/y，edges 含 from/to question_id。"""
    conn = _get_conn()
    try:
        board = conn.execute("SELECT * FROM boards WHERE id = ?", (board_id,)).fetchone()
        if not board:
            raise ValueError(f"地图不存在: {board_id}")
        conn.execute("DELETE FROM board_edges WHERE board_id = ?", (board_id,))
        conn.execute("DELETE FROM board_nodes WHERE board_id = ?", (board_id,))
        for n in nodes or []:
            qid = int(n.get("question_id") or 0)
            if not qid:
                continue
            conn.execute(
                "INSERT INTO board_nodes (board_id, question_id, x, y) VALUES (?, ?, ?, ?)",
                (board_id, qid, float(n.get("x", 0)), float(n.get("y", 0))),
            )
        for e in edges or []:
            fq = int(e.get("from_question_id") or 0)
            tq = int(e.get("to_question_id") or 0)
            if not fq or not tq or fq == tq:
                continue
            conn.execute(
                "INSERT INTO board_edges (board_id, from_question_id, to_question_id) VALUES (?, ?, ?)",
                (board_id, fq, tq),
            )
        conn.execute("UPDATE boards SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (board_id,))
        conn.commit()
    finally:
        conn.close()
    return next((b for b in get_boards() if b["id"] == board_id), None)
