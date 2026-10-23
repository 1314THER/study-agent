"""Read-only SQLite snapshots and idempotent, transactional cloud imports.

The bundle contains private data. It is created with mode 0700, is never served
by the web application, and must be encrypted by the deployment backup system.
"""
import base64
from datetime import datetime, timezone
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import shutil
import sqlite3
import time
import uuid
from sqlalchemy import select, insert, update, func
from . import models as m
from .repository import rowdict

NAMESPACE = uuid.UUID("c2a6f7c9-35a9-4829-a931-556d73cba427")
DB_NAMES = {"study_agent.db": "questions", "mastery.db": "mastery", "jobs.sqlite3": "jobs",
            "question_pool.db": "pool", "routine-review.sqlite3": "review", "exam-analyses.sqlite3": "exam",
            "exam-templates.sqlite3": "templates", "student-analysis.sqlite3": "student"}
ADMIN_KINDS = {"pool", "review", "templates"}


def stable(value):
    return str(uuid.uuid5(NAMESPACE, value))


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def decode(value):
    if isinstance(value, bytes):
        return {"__base64__": base64.b64encode(value).decode()}
    if isinstance(value, str) and value[:1] in ("{", "["):
        try:
            return json.loads(value)
        except ValueError:
            pass
    return value


def timestamp(value):
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return 0.0


def tables(path):
    with sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True) as c:
        c.row_factory = sqlite3.Row
        names = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {name: [dict(r) for r in c.execute('SELECT * FROM "' + name.replace('"', '""') + '"')] for name in names}


def snapshot(owner, accounts, destination):
    owner, destination = Path(owner).resolve(), Path(destination).resolve()
    accounts = Path(accounts).resolve() if accounts else None
    if destination.exists():
        raise ValueError("快照目录已存在，请使用新目录")
    if destination.is_relative_to(owner) or (accounts and destination.is_relative_to(accounts)):
        raise ValueError("快照目录必须位于源数据目录之外")
    destination.mkdir(parents=True, mode=0o700)
    manifest = {"version": 1, "created_at": time.time(), "databases": [], "assets": [], "files": []}

    def copy_db(source, relative, user_id, kind):
        if not source.is_file() or source.is_symlink():
            return
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as src, sqlite3.connect(target) as dst:
            src.backup(dst)
            if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("SQLite 快照完整性检查失败")
        target.chmod(0o600)
        counts = {name: len(rows) for name, rows in tables(target).items()}
        manifest["databases"].append({"path": relative, "user_id": user_id, "kind": kind, "sha256": sha(target), "tables": counts})

    def copy_file(source, relative, bucket, **info):
        if source.is_symlink() or not source.is_file():
            raise ValueError("备份拒绝符号链接")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copyfile(source, target)
        target.chmod(0o600)
        manifest[bucket].append({"path": relative, "sha256": sha(target), "size": target.stat().st_size, **info})

    workspaces = [("studyadmin", owner)]
    if accounts:
        copy_db(accounts / "accounts.db", "auth/accounts.db", None, "auth")
        copy_db(accounts / "catalog.db", "content/catalog.db", None, "catalog")
        for user in sorted((accounts / "users").glob("user-*")):
            if user.is_dir() and not user.is_symlink():
                workspaces.append((user.name.removeprefix("user-"), user))
    for user_id, directory in workspaces:
        for name, kind in DB_NAMES.items():
            candidates = [directory / name, directory / ".runtime" / name]
            found = [p for p in candidates if p.is_file()]
            if len(found) > 1:
                raise ValueError(f"同一工作区发现两个 {name}，请先确认实际生效路径")
            if found:
                copy_db(found[0], f"workspaces/{user_id}/{name}", user_id, kind)
        for base in (directory / "question-assets", directory / ".runtime" / "question-assets", directory / "uploads", directory / ".runtime" / "uploads"):
            if base.is_dir():
                for source in sorted(base.rglob("*")):
                    if source.is_file():
                        rel = f"assets/{user_id}/{base.name}/{source.relative_to(base).as_posix()}"
                        copy_file(source, rel, "assets", user_id=user_id, legacy_name=source.name,
                                  role="question_assets" if base.name == "question-assets" else "uploads", legacy_path=str(source))
        for base in (directory / "question-pool", directory / ".runtime" / "question-pool"):
            if base.is_dir():
                for source in sorted(base.rglob("*")):
                    if source.is_file():
                        rel = f"assets/{user_id}/source-files/{source.relative_to(base).as_posix()}"
                        copy_file(source, rel, "assets", user_id=user_id, legacy_name=source.name, role="source_files", legacy_path=str(source))
        for name in ("settings.json", "patterns.yaml", "board_order.yaml", ".env"):
            for source in (directory / name, directory / "backend" / name):
                if source.is_file():
                    copy_file(source, f"config/{user_id}/{source.parent.name}-{name}", "files", user_id=user_id)
    (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    (destination / "manifest.json").chmod(0o600)
    return manifest


def inspect_bundle(bundle):
    root = Path(bundle).resolve()
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest.get("version") != 1:
        raise ValueError("快照版本不支持")
    for entry in manifest["databases"] + manifest["assets"] + manifest["files"]:
        target = (root / entry["path"]).resolve()
        if not target.is_relative_to(root) or target.is_symlink() or sha(target) != entry["sha256"]:
            raise ValueError("快照文件校验失败")
    for entry in manifest["databases"]:
        if {k: len(v) for k, v in tables(root / entry["path"]).items()} != entry["tables"]:
            raise ValueError("快照记录数不匹配")
    return manifest


def import_bundle(database, bundle, asset_root, *, apply=False):
    root, asset_root = Path(bundle).resolve(), Path(asset_root).resolve()
    manifest = inspect_bundle(root)
    report = {"databases": len(manifest["databases"]), "assets": len(manifest["assets"]),
              "source_rows": sum(sum(d["tables"].values()) for d in manifest["databases"]), "applied": False}
    if not apply:
        return report
    run_id = stable(sha(root / "manifest.json"))
    with database.transaction() as c:
        if c.execute(select(m.migration_runs).where(m.migration_runs.c.id == run_id)).first():
            return {**report, "applied": True, "already_imported": True}
        # Prevent two imports from racing the alias/content registry.
        if c.dialect.name == "postgresql":
            from sqlalchemy import text
            c.execute(text("SELECT pg_advisory_xact_lock(735921002)"))
        sources = [(d, tables(root / d["path"])) for d in manifest["databases"]]
        existing_users = set(c.scalars(select(m.users.c.id)).all())
        for desc, data in sources:
            if desc["kind"] == "auth":
                for user in data.get("users", []):
                    if user["id"] in existing_users:
                        raise ValueError("目标库已有同名用户，拒绝覆盖；请使用空目标库或先完成迁移")
                    c.execute(insert(m.users).values(**{col.name: user.get(col.name) for col in m.users.columns}))
                    existing_users.add(user["id"])
        workspace_users = {d["user_id"] for d, _ in sources if d["user_id"]}
        for user_id in workspace_users - existing_users:
            if user_id != "studyadmin":
                raise ValueError("个人工作区缺少对应账号")
            c.execute(insert(m.users).values(id=user_id, username=user_id, username_norm=user_id, password_hash="!disabled-until-bootstrap", role="owner", created_at=time.time(), disabled=1))
            existing_users.add(user_id)
        mapping = {}

        def alias(user, resource, old, target):
            key = (user, resource, str(old))
            if key in mapping:
                if mapping[key] != target:
                    raise ValueError("旧记录映射冲突")
                return
            previous = c.execute(select(m.aliases.c.resource_id).where(m.aliases.c.user_id == user, m.aliases.c.resource == resource, m.aliases.c.legacy_id == str(old))).scalar()
            if previous and previous != target:
                raise ValueError("目标映射冲突")
            if not previous:
                c.execute(insert(m.aliases).values(user_id=user, resource=resource, legacy_id=str(old), resource_id=target))
            mapping[key] = target

        public, public_patterns, public_links = {}, {}, []
        published_catalog = False
        for desc, data in sources:
            if desc["kind"] == "catalog":
                for catalog in data.get("shared_catalog", []):
                    published_catalog = True
                    definition = decode(catalog["definitions_json"])
                    for q in definition.get("questions", []):
                        public[str(q["id"])] = q
                    for pattern in definition.get("patterns", []):
                        public_patterns[str(pattern["id"])] = pattern
                    public_links.extend(definition.get("links", []))
        linked_questions = {str(link["question_id"]) for desc, data in sources if desc["kind"] == "mastery" and desc["user_id"] == "studyadmin" for link in data.get("pattern_questions", [])}
        for desc, data in sources:
            if not published_catalog and desc["kind"] == "mastery" and desc["user_id"] == "studyadmin":
                public_patterns.update({str(p["id"]): p for p in data.get("patterns", []) if p.get("catalog_id") is None})
                public_links.extend(data.get("pattern_questions", []))
            if not published_catalog and desc["kind"] == "questions" and desc["user_id"] == "studyadmin":
                from backend.catalog import _public_question
                for q in data.get("questions", []):
                    if q.get("source_type") == "精选母题" or str(q["id"]) in linked_questions:
                        approved = _public_question(q)
                        if approved is not None:
                            public.setdefault(str(q["id"]), approved)
        for old, q in public.items():
            qid = stable("catalog:questions:" + old)
            payload = {k: decode(v) for k, v in q.items() if k not in ("id", "user_id", "catalog_id")}
            c.execute(insert(m.questions).values(id=qid, owner_user_id=None, content=q["content"], data=payload, revision=1,
                       active=bool(q.get("catalog_active", 1)), created_at=timestamp(q.get("created_at")), updated_at=time.time()))
            c.execute(insert(m.question_versions).values(question_id=qid, revision=1, data=payload, created_at=time.time()))
        for canonical, pattern in public_patterns.items():
            definition = {k: decode(v) for k, v in pattern.items() if k not in ("id", "catalog_id", "user_id")}
            definition["questions"] = {link["role"]: stable("catalog:questions:" + str(link["question_id"])) for link in public_links
                if str(link["pattern_id"]) == canonical and str(link["question_id"]) in public}
            c.execute(insert(m.patterns).values(id=stable("catalog:patterns:" + canonical), data=definition, active=True, revision=1))
        version_mapping = {}
        version_hashes = {}
        for old, q in public.items():
            digest = json.dumps({"content": q["content"], "answer_json": decode(q.get("answer_json", "{}"))}, sort_keys=True)
            version_hashes[stable("catalog:questions:" + old)] = {digest: 1}
        for desc, data in sources:
            user, kind = desc["user_id"], desc["kind"]
            if not user:
                continue
            for table, rows in data.items():
                for index, row in enumerate(rows):
                    old_id = row.get("id", row.get("session_id", row.get("job_id", row.get("round_id", index))))
                    resource = kind + "." + table
                    target = stable(user + ":" + resource + ":" + str(old_id))
                    if kind == "questions" and table == "questions":
                        catalog_id = row.get("catalog_id")
                        canonical = str(catalog_id) if catalog_id is not None else str(old_id) if user == "studyadmin" and str(old_id) in public else None
                        if canonical is not None and canonical not in public:
                            # Withdrawn catalog questions remain historical content.
                            payload = {k: decode(v) for k, v in row.items() if k not in ("id", "user_id", "catalog_id")}
                            public[canonical] = row
                            cqid = stable("catalog:questions:" + canonical)
                            c.execute(insert(m.questions).values(id=cqid, owner_user_id=None, content=row["content"], data=payload, revision=1, active=False, created_at=timestamp(row.get("created_at")), updated_at=time.time()))
                            c.execute(insert(m.question_versions).values(question_id=cqid, revision=1, data=payload, created_at=time.time()))
                        if canonical is not None:
                            target = stable("catalog:questions:" + canonical)
                            source_answer = decode(row.get("answer_json", "{}"))
                            digest = json.dumps({"content": row["content"], "answer_json": source_answer}, sort_keys=True)
                            known = version_hashes.setdefault(target, {})
                            if digest not in known:
                                current = c.execute(select(m.questions).where(m.questions.c.id == target)).first()
                                # Preserve the available per-user historical definition,
                                # then append the published definition as current again.
                                historical_revision = current.revision + 1
                                c.execute(insert(m.question_versions).values(question_id=target, revision=historical_revision,
                                    data={"content": row["content"], "answer_json": source_answer}, created_at=time.time()))
                                c.execute(insert(m.question_versions).values(question_id=target, revision=historical_revision + 1,
                                    data=current.data, created_at=time.time()))
                                c.execute(update(m.questions).where(m.questions.c.id == target).values(revision=historical_revision + 1))
                                known[digest] = historical_revision
                            version_mapping[user, str(old_id)] = known[digest]
                        else:
                            payload = {k: decode(v) for k, v in row.items() if k not in ("id", "user_id", "catalog_id")}
                            c.execute(insert(m.questions).values(id=target, owner_user_id=user, content=row["content"], data=payload, revision=1,
                                active=True, created_at=timestamp(row.get("created_at")), updated_at=time.time()))
                            c.execute(insert(m.question_versions).values(question_id=target, revision=1, data=payload, created_at=time.time()))
                            version_mapping[user, str(old_id)] = 1
                    if kind == "mastery" and table == "patterns":
                        catalog_id = row.get("catalog_id")
                        canonical = str(catalog_id) if catalog_id is not None else str(old_id) if user == "studyadmin" else None
                        if canonical in public_patterns:
                            target = stable("catalog:patterns:" + canonical)
                    alias(user, resource, old_id, target)

        access = set()
        def grant(user, qid):
            if (user, qid) not in access:
                c.execute(insert(m.question_access).values(user_id=user, question_id=qid))
                access.add((user, qid))

        for desc, data in sources:
            user, kind = desc["user_id"], desc["kind"]
            if not user:
                continue
            for table, rows in data.items():
                for index, row in enumerate(rows):
                    old_id = row.get("id", row.get("session_id", row.get("job_id", row.get("round_id", index))))
                    resource = kind + "." + table
                    target = mapping[user, resource, str(old_id)]
                    payload = {k: decode(v) for k, v in row.items()}
                    refs = {}
                    for key, reference in list(payload.items()):
                        target_resource = {"question_id": "questions.questions", "pattern_id": "mastery.patterns", "board_id": "mastery.boards", "list_id": "questions.question_lists", "round_id": "mastery.loop_rounds"}.get(key)
                        if target_resource and reference is not None:
                            resolved = mapping.get((user, target_resource, str(reference)))
                            if not resolved and key == "question_id":
                                raise ValueError(f"{resource} 引用了不存在的题目；需先修复源库")
                            if resolved:
                                refs[key] = resolved
                    qid = refs.get("question_id")
                    if qid:
                        grant(user, qid)
                    if kind == "questions" and table == "questions":
                        continue
                    if kind == "questions" and table == "practice_records":
                        if not qid:
                            raise ValueError("作答缺少题目引用")
                        result = payload.get("grade_json") or {"is_correct": bool(row.get("correct"))}
                        c.execute(insert(m.attempts).values(id=target, user_id=user, question_id=qid, question_revision=version_mapping.get((user, str(row["question_id"])), 1),
                            request_id="migration:" + target, student_answer=row.get("student_answer") or "", result=result,
                            asset_ids=[], created_at=timestamp(row.get("created_at"))))
                    elif kind == "jobs" and table == "teaching_sessions":
                        state = payload["state_json"]
                        if state.get("question_id") is not None:
                            state["question_id"] = mapping.get((user, "questions.questions", str(state["question_id"])))
                        state.update(session_id=target, pending_job=None)
                        c.execute(insert(m.teaching_sessions).values(session_id=target, user_id=user, state_json=state, revision=row.get("revision", 0), pending_job=None,
                            created_at=timestamp(row.get("created_at")), updated_at=timestamp(row.get("updated_at"))))
                    elif kind == "jobs" and table == "jobs":
                        status = row.get("status", "interrupted")
                        c.execute(insert(m.jobs).values(id=target, user_id=user, request_id="migration:" + target,
                            kind=row.get("kind", "solve"), fingerprint=row.get("fingerprint", ""), args=payload.get("args_json") or {},
                            status="interrupted" if status in ("queued", "running") else status, stage=row.get("stage", "已迁移"), progress=row.get("progress", 0),
                            result=payload.get("result_json"), error=payload.get("error_json"), created_at=timestamp(row.get("created_at")), updated_at=timestamp(row.get("updated_at"))))
                    elif kind == "mastery" and table == "patterns" and target in {stable("catalog:patterns:" + key) for key in public_patterns}:
                        if not c.execute(select(m.patterns.c.id).where(m.patterns.c.id == target)).first():
                            canonical = next(key for key in public_patterns if stable("catalog:patterns:" + key) == target)
                            definition = {k: decode(v) for k, v in public_patterns[canonical].items() if k not in ("id", "catalog_id", "user_id")}
                            c.execute(insert(m.patterns).values(id=target, data=definition, active=True, revision=1))
                    else:
                        values = dict(id=target, kind=resource, data={**payload, **refs, "legacy": payload}, created_at=timestamp(row.get("created_at")))
                        if kind in ADMIN_KINDS:
                            if user != "studyadmin":
                                raise ValueError("普通账号工作区出现管理员数据，请先确认归属")
                            c.execute(insert(m.admin_records).values(**values))
                        else:
                            c.execute(insert(m.learning_records).values(user_id=user, question_id=qid, **values))
        for asset in manifest["assets"]:
            user = asset["user_id"]
            asset_id = stable(user + ":asset:" + asset["path"])
            key = user + "/" + asset_id + Path(asset["legacy_name"]).suffix
            target = asset_root / key
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if target.exists() and sha(target) != asset["sha256"]:
                raise ValueError("目标附件校验冲突")
            shutil.copyfile(root / asset["path"], target)
            target.chmod(0o600)
            publicly_referenced = asset.get("role", "question_assets") == "question_assets" and any(
                asset["legacy_name"] in (decode(q.get("answer_json", "{}")) or {}).get("asset_refs", []) for q in public.values())
            c.execute(insert(m.assets).values(id=asset_id, owner_user_id=None if publicly_referenced else user, storage_key=key, filename=asset["legacy_name"], media_type=mimetypes.guess_type(asset["legacy_name"])[0] or "application/octet-stream", size=asset["size"], sha256=asset["sha256"], created_at=time.time()))
            alias(user, "assets" if asset.get("role", "question_assets") == "question_assets" else "source_files", asset["legacy_name"] if asset.get("role", "question_assets") == "question_assets" else asset.get("legacy_path", asset["path"]), asset_id)
        # Expired sessions and email challenges deliberately require re-login.
        c.execute(insert(m.migration_runs).values(id=run_id, manifest={**report, "source_manifest": manifest}, created_at=time.time()))
    return {**report, "applied": True, "run_id": run_id}


def export_cloud(database, destination):
    """Lossless export of ALL cloud writes before a rollback, not an SQLite restore."""
    path = Path(destination)
    if path.exists():
        raise ValueError("导出文件已存在")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with database.transaction() as c:
        if c.dialect.name == "postgresql":
            from sqlalchemy import text
            c.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        with path.open("x") as f:
            path.chmod(0o600)
            for table in m.metadata.sorted_tables:
                for row in c.execute(select(table)):
                    f.write(json.dumps({"table": table.fullname, "row": dict(row._mapping)}, default=lambda v: {"__base64__": base64.b64encode(v).decode()}, ensure_ascii=False) + "\n")


def verify_import(database, bundle, asset_root):
    root, asset_root = Path(bundle).resolve(), Path(asset_root).resolve()
    manifest = inspect_bundle(root)
    run_id = stable(sha(root / "manifest.json"))
    with database.transaction() as c:
        if not c.execute(select(m.migration_runs.c.id).where(m.migration_runs.c.id == run_id)).first():
            raise ValueError("目标库中没有这个快照的成功导入记录")
        checked = 0
        for desc in manifest["databases"]:
            if not desc["user_id"]:
                continue
            for table, expected in desc["tables"].items():
                actual = c.scalar(select(func.count()).select_from(m.aliases).where(m.aliases.c.user_id == desc["user_id"], m.aliases.c.resource == desc["kind"] + "." + table))
                if actual != expected:
                    raise ValueError("迁移记录数量不匹配：" + desc["kind"] + "." + table)
                checked += actual
        for asset in manifest["assets"]:
            asset_id = stable(asset["user_id"] + ":asset:" + asset["path"])
            target = c.execute(select(m.assets.c.storage_key).where(m.assets.c.id == asset_id)).scalar()
            if not target or sha(asset_root / target) != asset["sha256"]:
                raise ValueError("目标附件缺失或校验不符")
    return {"verified": True, "mapped_rows": checked, "assets": len(manifest["assets"])}
