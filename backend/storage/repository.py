"""Ownership and transaction boundary for every cloud client."""
from contextlib import contextmanager, nullcontext
from copy import deepcopy
import hashlib
import json
import time
import uuid
from sqlalchemy import select, insert, update, delete, or_, and_, func
from fastapi import HTTPException
from backend.identity import current_identity, current_user_id, require_catalog_editor
from . import models as m


def uid():
    return str(uuid.uuid4())


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def rowdict(row):
    return dict(row._mapping) if row is not None else None


class Repository:
    def __init__(self, database):
        self.db = database

    def visible(self, table=m.questions):
        return or_(table.c.owner_user_id.is_(None), table.c.owner_user_id == current_user_id())

    def question(self, question_id, *, conn=None):
        def read(c):
            row = rowdict(c.execute(select(m.questions).where(m.questions.c.id == str(question_id), self.visible())).first())
            if row is None:
                raise HTTPException(404, "题目不存在")
            data = deepcopy(row.pop("data"))
            return {**data, **row, "answer_json": data.get("answer_json", {})}
        if conn is not None:
            return read(conn)
        with self.db.transaction() as c:
            return read(c)

    def questions(self, limit=50, offset=0, query="", wrong=False):
        condition = and_(self.visible(), m.questions.c.active.is_(True))
        if query:
            condition = and_(condition, m.questions.c.content.ilike("%" + query.replace("%", "\\%").replace("_", "\\_") + "%", escape="\\"))
        if wrong:
            ids = select(m.attempts.c.question_id).where(m.attempts.c.user_id == current_user_id(), m.attempts.c.result["is_correct"].as_boolean() == False)
            condition = and_(condition, m.questions.c.id.in_(ids))
        with self.db.transaction() as c:
            total = c.scalar(select(func.count()).select_from(m.questions).where(condition))
            ids = c.scalars(select(m.questions.c.id).where(condition).order_by(m.questions.c.created_at.desc(), m.questions.c.id).limit(limit).offset(offset)).all()
            return {"items": [self.question(i, conn=c) for i in ids], "total": total, "offset": offset, "limit": limit}

    def question_version(self, question_id, revision):
        with self.db.transaction() as c:
            current = self.question(question_id, conn=c)
            version = c.execute(select(m.question_versions.c.data).where(m.question_versions.c.question_id == question_id, m.question_versions.c.revision == revision)).scalar()
            if version is None:
                raise HTTPException(404, "题目版本不存在")
            return {**current, **deepcopy(version), "id": question_id, "revision": revision}

    def save_question(self, content, answer_json, *, public=False, question_id=None, data=None, expected_revision=None, conn=None):
        if public:
            require_catalog_editor()
        owner = None if public else current_user_id()
        now = time.time()
        payload = {**(data or {}), "answer_json": answer_json}
        with (nullcontext(conn) if conn is not None else self.db.transaction()) as c:
            old = None
            if question_id:
                self.question(question_id, conn=c)
                old = rowdict(c.execute(select(m.questions).where(m.questions.c.id == question_id).with_for_update()).first())
                if old["owner_user_id"] is None:
                    require_catalog_editor()
                elif old["owner_user_id"] != current_user_id():
                    raise HTTPException(403, "不能修改其他账号的题目")
                if expected_revision is not None and old["revision"] != expected_revision:
                    raise HTTPException(409, "题目已更新，请刷新")
                owner = old["owner_user_id"]
            question_id = question_id or uid()
            revision = old["revision"] + 1 if old else 1
            if owner is None:
                from backend.catalog import _public_question
                published = _public_question({"answer_json": json.dumps(answer_json)})
                if published is None:
                    raise HTTPException(409, "题目来源尚未确认可公开")
                payload["answer_json"] = json.loads(published["answer_json"])
                for asset_id in answer_json.get("asset_refs", []):
                    asset = self.legacy_asset(asset_id) if isinstance(asset_id, str) and asset_id.endswith(".png") else self.asset(asset_id)
                    c.execute(update(m.assets).where(m.assets.c.id == asset["id"]).values(owner_user_id=None))
            values = dict(owner_user_id=owner, content=content, data=payload, revision=revision, active=True, updated_at=now)
            if old:
                c.execute(update(m.questions).where(m.questions.c.id == question_id).values(**values))
            else:
                c.execute(insert(m.questions).values(id=question_id, created_at=now, **values))
            c.execute(insert(m.question_versions).values(question_id=question_id, revision=revision, data={**payload, "content": content}, created_at=now))
            result = self.question(question_id, conn=c)
        return result

    def withdraw_question(self, question_id):
        question = self.question(question_id)
        if question["owner_user_id"] is None:
            require_catalog_editor()
        with self.db.transaction() as c:
            c.execute(update(m.questions).where(m.questions.c.id == question_id).values(active=False, updated_at=time.time()))

    def grant(self, c, question_id):
        self.question(question_id, conn=c)
        condition = and_(m.question_access.c.user_id == current_user_id(), m.question_access.c.question_id == question_id)
        if not c.execute(select(m.question_access).where(condition)).first():
            c.execute(insert(m.question_access).values(user_id=current_user_id(), question_id=question_id))

    def asset(self, asset_id):
        with self.db.transaction() as c:
            row = rowdict(c.execute(select(m.assets).where(m.assets.c.id == asset_id, self.visible(m.assets))).first())
            if row is None:
                raise HTTPException(404, "附件不存在")
            return row

    def legacy_asset(self, name):
        own = self.alias("assets", name)
        if own:
            return self.asset(own)
        with self.db.transaction() as c:
            row = c.execute(select(m.assets).join(m.aliases, m.aliases.c.resource_id == m.assets.c.id).where(
                m.aliases.c.resource == "assets", m.aliases.c.legacy_id == name, m.assets.c.owner_user_id.is_(None))).first()
            if row is None:
                raise HTTPException(404, "题图不存在")
            return rowdict(row)

    def save_asset(self, **values):
        with self.db.transaction() as c:
            c.execute(insert(m.assets).values(**values))
        return self.asset(values["id"])

    def attempts(self, limit=50, offset=0):
        with self.db.transaction() as c:
            condition = m.attempts.c.user_id == current_user_id()
            items = [rowdict(r) for r in c.execute(select(m.attempts).where(condition).order_by(m.attempts.c.created_at.desc()).limit(limit).offset(offset))]
            for item in items:
                snapshot = c.execute(select(m.question_versions.c.data).where(m.question_versions.c.question_id == item["question_id"], m.question_versions.c.revision == item["question_revision"])).scalar()
                item["question_content"] = (snapshot or {}).get("content", "")
            return {"items": items,
                    "total": c.scalar(select(func.count()).select_from(m.attempts).where(condition)), "offset": offset, "limit": limit}

    def save_attempt(self, question_id, student_answer, result, request_id, asset_ids=None, revision=None):
        for asset_id in asset_ids or []:
            self.asset(asset_id)
        with self.db.transaction() as c:
            previous = c.execute(select(m.attempts).where(m.attempts.c.user_id == current_user_id(), m.attempts.c.request_id == request_id)).first()
            if previous:
                previous = rowdict(previous)
                if previous["question_id"] != question_id or previous["student_answer"] != student_answer or previous["asset_ids"] != (asset_ids or []):
                    raise HTTPException(409, "请求编号已用于其他作答")
                return previous
            question = self.question(question_id, conn=c)
            self.grant(c, question_id)
            values = dict(id=uid(), user_id=current_user_id(), question_id=question_id, question_revision=revision or question["revision"],
                          request_id=request_id, student_answer=student_answer, result=result, asset_ids=asset_ids or [], created_at=time.time())
            c.execute(insert(m.attempts).values(**values))
            return values

    def progress(self):
        attempts = self.attempts(200, 0)
        recent = attempts["items"]
        with self.db.transaction() as c:
            all_results = c.execute(select(m.attempts.c.result).where(m.attempts.c.user_id == current_user_id())).scalars().all()
            records = [rowdict(r) for r in c.execute(select(m.learning_records).where(m.learning_records.c.user_id == current_user_id(), m.learning_records.c.kind.in_(["mastery.pattern_mastery", "mastery.category_mastery"]))) ]
            pattern_names = {r.id: r.data.get("name", "套路") for r in c.execute(select(m.patterns))}
            for record in records:
                record["display_name"] = record["data"].get("category") or pattern_names.get(record["data"].get("pattern_id"), "套路学习")
        return {"attempt_count": len(all_results), "correct_count": sum(r.get("is_correct") is True for r in all_results),
                "review_count": sum(r.get("is_correct") is not True for r in all_results), "recent_attempts": recent[:20], "mastery": records}

    def teaching(self, session_id):
        with self.db.transaction() as c:
            row = rowdict(c.execute(select(m.teaching_sessions).where(m.teaching_sessions.c.session_id == session_id, m.teaching_sessions.c.user_id == current_user_id())).first())
        if not row:
            raise HTTPException(404, "教学会话不存在")
        return {**row["state_json"], "revision": row["revision"], "pending_job": row["pending_job"]}

    def persist_teaching(self, state):
        now = time.time()
        with self.db.transaction() as c:
            if state.get("question_id"):
                self.grant(c, state["question_id"])
            condition = and_(m.teaching_sessions.c.session_id == state["session_id"], m.teaching_sessions.c.user_id == current_user_id())
            values = dict(state_json=deepcopy(state), revision=state.get("revision", 0), pending_job=state.get("pending_job"), updated_at=now)
            if c.execute(select(m.teaching_sessions.c.session_id).where(condition)).first():
                c.execute(update(m.teaching_sessions).where(condition).values(**values))
            else:
                c.execute(insert(m.teaching_sessions).values(session_id=state["session_id"], user_id=current_user_id(), created_at=state.get("created_at", now), **values))

    def job(self, job_id):
        with self.db.transaction() as c:
            row = rowdict(c.execute(select(m.jobs).where(m.jobs.c.id == job_id, m.jobs.c.user_id == current_user_id())).first())
            if row is None:
                raise HTTPException(404, "任务不存在")
            row.pop("fingerprint", None)
            row["job_id"] = row["id"]
            return row

    def submit_job(self, kind, args, request_id):
        digest = fingerprint({"kind": kind, "args": args})
        with self.db.transaction() as c:
            # Serialise same-account submissions without an in-process-only lock.
            c.execute(select(m.users.c.id).where(m.users.c.id == current_user_id()).with_for_update()).first()
            old = rowdict(c.execute(select(m.jobs).where(m.jobs.c.user_id == current_user_id(), m.jobs.c.request_id == request_id)).first())
            if old:
                if old["fingerprint"] != digest:
                    raise HTTPException(409, "请求编号已用于其他任务")
                return old["id"], False
            values = dict(id=uid(), user_id=current_user_id(), kind=kind, args=args, request_id=request_id, fingerprint=digest,
                          status="queued", stage="已进入后台队列", progress=0, created_at=time.time(), updated_at=time.time())
            c.execute(insert(m.jobs).values(**values))
            return values["id"], True

    def update_job(self, job_id, **values):
        with self.db.transaction() as c:
            return c.execute(update(m.jobs).where(m.jobs.c.id == job_id, m.jobs.c.user_id == current_user_id(), m.jobs.c.status.in_(["queued", "running"])).values(updated_at=time.time(), **values)).rowcount

    def alias(self, resource, legacy_id, resource_id=None, *, conn=None, user_id=None):
        def act(c):
            condition = and_(m.aliases.c.user_id == (user_id or current_user_id()), m.aliases.c.resource == resource, m.aliases.c.legacy_id == str(legacy_id))
            old = c.execute(select(m.aliases.c.resource_id).where(condition)).scalar()
            if old:
                if resource_id and resource_id != old:
                    raise ValueError("旧 ID 映射发生冲突")
                return old
            if resource_id:
                c.execute(insert(m.aliases).values(user_id=user_id or current_user_id(), resource=resource, legacy_id=str(legacy_id), resource_id=resource_id))
                return resource_id
            return None
        if conn is not None:
            return act(conn)
        with self.db.transaction() as c:
            return act(c)

    def records(self, kind, *, admin=False, limit=None, offset=0):
        if admin:
            require_catalog_editor()
        table = m.admin_records if admin else m.learning_records
        cond = table.c.kind == kind
        if not admin:
            cond = and_(cond, table.c.user_id == current_user_id())
        with self.db.transaction() as c:
            query = select(table).where(cond).order_by(table.c.created_at, table.c.id).offset(offset)
            if limit is not None:
                query = query.limit(limit)
            return [rowdict(r) for r in c.execute(query)]
