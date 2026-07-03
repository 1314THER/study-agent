"""
单用户小题库 —— SQLite 数据库

知识点分类从 categories.py 读取，调整时改那个文件即可。
"""

import sqlite3
import json
import os

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


def save_question(question_text: str, answer_dict: dict):
    """从 answer_dict 提取各字段，分别存入数据库"""

    # 处理 category
    category = answer_dict.get("category", {})
    if not isinstance(category, dict):
        category = {}
    category_level1 = category.get("level1")
    category_level2 = category.get("level2")

    # 处理 difficulty
    difficulty = answer_dict.get("difficulty", {})
    if isinstance(difficulty, dict):
        difficulty_level = difficulty.get("level")
        difficulty_score = difficulty.get("total_score")
        difficulty_dimensions = json.dumps(difficulty.get("dimensions", {}), ensure_ascii=False)
    else:
        difficulty_level = str(difficulty) if difficulty else None
        difficulty_score = None
        difficulty_dimensions = None

    conn = get_connection()
    conn.execute(
        """INSERT OR REPLACE INTO questions
           (content, answer_json, category_level1, category_level2,
            difficulty_level, difficulty_score, difficulty_dimensions,
            common_mistakes, knowledge_points)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            question_text.strip(),
            json.dumps(answer_dict, ensure_ascii=False),
            category_level1,
            category_level2,
            difficulty_level,
            difficulty_score,
            difficulty_dimensions,
            json.dumps(answer_dict.get("common_mistakes", []), ensure_ascii=False),
            json.dumps(answer_dict.get("knowledge_points", []), ensure_ascii=False)
        )
    )
    conn.commit()
    conn.close()
    print(f"[Database] 题目已保存（{category_level1} → {category_level2}，难度 {difficulty_level}）")


def get_all_questions():
    conn = get_connection()
    rows = conn.execute(
        """SELECT id, content, category_level1, category_level2,
                  difficulty_level, difficulty_score, difficulty_dimensions,
                  knowledge_points, created_at
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
