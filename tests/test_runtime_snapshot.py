from contextlib import closing
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('runtime_snapshot',Path(__file__).resolve().parents[1]/'deploy/runtime_snapshot.py')
snapshot=importlib.util.module_from_spec(spec);spec.loader.exec_module(snapshot)


class RuntimeSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.source=self.root/'owner';self.source.mkdir()
        self.backup=self.root/'backup';self.target=self.root/'restored';self.target.mkdir()
        for name in ('study_agent.db','mastery.db','.runtime/question_pool.db','.runtime/routine-review.sqlite3'):
            file=self.source/name;file.parent.mkdir(parents=True,exist_ok=True)
            with closing(sqlite3.connect(file)) as db:
                db.execute('CREATE TABLE rows(value TEXT)');db.execute('INSERT INTO rows VALUES (?)',(name,));db.commit()
        for name in ('.runtime/question-pool/snapshots/source/figure.png','.runtime/question-assets/asset.png',
                     '.runtime/routine-matching/graph.json','.runtime/routine-matching/state.json','.env'):
            file=self.source/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_text('private test fixture')

    def test_complete_roundtrip_and_absent_paths_do_not_leave_upgrade_data(self):
        m=snapshot.backup(self.source,self.backup)
        self.assertIn('.runtime/routine-matching/graph.json',m['files'])
        unexpected=self.target/'.runtime/jobs.sqlite3';unexpected.parent.mkdir();unexpected.write_text('later data')
        snapshot.restore(self.backup,self.target)
        self.assertFalse(unexpected.exists())
        for name in m['files']:self.assertEqual(snapshot.sha256(self.backup/name),snapshot.sha256(self.target/name))
        self.assertEqual((self.backup/snapshot.MANIFEST).stat().st_mode&0o777,0o600)

    def test_sqlite_wal_is_merged_without_restoring_sidecars(self):
        file=self.source/'.accounts/accounts.db';file.parent.mkdir()
        db=sqlite3.connect(file);self.addCleanup(db.close);db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE accounts(name TEXT)');db.execute("INSERT INTO accounts VALUES ('owner')");db.commit()
        self.assertTrue(Path(str(file)+'-wal').exists())
        m=snapshot.backup(self.source,self.backup)
        self.assertNotIn('.accounts/accounts.db-wal',m['files'])
        with closing(sqlite3.connect(self.backup/'.accounts/accounts.db')) as saved:
            self.assertEqual(saved.execute('SELECT name FROM accounts').fetchone()[0],'owner')

    def test_tampering_or_extra_files_rejected_before_restore(self):
        snapshot.backup(self.source,self.backup)
        marker=self.target/'.env';marker.write_text('keep original')
        (self.backup/'.env').write_text('tampered')
        with self.assertRaises(ValueError):snapshot.restore(self.backup,self.target)
        self.assertEqual(marker.read_text(),'keep original')

    def test_links_and_nested_destination_are_rejected(self):
        (self.source/'.runtime/question-assets/link').symlink_to(self.source/'.env')
        with self.assertRaises(ValueError):snapshot.backup(self.source,self.backup)
        with self.assertRaises(ValueError):snapshot.backup(self.source,self.source/'.runtime/question-pool/backup')

    def test_manifest_cannot_restore_an_unmanaged_path(self):
        snapshot.backup(self.source,self.backup)
        m=json.loads((self.backup/snapshot.MANIFEST).read_text());m['files']['../../outside']={'size':1,'sha256':'x'}
        (self.backup/snapshot.MANIFEST).write_text(json.dumps(m))
        with self.assertRaises(ValueError):snapshot.restore(self.backup,self.target)

    def test_destination_symlink_is_rejected_without_overwriting_other_files(self):
        snapshot.backup(self.source,self.backup)
        external=self.root/'external';external.mkdir();(external/'unchanged').write_text('safe')
        (self.target/'.runtime').symlink_to(external)
        with self.assertRaises(ValueError):snapshot.restore(self.backup,self.target)
        self.assertEqual((external/'unchanged').read_text(),'safe')

    def test_wrong_destination_type_is_rejected_before_touching_existing_data(self):
        snapshot.backup(self.source,self.backup)
        marker=self.target/'.env';marker.write_text('original')
        (self.target/'study_agent.db').mkdir()
        with self.assertRaises(ValueError):snapshot.restore(self.backup,self.target)
        self.assertEqual(marker.read_text(),'original')

    def test_space_estimate_includes_figures_and_sqlite_databases(self):
        expected=sum(p.stat().st_size for p in self.source.rglob('*') if p.is_file())
        self.assertEqual(snapshot.required_bytes(self.source),expected)
