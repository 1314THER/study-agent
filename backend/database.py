"""
单用户小题库 —— SQLite 数据库

知识点分类从 categories.py 读取，调整时改那个文件即可。
"""

import sqlite3
import json
import os
from backend.categories import CATEGORIES

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
    """)
    conn.commit()
    # 迁移：新增 question_type 列（首次创建时一并添加，已存在则跳过）
    try:
        conn.execute("ALTER TABLE questions ADD COLUMN question_type TEXT")
        conn.commit()
        print("[Database] 新增 question_type 列")
    except sqlite3.OperationalError:
        pass  # 列已存在
    conn.close()
    print("[Database] 数据库初始化完成")


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
    """确保知识点来自对应板块的列表"""
    if not level1 or level1 not in CATEGORIES:
        return []
    valid = set(CATEGORIES[level1])
    return [p for p in points if p in valid]


def save_question(question_text: str, answer_dict: dict):
    """从 answer_dict 提取各字段，分别存入数据库（入库前清洗，保证字段来自字典）"""

    # 处理 category（清洗）
    category = answer_dict.get("category", {})
    category_level1, category_level2 = _sanitize_category(category)

    # 处理 difficulty（清洗）
    difficulty = answer_dict.get("difficulty", {})
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
    if question_type not in ("选择题", "填空题", "大题", "非常规压轴题"):
        question_type = None

    conn = get_connection()
    conn.execute(
        """INSERT OR REPLACE INTO questions
           (content, answer_json, category_level1, category_level2,
            difficulty_level, difficulty_score, difficulty_dimensions,
            common_mistakes, knowledge_points, question_type)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
        )
    )
    conn.commit()
    conn.close()
    print(f"[Database] 题目已保存（{category_level1} → {category_level2}，难度 {difficulty_level}）")
    if raw_kps != clean_kps:
        print(f"  [Sanitize] 知识点被清理: {raw_kps} → {clean_kps}")


def get_all_questions():
    conn = get_connection()
    rows = conn.execute(
        """SELECT id, content, category_level1, category_level2,
                  difficulty_level, difficulty_score, difficulty_dimensions,
                  knowledge_points, question_type, created_at
           FROM questions ORDER BY created_at DESC"""
    ).fetchall()
    conn.close()

    result = []
    for r in rows:
        d = dict(r)
        # JSON 字段解析
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
    for key in ("answer_json", "difficulty_dimensions", "knowledge_points", "common_mistakes"):
        val = d.get(key)
        if val:
            try:
                d[key] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def search_questions(keywords=None, categories=None, difficulties=None, types=None, limit=200):
    """按关键词（AND 多词匹配）+ 板块 + 难度 + 题型筛选"""
    conn = get_connection()
    where_clauses = []
    params = []

    if keywords:
        for kw in keywords:
            if kw.strip():
                where_clauses.append("content LIKE ?")
                params.append(f"%{kw.strip()}%")

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

    where_sql = " AND ".join(where_clauses) if where_clauses else "1"
    rows = conn.execute(
        f"""SELECT id, content, category_level1, category_level2,
                   difficulty_level, difficulty_score, difficulty_dimensions,
                   knowledge_points, question_type, created_at
            FROM questions WHERE {where_sql}
            ORDER BY created_at DESC LIMIT ?""",
        params + [limit]
    ).fetchall()
    conn.close()

    result = []
    for r in rows:
        d = dict(r)
        for key in ("difficulty_dimensions", "knowledge_points"):
            val = d.get(key)
            if val:
                try:
                    d[key] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    pass
        result.append(d)
    return result


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
