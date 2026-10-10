"""Owner-published shared definitions, with private learning-state projections.

catalog.db is the authoritative public library. Only question content, answers,
pattern definitions and board layout are published; personal attempts, teaching,
jobs, settings and credentials never enter it. Projections let the existing
SQLite learning engine keep all learner state in that learner's workspace.
"""

import hashlib
import json
from pathlib import Path
import sqlite3
import threading

from backend.data_paths import workspace, data_path
from backend.identity import identity_context, require_catalog_editor

_LOCK = threading.RLock()
_PERSONAL_QUESTION_FIELDS = {"user_id", "catalog_id", "catalog_active", "last_viewed_at", "last_edited_at", "last_exam_at"}


def _public_question(row):
    """Keep unapproved pool material in the owner workspace at publication."""
    row = dict(row)
    try:
        answer = json.loads(row.get("answer_json") or "{}")
    except (TypeError, ValueError):
        return row
    if not isinstance(answer, dict):
        return row
    if answer.get("source_publication_pending"):
        return None
    origins = answer.get("provenance")
    if isinstance(origins, list) and any(isinstance(o, dict) and "publication_allowed" in o for o in origins):
        allowed = [o for o in origins if isinstance(o, dict) and o.get("publication_allowed") is True]
        answer["provenance"] = [
            {k: v for k, v in o.items() if o.get("publication_allowed") is not False or k not in ("original_answer", "original_solution")}
            for o in origins if isinstance(o, dict)
        ]
        answer.pop("source_answer", None)
        answer.pop("source_solution", None)
        if allowed:
            answer["source_answer"] = allowed[0].get("original_answer", "")
            answer["source_solution"] = allowed[0].get("original_solution", "")
        row["answer_json"] = json.dumps(answer, ensure_ascii=False)
    return row


def publish_catalog(owner_directory, catalog_path):
    require_catalog_editor()
    from backend.database import get_connection
    from backend.patterns import _get_conn
    with _LOCK, identity_context({"id": "studyadmin", "username": "studyadmin", "role": "owner"}), workspace(owner_directory):
        with get_connection() as questions, _get_conn() as mastery:
            patterns = [dict(r) for r in mastery.execute("SELECT * FROM patterns WHERE catalog_id IS NULL ORDER BY id")]
            links = [dict(r) for r in mastery.execute("SELECT pattern_id,question_id,role FROM pattern_questions ORDER BY pattern_id,role")]
            pattern_ids = {p["id"] for p in patterns}
            links = [r for r in links if r["pattern_id"] in pattern_ids]
            shared_ids = {r["question_id"] for r in links}
            shared_ids.update(r[0] for r in questions.execute("SELECT id FROM questions WHERE source_type='精选母题' AND catalog_id IS NULL"))
            rows = [published for r in questions.execute("SELECT * FROM questions ORDER BY id")
                    if r["id"] in shared_ids for published in [_public_question(r)] if published is not None]
            available = {r["id"] for r in rows}
            links = [r for r in links if r["question_id"] in available]
            payload = {
                "questions": [{k: v for k, v in r.items() if k not in _PERSONAL_QUESTION_FIELDS} for r in rows],
                "patterns": [{k: v for k, v in p.items() if k != "catalog_id"} for p in patterns],
                "links": links,
                "boards": [dict(r) for r in mastery.execute("SELECT * FROM boards ORDER BY id")],
                "nodes": [dict(r) for r in mastery.execute("SELECT * FROM board_nodes ORDER BY id") if r["question_id"] in available or r["pattern_id"] in pattern_ids],
                "edges": [dict(r) for r in mastery.execute("SELECT * FROM board_edges ORDER BY id") if r["from_question_id"] in available and r["to_question_id"] in available],
                "levels": [dict(r) for r in mastery.execute("SELECT * FROM board_levels ORDER BY id")],
            }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        revision = hashlib.sha256(encoded.encode()).hexdigest()
        path = Path(catalog_path)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with sqlite3.connect(str(path)) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS shared_catalog (id INTEGER PRIMARY KEY CHECK(id=1), revision TEXT NOT NULL, definitions_json TEXT NOT NULL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)")
            row = conn.execute("SELECT revision FROM shared_catalog WHERE id=1").fetchone()
            if row and row[0] == revision:
                return revision
            conn.execute("INSERT INTO shared_catalog (id,revision,definitions_json) VALUES (1,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,definitions_json=excluded.definitions_json,updated_at=CURRENT_TIMESTAMP", (revision, encoded))
        path.chmod(0o600)
        return revision


def _upsert(conn, table, row, conflict="id"):
    columns = list(row)
    names = ",".join(columns)
    updates = ",".join(f"{key}=excluded.{key}" for key in columns if key != conflict)
    conn.execute(f"INSERT INTO {table} ({names}) VALUES ({','.join('?' for _ in columns)}) ON CONFLICT({conflict}) DO UPDATE SET {updates}", list(row.values()))


def sync_catalog(catalog_path):
    """Refresh definitions atomically without resetting personal progress.

    Negative projection ids cannot collide with new personal AUTO_INCREMENT ids.
    If the learner already saved identical content, reuse that question id so
    existing mistakes and attempts remain attached. catalog_id is always stable.
    Withdrawn questions are retained for historical learning records and removed
    from the shared mother list; withdrawn patterns leave the active curriculum.
    """
    path = Path(catalog_path)
    if not path.is_file():
        return False
    from backend.database import get_connection, _index_question_steps, _sync_question_to_source_list
    from backend.patterns import MASTERY_DB
    with _LOCK:
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as source:
            item = source.execute("SELECT revision,definitions_json FROM shared_catalog WHERE id=1").fetchone()
        if item is None:
            return False
        revision, encoded = item
        payload = json.loads(encoded)
        conn = get_connection()
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS catalog_projection (id INTEGER PRIMARY KEY CHECK(id=1), revision TEXT NOT NULL)")
            old = conn.execute("SELECT revision FROM catalog_projection WHERE id=1").fetchone()
            if old and old[0] == revision:
                return False
            conn.commit()
            conn.execute("ATTACH DATABASE ? AS learning", (data_path("mastery.db", MASTERY_DB),))
            conn.execute("BEGIN IMMEDIATE")
            qmap = {}
            columns = {r["name"] for r in conn.execute("PRAGMA table_info(questions)")}
            for question in payload["questions"]:
                canonical = question["id"]
                existing = conn.execute("SELECT id FROM questions WHERE catalog_id=?", (canonical,)).fetchone()
                if not existing:
                    existing = conn.execute("SELECT id FROM questions WHERE content=?", (question["content"],)).fetchone()
                local_id = existing["id"] if existing else -canonical
                # A renamed catalog entry may collide with a personal duplicate.
                duplicate = conn.execute("SELECT id FROM questions WHERE content=? AND id<>?", (question["content"], local_id)).fetchone()
                if duplicate:
                    conn.execute("UPDATE questions SET content=content || ? WHERE id=?", ("\n（个人副本 #" + str(duplicate["id"]) + "）", duplicate["id"]))
                row = {k: v for k, v in question.items() if k in columns and k not in _PERSONAL_QUESTION_FIELDS}
                row.update(id=local_id, catalog_id=canonical, catalog_active=1, user_id=None)
                _upsert(conn, "questions", row)
                qmap[canonical] = local_id
                _index_question_steps(conn, local_id, answer_json_text=question["answer_json"])
                all_list = conn.execute("SELECT id FROM question_lists WHERE name='全部' AND list_type='system'").fetchone()
                if all_list:
                    conn.execute("INSERT OR IGNORE INTO question_list_members (list_id,question_id) VALUES (?,?)", (all_list["id"], local_id))
                _sync_question_to_source_list(conn, local_id, question.get("source_type"))
            active = set(qmap.values())
            for r in conn.execute("SELECT id FROM questions WHERE catalog_id IS NOT NULL").fetchall():
                if r["id"] not in active:
                    conn.execute("UPDATE questions SET catalog_active=0 WHERE id=?", (r["id"],))
                    conn.execute("DELETE FROM question_list_members WHERE question_id=? AND list_id IN (SELECT id FROM question_lists WHERE list_type='system' AND name='母题')", (r["id"],))
            pmap = {}
            active_patterns = {-p["id"] for p in payload["patterns"]}
            for r in conn.execute("SELECT id FROM learning.patterns WHERE catalog_id IS NOT NULL").fetchall():
                if r["id"] not in active_patterns:
                    conn.execute("DELETE FROM learning.pattern_questions WHERE pattern_id=?", (r["id"],))
                    conn.execute("DELETE FROM learning.patterns WHERE id=?", (r["id"],))
            for pattern in payload["patterns"]:
                canonical = pattern["id"]
                local_id = -canonical
                row = dict(pattern, id=local_id, catalog_id=canonical)
                _upsert(conn, "learning.patterns", row)
                pmap[canonical] = local_id
                conn.execute("INSERT OR IGNORE INTO learning.pattern_mastery (pattern_id) VALUES (?)", (local_id,))
            # Personal generated variants stay attached to their shared pattern.
            conn.execute("DELETE FROM learning.pattern_questions WHERE pattern_id<0 AND (role='mother' OR question_id IN (SELECT id FROM main.questions WHERE catalog_id IS NOT NULL))")
            for link in payload["links"]:
                local_pid = pmap[link["pattern_id"]]
                local_qid = qmap[link["question_id"]]
                conn.execute("INSERT INTO learning.pattern_questions (pattern_id,question_id,role) VALUES (?,?,?) ON CONFLICT(pattern_id,role) DO UPDATE SET question_id=excluded.question_id", (local_pid, local_qid, link["role"]))
            # Boards are curriculum definitions, never a learner's practice data.
            for table in ("board_nodes", "board_edges", "board_levels", "boards"):
                conn.execute(f"DELETE FROM learning.{table}")
            for board in payload["boards"]:
                _upsert(conn, "learning.boards", board)
            for level in payload["levels"]:
                _upsert(conn, "learning.board_levels", level)
            for node in payload["nodes"]:
                row = dict(node)
                row["question_id"] = qmap.get(row["question_id"])
                row["pattern_id"] = pmap.get(row["pattern_id"])
                _upsert(conn, "learning.board_nodes", row)
            for edge in payload["edges"]:
                row = dict(edge, from_question_id=qmap[edge["from_question_id"]], to_question_id=qmap[edge["to_question_id"]])
                _upsert(conn, "learning.board_edges", row)
            categories = {p["category"] for p in payload["patterns"]}
            categories.update(r[0] for r in conn.execute("SELECT category FROM learning.category_mastery"))
            for category in categories:
                total = conn.execute("SELECT COUNT(*) FROM learning.patterns WHERE category=?", (category,)).fetchone()[0]
                mastered = conn.execute("SELECT COUNT(*) FROM learning.patterns p JOIN learning.pattern_mastery m ON p.id=m.pattern_id WHERE p.category=? AND m.state='third_pass'", (category,)).fetchone()[0]
                conn.execute("INSERT INTO learning.category_mastery (category,total_patterns,mastered_patterns,percent) VALUES (?,?,?,?) ON CONFLICT(category) DO UPDATE SET total_patterns=excluded.total_patterns,mastered_patterns=excluded.mastered_patterns,percent=excluded.percent", (category, total, mastered, round(mastered / total * 100, 1) if total else 0))
            conn.execute("INSERT INTO catalog_projection (id,revision) VALUES (1,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision", (revision,))
            conn.commit()
            return True
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
