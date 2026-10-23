"""Reuse the audited account rules with PostgreSQL persistence."""
from contextlib import contextmanager
import os
import re
from sqlalchemy import text
from backend.auth import AccountStore, AuthError, ROOT
from .models import users, login_sessions, email_challenges, auth_rate_events


class Row:
    def __init__(self, row):
        self.row = row
    def __getitem__(self, key):
        return self.row._mapping[key] if isinstance(key, str) else self.row[key]
    def keys(self):
        return self.row._mapping.keys()


class Result:
    def __init__(self, result):
        self.result = result
    def fetchone(self):
        row = self.result.fetchone()
        return Row(row) if row is not None else None
    def fetchall(self):
        return [Row(r) for r in self.result.fetchall()]
    @property
    def rowcount(self):
        return self.result.rowcount


class AuthConnection:
    def __init__(self, conn):
        self.conn = conn
    def execute(self, sql, values=()):
        if sql == "BEGIN IMMEDIATE":
            return None
        for table in ("login_sessions", "email_challenges", "auth_rate_events", "users"):
            sql = re.sub(r"\b" + table + r"\b", "auth." + table, sql)
        sql = sql.replace("rowid DESC", "token_hash DESC")
        pieces = sql.split("?")
        sql = pieces[0] + "".join(":p" + str(i) + piece for i, piece in enumerate(pieces[1:]))
        return Result(self.conn.execute(text(sql), {"p" + str(i): v for i, v in enumerate(values)}))


class CloudAccountStore(AccountStore):
    def __init__(self, database, root, **kwargs):
        super().__init__(root, os.path.join(root, "owner"), **kwargs)
        self.database = database

    def prepare(self):
        if not self._prepared:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            (self.root / "users").mkdir(exist_ok=True, mode=0o700)
            self._prepared = True

    @contextmanager
    def connection(self):
        self.prepare()
        with self.database.transaction() as conn:
            if conn.dialect.name == "postgresql":
                # Verification consumption, rate counting and session creation
                # need the same cross-process serialization as BEGIN IMMEDIATE.
                conn.execute(text("SELECT pg_advisory_xact_lock(735921001)"))
            yield AuthConnection(conn)

    def prepare_workspace(self, user):
        directory = self.workspace_for(user)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if directory.is_symlink() or not directory.resolve().is_relative_to(self.root.resolve()):
            raise AuthError("invalid_workspace", "账号目录不可用", 503)
        return directory

    def bootstrap_owner(self, password, **kwargs):
        result = super().bootstrap_owner(password, **kwargs)
        if kwargs.get("replace_password"):
            from sqlalchemy import update
            from .models import native_sessions
            with self.database.transaction() as c:
                c.execute(update(native_sessions).where(native_sessions.c.user_id == result).values(revoked=True))
        return result
