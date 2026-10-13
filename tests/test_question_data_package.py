"""Exercise private data export and reversible installation with real SQLite files."""
from contextlib import closing
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('question_data_package_tested', ROOT / 'deploy/question_data_package.py')
package = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package)


class QuestionDataPackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source'
        self.exported = self.root / 'exported'
        self.target = self.root / 'target'
        self.candidate = self.root / 'candidate'
        self.backup = self.root / 'backup'
        self.attachment = '.runtime/question-assets/' + 'a' * 64 + '.png'
        self.create_data(self.source)
        self.write(self.source, self.attachment, b'original attachment')

    @staticmethod
    def write(root, relative, content):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def create_data(self, root, identifier=1):
        pool = root / package.DATABASES[0]
        pool.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(pool)) as db:
            db.executescript('''
                CREATE TABLE pool_items (id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL, formal_question_id INTEGER);
                CREATE TABLE pool_sources (id INTEGER PRIMARY KEY);
                CREATE TABLE pool_occurrences (id INTEGER PRIMARY KEY);
                CREATE TABLE pool_commits (request_id TEXT PRIMARY KEY);
            ''')
            db.execute('INSERT INTO pool_items VALUES (?, ?, NULL)', (identifier, 'fingerprint-' + str(identifier)))
            db.execute('INSERT INTO pool_sources VALUES (?)', (identifier,))
            db.execute('INSERT INTO pool_occurrences VALUES (?)', (identifier,))
            db.commit()
        with closing(sqlite3.connect(root / package.DATABASES[1])) as db:
            db.executescript('''
                CREATE TABLE review_runs (run_id TEXT PRIMARY KEY, status TEXT NOT NULL,
                    worker_pid INTEGER, job_id TEXT, stop INTEGER NOT NULL DEFAULT 0, reason TEXT NOT NULL DEFAULT '');
                CREATE TABLE review_items (run_id TEXT NOT NULL, item_id INTEGER NOT NULL,
                    content_hash TEXT NOT NULL, PRIMARY KEY (run_id, item_id));
            ''')
            run_id = 'run-' + str(identifier)
            db.execute('INSERT INTO review_runs(run_id,status,worker_pid,job_id) VALUES (?, ?, ?, ?)',
                       (run_id, 'done', 12345, 'local-job'))
            db.execute('INSERT INTO review_items VALUES (?, ?, ?)', (run_id, identifier, 'content-' + str(identifier)))
            db.commit()

    def finish_export(self, required=None):
        manifest = package.export(self.source, self.exported, required or [self.attachment])
        # The shell wrapper checks the driver's checksums before execution.
        for name in package.DRIVERS:
            self.write(self.exported, name, b'fixture driver; never executed\n')
        sums = []
        for path in sorted(self.exported.rglob('*')):
            if path.is_file() and path.name != 'SHA256SUMS':
                sums.append(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.relative_to(self.exported).as_posix())
        (self.exported / 'SHA256SUMS').write_text('\n'.join(sums) + '\n')
        package.verify(self.exported)
        return manifest

    def make_candidate(self):
        for relative in package.DATABASES:
            path = self.candidate / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.exported / relative, path)

    @staticmethod
    def pool_rows(root):
        with closing(sqlite3.connect(root / package.DATABASES[0])) as db:
            return db.execute('SELECT id,fingerprint FROM pool_items ORDER BY id').fetchall()

    @staticmethod
    def review_rows(root):
        with closing(sqlite3.connect(root / package.DATABASES[1])) as db:
            return db.execute('SELECT run_id,item_id,content_hash FROM review_items ORDER BY run_id,item_id').fetchall()

    def test_export_includes_committed_wal_rows_and_keeps_source_process_state(self):
        pool_path = self.source / package.DATABASES[0]
        db = sqlite3.connect(pool_path)
        self.addCleanup(db.close)
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        db.execute('INSERT INTO pool_items VALUES (2, ?, NULL)', ('fingerprint-2',))
        db.commit()
        self.assertGreater(Path(str(pool_path) + '-wal').stat().st_size, 0)
        with closing(sqlite3.connect(pool_path.as_uri() + '?mode=ro&immutable=1', uri=True)) as main_only:
            self.assertEqual(main_only.execute('SELECT count(*) FROM pool_items').fetchone()[0], 1)
        with closing(sqlite3.connect(self.source / package.DATABASES[1])) as review:
            review.execute("UPDATE review_runs SET status='running'")
            review.commit()
        manifest = package.export(self.source, self.exported, [self.attachment])
        self.assertEqual(manifest['counts']['pool_items'], 2)
        self.assertEqual(self.pool_rows(self.exported), [(1, 'fingerprint-1'), (2, 'fingerprint-2')])
        with closing(sqlite3.connect(self.exported / package.DATABASES[1])) as saved:
            self.assertEqual(saved.execute('SELECT status,worker_pid,job_id,stop FROM review_runs').fetchone(),
                             ('interrupted', None, None, 1))
        with closing(sqlite3.connect(self.source / package.DATABASES[1])) as original:
            self.assertEqual(original.execute('SELECT status,worker_pid,job_id,stop FROM review_runs').fetchone(),
                             ('running', 12345, 'local-job', 0))
        self.assertFalse(any(p.name.endswith(('-wal', '-shm', '-journal')) for p in self.exported.rglob('*')))
        package.verify(self.exported, check_drivers=False)

    def test_export_excludes_accounts_environment_and_unrequested_files(self):
        self.write(self.source, '.accounts/owner.db', b'private account fixture')
        self.write(self.source, 'backend/.env', b'private configuration fixture')
        self.write(self.source, '.runtime/question-pool/files/unreferenced.txt', b'not selected')
        manifest = package.export(self.source, self.exported, [self.attachment])
        self.assertEqual(set(manifest['files']), set(package.DATABASES) | {self.attachment})
        self.assertFalse((self.exported / '.accounts').exists())
        self.assertFalse((self.exported / 'backend/.env').exists())

    def test_export_rejects_explicit_environment_and_account_paths(self):
        for index, relative in enumerate(('.accounts/owner.db', '.runtime/question-pool/files/.env')):
            with self.subTest(relative=relative):
                self.write(self.source, relative, b'private fixture')
                with self.assertRaisesRegex(ValueError, '范围外路径'):
                    package.export(self.source, self.root / ('rejected-' + str(index)), [relative])

    def test_finder_metadata_does_not_enter_manifest(self):
        self.exported.mkdir()
        self.write(self.source, '.runtime/question-pool/files/.DS_Store', b'Finder metadata')
        manifest = package.export(self.source, self.exported, [self.attachment])
        self.write(self.exported, '.DS_Store', b'Finder metadata')
        self.write(self.exported, '.runtime/.DS_Store', b'nested Finder metadata')
        self.assertFalse(any(Path(name).name == '.DS_Store' for name in manifest['files']))
        package.verify(self.exported, check_drivers=False)

    def test_same_attachment_name_with_different_content_refuses_before_mutation(self):
        self.finish_export()
        self.make_candidate()
        self.create_data(self.target, identifier=7)
        self.write(self.target, self.attachment, b'existing different attachment')
        before_pool, before_review = self.pool_rows(self.target), self.review_rows(self.target)
        with self.assertRaisesRegex(ValueError, '同名附件'):
            package.apply(self.exported, self.candidate, self.target, self.backup)
        self.assertEqual(self.pool_rows(self.target), before_pool)
        self.assertEqual(self.review_rows(self.target), before_review)
        self.assertEqual((self.target / self.attachment).read_bytes(), b'existing different attachment')
        self.assertFalse(self.backup.exists())

    def test_rollback_restores_both_databases_and_removes_new_attachment_after_partial_apply(self):
        self.finish_export()
        self.make_candidate()
        self.create_data(self.target, identifier=7)
        before_pool, before_review = self.pool_rows(self.target), self.review_rows(self.target)
        real_install = package.atomic_install

        def fail_review_install(source, target, uid=None, gid=None):
            if target == self.target / package.DATABASES[1]:
                raise OSError('simulated second database installation failure')
            return real_install(source, target, uid, gid)

        with patch.object(package, 'atomic_install', side_effect=fail_review_install):
            with self.assertRaisesRegex(OSError, 'simulated'):
                package.apply(self.exported, self.candidate, self.target, self.backup)
        self.assertTrue((self.target / self.attachment).exists())
        self.assertEqual(self.pool_rows(self.target), [(1, 'fingerprint-1')])
        self.assertEqual(self.review_rows(self.target), before_review)
        package.rollback(self.target, self.backup)
        self.assertEqual(self.pool_rows(self.target), before_pool)
        self.assertEqual(self.review_rows(self.target), before_review)
        self.assertFalse((self.target / self.attachment).exists())

    def test_repeated_apply_skips_existing_attachment_and_does_not_register_it_for_rollback(self):
        self.finish_export()
        self.make_candidate()
        self.create_data(self.target)
        package.apply(self.exported, self.candidate, self.target, self.backup)
        path = self.target / self.attachment
        original_stat = path.stat()
        second_backup = self.root / 'second-backup'
        with patch.object(package, 'atomic_install', wraps=package.atomic_install) as installs:
            package.apply(self.exported, self.candidate, self.target, second_backup)
        self.assertEqual(path.stat().st_ino, original_stat.st_ino)
        self.assertEqual(path.stat().st_mtime_ns, original_stat.st_mtime_ns)
        self.assertEqual(len(installs.call_args_list), 2)
        self.assertTrue(all(call.args[1] != path for call in installs.call_args_list))
        ledger = json.loads((second_backup / package.LEDGER).read_text())
        self.assertEqual(ledger['added_files'], [])
        package.rollback(self.target, second_backup)
        self.assertEqual(path.read_bytes(), b'original attachment')

    def test_verify_rejects_corrupted_payload(self):
        self.finish_export()
        (self.exported / self.attachment).write_bytes(b'corrupted')
        with self.assertRaisesRegex(ValueError, '文件校验失败'):
            package.verify(self.exported)

    def test_verify_rejects_manifest_counts_and_out_of_scope_entries(self):
        original = self.finish_export()
        for label in ('counts', 'outside', 'missing-database'):
            with self.subTest(damage=label):
                damaged = json.loads(json.dumps(original))
                if label == 'counts':
                    damaged['counts']['pool_items'] += 1
                elif label == 'outside':
                    damaged['files']['backend/.env'] = {'size': 0, 'sha256': '0' * 64}
                else:
                    del damaged['files'][package.DATABASES[0]]
                (self.exported / package.MANIFEST).write_text(json.dumps(damaged))
                with self.assertRaises(ValueError):
                    package.verify(self.exported)

    def test_verify_rejects_an_unlisted_file(self):
        self.finish_export()
        self.write(self.exported, '.runtime/question-pool/files/unlisted.txt', b'unlisted fixture')
        with self.assertRaisesRegex(ValueError, '清单不一致'):
            package.verify(self.exported)

    def test_verify_live_rejects_missing_attachment(self):
        self.finish_export()
        self.make_candidate()
        self.create_data(self.target)
        package.apply(self.exported, self.candidate, self.target, self.backup)
        (self.target / self.attachment).unlink()
        with self.assertRaises(ValueError):
            package.verify_live(self.exported, self.target)


if __name__ == '__main__':
    unittest.main()
