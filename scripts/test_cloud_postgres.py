"""Run cloud tests on a disposable, loopback-only PostgreSQL (optional pgserver)."""
from pathlib import Path
import os
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fasteners
import pgserver

with tempfile.TemporaryDirectory(prefix="study-pg-tests-") as folder:
    pgserver.PostgresServer.runtime_path = Path(folder) / "runtime"
    pgserver.PostgresServer.runtime_path.mkdir()
    pgserver.PostgresServer._lock = fasteners.InterProcessLock(Path(folder) / "server.lock")
    server = pgserver.get_server(Path(folder) / "data", cleanup_mode="stop")
    os.environ["STUDY_TEST_DATABASE_URL"] = server.get_uri()
    os.environ["STUDY_TEST_ISOLATED_DATABASE"] = "1"
    os.environ["STUDY_DATABASE_URL"] = server.get_uri()
    from alembic import command
    from alembic.config import Config
    command.upgrade(Config(str(Path(__file__).resolve().parent.parent / "alembic.ini")), "head")
    suite = unittest.defaultTestLoader.loadTestsFromNames(["tests.test_cloud", "tests.test_cloud_migration"])
    success = unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful()
    server._cleanup()
sys.exit(0 if success else 1)
