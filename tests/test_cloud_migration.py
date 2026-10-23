import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from sqlalchemy import select, func
from backend.storage.database import Database
from backend.storage.migration import snapshot, import_bundle, inspect_bundle, export_cloud, verify_import
from backend.storage import models as m


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.owner = self.root / "owner"; self.owner.mkdir()
        with sqlite3.connect(self.owner / "study_agent.db") as c:
            c.executescript("CREATE TABLE questions (id INTEGER PRIMARY KEY, content TEXT, answer_json TEXT, source_type TEXT); CREATE TABLE practice_records(id INTEGER PRIMARY KEY, question_id INTEGER, correct INTEGER, student_answer TEXT, grade_json TEXT);")
            c.execute("INSERT INTO questions VALUES (1,'私有题',?,'模拟题')", (json.dumps({"final_answer": "2"}),))
            c.execute("INSERT INTO questions VALUES (2,'公共题',?,'精选母题')", (json.dumps({"final_answer": "3"}),))
            c.execute("INSERT INTO practice_records VALUES (1,1,1,'2',?)", (json.dumps({"is_correct": True}),))
        with sqlite3.connect(self.owner / "mastery.db") as c:
            c.executescript("CREATE TABLE patterns(id INTEGER PRIMARY KEY, name TEXT); CREATE TABLE pattern_mastery(id INTEGER PRIMARY KEY, pattern_id INTEGER, state TEXT);")
            c.execute("INSERT INTO patterns VALUES (1,'函数套路')")
            c.execute("INSERT INTO pattern_mastery VALUES (1,1,'first_pass')")
        self.bundle = self.root / "bundle"
        snapshot(self.owner, None, self.bundle)
        url = os.environ.get("STUDY_TEST_DATABASE_URL", "sqlite:///:memory:")
        if "STUDY_TEST_DATABASE_URL" in os.environ and os.environ.get("STUDY_TEST_ISOLATED_DATABASE") != "1": raise RuntimeError("隔离数据库标记缺失")
        self.db = Database(url)
        if self.db.engine.dialect.name == "postgresql": m.metadata.drop_all(self.db.engine)
        self.db.create_schema(); self.addCleanup(self.db.engine.dispose)

    def count(self, table):
        with self.db.transaction() as c: return c.scalar(select(func.count()).select_from(table))

    def test_dry_run_does_not_write_and_import_is_idempotent(self):
        report = import_bundle(self.db, self.bundle, self.root / "assets")
        self.assertFalse(report["applied"]); self.assertEqual(self.count(m.questions), 0)
        import_bundle(self.db, self.bundle, self.root / "assets", apply=True)
        self.assertEqual(self.count(m.questions), 2)
        self.assertTrue(verify_import(self.db, self.bundle, self.root / "assets")["verified"])
        self.assertEqual(self.count(m.attempts), 1)
        self.assertEqual(self.count(m.patterns), 1)
        self.assertTrue(import_bundle(self.db, self.bundle, self.root / "assets", apply=True)["already_imported"])
        self.assertEqual(self.count(m.questions), 2)
        with self.db.transaction() as c:
            attempt = c.execute(select(m.attempts)).first()
            alias = c.execute(select(m.aliases.c.resource_id).where(m.aliases.c.resource == "questions.questions", m.aliases.c.legacy_id == "1")).scalar()
            self.assertEqual(attempt.question_id, alias)
            self.assertEqual(attempt.user_id, "studyadmin")
        original = sqlite3.connect(self.owner / "study_agent.db")
        self.assertEqual(original.execute("SELECT count(*) FROM questions").fetchone()[0], 2); original.close()

    def test_bundle_tampering_is_rejected_before_import(self):
        target = self.bundle / "workspaces/studyadmin/study_agent.db"
        with target.open("ab") as f: f.write(b"tampered")
        with self.assertRaises(ValueError): import_bundle(self.db, self.bundle, self.root / "assets", apply=True)
        self.assertEqual(self.count(m.users), 0)

    def test_missing_question_rolls_back_whole_import(self):
        with sqlite3.connect(self.owner / "study_agent.db") as c: c.execute("UPDATE practice_records SET question_id=999")
        broken = self.root / "broken"; snapshot(self.owner, None, broken)
        with self.assertRaises(ValueError): import_bundle(self.db, broken, self.root / "assets", apply=True)
        self.assertEqual(self.count(m.users), 0); self.assertEqual(self.count(m.questions), 0)

    def test_cloud_export_keeps_new_writes_and_never_overwrites(self):
        import_bundle(self.db, self.bundle, self.root / "assets", apply=True)
        output = self.root / "export.jsonl"; export_cloud(self.db, output)
        rows = [json.loads(line) for line in output.read_text().splitlines()]
        self.assertTrue(any(r["table"] == "learning.attempts" for r in rows))
        self.assertTrue(any(r["table"] == "auth.users" for r in rows))
        with self.assertRaises(ValueError): export_cloud(self.db, output)

    def test_user_integer_ids_and_shared_negative_ids_keep_their_owners(self):
        from backend.auth import AccountStore
        from cryptography.fernet import Fernet
        from tests.test_cloud import Mailer
        accounts = self.root / "accounts"
        mailer = Mailer()
        store = AccountStore(accounts, self.owner, encryption_key=Fernet.generate_key(), mailer=mailer)
        store.bootstrap_owner("owner-password-123")
        identities = []
        for name in ("alice", "bob"):
            email = name + "@example.com"
            store.send_email_code(email, name)
            _, user, _ = store.register(name, email, mailer.codes[email], "test-password-123", "sk-example-private", name)
            identities.append(user["id"])
            directory = accounts / "users" / ("user-" + user["id"]); directory.mkdir()
            with sqlite3.connect(directory / "study_agent.db") as c:
                c.executescript("CREATE TABLE questions (id INTEGER PRIMARY KEY, content TEXT, answer_json TEXT, catalog_id INTEGER); CREATE TABLE practice_records(id INTEGER PRIMARY KEY, question_id INTEGER, correct INTEGER, student_answer TEXT);")
                c.execute("INSERT INTO questions VALUES (1,?,?,NULL)", (name + "私有题", json.dumps({"final_answer": "2"})))
                c.execute("INSERT INTO questions VALUES (-2,?,?,2)", ("公共题旧版" if name == "alice" else "公共题", json.dumps({"final_answer": "2" if name == "alice" else "3"})))
                c.execute("INSERT INTO practice_records VALUES (1,-2,1,'2')")
            with sqlite3.connect(directory / "mastery.db") as c:
                c.executescript("CREATE TABLE patterns(id INTEGER PRIMARY KEY, name TEXT, catalog_id INTEGER); CREATE TABLE pattern_mastery(id INTEGER PRIMARY KEY, pattern_id INTEGER, state TEXT);")
                c.execute("INSERT INTO patterns VALUES (-1,'函数套路',1)")
                c.execute("INSERT INTO pattern_mastery VALUES (1,-1,'first_pass')")
        bundle = self.root / "all-users"
        snapshot(self.owner, accounts, bundle)
        import_bundle(self.db, bundle, self.root / "assets", apply=True)
        self.assertTrue(verify_import(self.db, bundle, self.root / "assets")["verified"])
        with self.db.transaction() as c:
            aliases = list(c.execute(select(m.aliases).where(m.aliases.c.resource == "questions.questions", m.aliases.c.legacy_id == "1")))
            self.assertEqual(len({a.resource_id for a in aliases}), 3)
            shared = list(c.scalars(select(m.aliases.c.resource_id).where(m.aliases.c.resource == "questions.questions", m.aliases.c.legacy_id == "-2")))
            self.assertEqual(len(set(shared)), 1)
            public = c.execute(select(m.questions).where(m.questions.c.id == shared[0])).first()
            self.assertIsNone(public.owner_user_id)
            self.assertEqual(public.content, "公共题")
            attempt = c.execute(select(m.attempts).where(m.attempts.c.user_id == identities[0])).first()
            version = c.execute(select(m.question_versions).where(m.question_versions.c.question_id == attempt.question_id, m.question_versions.c.revision == attempt.question_revision)).first()
            self.assertEqual(version.data["content"], "公共题旧版")
            pattern_ids = set(c.scalars(select(m.aliases.c.resource_id).where(m.aliases.c.resource == "mastery.patterns")))
            self.assertEqual(len(pattern_ids), 1)
            self.assertEqual(self.count(m.questions), 4)


if __name__ == "__main__": unittest.main()
