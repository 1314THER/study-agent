"""
单用户小题库 —— SQLite 数据库

知识点分类从 categories.py 读取，调整时改那个文件即可。
"""

import sqlite3
import json
import os
from backend.categories import CATEGORIES
from backend.steps import _load_steps

# 结构化字段的合法值（写死，不依赖模型输出）
_VALID_CATEGORIES = set(CATEGORIES.keys())
_VALID_DIFFICULTY_LEVELS = {"容易", "中等", "困难", "极难"}
_VALID_DIMENSION_KEYS = {"非常规程度", "计算量", "理解难度", "分类讨论", "知识点密度"}

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "study_agent.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT UNIQUE NOT NULL,
            answer_json TEXT NOT NULL,

            -- 知识点分类（从 categories.py 的固定列表选取）
            category_level1 TEXT,
            category_level2 TEXT,

            -- 难度（拆成独立字段，方便查询和展示）
            difficulty_level TEXT,          -- 容易/中等/困难/极难
            difficulty_score INTEGER,       -- 0-12
            difficulty_dimensions TEXT,      -- 六维度得分 JSON

            -- 常见错误
            common_mistakes TEXT,

            -- 原字段保留
            knowledge_points TEXT,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS mistakes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER NOT NULL REFERENCES questions(id),
            mistake_type TEXT NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS practice_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER NOT NULL REFERENCES questions(id),
            correct INTEGER NOT NULL,
            duration_seconds INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS step_errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER NOT NULL REFERENCES questions(id),
            step_number INTEGER NOT NULL,
            chunk_id INTEGER NOT NULL,
            mistake_type TEXT NOT NULL,
            mistake_detail TEXT DEFAULT '',
            student_input TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_step_errors_qid ON step_errors(question_id);
        CREATE INDEX IF NOT EXISTS idx_step_errors_type ON step_errors(mistake_type);
    """)
    conn.commit()
    # 迁移：新增 question_type 列（首次创建时一并添加，已存在则跳过）
    try:
        conn.execute("ALTER TABLE questions ADD COLUMN question_type TEXT")
        conn.commit()
        print("[Database] 新增 question_type 列")
    except sqlite3.OperationalError:
        pass  # 列已存在
    # 迁移：新增 source_type / source_meta 列
    for col in ("source_type", "source_meta"):
        try:
            conn.execute(f"ALTER TABLE questions ADD COLUMN {col} TEXT")
            conn.commit()
            print(f"[Database] 新增 {col} 列")
        except sqlite3.OperationalError:
            pass
    # 迁移：新增时间追踪列
    for col in ("last_viewed_at", "last_edited_at", "last_exam_at"):
        try:
            conn.execute(f"ALTER TABLE questions ADD COLUMN {col} TIMESTAMP")
            conn.commit()
            print(f"[Database] 新增 {col} 列")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute(f"ALTER TABLE questions ADD COLUMN {col} TEXT")
            conn.commit()
            print(f"[Database] 新增 {col} 列")
        except sqlite3.OperationalError:
            pass
    # 迁移：新增 steps_structure 列
    try:
        conn.execute("ALTER TABLE questions ADD COLUMN steps_structure TEXT")
        conn.commit()
        print("[Database] 新增 steps_structure 列")
    except sqlite3.OperationalError:
        pass
    conn.close()
    print("[Database] 数据库初始化完成")



def _build_steps_structure(chunk_results: list) -> str:
    """
    从 chunk_results 中提取步骤索引，返回 JSON 字符串
    [
        {"chunk_id":1, "step_number":1, "step_level1":"...", "step_level2":"...", "difficulty_score":1},
        ...
    ]
    """
    if not chunk_results:
        return "[]"
    index = []
    for cr in chunk_results:
        chunk_id = cr.get("chunk_id", 1)
        for step in cr.get("steps", []):
            score = None
            sd = step.get("step_difficulty")
            if isinstance(sd, dict):
                score = sd.get("score")
            entry = {
                "chunk_id": chunk_id,
                "step_number": step.get("step_number"),
                "step_level1": step.get("step_level1"),
                "step_level2": step.get("title", ""),
                "difficulty_score": score,
            }
            index.append(entry)
    return json.dumps(index, ensure_ascii=False)


def find_question(question_text: str):
    conn = get_connection()
    row = conn.execute(
        "SELECT answer_json FROM questions WHERE content = ?",
        (question_text.strip(),)
    ).fetchone()
    conn.close()
    if row:
        return json.loads(row["answer_json"])
    return None


def _sanitize_category(cat: dict) -> tuple:
    """确保 category 字段的值来自 CATEGORIES 字典"""
    if not isinstance(cat, dict):
        return None, None
    level1 = cat.get("level1")
    level2 = cat.get("level2")
    if level1 not in _VALID_CATEGORIES:
        level1 = None
    if not level1:
        level2 = None
    elif level2 and level2 not in CATEGORIES.get(level1, []):
        level2 = None
    return level1, level2


def _sanitize_difficulty(diff) -> tuple:
    """确保 difficulty 字段的值符合规范"""
    if not isinstance(diff, dict):
        return None, None, "{}"
    level = diff.get("level")
    if level not in _VALID_DIFFICULTY_LEVELS:
        level = None
    score = diff.get("total_score")
    dims = diff.get("dimensions", {})
    if isinstance(dims, dict):
        dims = {k: v for k, v in dims.items() if k in _VALID_DIMENSION_KEYS}
    return level, score, json.dumps(dims, ensure_ascii=False)


def _sanitize_knowledge_points(level1: str, points: list) -> list:
    """知识点不按板块限制，所有板块的子板块名均有效"""
    if not points:
        return []
    all_valid = set()
    for subs in CATEGORIES.values():
        all_valid.update(subs)
    return [p for p in points if p in all_valid]


def save_question(question_text: str, answer_dict: dict):
    """从 answer_dict 提取各字段，分别存入数据库（入库前清洗，保证字段来自字典）"""

    # 处理 category（清洗）
    category = answer_dict.get("category", {})
    category_level1, category_level2 = _sanitize_category(category)

    # 处理 difficulty（清洗）
    difficulty = answer_dict.get("overall_difficulty") or answer_dict.get("difficulty", {})
    difficulty_level, difficulty_score, difficulty_dimensions = _sanitize_difficulty(difficulty)

    # 处理 knowledge_points（清洗）
    raw_kps = answer_dict.get("knowledge_points", [])
    if not isinstance(raw_kps, list):
        raw_kps = []
    clean_kps = _sanitize_knowledge_points(category_level1, raw_kps)

    # 提取 question_type（从 chunk_results[0].chunk_type 或 answer_dict 顶层）
    question_type = answer_dict.get("question_type")
    if not question_type:
        chunk_results = answer_dict.get("chunk_results", [])
        if chunk_results and isinstance(chunk_results, list):
            first = chunk_results[0]
            if isinstance(first, dict):
                question_type = first.get("chunk_type")
    if question_type not in ("选择题", "填空题"):
        question_type = "大题"

    # 构建 steps_structure（从 chunk_results 提取步骤索引）
    chunk_results = answer_dict.get("chunk_results", [])
    steps_structure = _build_steps_structure(chunk_results)

    conn = get_connection()
    conn.execute(
        """INSERT OR REPLACE INTO questions
           (content, answer_json, category_level1, category_level2,
            difficulty_level, difficulty_score, difficulty_dimensions,
            common_mistakes, knowledge_points, question_type, steps_structure)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            question_text.strip(),
            json.dumps(answer_dict, ensure_ascii=False),
            category_level1,
            category_level2,
            difficulty_level,
            difficulty_score,
            difficulty_dimensions,
            json.dumps(answer_dict.get("common_mistakes", []), ensure_ascii=False),
            json.dumps(clean_kps, ensure_ascii=False),
            question_type,
            steps_structure,
        )
    )
    conn.commit()
    # 获取新增/更新的题目 ID
    row = conn.execute("SELECT id FROM questions WHERE content = ?", (question_text.strip(),)).fetchone()
    question_id = row["id"] if row else None
    conn.close()
    print(f"[Database] 题目已保存（ID={question_id}, {category_level1} → {category_level2}，难度 {difficulty_level}）")
    if raw_kps != clean_kps:
        print(f"  [Sanitize] 知识点被清理: {raw_kps} → {clean_kps}")
    return question_id


def get_all_questions():
    conn = get_connection()
    rows = conn.execute(
        """SELECT id, content, category_level1, category_level2,
                  difficulty_level, difficulty_score, difficulty_dimensions,
                  knowledge_points, question_type, steps_structure,
                  created_at, last_viewed_at, last_edited_at, last_exam_at
           FROM questions ORDER BY created_at DESC"""
    ).fetchall()
    conn.close()

    result = []
    for r in rows:
        d = dict(r)
        # JSON 字段解析
        for key in ("difficulty_dimensions", "knowledge_points", "steps_structure"):
            val = d.get(key)
            if val:
                try:
                    d[key] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    pass
        for key in ("difficulty_dimensions", "knowledge_points"):
            val = d.get(key)
            if val:
                try:
                    d[key] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    pass
        result.append(d)
    return result

def get_question_by_id(qid: int):
    """返回单题完整记录（含 answer_json），所有 JSON 字段已解析。无记录返回 None。"""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM questions WHERE id = ?", (qid,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    for key in ("answer_json", "difficulty_dimensions", "knowledge_points", "common_mistakes", "steps_structure"):
        val = d.get(key)
        if val:
            try:
                d[key] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def search_questions(keywords=None, categories=None, difficulties=None, types=None, limit=200, mode="content", error_type=None, page=1, page_size=None):
    """按关键词（AND 多词匹配）+ 板块 + 难度 + 题型筛选
    mode="content": 仅搜索题目原文
    mode="global":  同时搜索板块、知识点、步骤错因"""
    conn = get_connection()
    is_global = (mode == "global")
    where_clauses = []
    params = []

    if keywords:
        for kw in keywords:
            kw_s = kw.strip()
            if not kw_s:
                continue
            if is_global:
                # 全局搜索：搜题目原文 + 板块 + 知识点 + 错因
                kw_pat = f"%{kw_s}%"
                global_conds = [
                    "q.content LIKE ?",
                    "q.category_level1 LIKE ?",
                    "q.category_level2 LIKE ?",
                    "q.knowledge_points LIKE ?",
                    "e.mistake_type LIKE ?",
                    "e.mistake_detail LIKE ?"
                ]
                where_clauses.append(f"({' OR '.join(global_conds)})")
                params.extend([kw_pat] * 6)
            else:
                where_clauses.append("content LIKE ?")
                params.append(f"%{kw_s}%")

    if categories:
        placeholders = ",".join("?" for _ in categories)
        where_clauses.append(f"category_level1 IN ({placeholders})")
        params.extend(categories)

    if difficulties:
        placeholders = ",".join("?" for _ in difficulties)
        where_clauses.append(f"difficulty_level IN ({placeholders})")
        params.extend(difficulties)

    if types:
        placeholders = ",".join("?" for _ in types)
        where_clauses.append(f"question_type IN ({placeholders})")
        params.extend(types)

    if error_type:
        q_id = "q.id" if is_global else "questions.id"
        if error_type == "none":
            where_clauses.append(f"NOT EXISTS (SELECT 1 FROM step_errors e2 WHERE e2.question_id = {q_id})")
        elif error_type == "errors":
            where_clauses.append(f"EXISTS (SELECT 1 FROM step_errors e2 WHERE e2.question_id = {q_id})")
        else:
            where_clauses.append(f"EXISTS (SELECT 1 FROM step_errors e2 WHERE e2.question_id = {q_id} AND e2.mistake_type = ?)")
            params.append(error_type)

    from_clause = "FROM questions"
    select_prefix = ""
    q_prefix = ""
    if is_global:
        from_clause = "FROM questions q LEFT JOIN step_errors e ON e.question_id = q.id"
        select_prefix = "DISTINCT "
        q_prefix = "q."
    where_sql = " AND ".join(where_clauses) if where_clauses else "1"
    rows = conn.execute(
        f"""SELECT {select_prefix}{q_prefix}id, {q_prefix}content, {q_prefix}category_level1, {q_prefix}category_level2,
                   {q_prefix}difficulty_level, {q_prefix}difficulty_score, {q_prefix}difficulty_dimensions,
                   {q_prefix}knowledge_points, {q_prefix}question_type, {q_prefix}steps_structure,
                   {q_prefix}created_at, {q_prefix}last_viewed_at, {q_prefix}last_edited_at, {q_prefix}last_exam_at
            {from_clause} WHERE {where_sql}
            ORDER BY {q_prefix}created_at DESC LIMIT ?""",
        params + [limit]
    ).fetchall()
    # Pagination: count total before closing connection
    total_count = None
    if page_size and page_size != "all":
        count_sql = f"SELECT COUNT(DISTINCT {q_prefix}id) {from_clause} WHERE {where_sql}"
        c = conn.execute(count_sql, params).fetchone()
        total_count = c[0] if c else 0

    conn.close()

    all_rows = []
    for r in rows:
        d = dict(r)
        for key in ("difficulty_dimensions", "knowledge_points", "steps_structure"):
            val = d.get(key)
            if val:
                try:
                    d[key] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    pass
        for key in ("difficulty_dimensions", "knowledge_points", "steps_structure"):
            val = d.get(key)
            if val:
                try:
                    d[key] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    pass
        all_rows.append(d)
    
    if page_size and page_size != "all":
        offset = (page - 1) * int(page_size)
        paginated = all_rows[offset:offset + int(page_size)]
        return {"data": paginated, "total": total_count, "page": page, "page_size": int(page_size)}
    elif page_size == "all":
        return {"data": all_rows, "total": len(all_rows)}
    else:
        return all_rows


def delete_question(qid: int) -> bool:
    """删除指定 id 的题目，返回是否成功删除"""
    conn = get_connection()
    cursor = conn.execute("DELETE FROM questions WHERE id = ?", (qid,))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def ai_search_questions(query: str, limit: int = 20):
    """AI 语义搜索预留接口（当前返回空列表）"""
    return {"query": query, "results": [], "total": 0, "note": "AI 搜索功能开发中"}

# ---------- 时间追踪 ----------
def update_question_time(question_id: int, field: str):
    """更新题目的某个时间戳为当前时间"""
    if field not in ("last_viewed_at", "last_edited_at", "last_exam_at"):
        raise ValueError(f"Invalid field: {field}")
    conn = get_connection()
    conn.execute(f"UPDATE questions SET {field} = CURRENT_TIMESTAMP WHERE id = ?", (question_id,))
    conn.commit()
    conn.close()


# ---------- 来源类型校验 ----------
_VALID_SOURCE_TYPES = {"ai_generated", "human", "exam_paper", "web_search", "exam_ocr"}


def add_step_error(question_id: int, step_number: int, chunk_id: int,
                   mistake_type: str, mistake_detail: str = "") -> int:
    """写入一条错因记录，返回 id"""
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO step_errors
           (question_id, step_number, chunk_id, mistake_type, mistake_detail)
           VALUES (?, ?, ?, ?, ?)""",
        (question_id, step_number, chunk_id, mistake_type, mistake_detail)
    )
    conn.commit()
    eid = cur.lastrowid
    conn.close()
    return eid


def get_step_errors(question_id: int) -> list:
    """返回某题的所有错因记录（按步骤排序）"""
    conn = get_connection()
    rows = conn.execute(
        """SELECT id, step_number, chunk_id, mistake_type, mistake_detail, created_at
           FROM step_errors WHERE question_id = ?
           ORDER BY chunk_id, step_number""",
        (question_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_step_error(error_id: int, question_id: int) -> bool:
    """删除一条错因记录"""
    conn = get_connection()
    cur = conn.execute(
        "DELETE FROM step_errors WHERE id = ? AND question_id = ?",
        (error_id, question_id)
    )
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def get_questions_with_errors() -> list:
    """返回至少有一条错因记录的题目列表"""
    conn = get_connection()
    rows = conn.execute(
        """SELECT DISTINCT q.id, q.content, q.category_level1, q.category_level2,
                  q.difficulty_level, q.difficulty_score, q.question_type, q.source_type, q.source_meta, q.created_at,
                  q.last_viewed_at, q.last_edited_at, q.last_exam_at
           FROM questions q
           INNER JOIN step_errors e ON e.question_id = q.id
           ORDER BY q.created_at DESC"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
