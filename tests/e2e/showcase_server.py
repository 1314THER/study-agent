"""Isolated project showcase server. Never loads or writes the owner's ledger."""
import os
from pathlib import Path
import socket
import sys
import tempfile


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

with tempfile.TemporaryDirectory(prefix="study-showcase-browser-") as directory:
    os.environ.update(
        STUDY_AGENT_DATA_DIR=directory,
        STUDY_AGENT_JOB_DIR=directory + "/jobs",
        STUDY_AGENT_LOG_DIR=directory + "/logs",
        STUDY_AUTH_ENABLED="0",
        STUDY_LOCAL_CODEX="0",
    )
    from backend.showcase import app
    import uvicorn

    assert not {"backend.main", "backend.demo", "backend.database", "backend.solver", "backend.teach",
                "backend.settings", "backend.jobs", "backend.routine_review", "backend.question_pool",
                "backend.account_app"}.intersection(sys.modules), (
        "The public showcase must not initialize owner, teaching or AI modules."
    )
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    print("SHOWCASE_PORT=" + str(sock.getsockname()[1]), flush=True)
    uvicorn.Server(uvicorn.Config(app, log_level="warning")).run(sockets=[sock])
    forbidden = [
        path for path in Path(directory).rglob("*")
        if path.suffix in {".db", ".sqlite", ".sqlite3"}
        or path.name in {".accounts", "question-pool", "sessions", ".demo-sessions", "settings.json", ".env"}
    ]
    if forbidden:
        raise AssertionError("Showcase created owner or visitor data: " + str(forbidden))
