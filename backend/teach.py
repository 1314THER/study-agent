import json
import logging
import os
import re
import threading
import time
from copy import deepcopy
from contextlib import contextmanager
from contextvars import ContextVar
import backend.settings as runtime_settings
from backend.data_paths import workspace_directory
from backend.solver import (
    TEACHER_CONFIG,
    call_deepseek,
    step_final_check,
    step_solver_only,
    step_verify_all,
)
from backend.database import find_question, save_question as db_save_question
from backend.geometry import prepare_geometry, release_hint

logger = logging.getLogger(__name__)
_TURN_SNAPSHOT = ContextVar("teaching_turn_snapshot", default=None)


class TeachingConflict(ValueError):
    """A stale or concurrent teaching turn must not advance the session."""


PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")

def _rp(n):
    with open(os.path.join(PROMPTS_DIR, f"{n}.md"), encoding="utf-8") as f:
        return f.read().strip()

TC = _rp("teach_check")
TF = _rp("teach_format")

def _ej(t):
    t = t.strip()
    m = re.search(r"```(\s*json)?\s*\n?(.*?)\n?```", t, re.DOTALL)
    if m:
        t = m.group(2) or m.group(1) or ""
        t = t.strip()
    for c, cl in [("[", "]"), ("{", "}")]:
        f = t.find(c)
        if f >= 0:
            t = t[f:]
            l = t.rfind(cl)
            if l >= 0:
                t = t[:l+1]
            break
    return t.strip()

def _bs(crr):
    r, ht = [], False
    fa_list = []
    for cr in crr:
        ct = cr.get("chunk_type", "整体")
        cn = cr.get("category", {}).get("level1", "")
        fa = cr.get("final_answer", "")
        for s in cr.get("steps", []):
            st = {"chunk_id": cr.get("chunk_id", 1)}
            st["chunk_type"] = ct
            st["category"] = cn
            st["step_number"] = s.get("step_number", 0)
            st["title"] = s.get("title", "")
            st["step_prompt"] = s.get("step_prompt", "")
            st["step_answer"] = s.get("step_answer", "")
            st["standard_writing"] = s.get("standard_writing", "")
            st["detailed_writing"] = s.get("detailed_writing", "")
            st["knowledge_point"] = s.get("knowledge_point", "")
            st["step_level1"] = s.get("step_level1", "")
            st["step_difficulty"] = deepcopy(s.get("step_difficulty"))
            st["geometry_key"] = f"{cr.get('chunk_id', 1)}-{s.get('step_number', 0)}"
            if st["step_prompt"]:
                ht = True
            r.append(st)
        if fa:
            fa_list.append({"chunk_id": cr.get("chunk_id", 1), "chunk_type": ct,
                      "category": cn, "step_number": 999, "title": "\u6700\u7ec8\u7b54\u6848",
                      "step_prompt": "\u8bf7\u5199\u51fa\u8fd9\u9053\u9898\u7684\u6700\u7ec8\u7b54\u6848",
                      "step_answer": fa, "standard_writing": fa,
                      "detailed_writing": "", "knowledge_point": ""})
    r.extend(fa_list)
    return r, ht

def _fs(steps, teacher=None):
    tg = [s for s in steps if s["title"] != "\u6700\u7ec8\u7b54\u6848"]
    if not tg:
        return steps
    inp = [{
        "chunk_id": s.get("chunk_id"),
        "step_number": s.get("step_number"),
        "title": s.get("title", ""),
        "knowledge_point": s.get("knowledge_point", ""),
        "standard_writing": s.get("standard_writing", ""),
    } for s in tg]
    cfg = runtime_settings.get_teacher_config(teacher)
    try:
        c, _ = call_deepseek(TF, json.dumps(inp, ensure_ascii=False, indent=2),
                             temperature=0.3,
                             model=cfg.get("verifier", {}).get("model", "deepseek-flash"),
                             reasoning_effort=cfg.get("verifier", {}).get("reasoning_effort"))
        rl = json.loads(_ej(c))
    except Exception as e:
        logger.warning("_fs AI call or parse failed: %s", e)
        rl = None
    ns = []
    idx = 0
    for s in steps:
        ss = dict(s)
        if ss["title"] == "\u6700\u7ec8\u7b54\u6848":
            ss["step_prompt"] = "\u8bf7\u5199\u51fa\u8fd9\u9053\u9898\u7684\u6700\u7ec8\u7b54\u6848"
            ss["step_answer"] = ss["standard_writing"]
        else:
            if rl and idx < len(rl):
                m = rl[idx]
                ss["step_prompt"] = m.get("step_prompt", ss.get("step_prompt", ""))
                ss["step_answer"] = m.get("step_answer", ss.get("step_answer", ""))
            # Fallback: use title as prompt
            if not ss.get("step_prompt"):
                label = f"\u7b2c {ss.get('step_number', '')} \u6b65" if ss.get("step_number") else "\u8fd9\u4e00\u6b65"
                ss["step_prompt"] = f"\u8bf7\u5b8c\u6210{label}\uff1a{ss.get('title', '')}\u3002\u5199\u51fa\u8fd9\u4e00\u6b65\u7684\u5177\u4f53\u8fc7\u7a0b\u548c\u6838\u5fc3\u7ed3\u679c\u3002"
            if not ss.get("step_answer"):
                ss["step_answer"] = ss.get("standard_writing", "")
            idx += 1
        ns.append(ss)
    return ns


def _set_category_from_chunks(aj):
    """入库前从第一个块补一级板块，避免新题按板块搜索不到。"""
    if aj.get("category"):
        return
    cr = aj.get("chunk_results") or []
    if not cr:
        return
    first_cat = cr[0].get("category")
    if isinstance(first_cat, dict):
        aj["category"] = {"level1": first_cat.get("level1"), "level2": first_cat.get("level2")}
    elif first_cat:
        aj["category"] = {"level1": first_cat, "level2": ""}


def _mg(cr, ts):
    si = 0
    for cr_ in cr:
        for s in cr_.get("steps", []):
            if si < len(ts):
                s["step_prompt"] = ts[si].get("step_prompt", "")
                s["step_answer"] = ts[si].get("step_answer", "")
                si += 1
    return cr

def teach_find_or_format(question, teacher=None):
    r = find_question(question)
    if not r or not r.get("chunk_results"):
        return {"found": False}
    old_geometry = deepcopy(r.get("geometry"))
    if not r.get("formatter_fallback"):
        prepare_geometry(question, r, teacher)
    cr = r["chunk_results"]
    steps, ht = _bs(cr)
    if not ht:
        steps = _fs(steps, teacher)
        cr = _mg(cr, steps)
        r["chunk_results"] = cr
        try:
            db_save_question(question, r)
        except Exception:
            pass
    elif r.get("geometry") != old_geometry:
        db_save_question(question, r)
    fc = cr[0] if cr else {}
    cn = fc.get("category", {}).get("level1", "")
    return {"found": True, "question": question, "category": cn,
            "steps": steps, "total_steps": len(steps),
            "chunk_results": cr,
            "overall_difficulty": r.get("overall_difficulty"),
            "geometry": r.get("geometry"), "asset_refs": r.get("asset_refs", []),
            "from_db": True}

def teach_start(question, teacher=None, asset_refs=None):
    assets = {"asset_refs": asset_refs} if asset_refs else {}
    sr = step_solver_only(question, teacher=teacher, **assets)
    if sr.get("error"):
        return sr
    vr = step_verify_all(sr["content"], question, sr.get("category"),
                         teacher=teacher)
    if vr.get("error"):
        return vr
    final = step_final_check(
        question, vr["chunk_results"], [], {},
        teacher=teacher, solver_content=sr["content"], verifier_category=sr.get("category"), **assets,
    )
    cr = final.get("chunk_results") or vr["chunk_results"]
    steps, _ = _bs(cr)
    steps = _fs(steps, teacher)
    cr = _mg(cr, steps)
    aj = dict(final)
    aj.pop("error", None)
    aj.pop("formatter_note", None)
    aj["chunk_results"] = cr
    aj.setdefault("knowledge_points", [])
    aj.setdefault("final_answer", "")
    _set_category_from_chunks(aj)
    for c in cr:
        if c.get("final_answer"):
            aj["final_answer"] += (" | " if aj["final_answer"] else "") + c["final_answer"]
        for kp in c.get("knowledge_points", []):
            if kp not in aj["knowledge_points"]:
                aj["knowledge_points"].append(kp)
    try:
        db_save_question(question, aj)
    except Exception:
        pass
    steps, _ = _bs(cr)
    return {"question": question, "category": sr.get("category"),
            "steps": steps, "total_steps": len(steps),
            "chunk_results": cr,
            "overall_difficulty": final.get("overall_difficulty") or vr.get("overall_difficulty"),
            "geometry": final.get("geometry"), "asset_refs": final.get("asset_refs", []),
            "formatter_fallback": final.get("formatter_fallback", False),
            "from_db": False}

def teach_check(question, step_prompt, step_answer, user_answer, teacher=None):
    up = f"原题：{question}\n当前步骤引导问题：{step_prompt}\n参考答案：{step_answer}\n学生回答：{user_answer}"
    cfg = runtime_settings.get_teacher_config(teacher)
    c, _ = call_deepseek(TC, up, temperature=0.2,
                         model=cfg.get("verifier", {}).get("model", "deepseek-flash"),
                         reasoning_effort=cfg.get("verifier", {}).get("reasoning_effort"))
    try:
        return json.loads(_ej(c))
    except Exception:
        return {"is_correct": False, "is_partial": False,
                "feedback": "抱歉，无法判断", "error_type": "其他", "error_detail": ""}

# ====== 对话式教学会话管理 ======

import uuid as _uuid
from typing import Optional, List, Dict, Any

# 读取新对话式 prompt

class TeachSessionManager:
    """SQLite-backed teaching sessions, cached only within their workspace."""

    def __init__(self):
        self._sessions: Dict[str, dict] = {}
        self._session_owners: Dict[str, Optional[str]] = {}
        self._lock = threading.RLock()
        self._turn_locks = {}

    def _persist(self, session):
        from backend.storage.database import current_repository
        repo = current_repository()
        if repo is not None:
            repo.persist_teaching(session)
            return
        from backend.jobs import storage_connection
        now = time.time()
        session.setdefault("revision", 0)
        session.setdefault("created_at", now)
        with storage_connection() as conn:
            conn.execute("INSERT INTO teaching_sessions VALUES (?,?,?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET "
                         "state_json=excluded.state_json,revision=excluded.revision,pending_job=excluded.pending_job,updated_at=excluded.updated_at",
                         (session["session_id"], json.dumps(session, ensure_ascii=False), session["revision"],
                          session.get("pending_job"), session["created_at"], now))

    def _store(self, session):
        self._persist(session)
        from backend.storage.database import current_repository
        if current_repository() is not None:
            return
        self._sessions[session["session_id"]] = session
        self._session_owners[session["session_id"]] = workspace_directory()

    def reserve(self, session_id, job_id, expected_revision=None):
        with self._lock:
            session = self.get(session_id)
            if not session:
                raise TeachingConflict("教学会话不存在，请重新开始。")
            if expected_revision is not None and expected_revision != session.get("revision", 0):
                raise TeachingConflict("教学步骤已更新，请刷新后再回答。")
            if session.get("pending_job") and session["pending_job"] != job_id:
                raise TeachingConflict("当前回答仍在处理中，请等待老师反馈。")
            session["pending_job"] = job_id
            self._persist(session)

    def release(self, session_id, job_id):
        with self._lock:
            session = self.get(session_id)
            if session and session.get("pending_job") == job_id:
                session["pending_job"] = None
                self._persist(session)

    @contextmanager
    def transaction(self, session_id, expected_revision=None):
        from backend.jobs import current_job_id
        key = (workspace_directory(), session_id)
        with self._lock:
            turn_lock = self._turn_locks.setdefault(key, threading.RLock())
        with turn_lock:
            with self._lock:
                original = self.get(session_id)
                if not original:
                    raise TeachingConflict("教学会话不存在，请重新开始。")
                if expected_revision is not None and expected_revision != original.get("revision", 0):
                    raise TeachingConflict("教学步骤已更新，请刷新后再回答。")
                if original.get("pending_job") and original["pending_job"] != current_job_id():
                    raise TeachingConflict("当前回答仍在处理中，请等待老师反馈。")
                snapshot = deepcopy(original)
            token = _TURN_SNAPSHOT.set((self, session_id, snapshot))
            try:
                yield snapshot
                snapshot["revision"] = original.get("revision", 0) + 1
                if snapshot.get("pending_job") == current_job_id():
                    snapshot["pending_job"] = None
                with self._lock:
                    self._store(snapshot)
            finally:
                _TURN_SNAPSHOT.reset(token)

    def create(self, question: str, teacher: str = None, asset_refs: list = None) -> dict:
        """创建新教学会话：解题 → 取步骤 → 存入 session"""
        # 先尝试从题库找
        from backend.database import find_question
        r = find_question(question)
        vr = None
        if r and r.get("chunk_results"):
            if not r.get("formatter_fallback"):
                prepare_geometry(question, r, teacher, asset_refs or r.get("asset_refs"))
            cr = r["chunk_results"]
        else:
            # 走完整解题流水线
            from backend.solver import step_final_check, step_solver_only, step_verify_all
            assets = {"asset_refs": asset_refs} if asset_refs else {}
            sr = step_solver_only(question, teacher=teacher, **assets)
            if sr.get("error"):
                return {"error": sr.get("error"), "detail": sr.get("detail", "")}
            vr = step_verify_all(sr["content"], question, sr.get("category"), teacher=teacher)
            if vr.get("error"):
                return {"error": vr.get("error"), "detail": vr.get("detail", "")}
            final = step_final_check(
                question, vr["chunk_results"], [], {},
                teacher=teacher, solver_content=sr["content"], verifier_category=sr.get("category"), **assets,
            )
            cr = final.get("chunk_results") or vr["chunk_results"]
            # 入库
            aj = dict(final)
            aj.pop("error", None)
            aj.pop("formatter_note", None)
            aj.setdefault("knowledge_points", [])
            aj.setdefault("final_answer", "")
            aj["chunk_results"] = cr
            _set_category_from_chunks(aj)
            for c in cr:
                if c.get("final_answer"):
                    aj["final_answer"] += (" | " if aj["final_answer"] else "") + c["final_answer"]
                for kp in c.get("knowledge_points", []):
                    if kp not in aj["knowledge_points"]:
                        aj["knowledge_points"].append(kp)
            try:
                db_save_question(question, aj)
            except Exception:
                pass

        # 从 chunk_results 构建步骤列表（不含最终答案步骤）
        steps = []
        final_answers = []
        for cr_ in cr:
            ct = cr_.get("chunk_type", "整体")
            cn = cr_.get("category", {}).get("level1", "")
            fa = cr_.get("final_answer", "")
            for s in cr_.get("steps", []):
                steps.append({
                    "chunk_id": cr_.get("chunk_id", 1),
                    "chunk_type": ct,
                    "category": cn,
                    "step_number": s.get("step_number", 0),
                    "title": s.get("title", ""),
                    "standard_writing": s.get("standard_writing", ""),
                    "detailed_writing": s.get("detailed_writing", ""),
                    "knowledge_point": s.get("knowledge_point", ""),
                    "step_answer": s.get("step_answer", s.get("standard_writing", "")),
                    "step_prompt": s.get("step_prompt", ""),
                    "step_level1": s.get("step_level1", ""),
                    "step_difficulty": deepcopy(s.get("step_difficulty")),
                    "geometry_key": f"{cr_.get('chunk_id', 1)}-{s.get('step_number', 0)}",
                })
            if fa:
                final_answers.append({
                    "chunk_id": cr_.get("chunk_id", 1),
                    "chunk_type": ct,
                    "category": cn,
                    "step_number": 999,
                    "title": "最终答案",
                    "standard_writing": fa,
                    "detailed_writing": "",
                    "knowledge_point": "",
                    "step_answer": fa,
                    "step_prompt": "请写出这道题的最终答案",
                })
        # 最终答案统一放在所有步骤最后
        # steps.extend(final_answers)
        # 先入库基本数据（无论是否有 prompts）
        save_aj = dict(r) if r else {}
        save_aj["chunk_results"] = cr
        _set_category_from_chunks(save_aj)
        if 'aj' in dir():
            for key in ("overall_difficulty", "knowledge_points", "final_answer", "formatter_fallback", "geometry", "asset_refs"):
                if aj.get(key):
                    save_aj[key] = aj[key]
        save_aj.pop("error", None)
        save_aj.pop("formatter_note", None)
        try:
            saved_qid_first = db_save_question(question, save_aj)
        except Exception as e:
            saved_qid_first = None
            logger.warning("first save_question failed: %s", e)

        # 预生成每步的引导语和期望回答（仅当缺失时）
        has_all_prompts = all(s.get("step_prompt") for s in steps if s.get("title") != "最终答案")
        if not has_all_prompts:
            try:
                steps = _fs(steps, teacher)
                # 合并回 chunk_results
                si = 0
                for cr_ in cr:
                    for s in cr_.get("steps", []):
                        if si < len(steps):
                            s["step_prompt"] = steps[si].get("step_prompt", "")
                            s["step_answer"] = steps[si].get("step_answer", "")
                            si += 1
                # 更新入库（带 prompts）
                save_aj["chunk_results"] = cr
                saved_qid = db_save_question(question, save_aj)
            except Exception as e:
                saved_qid = None
                logger.warning("_fs or second save_question failed: %s", e)
        session_id = str(_uuid.uuid4())
        session = {
            "session_id": session_id,
            "question_id": (saved_qid if 'saved_qid' in dir() and saved_qid is not None else saved_qid_first if 'saved_qid_first' in dir() else None),
            "question": question,
            "teacher": teacher or "liangliang",
            "steps": steps,
            "total_steps": len(steps),
            "current_step": 0,
            "step_introduced": False,   # 当前步骤是否已给过引导
            "step_viewed_answer": False,  # 当前步骤是否已查看完整答案
            "attempt_count": 0,         # 当前步骤的回答次数
            "messages": [],             # [{role, content, step_index, ...}]
            "stats": {"correct": 0, "wrong": 0, "skipped": 0, "viewed_answer": 0},
            "step_results": [],         # 每步的最终记录 [{step_index, correct, attempts, ...}]
            "revision": 0,
            "pending_job": None,
            "chunk_results": cr,
            "geometry": deepcopy(save_aj.get("geometry")),
            "asset_refs": save_aj.get("asset_refs", []),
            "geometry_state": {"released": {}, "completed": []},
            "overall_difficulty": (r.get("overall_difficulty") if (r and r.get("chunk_results")) else (vr.get("overall_difficulty") if vr else None)),
        }
        with self._lock:
            self._store(session)
            owner = workspace_directory()
            from backend.storage.database import current_repository
            if owner is not None and current_repository() is None:
                self._session_owners[session_id] = owner
                # Keep repeated starts on an existing question from growing demo
                # memory indefinitely. The regular owner's sessions stay intact.
                own_sessions = [sid for sid, directory in self._session_owners.items() if directory == owner]
                for old_id in own_sessions[:-20]:
                    self._sessions.pop(old_id, None)
                    del self._session_owners[old_id]
                    from backend.jobs import storage_connection
                    with storage_connection() as conn:
                        conn.execute("DELETE FROM teaching_sessions WHERE session_id=?", (old_id,))
        return {"session_id": session_id, **session}

    def get(self, session_id: str) -> Optional[dict]:
        transaction = _TURN_SNAPSHOT.get()
        if transaction and transaction[:2] == (self, session_id):
            return transaction[2]
        from backend.storage.database import current_repository
        repo = current_repository()
        if repo is not None:
            from fastapi import HTTPException
            try:
                return repo.teaching(session_id)
            except HTTPException as exc:
                if exc.status_code == 404:
                    return None
                raise
        with self._lock:
            if session_id in self._session_owners and self._session_owners[session_id] != workspace_directory():
                return None
            if session_id in self._sessions:
                return self._sessions[session_id]
            from backend.jobs import storage_connection
            with storage_connection() as conn:
                row = conn.execute("SELECT state_json,revision,pending_job FROM teaching_sessions WHERE session_id=?", (session_id,)).fetchone()
            if not row:
                return None
            session = json.loads(row["state_json"])
            session["revision"], session["pending_job"] = row["revision"], row["pending_job"]
            self._sessions[session_id] = session
            self._session_owners[session_id] = workspace_directory()
            return session

    def forget_workspace(self, directory) -> None:
        directory = os.path.abspath(os.fspath(directory))
        with self._lock:
            for session_id, owner in list(self._session_owners.items()):
                if owner == directory:
                    self._sessions.pop(session_id, None)
                    del self._session_owners[session_id]
                    self._turn_locks.pop((directory, session_id), None)

    def add_message(self, session_id: str, role: str, content: str,
                    step_index: int = None, metadata: dict = None):
        sess = self.get(session_id)
        if not sess:
            return
        msg = {"role": role, "content": content, "step_index": step_index or sess["current_step"]}
        if metadata:
            msg.update(metadata)
        sess["messages"].append(msg)
        if _TURN_SNAPSHOT.get() is None:
            self._persist(sess)

    def advance_step(self, session_id: str):
        sess = self.get(session_id)
        if not sess:
            return
        sess["current_step"] += 1
        sess["step_introduced"] = False
        sess["step_viewed_answer"] = False
        sess["attempt_count"] = 0
        if _TURN_SNAPSHOT.get() is None:
            self._persist(sess)

    def is_complete(self, session_id: str) -> bool:
        sess = self.get(session_id)
        return sess and sess["current_step"] >= sess["total_steps"]


# 全局会话管理器实例
_session_manager = TeachSessionManager()


def forget_workspace(directory) -> None:
    """Remove a visitor's teaching history after their sandbox expires."""
    _session_manager.forget_workspace(directory)




def _do_chat_turn(session_id: str, student_message: str = None) -> dict:
    """执行一轮对话：使用预生成的 step_prompt/step_answer 做比对（更轻量）"""
    sess = _session_manager.get(session_id)
    if not sess:
        return {"error": "session_not_found", "detail": "会话不存在"}

    if sess["current_step"] >= sess["total_steps"]:
        return {"action": "complete", "message": "所有步骤已完成！", "session_id": session_id}

    step = sess["steps"][sess["current_step"]]

    # 情况 B：学生发了消息 → 先处理, 再决定是否展示引导（必须放在 step_introduced 之前）
    if student_message:
        _session_manager.add_message(session_id, "student", student_message)
        sess["attempt_count"] += 1

        # 检查跳过命令（不调用 AI）
        if any(kw in student_message for kw in ["跳过", "skip", "跳過", "下一步", "下一题"]):
            release_hint(sess, step, full=True)
            skipped_index = sess["current_step"]
            sess["step_results"].append({
                "step_index": skipped_index,
                "correct": True,
                "attempts": sess["attempt_count"],
                "viewed_answer": bool(sess.get("step_viewed_answer")),
            })
            sess["stats"]["skipped"] = sess["stats"].get("skipped", 0) + 1
            _session_manager.add_message(session_id, "system", f"已跳过步骤 {skipped_index+1}")
            _session_manager.advance_step(session_id)
            if sess["current_step"] < sess["total_steps"]:
                next_step = sess["steps"][sess["current_step"]]
                next_msg = next_step.get("step_prompt") or f"请完成第 {sess['current_step']+1} 步：{next_step.get('title', '')}。请写出这一步的具体过程和核心结果。"
                return {
                    "action": "advance",
                    "message": f"已跳过步骤 {skipped_index+1}。",
                    "next_step_message": next_msg,
                    "current_step": sess["current_step"] + 1,
                    "total_steps": sess["total_steps"],
                    "session_id": session_id,
                }
            else:
                return {
                    "action": "complete",
                    "message": "🎉 所有步骤已完成！",
                    "session_id": session_id,
                    "question_id": sess.get("question_id"),
                    "stats": sess["stats"],
                    "step_results": sess["step_results"],
                }

        # 处理"不会"、"提示"、"答案"等请求（不调 AI）
        if any(kw in student_message for kw in ["提示", "hint", "不会", "不懂", "不知道", "看不懂"]):
            step_answer = step.get("step_answer") or step.get("standard_writing", "")
            hint_len = min(60 + sess["attempt_count"] * 40, len(step_answer))
            partial = step_answer[:hint_len]
            if partial:
                partial = partial[:partial.rfind(" ")] if " " in partial else partial
            if len(step.get("step_answer", "")) > hint_len:
                partial += "..."
            feedback = f"给你一点提示：{partial}\n\n再想想看？"
            drawing_hint = release_hint(sess, step)
            if drawing_hint:
                feedback = drawing_hint["text"]
            _session_manager.add_message(session_id, "teacher", feedback, metadata={"action": "guide"})
            return {"action": "guide", "message": feedback, "current_step": sess["current_step"] + 1, "total_steps": sess["total_steps"], "session_id": session_id}
        
        if any(kw in student_message for kw in ["答案", "answer", "看一下答案"]):
            release_hint(sess, step, full=True)
            if not sess.get("step_viewed_answer"):
                sess["stats"]["viewed_answer"] = sess["stats"].get("viewed_answer", 0) + 1
                sess["step_viewed_answer"] = True
            answer = step.get("step_answer", step.get("standard_writing", ""))
            feedback = f"这一步的关键答案是：{answer}\n\n理解了之后，请继续完成下一步。"
            _session_manager.add_message(session_id, "teacher", feedback, metadata={"action": "show_answer"})
            return {"action": "guide", "message": feedback, "current_step": sess["current_step"] + 1, "total_steps": sess["total_steps"], "session_id": session_id}

    # 情况 A：当前步骤尚未展示引导 → 用 title 做引导（此刻 step_introduced 在 student_message 之后）
    if not sess["step_introduced"]:
        sess["step_introduced"] = True
        msg = step.get("step_prompt") or f"请完成第 {sess['current_step']+1} 步：{step.get('title', '')}。请写出这一步的具体过程和核心结果。"
        _session_manager.add_message(session_id, "teacher", msg, metadata={"action": "guide"})
        return {
            "action": "guide",
            "message": msg,
            "current_step": sess["current_step"] + 1,
            "total_steps": sess["total_steps"],
            "session_id": session_id,
        }

    # 情况 C：有学生消息且未被跳过/提示/答案拦截 → 用 teach_check 做比对
    if student_message:
        up = f"原题：{sess['question']}\n当前步骤引导问题：{step.get('step_prompt', '')}\n参考答案：{step.get('step_answer', step.get('standard_writing', ''))}\n学生回答：{student_message}"
        cfg = runtime_settings.get_teacher_config(sess.get("teacher"))

        try:
            c, _ = call_deepseek(TC, up, temperature=0.2,
                                 model=cfg.get("verifier", {}).get("model", "deepseek-flash"))
            check_result = json.loads(_ej(c))
        except Exception as exc:
            # A failed request is not a wrong student answer. The enclosing
            # snapshot transaction discards messages, attempt count and stats.
            raise RuntimeError("AI 暂时无法判断，请稍后重试。") from exc

        is_correct = check_result.get("is_correct", False)
        is_partial = check_result.get("is_partial", False)
        feedback = check_result.get("feedback", "")
        error_type = check_result.get("error_type")
        error_detail = check_result.get("error_detail")

        if is_correct:
            release_hint(sess, step, full=True)
            # 答对 → 记录并推进到下一步
            sess["step_results"].append({
                "step_index": sess["current_step"],
                "correct": True,
                "attempts": sess["attempt_count"],
                "viewed_answer": bool(sess.get("step_viewed_answer")),
            })
            sess["stats"]["correct"] += 1
            _session_manager.add_message(session_id, "teacher", feedback, metadata={
                "action": "advance", "is_correct": True,
                "error_type": error_type, "error_detail": error_detail})
            _session_manager.advance_step(session_id)

            if sess["current_step"] < sess["total_steps"]:
                next_step = sess["steps"][sess["current_step"]]
                next_msg = next_step.get("step_prompt") or f"好的，让我们进入下一步——{next_step.get('title', '步骤 ' + str(sess['current_step'] + 1))}。请写出这一步的具体过程和核心结果。"
                return {
                    "action": "advance",
                    "message": feedback,
                    "next_step_message": next_msg,
                    "current_step": sess["current_step"] + 1,
                    "total_steps": sess["total_steps"],
                    "session_id": session_id,
                }
            else:
                return {
                    "action": "complete",
                    "message": feedback + "\n\n🎉 你完成了所有步骤！",
                    "session_id": session_id,
                                        "question_id": sess.get("question_id"),
                    "stats": sess["stats"],
                    "step_results": sess["step_results"],
                }
        else:
            # 答错 → 留在当前步骤，返回反馈
            sess["stats"]["wrong"] = sess["stats"].get("wrong", 0) + 1
            _session_manager.add_message(session_id, "teacher", feedback, metadata={
                "action": "guide", "is_correct": is_correct, "is_partial": is_partial,
                "error_type": error_type, "error_detail": error_detail})
            return {
                "action": "guide",
                "message": feedback,
                "is_correct": is_correct,
                "is_partial": is_partial,
                "error_type": error_type,
                "error_detail": error_detail,
                "current_step": sess["current_step"] + 1,
                "total_steps": sess["total_steps"],
                "session_id": session_id,
            }

    # 备选（不应走到这里）
    msg = step.get("step_prompt") or f"请尝试完成第 {sess['current_step']+1} 步。"
    return {"action": "guide", "message": msg, "session_id": session_id}


def teach_ack_prompt(session_id: str, expected_revision=None) -> dict:
    """前端展示完下一步引导后确认，避免提示词被跳过或重复"""
    with _session_manager.transaction(session_id, expected_revision) as sess:
        if sess["current_step"] < sess["total_steps"]:
            sess["step_introduced"] = True
    return {
        "ok": True,
        "current_step": sess["current_step"] + 1,
        "total_steps": sess["total_steps"],
        "step_introduced": sess["step_introduced"],
        "revision": sess["revision"],
    }


def teach_session_start(question: str, teacher: str = None, asset_refs: list = None) -> dict:
    """对外：创建教学会话，返回会话信息和第一轮 AI 引导"""
    result = _session_manager.create(question, teacher, asset_refs)
    if result.get("error"):
        return result

    result["steps"] = result.get("steps", [])
    result["chunk_results"] = result.get("chunk_results", [])

    # 使用预生成的步骤引导作为第一轮消息（零 AI 调用）
    sess = _session_manager.get(result["session_id"])
    first_step = sess["steps"][0] if sess["steps"] else {}
    first_msg = first_step.get("step_prompt") or f"请尝试完成第 1 步：{first_step.get('title', '')}"
    sess["step_introduced"] = True
    sess["messages"].append({"role": "teacher", "content": first_msg, "step_index": sess["current_step"], "action": "guide"})
    _session_manager._persist(sess)

    return {
        "session_id": result["session_id"],
        "question_id": sess.get("question_id"),
        "action": "guide",
        "message": first_msg,
        "steps": sess["steps"],
        "chunk_results": sess["chunk_results"],
        "geometry": sess.get("geometry"), "asset_refs": sess.get("asset_refs", []),
        "geometry_state": sess.get("geometry_state", {"released": {}, "completed": []}),
        "total_steps": sess["total_steps"],
        "current_step": 1,
        "revision": sess.get("revision", 0),
    }




def teach_session_chat(session_id: str, student_message: str, expected_revision=None) -> dict:
    """对外：发送学生消息，返回 AI 回应"""
    with _session_manager.transaction(session_id, expected_revision) as sess:
        result = _do_chat_turn(session_id, student_message)
        if result.get("error"):
            raise RuntimeError(result.get("detail") or result["error"])
        if result.get("next_step_message"):
            _session_manager.add_message(session_id, "teacher", result["next_step_message"], metadata={"action": "guide"})
            sess["step_introduced"] = True
        if result.get("action") == "complete":
            _save_completed_session(sess)
            result["question_id"] = sess.get("question_id")
            result["saved_question_id"] = sess.get("question_id")
    result["revision"] = sess["revision"]
    result["geometry_state"] = deepcopy(sess.get("geometry_state", {"released": {}, "completed": []}))
    return result


def reserve_teaching_job(session_id, job_id, expected_revision=None):
    _session_manager.reserve(session_id, job_id, expected_revision)


def release_teaching_job(session_id, job_id):
    _session_manager.release(session_id, job_id)


def _save_completed_session(sess, manual_errors=None):
    """Server-side completion cannot be lost when the summary page is closed."""
    from backend.database import add_step_error, get_step_errors
    result = {"chunk_results": sess.get("chunk_results") or [], "overall_difficulty": sess.get("overall_difficulty")}
    result.update(geometry=sess.get("geometry"), asset_refs=sess.get("asset_refs", []))
    _set_category_from_chunks(result)
    if not sess.get("question_id"):
        sess["question_id"] = db_save_question(sess["question"], result)
    qid = sess.get("question_id")
    if not qid:
        return
    tags = {}
    student = ""
    for message in sess.get("messages") or []:
        if message["role"] == "student":
            student = message.get("content", "")
        elif message.get("is_correct") is False and message.get("error_type"):
            index = message.get("step_index", 0)
            if index < len(sess.get("steps") or []):
                step = sess["steps"][index]
                tags[(step.get("chunk_id", 1), step.get("step_number", index + 1))] = {
                    "mistake_type": message["error_type"], "mistake_detail": message.get("error_detail", ""), "student_input": student}
    if isinstance(manual_errors, dict):
        for key, value in manual_errors.items():
            parts = key.split("-")
            if len(parts) == 2:
                tags[(int(parts[0]), int(parts[1]))] = {"mistake_type": value.get("error_type", "其他"),
                                                     "mistake_detail": value.get("error_detail", ""), "student_input": value.get("student_input", "")}
    elif manual_errors:
        for tag in manual_errors:
            tags[(tag.get("chunk_id", 1), tag["step_number"])] = tag
    existing = {(e["chunk_id"], e["step_number"], e["mistake_type"], e.get("mistake_detail", ""), e.get("student_input") or "") for e in get_step_errors(qid)}
    for (chunk, step), tag in tags.items():
        identity = (chunk, step, tag["mistake_type"], tag.get("mistake_detail", ""), tag.get("student_input") or "")
        if identity not in existing:
            add_step_error(qid, step, chunk, tag["mistake_type"], tag.get("mistake_detail", ""), tag.get("student_input"))
            existing.add(identity)
    sess["results_saved"] = True


def teach_finish_session(session_id, step_errors=None, expected_revision=None):
    with _session_manager.transaction(session_id, expected_revision) as sess:
        _save_completed_session(sess, step_errors)
    return {"saved_question_id": sess.get("question_id"), "question_id": sess.get("question_id"),
            "saved": bool(sess.get("question_id")), "revision": sess["revision"]}


def teach_get_session(session_id: str) -> Optional[dict]:
    """对外：获取会话完整信息"""
    sess = _session_manager.get(session_id)
    if not sess:
        return None
    return {
        "session_id": sess["session_id"],
        "question_id": sess.get("question_id"),
        "question": sess["question"],
        "teacher": sess["teacher"],
        "steps": sess["steps"],
        "chunk_results": sess.get("chunk_results", []),
        "geometry": sess.get("geometry"), "asset_refs": sess.get("asset_refs", []),
        "geometry_state": sess.get("geometry_state", {"released": {}, "completed": []}),
        "current_step": sess["current_step"],
        "total_steps": sess["total_steps"],
        "messages": sess["messages"],
        "stats": sess["stats"],
        "step_results": sess["step_results"],
        "step_introduced": sess.get("step_introduced", False),
        "step_viewed_answer": sess.get("step_viewed_answer", False),
        "overall_difficulty": sess.get("overall_difficulty"),
        "revision": sess.get("revision", 0),
        "pending_job": sess.get("pending_job"),
        "results_saved": sess.get("results_saved", False),
    }
