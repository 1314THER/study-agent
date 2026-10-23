from contextlib import contextmanager
from contextvars import ContextVar
import os
import threading
from sqlalchemy import create_engine, event, text
from sqlalchemy.pool import StaticPool
from .models import metadata, SCHEMAS

_repository = ContextVar("cloud_repository", default=None)


def current_repository():
    return _repository.get()


@contextmanager
def repository_context(repository):
    token = _repository.set(repository)
    try:
        yield repository
    finally:
        _repository.reset(token)


class Database:
    def __init__(self, url=None):
        url = url or os.environ["STUDY_DATABASE_URL"]
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        sqlite = url.startswith("sqlite")
        kwargs = {"pool_pre_ping": True}
        self.lock = threading.RLock()
        if sqlite:
            kwargs.update(connect_args={"check_same_thread": False})
            if ":memory:" in url:
                kwargs["poolclass"] = StaticPool
        self.engine = create_engine(url, **kwargs)
        if sqlite:
            # SQLite's DDL compiler does not use the Table SQL compiler. Attach one
            # database per schema, including for foreign-key and migration tests.
            @event.listens_for(self.engine, "connect")
            def attach(conn, record):
                from pathlib import Path
                conn.execute("PRAGMA foreign_keys=ON")
                for name in SCHEMAS:
                    path = ":memory:" if ":memory:" in url else str(Path(url.split("///", 1)[1]).absolute()) + "." + name
                    conn.execute(f'ATTACH DATABASE ? AS "{name}"', (path,))
            # Cross-schema FK enforcement is PostgreSQL-only. SQLite is a smoke
            # backend, never a substitute for PostgreSQL integration tests.

    @contextmanager
    def transaction(self):
        if self.engine.dialect.name == "sqlite":
            with self.lock, self.engine.begin() as conn:
                yield conn
        else:
            with self.engine.begin() as conn:
                yield conn

    def create_schema(self):
        if self.engine.dialect.name == "postgresql":
            with self.transaction() as conn:
                for name in SCHEMAS:
                    conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{name}"'))
        metadata.create_all(self.engine)
        from .constraints import install_ownership_guards
        with self.transaction() as conn:
            install_ownership_guards(conn)
