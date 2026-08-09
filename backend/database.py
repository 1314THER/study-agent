"""
单用户小题库 —— SQLite 数据库

知识点分类从 categories.py 读取，调整时改那个文件即可。
"""

import json
import os
import random
import re
import sqlite3
from backend import difficulty as diff
from backend.categories import CATEGORIES
from backend.steps import _load_steps

# 结构化字段的合法值（写死，不依赖模型输出）
_VALID_CATEGORIES = set(CATEGORIES.keys())
_VALID_DIFFICULTY_LEVELS = {"容易", "中等", "困难", "极难", "未知"}
_VALID_DIMENSION_KEYS = set(diff.DIM_KEYS)
_VALID_SOURCE_TYPES = {"ai生成", "高考题", "模拟题", "精选母题"}
_CATEGORY_ALIASES = {
    "集合与常用逻辑用语": "集合与逻辑用语",
}

# 每种来源允许的二级标签字段，入库时只保留这些键
_SOURCE_META_FIELDS = {
    "模拟题": {"paper", "question_no"},
    "高考题": {"paper", "question_no"},
    "ai生成": {"reference_id"},
    "精选母题": {"owner", "mother_id", "category", "pattern"},
}
_DIMENSION_ALIASES = dict(diff.DIM_ALIASES)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "study_agent.db")


_MATH_SPAN_PATTERN = re.compile(r"\$\$.*?\$\$|\$[^$\n]*?\$", re.DOTALL)
_OPTION_LABEL_PATTERN = re.compile(r"(?<![A-Za-z0-9$\\])([A-H])\s*[.．、)]\s*")


def _plain_segments(text: str) -> list:
    """把字符串切成“非公式”片段，LaTeX 的 $...$ / $$...$$ 原样保留。"""
    out = []
    pos = 0
    for m in _MATH_SPAN_PATTERN.finditer(text):
        if m.start() > pos:
            out.append(text[pos:m.start()])
        out.append(m.group(0))
        pos = m.end()
    if pos < len(text):
        out.append(text[pos:])
    return out


def looks_like_choice_question(text: str) -> bool:
    """内容中出现两个以上 A/B/C/D 选项标记时，按选择题处理。"""
    if not text:
        return False
    labels = set()
    for segment in _plain_segments(text):
        for m in _OPTION_LABEL_PATTERN.finditer(segment):
            labels.add(m.group(1).upper())
            if len(labels) >= 2:
                return True
    return False


def looks_like_multi_choice_question(question_text: str = "", answer_dict: dict = None) -> bool:
    """题干带（多选）或最终答案选了多个选项时，按多选题处理。"""
    if question_text and "多选" in question_text:
        return True
    if not isinstance(answer_dict, dict):
        return False
    final_answer = answer_dict.get("final_answer") or ""
    chunk_results = answer_dict.get("chunk_results")
    if not final_answer and isinstance(chunk_results, list) and chunk_results:
        first = chunk_results[0]
        if isinstance(first, dict):
            final_answer = first.get("final_answer") or ""
    cleaned = re.sub(r"\$", "", final_answer or "")
    m = re.search(r"选\s*([A-H](?:\s*[、,，/]\s*[A-H]|\s*[A-H])+)", cleaned)
    if not m:
        return False
    labels = set(re.findall(r"[A-H]", m.group(1)))
    return len(labels) >= 2


def _normalize_choice_question_text(text: str) -> str:
    """把选择题选项统一为独立成行，选项之间只换一行。"""
    if not text:
        return text
    s = text.replace("\r\n", "\n")
    segments = _plain_segments(s)
    for i, segment in enumerate(segments):
        if segment.startswith(("$", "$$")):
            continue
        segments[i] = _OPTION_LABEL_PATTERN.sub(r"\n\1. ", segment)
    s = "".join(segments)
    lines = []
    for line in s.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        lines.append(stripped)
    return "\n".join(lines).strip()


def _ensure_multi_choice_marker(text: str) -> str:
    """多选题入库前在题干开头补上（多选），方便学生一眼区分。"""
    if not text:
        return text
    if re.match(r"^[（(]\s*多选\s*[）)]", text.strip()):
        return text
    return "（多选）" + text.strip()


def _collect_step_knowledge_points(chunk_results: list) -> list:
    """从各步骤的 knowledge_point 收集去重后的知识点。"""
    if not isinstance(chunk_results, list):
        return []
    out = []
    seen = set()
    for cr in chunk_results:
        if not isinstance(cr, dict):
            continue
        for step in cr.get("steps", []) or []:
            if not isinstance(step, dict):
                continue
            kp = step.get("knowledge_point")
            if not kp:
                continue
            for part in re.split(r"[、,，;；]+", str(kp)):
                part = part.strip()
                if part and part not in seen:
                    seen.add(part)
                    out.append(part)
    return out


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# 系统题单 ID 缓存（init_db 时填充）
_SYSTEM_LIST_IDS = {}

def _ensure_system_lists(conn):
    for name in ("全部", "母题", "高考题"):
        row = conn.execute("SELECT id FROM question_lists WHERE name = ? AND list_type = 'system'", (name,)).fetchone()
        if not row:
            cur = conn.execute("INSERT INTO question_lists (name, list_type) VALUES (?, 'system')", (name,))
            _SYSTEM_LIST_IDS[name] = cur.lastrowid
        else:
            _SYSTEM_LIST_IDS[name] = row["id"]
    conn.commit()


def _sanitize_source_meta(source_type, source_meta):
    """按来源类型清洗二级标签，未知来源或非 dict 一律返回 {}"""
    if not source_type or source_type not in _SOURCE_META_FIELDS:
        return {}
    if not isinstance(source_meta, dict):
        return {}
    allowed = _SOURCE_META_FIELDS[source_type]
    out = {}
    for key in allowed:
        val = source_meta.get(key)
        if val is None:
            continue
        if isinstance(val, str):
            val = val.strip()
            if not val:
                continue
        elif isinstance(val, (int, float)) and not isinstance(val, bool):
            val = str(val).strip()
        else:
            continue
        out[key] = val
    return out


def _backfill_legacy_source_meta(conn):
    """老库里的题没有二级标签：统一补成 模拟题 · test · 第 n 题（n 随机 1-19）"""
    rows = conn.execute(
        """SELECT id, source_type, source_meta FROM questions
           WHERE source_type = '模拟题'
             AND (source_meta IS NULL OR source_meta = '' OR source_meta = '{}')"""
    ).fetchall()
    changed = 0
    for row in rows:
        meta = {"paper": "test", "question_no": str(random.randint(1, 19))}
        conn.execute(
            "UPDATE questions SET source_meta = ? WHERE id = ?",
            (json.dumps(meta, ensure_ascii=False), row["id"]),
        )
        changed += 1
    if changed:
        conn.commit()
        print(f"[Database] 已为 {changed} 道旧题补写 模拟题·test·随机题号")


def _sync_question_to_source_list(conn, question_id, source_type):
    """按一级来源自动加入对应系统题单：高考题→高考题，精选母题→母题"""
    list_name = None
    if source_type == "高考题":
        list_name = "高考题"
    elif source_type == "精选母题":
        list_name = "母题"
    if not list_name:
        return
    row = conn.execute(
        "SELECT id FROM question_lists WHERE name = ? AND list_type = 'system'",
        (list_name,),
    ).fetchone()
    if row:
        conn.execute(
            "INSERT OR IGNORE INTO question_list_members (list_id, question_id) VALUES (?, ?)",
            (row["id"], question_id),
        )


def _backfill_source_lists(conn):
    """老题回填：已经带来源标签的题目补进对应系统题单"""
    rows = conn.execute("SELECT id, source_type FROM questions").fetchall()
    changed = 0
    for row in rows:
        before = conn.total_changes
        _sync_question_to_source_list(conn, row["id"], row["source_type"])
        if conn.total_changes != before:
            changed += 1
    if changed:
        conn.commit()
        print(f"[Database] 已为 {changed} 道题补进来源对应题单")


def _backfill_choice_questions(conn):
    """老题回填：选择题/多选题的题型与选项排版，并从步骤级补回知识点。"""
    rows = conn.execute(
        "SELECT id, content, question_type, answer_json, knowledge_points, category_level1 FROM questions"
    ).fetchall()
    changed = 0
    for row in rows:
        content = row["content"] or ""
        qtype = row["question_type"]
        answer_json = row["answer_json"]
        try:
            aj = json.loads(answer_json) if answer_json else {}
        except (json.JSONDecodeError, TypeError):
            aj = {}
        if not isinstance(aj, dict):
            aj = {}

        is_multi = looks_like_multi_choice_question(content, aj)
        is_choice = looks_like_choice_question(content)
        if is_multi:
            effective = "多选题"
        elif is_choice:
            effective = "选择题"
        else:
            effective = qtype if qtype in ("选择题", "填空题", "大题") else "大题"

        row_changed = False
        if effective in ("选择题", "多选题") and qtype != effective:
            aj["question_type"] = effective
            chunk_results = aj.get("chunk_results")
            if isinstance(chunk_results, list) and chunk_results and isinstance(chunk_results[0], dict):
                chunk_results[0]["chunk_type"] = effective
            conn.execute(
                "UPDATE questions SET question_type = ?, answer_json = ? WHERE id = ?",
                (effective, json.dumps(aj, ensure_ascii=False), row["id"]),
            )
            row_changed = True
        if effective in ("选择题", "多选题"):
            if effective == "多选题":
                content = _ensure_multi_choice_marker(content)
            new_content = _normalize_choice_question_text(content)
            if new_content != content:
                conn.execute(
                    "UPDATE questions SET content = ? WHERE id = ?",
                    (new_content, row["id"]),
                )
                row_changed = True

        # 知识点回填：顶层为空时从步骤级收集，并映射到二级知识点
        raw_kps = aj.get("knowledge_points")
        if not isinstance(raw_kps, list) or not raw_kps:
            collected = _collect_step_knowledge_points(aj.get("chunk_results"))
            if collected:
                clean_kps = _sanitize_knowledge_points(row["category_level1"], collected)
                aj["knowledge_points"] = clean_kps
                conn.execute(
                    "UPDATE questions SET answer_json = ?, knowledge_points = ? WHERE id = ?",
                    (json.dumps(aj, ensure_ascii=False), json.dumps(clean_kps, ensure_ascii=False), row["id"]),
                )
                row_changed = True
        elif not row["knowledge_points"]:
            clean_kps = _sanitize_knowledge_points(row["category_level1"], raw_kps)
            if clean_kps:
                conn.execute(
                    "UPDATE questions SET knowledge_points = ? WHERE id = ?",
                    (json.dumps(clean_kps, ensure_ascii=False), row["id"]),
                )
                row_changed = True
        if row_changed:
            changed += 1
    if changed:
        conn.commit()
        print(f"[Database] 已修正 {changed} 道题的题型/选项/知识点")


def _backfill_multi_choice_marker(conn):
    """老题回填：多选题题干开头统一补上（多选）标记"""
    rows = conn.execute(
        "SELECT id, content FROM questions WHERE question_type = '多选题'"
    ).fetchall()
    changed = 0
    for row in rows:
        content = row["content"] or ""
        new_content = _ensure_multi_choice_marker(content)
        if new_content != content:
            conn.execute(
                "UPDATE questions SET content = ? WHERE id = ?",
                (new_content, row["id"]),
            )
            changed += 1
    if changed:
        conn.commit()
        print(f"[Database] 已为 {changed} 道多选题补上（多选）标记")


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
            difficulty_level TEXT,          -- 容易/中等/困难/极难/未知
            difficulty_score INTEGER,       -- 0-15
            difficulty_dimensions TEXT,      -- 五维难度 JSON

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

        CREATE TABLE IF NOT EXISTS question_lists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            list_type TEXT NOT NULL DEFAULT 'user',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS question_list_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            list_id INTEGER NOT NULL REFERENCES question_lists(id),
            question_id INTEGER NOT NULL REFERENCES questions(id),
            is_removed INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(list_id, question_id)
        );
    """)
    conn.commit()
    _ensure_system_lists(conn)
    # 回填：将已有题目加入 "全部" 题单（仅在新装时执行一次）
    all_id = _SYSTEM_LIST_IDS.get("全部")
    if all_id:
        missing = conn.execute(
            "SELECT COUNT(*) FROM questions q WHERE NOT EXISTS (SELECT 1 FROM question_list_members m WHERE m.list_id = ? AND m.question_id = q.id)",
            (all_id,)
        ).fetchone()[0]
        if missing > 0:
            conn.execute(
                "INSERT OR IGNORE INTO question_list_members (list_id, question_id) SELECT ?, id FROM questions",
                (all_id,)
            )
            conn.commit()
            print(f"[Database] 已回填 {missing} 道题到「全部」题单")
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
    # 回填：老题没有二级标签时补成 模拟题·test·第 n 题（n 随机 1-19）
    try:
        _backfill_legacy_source_meta(conn)
    except sqlite3.OperationalError as e:
        print(f"[Database] 来源二级标签回填跳过: {e}")
    # 回填：老题按来源标签补进高考题/母题系统题单
    try:
        _backfill_source_lists(conn)
    except sqlite3.OperationalError as e:
        print(f"[Database] 来源题单回填跳过: {e}")
    # 回填：选项齐全却按大题保存的题改为选择题
    try:
        _backfill_choice_questions(conn)
    except sqlite3.OperationalError as e:
        print(f"[Database] 选择题题型回填跳过: {e}")
    # 回填：多选题题干开头统一加（多选）
    try:
        _backfill_multi_choice_marker(conn)
    except sqlite3.OperationalError as e:
        print(f"[Database] 多选题标记回填跳过: {e}")
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
    # 回填：把旧版难度维度字段名统一成新版，缺失时从 answer_json 补充
    try:
        rows = conn.execute(
            "SELECT id, difficulty_dimensions, answer_json FROM questions"
        ).fetchall()
        for row in rows:
            merged = {}
            col_dims = row["difficulty_dimensions"]
            if col_dims:
                try:
                    merged.update(_normalize_dimension_keys(json.loads(col_dims)))
                except (json.JSONDecodeError, TypeError):
                    pass
            aj_dims = {}
            if row["answer_json"]:
                try:
                    aj = json.loads(row["answer_json"])
                    diff = aj.get("overall_difficulty") or aj.get("difficulty") or {}
                    aj_dims = diff.get("dimensions", {}) or {}
                except (json.JSONDecodeError, TypeError):
                    pass
            merged.update(_normalize_dimension_keys(aj_dims))
            if merged:
                new_json = json.dumps(merged, ensure_ascii=False)
                if new_json != (col_dims or ""):
                    conn.execute(
                        "UPDATE questions SET difficulty_dimensions = ? WHERE id = ?",
                        (new_json, row["id"])
                    )
        conn.commit()
    except sqlite3.OperationalError as e:
        print(f"[Database] 难度维度回填跳过: {e}")
    # 迁移：新建题单表（兼容已有库）
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS question_lists (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, list_type TEXT NOT NULL DEFAULT 'user', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE IF NOT EXISTS question_list_members (id INTEGER PRIMARY KEY AUTOINCREMENT, list_id INTEGER NOT NULL REFERENCES question_lists(id), question_id INTEGER NOT NULL REFERENCES questions(id), is_removed INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(list_id, question_id))")
        print("[Database] 题单表已就绪")
    except sqlite3.OperationalError as e:
        print(f"[Database] 题单表初始化跳过: {e}")
    _ensure_system_lists(conn)
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
def _normalize_question(q: str) -> str:
    """归一化题目文本：去掉所有空白字符，使相同题目的不同格式能匹配"""
    import re
    return re.sub(r'\s+', '', q)




def find_question(question_text: str):
    conn = get_connection()
    q = question_text.strip()
    
    # 1. 精确匹配（快速路径）
    row = conn.execute(
        "SELECT answer_json FROM questions WHERE content = ?",
        (q,)
    ).fetchone()
    
    if not row:
        # 2. 模糊匹配：去除所有空白后比较（处理格式差异）
        norm_q = _normalize_question(q)
        rows = conn.execute("SELECT content, answer_json FROM questions").fetchall()
        for content, aj in rows:
            if _normalize_question(content) == norm_q:
                row = (aj,)
                break
    
    conn.close()
    if row:
        return json.loads(row[0])
    return None


def _sanitize_category(cat: dict) -> tuple:
    """确保 category 字段的值来自 CATEGORIES 字典"""
    if not isinstance(cat, dict):
        return None, None
    level1 = cat.get("level1")
    level2 = cat.get("level2")
    if level1 in _CATEGORY_ALIASES:
        level1 = _CATEGORY_ALIASES[level1]
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
        dims = _normalize_dimension_keys(dims)
    return level, score, json.dumps(dims, ensure_ascii=False)


def _normalize_dimension_keys(dims: dict) -> dict:
    """把旧版维度名映射到新版五维字段，并过滤未知字段。"""
    return diff.normalize_dims(dims)


def _build_l3_to_l2_map() -> dict:
    """构建三级→二级知识点映射"""
    import yaml
    path = os.path.join(os.path.dirname(__file__), "categories.yaml")
    result = {}
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        for l1, l2_dict in data.items():
            for l2_name, l3_list in l2_dict.items():
                for l3 in l3_list:
                    result[l3] = l2_name
    except:
        pass
    return result


def _sanitize_knowledge_points(level1: str, points: list) -> list:
    """AI 输出的三级知识点 -> 映射为二级知识点"""
    if not points:
        return []
    l3_map = _build_l3_to_l2_map()
    all_valid = set()
    for subs in CATEGORIES.values():
        all_valid.update(subs)
    result = []
    for p in points:
        if p in l3_map:
            l2 = l3_map[p]
            if l2 not in result:
                result.append(l2)
        elif p in all_valid:
            if p not in result:
                result.append(p)
    return result


def save_question(question_text: str, answer_dict: dict):
    """从 answer_dict 提取各字段，分别存入数据库（入库前清洗，保证字段来自字典）"""

    # 处理 category（清洗）
    category = answer_dict.get("category", {})
    category_level1, category_level2 = _sanitize_category(category)

    # 难度唯一标准：有步骤五维就从 chunk_results 重算，否则视为未知
    chunk_results = answer_dict.get("chunk_results", [])
    if isinstance(chunk_results, list) and chunk_results:
        if diff.has_step_dimensions(chunk_results):
            _, overall = diff.aggregate_chunk_results(chunk_results)
            answer_dict["overall_difficulty"] = overall
        else:
            old_od = answer_dict.get("overall_difficulty") or answer_dict.get("difficulty") or {}
            if isinstance(old_od, dict) and old_od and old_od != diff.UNKNOWN_DIFFICULTY:
                answer_dict.setdefault("legacy_difficulty", old_od)
            answer_dict["overall_difficulty"] = dict(diff.UNKNOWN_DIFFICULTY)
            for cr in chunk_results:
                if isinstance(cr, dict):
                    cr["difficulty"] = dict(diff.UNKNOWN_DIFFICULTY)

    # 处理 difficulty（清洗）
    difficulty = answer_dict.get("overall_difficulty") or answer_dict.get("difficulty", {})
    difficulty_level, difficulty_score, difficulty_dimensions = _sanitize_difficulty(difficulty)
    # 把清洗/归一化后的五维难度写回 answer_json，保证所有前端都能读到
    if isinstance(difficulty, dict) and difficulty_dimensions:
        try:
            normalized_dims = json.loads(difficulty_dimensions)
            if isinstance(normalized_dims, dict) and normalized_dims:
                difficulty["dimensions"] = normalized_dims
        except (json.JSONDecodeError, TypeError):
            pass

    # 处理 knowledge_points（清洗；顶层为空时从步骤级补）
    raw_kps = answer_dict.get("knowledge_points", [])
    if not isinstance(raw_kps, list):
        raw_kps = []
    if not raw_kps:
        raw_kps = _collect_step_knowledge_points(chunk_results)
    clean_kps = _sanitize_knowledge_points(category_level1, raw_kps)
    # 把清洗后的知识点写回 answer_json，保证详情页与库字段一致
    answer_dict["knowledge_points"] = clean_kps

    # 提取 question_type（从 chunk_results[0].chunk_type 或 answer_dict 顶层）
    question_type = answer_dict.get("question_type")
    if not question_type:
        if chunk_results and isinstance(chunk_results, list):
            first = chunk_results[0]
            if isinstance(first, dict):
                question_type = first.get("chunk_type")
    if question_type not in ("选择题", "填空题", "多选题"):
        question_type = "大题"
    # 兜底：答案有多个选项或题干带“多选”时按多选题保存
    if looks_like_multi_choice_question(question_text, answer_dict):
        question_type = "多选题"
        answer_dict["question_type"] = "多选题"
        if chunk_results and isinstance(chunk_results, list):
            first = chunk_results[0]
            if isinstance(first, dict):
                first["chunk_type"] = "多选题"
    elif question_type == "大题" and looks_like_choice_question(question_text):
        question_type = "选择题"
        answer_dict["question_type"] = "选择题"
        if chunk_results and isinstance(chunk_results, list):
            first = chunk_results[0]
            if isinstance(first, dict):
                first["chunk_type"] = "选择题"
    if question_type in ("选择题", "多选题"):
        if question_type == "多选题":
            question_text = _ensure_multi_choice_marker(question_text)
        question_text = _normalize_choice_question_text(question_text)

    # 处理 source_type（清洗）
    source_type = answer_dict.get("source_type")
    if source_type not in _VALID_SOURCE_TYPES:
        source_type = None
    source_meta = answer_dict.get("source_meta")
    if not isinstance(source_meta, dict):
        source_meta = None
    if source_type is None or source_meta is None:
        existing_conn = get_connection()
        try:
            existing_row = existing_conn.execute(
                "SELECT source_type, source_meta FROM questions WHERE content = ?",
                (question_text.strip(),)
            ).fetchone()
            if source_type is None and existing_row and existing_row["source_type"]:
                source_type = existing_row["source_type"]
            if source_meta is None and existing_row and existing_row["source_meta"]:
                try:
                    source_meta = json.loads(existing_row["source_meta"])
                except (json.JSONDecodeError, TypeError):
                    pass
        finally:
            existing_conn.close()
    if source_meta is None:
        source_meta = {}
    source_meta_json = json.dumps(_sanitize_source_meta(source_type, source_meta), ensure_ascii=False)

    # 构建 steps_structure（从 chunk_results 提取步骤索引）
    steps_structure = _build_steps_structure(chunk_results)
    # 追加预定义步骤名（方便按步骤名搜索）
    if category_level1 and steps_structure != "[]":
        try:
            from backend.steps import _load_steps
            all_steps = _load_steps()
            # 映射 category_level1 → steps.yaml 题型名
            cat_to_type = {
                "立体几何": "立体几何大题", "解析几何": "解析几何大题",
                "三角函数": "解三角形大题", "数列": "数列大题",
                "函数与导数": "函数与导数大题", "概率统计": "简单的概率统计大题",
            }
            step_type = cat_to_type.get(category_level1)
            if step_type and step_type in all_steps:
                extra = []
                for l1, l2_list in all_steps[step_type].items():
                    for l2 in l2_list:
                        extra.append({"step_level1": l1, "step_level2": l2})
                if extra:
                    existing = json.loads(steps_structure)
                    # 去重：已有的 step_level2 不重复加
                    existing_l2s = {s.get("step_level2","") for s in existing}
                    new_entries = [e for e in extra if e["step_level2"] not in existing_l2s]
                    if new_entries:
                        existing.extend(new_entries)
                        steps_structure = json.dumps(existing, ensure_ascii=False)
        except Exception:
            pass

    conn = get_connection()
    conn.execute(
        """INSERT INTO questions
           (content, answer_json, category_level1, category_level2,
            difficulty_level, difficulty_score, difficulty_dimensions,
            common_mistakes, knowledge_points, question_type, steps_structure,
            source_type, source_meta)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(content) DO UPDATE SET
            answer_json = excluded.answer_json,
            category_level1 = excluded.category_level1,
            category_level2 = excluded.category_level2,
            difficulty_level = excluded.difficulty_level,
            difficulty_score = excluded.difficulty_score,
            difficulty_dimensions = excluded.difficulty_dimensions,
            common_mistakes = excluded.common_mistakes,
            knowledge_points = excluded.knowledge_points,
            question_type = excluded.question_type,
            steps_structure = excluded.steps_structure,
            source_type = excluded.source_type,
            source_meta = excluded.source_meta""",
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
            source_type,
            source_meta_json,
        )
    )
    conn.commit()
    # 获取新增/更新的题目 ID
    row = conn.execute("SELECT id FROM questions WHERE content = ?", (question_text.strip(),)).fetchone()
    question_id = row["id"] if row else None
    conn.close()
    # 自动加入 "全部" 题单
    if question_id is not None:
        _all_conn = get_connection()
        try:
            _r = _all_conn.execute("SELECT id FROM question_lists WHERE name = '\u5168\u90e8' AND list_type = 'system'").fetchone()
            if _r:
                _all_conn.execute(
                    "INSERT OR IGNORE INTO question_list_members (list_id, question_id) VALUES (?, ?)",
                    (_r["id"], question_id)
                )
            _sync_question_to_source_list(_all_conn, question_id, source_type)
            _all_conn.commit()
        except Exception:
            pass
        _all_conn.close()
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
                  source_type, source_meta,
                  created_at, last_viewed_at, last_edited_at, last_exam_at
           FROM questions ORDER BY created_at DESC"""
    ).fetchall()
    conn.close()

    result = []
    for r in rows:
        d = dict(r)
        # JSON 字段解析
        for key in ("difficulty_dimensions", "knowledge_points", "steps_structure", "source_meta"):
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
    for key in ("answer_json", "difficulty_dimensions", "knowledge_points", "common_mistakes", "steps_structure", "source_meta"):
        val = d.get(key)
        if val:
            try:
                d[key] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def search_questions(keywords=None, categories=None, difficulties=None, types=None, limit=200, mode="content", error_type=None, page=1, page_size=None, source_type=None):
    """按关键词 + 板块 + 难度 + 题型 + 来源筛选
    关键词同时搜索题目原文、板块、知识点、错因、来源字段（OR），多个关键词之间取 AND。"""
    conn = get_connection()
    # 统一走全局模式：搜全字段
    is_global = True
    where_clauses = []
    params = []

    if keywords:
        for kw in keywords:
            kw_s = kw.strip()
            if not kw_s:
                continue
            kw_pat = f"%{kw_s}%"
            search_conds = [
                "q.content LIKE ?",
                "q.category_level1 LIKE ?",
                "q.category_level2 LIKE ?",
                "q.knowledge_points LIKE ?",
                "q.steps_structure LIKE ?",
                "q.difficulty_level LIKE ?",
                "e.mistake_type LIKE ?",
                "e.mistake_detail LIKE ?",
                "q.source_type LIKE ?",
                "q.source_meta LIKE ?"
            ]
            where_clauses.append(f"({' OR '.join(search_conds)})")
            params.extend([kw_pat] * 10)

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

    if source_type:
        where_clauses.append("q.source_type = ?")
        params.append(source_type)

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
                   {q_prefix}source_type, {q_prefix}source_meta,
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
        for key in ("difficulty_dimensions", "knowledge_points", "steps_structure", "source_meta"):
            val = d.get(key)
            if val:
                try:
                    d[key] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    pass
        for key in ("difficulty_dimensions", "knowledge_points", "steps_structure", "source_meta"):
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
    conn.execute("DELETE FROM question_list_members WHERE question_id = ?", (qid,))
    conn.execute("DELETE FROM step_errors WHERE question_id = ?", (qid,))
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


def add_step_error(question_id: int, step_number: int, chunk_id: int,
                   mistake_type: str, mistake_detail: str = "",
                   student_input: str = "") -> int:
    """写入一条错因记录，返回 id"""
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO step_errors
           (question_id, step_number, chunk_id, mistake_type, mistake_detail, student_input)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (question_id, step_number, chunk_id, mistake_type, mistake_detail, student_input)
    )
    conn.commit()
    eid = cur.lastrowid
    conn.close()
    return eid


def get_step_errors(question_id: int) -> list:
    """返回某题的所有错因记录（按步骤排序）"""
    conn = get_connection()
    rows = conn.execute(
        """SELECT id, step_number, chunk_id, mistake_type, mistake_detail, student_input, created_at
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


# ========== question list management ==========

def get_question_lists():
    conn = get_connection()
    rows = conn.execute("SELECT id, name, list_type FROM question_lists ORDER BY list_type DESC, id ASC").fetchall()
    result = []
    for r in rows:
        d = dict(r)
        cnt = conn.execute(
            """SELECT COUNT(*)
               FROM question_list_members m
               JOIN questions q ON q.id = m.question_id
               WHERE m.list_id = ? AND m.is_removed = 0""",
            (d["id"],)
        ).fetchone()[0]
        d["count"] = cnt
        result.append(d)
    error_cnt = conn.execute(
        """SELECT COUNT(DISTINCT e.question_id)
           FROM step_errors e
           JOIN questions q ON q.id = e.question_id"""
    ).fetchone()[0]
    result.append({
        "id": None,
        "name": "\u9519\u9898",
        "list_type": "system",
        "is_dynamic": True,
        "count": error_cnt
    })
    conn.close()
    return result


def create_question_list(name):
    conn = get_connection()
    cur = conn.execute("INSERT INTO question_lists (name, list_type) VALUES (?, 'user')", (name.strip(),))
    conn.commit()
    lid = cur.lastrowid
    conn.close()
    return lid


def delete_question_list(list_id):
    conn = get_connection()
    row = conn.execute("SELECT list_type FROM question_lists WHERE id = ?", (list_id,)).fetchone()
    if not row or row["list_type"] == "system":
        conn.close()
        return False
    conn.execute("DELETE FROM question_list_members WHERE list_id = ?", (list_id,))
    conn.execute("DELETE FROM question_lists WHERE id = ?", (list_id,))
    conn.commit()
    conn.close()
    return True


def rename_question_list(list_id, name):
    conn = get_connection()
    cur = conn.execute("UPDATE question_lists SET name = ? WHERE id = ?", (name.strip(), list_id))
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def add_question_to_lists(question_id, list_ids):
    conn = get_connection()
    added = 0
    skipped = 0
    for lid in list_ids:
        try:
            cur = conn.execute(
                "INSERT OR IGNORE INTO question_list_members (list_id, question_id) VALUES (?, ?)",
                (lid, question_id)
            )
            if cur.rowcount > 0:
                added += 1
            else:
                skipped += 1
        except Exception:
            skipped += 1
    conn.commit()
    conn.close()
    return {"added": added, "skipped": skipped}


def remove_question_from_list(question_id, list_id):
    conn = get_connection()
    row = conn.execute("SELECT list_type, name FROM question_lists WHERE id = ?", (list_id,)).fetchone()
    if not row:
        conn.close()
        return False
    if row["list_type"] == "system" and row["name"] == "全部":
        conn.close()
        return False
    cur = conn.execute(
        "UPDATE question_list_members SET is_removed = 1 WHERE list_id = ? AND question_id = ? AND is_removed = 0",
        (list_id, question_id)
    )
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def restore_question_to_list(question_id, list_id):
    conn = get_connection()
    cur = conn.execute(
        "UPDATE question_list_members SET is_removed = 0 WHERE list_id = ? AND question_id = ? AND is_removed = 1",
        (list_id, question_id)
    )
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def get_question_list_ids(question_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT list_id FROM question_list_members WHERE question_id = ? AND is_removed = 0",
        (question_id,)
    ).fetchall()
    conn.close()
    return [r["list_id"] for r in rows]


def get_list_questions(list_id, keywords=None, categories=None, difficulties=None, types=None, error_type=None, page=1, page_size=None, source_type=None):
    conn = get_connection()
    where_clauses = []
    params = []
    if keywords:
        for kw in keywords:
            kw_s = kw.strip()
            if not kw_s:
                continue
            kw_pat = "%%%s%%" % kw_s
            search_conds = [
                "q.content LIKE ?",
                "q.category_level1 LIKE ?",
                "q.category_level2 LIKE ?",
                "q.knowledge_points LIKE ?",
                "q.steps_structure LIKE ?",
                "q.difficulty_level LIKE ?",
                "e.mistake_type LIKE ?",
                "e.mistake_detail LIKE ?",
                "q.source_type LIKE ?",
                "q.source_meta LIKE ?"
            ]
            where_clauses.append("(" + " OR ".join(search_conds) + ")")
            params.extend([kw_pat] * 10)
    if categories:
        placeholders = ",".join("?" for _ in categories)
        where_clauses.append("q.category_level1 IN (" + placeholders + ")")
        params.extend(categories)
    if difficulties:
        placeholders = ",".join("?" for _ in difficulties)
        where_clauses.append("q.difficulty_level IN (" + placeholders + ")")
        params.extend(difficulties)
    if types:
        placeholders = ",".join("?" for _ in types)
        where_clauses.append("q.question_type IN (" + placeholders + ")")
        params.extend(types)
    if source_type:
        where_clauses.append("q.source_type = ?")
        params.append(source_type)
    if error_type:
        if error_type == "none":
            where_clauses.append("NOT EXISTS (SELECT 1 FROM step_errors e2 WHERE e2.question_id = q.id)")
        elif error_type == "errors":
            where_clauses.append("EXISTS (SELECT 1 FROM step_errors e2 WHERE e2.question_id = q.id)")
        else:
            where_clauses.append("EXISTS (SELECT 1 FROM step_errors e2 WHERE e2.question_id = q.id AND e2.mistake_type = ?)")
            params.append(error_type)
    where_clauses.append("m.list_id = ?")
    params.append(list_id)
    where_clauses.append("m.is_removed = 0")
    where_sql = " AND ".join(where_clauses)
    from_clause = "FROM questions q INNER JOIN question_list_members m ON m.question_id = q.id LEFT JOIN step_errors e ON e.question_id = q.id"
    count_sql = "SELECT COUNT(DISTINCT q.id) " + from_clause + " WHERE " + where_sql
    total = conn.execute(count_sql, params).fetchone()[0]
    limit_sql = ""
    if page_size and page_size != "all":
        offset = (page - 1) * int(page_size)
        limit_sql = " LIMIT " + str(int(page_size)) + " OFFSET " + str(offset)
    rows = conn.execute(
        "SELECT DISTINCT q.id, q.content, q.category_level1, q.category_level2, "
        "q.difficulty_level, q.difficulty_score, q.difficulty_dimensions, "
        "q.knowledge_points, q.question_type, q.source_type, q.source_meta, "
        "q.steps_structure, q.created_at, q.last_viewed_at, q.last_edited_at, q.last_exam_at "
        + from_clause + " WHERE " + where_sql + " ORDER BY m.id DESC" + limit_sql,
        params
    ).fetchall()
    conn.close()
    all_rows = []
    for r in rows:
        d = dict(r)
        for key in ("difficulty_dimensions", "knowledge_points", "steps_structure", "source_meta"):
            val = d.get(key)
            if val:
                try:
                    d[key] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    pass
        all_rows.append(d)
    if page_size and page_size != "all":
        return {"data": all_rows, "total": total, "page": page, "page_size": int(page_size)}
    return {"data": all_rows, "total": total}


def get_wrong_questions(keywords=None, categories=None, difficulties=None, types=None, error_type=None, page=1, page_size=None, source_type=None):
    conn = get_connection()
    where_clauses = ["EXISTS (SELECT 1 FROM step_errors e2 WHERE e2.question_id = q.id)"]
    params = []
    if keywords:
        for kw in keywords:
            kw_s = kw.strip()
            if not kw_s:
                continue
            kw_pat = "%%%s%%" % kw_s
            search_conds = [
                "q.content LIKE ?",
                "q.category_level1 LIKE ?",
                "q.category_level2 LIKE ?",
                "q.knowledge_points LIKE ?",
                "q.steps_structure LIKE ?",
                "q.difficulty_level LIKE ?",
                "e.mistake_type LIKE ?",
                "e.mistake_detail LIKE ?",
                "q.source_type LIKE ?",
                "q.source_meta LIKE ?"
            ]
            where_clauses.append("(" + " OR ".join(search_conds) + ")")
            params.extend([kw_pat] * 10)
    if categories:
        placeholders = ",".join("?" for _ in categories)
        where_clauses.append("q.category_level1 IN (" + placeholders + ")")
        params.extend(categories)
    if difficulties:
        placeholders = ",".join("?" for _ in difficulties)
        where_clauses.append("q.difficulty_level IN (" + placeholders + ")")
        params.extend(difficulties)
    if types:
        placeholders = ",".join("?" for _ in types)
        where_clauses.append("q.question_type IN (" + placeholders + ")")
        params.extend(types)
    if source_type:
        where_clauses.append("q.source_type = ?")
        params.append(source_type)
    if error_type and error_type != "errors":
        if error_type != "none":
            where_clauses.append("EXISTS (SELECT 1 FROM step_errors e2 WHERE e2.question_id = q.id AND e2.mistake_type = ?)")
            params.append(error_type)
    where_sql = " AND ".join(where_clauses)
    from_clause = "FROM questions q LEFT JOIN step_errors e ON e.question_id = q.id"
    count_sql = "SELECT COUNT(DISTINCT q.id) " + from_clause + " WHERE " + where_sql
    total = conn.execute(count_sql, params).fetchone()[0]
    limit_sql = ""
    if page_size and page_size != "all":
        offset = (page - 1) * int(page_size)
        limit_sql = " LIMIT " + str(int(page_size)) + " OFFSET " + str(offset)
    rows = conn.execute(
        "SELECT DISTINCT q.id, q.content, q.category_level1, q.category_level2, "
        "q.difficulty_level, q.difficulty_score, q.difficulty_dimensions, "
        "q.knowledge_points, q.question_type, q.source_type, q.source_meta, "
        "q.steps_structure, q.created_at, q.last_viewed_at, q.last_edited_at, q.last_exam_at "
        + from_clause + " WHERE " + where_sql + " ORDER BY q.created_at DESC" + limit_sql,
        params
    ).fetchall()
    conn.close()
    all_rows = []
    for r in rows:
        d = dict(r)
        for key in ("difficulty_dimensions", "knowledge_points", "steps_structure", "source_meta"):
            val = d.get(key)
            if val:
                try:
                    d[key] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    pass
        all_rows.append(d)
    if page_size and page_size != "all":
        return {"data": all_rows, "total": total, "page": page, "page_size": int(page_size)}
    return {"data": all_rows, "total": total}


def update_question_source_type(question_id, source_type):
    """兼容旧接口：只更新一级来源标签，保留已有二级标签"""
    return update_question_source(question_id, source_type, None)


def update_question_source(question_id, source_type, source_meta=None):
    """更新一级来源标签和二级标签（source_meta 为 None 时保留原有二级标签）"""
    if source_type not in _VALID_SOURCE_TYPES:
        return False
    conn = get_connection()
    row = conn.execute(
        "SELECT source_type, source_meta FROM questions WHERE id = ?",
        (question_id,)
    ).fetchone()
    if not row:
        conn.close()
        return False
    if source_meta is None:
        try:
            source_meta = json.loads(row["source_meta"]) if row["source_meta"] else {}
        except (json.JSONDecodeError, TypeError):
            source_meta = {}
    source_meta_json = json.dumps(_sanitize_source_meta(source_type, source_meta), ensure_ascii=False)
    cur = conn.execute(
        "UPDATE questions SET source_type = ?, source_meta = ? WHERE id = ?",
        (source_type, source_meta_json, question_id)
    )
    ok = cur.rowcount > 0
    if ok:
        _sync_question_to_source_list(conn, question_id, source_type)
    conn.commit()
    conn.close()
    return ok
