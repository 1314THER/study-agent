"""
单用户小题库 —— SQLite 数据库

存三样东西：
  1. questions  — 题目 + AI 解析结果
  2. mistakes   — 错因记录（预留）
  3. practice_records — 练习记录（预留）
"""

import sqlite3
import json
import os

# 数据库文件存在项目根目录
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "study_agent.db")


def get_connection():
    """连接数据库"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # 让查询结果可以用字段名访问
    return conn


def init_db():
    """初始化数据库（建表）"""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT UNIQUE NOT NULL,       -- 题目原文（唯一，去重用）
            answer_json TEXT NOT NULL,           -- 完整结构化解析
            subject TEXT,                        -- 科目
            difficulty TEXT,                     -- 难度
            knowledge_points TEXT,               -- 知识点列表（JSON 数组）
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS mistakes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER NOT NULL REFERENCES questions(id),
            mistake_type TEXT NOT NULL,          -- 思路错误/计算错误/规范错误
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS practice_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER NOT NULL REFERENCES questions(id),
            correct INTEGER NOT NULL,            -- 0=错 1=对
            duration_seconds INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()
    print("[Database] 数据库初始化完成")


def find_question(question_text: str):
    """根据题目原文查找缓存，找到则返回解析结果，找不到返回 None"""
    conn = get_connection()
    row = conn.execute(
        "SELECT answer_json FROM questions WHERE content = ?",
        (question_text.strip(),)
    ).fetchone()
    conn.close()

    if row:
        print("[Database] 找到缓存题目，直接复用")
        return json.loads(row["answer_json"])
    return None


def save_question(question_text: str, answer_dict: dict):
    """保存题目和解析结果到数据库"""
    conn = get_connection()
    conn.execute(
        """INSERT OR REPLACE INTO questions
           (content, answer_json, subject, difficulty, knowledge_points)
           VALUES (?, ?, ?, ?, ?)""",
        (
            question_text.strip(),
            json.dumps(answer_dict, ensure_ascii=False),
            answer_dict.get("subject"),
            answer_dict.get("difficulty"),
            json.dumps(answer_dict.get("knowledge_points", []), ensure_ascii=False)
        )
    )
    conn.commit()
    conn.close()
    print("[Database] 题目已保存")


def get_all_questions():
    """查看所有已保存的题目（后续可以展示用）"""
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, content, subject, difficulty, created_at FROM questions ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
