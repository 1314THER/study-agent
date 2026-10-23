"""Adapt learning-engine functions without letting cloud requests open SQLite."""
from copy import deepcopy
import functools
import json
import time
from sqlalchemy import select, insert, update, delete, and_
from fastapi import HTTPException
from backend.identity import current_user_id
from .database import current_repository
from . import models as m
from .repository import uid, rowdict


def record(repo, kind, data, question_id=None):
    value = dict(id=uid(), user_id=current_user_id(), kind=kind, data=data, question_id=question_id, created_at=time.time())
    with repo.db.transaction() as c:
        if question_id:
            repo.grant(c, question_id)
        c.execute(insert(m.learning_records).values(**value))
    return value


def matching(repo, content):
    with repo.db.transaction() as c:
        qid = c.scalar(select(m.questions.c.id).where(repo.visible(), m.questions.c.content == content.strip(), m.questions.c.active.is_(True))
                       .order_by(m.questions.c.owner_user_id.is_(None), m.questions.c.created_at.desc()).limit(1))
        return repo.question(qid, conn=c) if qid else None


def dispatch(repo, name, *args, **kwargs):
    if name in ("get_connection", "init_db"):
        raise RuntimeError("云端请求不能打开旧 SQLite 数据库")
    if name in ("find_question", "find_question_id"):
        q = matching(repo, args[0])
        return (q["id"] if name.endswith("_id") else deepcopy(q["answer_json"])) if q else None
    if name == "save_question":
        old = matching(repo, args[0]) if kwargs.get("match_existing", True) else None
        if old and (old["owner_user_id"] is None or not kwargs.get("overwrite_existing", True)):
            return old["id"]
        return repo.save_question(args[0].strip(), args[1], question_id=old["id"] if old else None)["id"]
    if name == "get_question_by_id":
        try:
            return repo.question(str(args[0]))
        except HTTPException as e:
            if e.status_code == 404:
                return None
            raise
    if name == "get_all_questions":
        return repo.questions(10000)["items"]
    if name in ("search_questions", "get_wrong_questions", "get_questions_with_errors"):
        keywords = kwargs.get("keywords") or []
        return repo.questions(min(kwargs.get("page_size") or kwargs.get("limit") or 200, 1000),
                              ((kwargs.get("page") or 1) - 1) * (kwargs.get("page_size") or 200),
                              " ".join(keywords) if isinstance(keywords, list) else str(keywords), wrong=name != "search_questions")["items"]
    if name == "delete_question":
        repo.withdraw_question(str(args[0])); return True
    if name == "add_practice_record":
        qid = str(args[0])
        result = kwargs.get("grade_json") or {"is_correct": bool(args[1] if len(args) > 1 else kwargs.get("correct"))}
        return repo.save_attempt(qid, kwargs.get("student_answer") or "", result, uid())["id"]
    if name == "add_step_error":
        keys = ["question_id", "step_number", "chunk_id", "mistake_type", "mistake_detail", "student_input"]
        data = {**dict(zip(keys, args)), **kwargs}
        qid = str(data["question_id"])
        return record(repo, "questions.step_errors", data, qid)["id"]
    if name == "get_step_errors":
        return [{**r["data"], "id": r["id"]} for r in repo.records("questions.step_errors") if r["question_id"] == str(args[0])]
    if name == "update_question_time":
        repo.question(str(args[0])); return
    if name == "get_question_lists":
        return [{"id": r["id"], **r["data"]} for r in repo.records("questions.question_lists")]
    if name == "create_question_list":
        return record(repo, "questions.question_lists", {"name": args[0], "list_type": "user"})["id"]
    raise HTTPException(501, f"云端请使用 /api/v1 接口：{name}")


def install(namespace):
    # Internal SQL helpers remain local-only. Public persistence functions must
    # explicitly adapt or fail closed, never silently use the owner's DB.
    for name, original in list(namespace.items()):
        if not callable(original) or getattr(original, "__module__", "") != "backend.database" or name.startswith("_"):
            continue
        if name.startswith(("looks_like",)):
            continue
        @functools.wraps(original)
        def wrapped(*args, __name=name, __original=original, **kwargs):
            repo = current_repository()
            return dispatch(repo, __name, *args, **kwargs) if repo else __original(*args, **kwargs)
        namespace[name] = wrapped

