"""Run the release's optional import gate and actual maintenance guards."""

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "deploy/sync-sites.sh").read_text()
GATE_MARKER = '# Optional gate for this release:'
GATE_START = SCRIPT.index('    python3 - "$APP_DIR" <<\'PY\'\n', SCRIPT.index(GATE_MARKER)) + len('    python3 - "$APP_DIR" <<\'PY\'\n')
GATE = SCRIPT[GATE_START:SCRIPT.index('\nPY\n', GATE_START)]
STATUS_START = SCRIPT.index('state = json.load(open(sys.argv[1], encoding="utf-8"))', SCRIPT.index('LEGACY=()'))
STATUS = 'import json, sys\n' + SCRIPT[STATUS_START:SCRIPT.index('\nPY\n', STATUS_START)]
RUN = 'a4b37d61d62147939df3b08634e7cbb5'


class QuestionImportReleaseGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.runtime = self.root / '.runtime'
        self.runtime.mkdir()
        self.pool = self.runtime / 'question_pool.db'
        self.review = self.runtime / 'routine-review.sqlite3'
        with sqlite3.connect(self.pool) as db:
            for table, count in (('pool_items', 23255), ('pool_sources', 61), ('pool_occurrences', 23536)):
                db.execute('CREATE TABLE ' + table + '(id INTEGER PRIMARY KEY)')
                db.executemany('INSERT INTO ' + table + ' VALUES(?)', ((i,) for i in range(count)))
        with sqlite3.connect(self.review) as db:
            db.execute('CREATE TABLE review_runs(run_id TEXT PRIMARY KEY,status TEXT)')
            db.execute('INSERT INTO review_runs VALUES(?,?)', (RUN, 'done'))
            db.execute('CREATE TABLE review_items(run_id TEXT,item_id INTEGER,primary_id INTEGER)')
            db.executemany('INSERT INTO review_items VALUES(?,?,?)', ((RUN, i, 1 if i < 17005 else None) for i in range(23255)))

    def gate(self):
        return subprocess.run([sys.executable, '-c', GATE, str(self.root)], capture_output=True, text=True)

    def assert_blocked(self):
        response = self.gate()
        self.assertNotEqual(response.returncode, 0)
        self.assertIn('请先完成本轮23,255题和审核导入；网站尚未停止', response.stderr)
        return response

    def test_complete_import_passes_without_changing_databases(self):
        before = [hashlib.sha256(path.read_bytes()).hexdigest() for path in (self.pool, self.review)]
        result = self.gate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('检查通过', result.stdout)
        self.assertEqual(before, [hashlib.sha256(path.read_bytes()).hexdigest() for path in (self.pool, self.review)])

    def test_later_archive_and_added_rows_do_not_block_release(self):
        with sqlite3.connect(self.review) as db:
            db.execute("UPDATE review_runs SET status='archived'")
            db.execute('INSERT INTO review_runs VALUES(?,?)', ('later-run', 'done'))
        with sqlite3.connect(self.pool) as db:
            db.execute('INSERT INTO pool_items VALUES(50000)')
        result = self.gate()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_each_required_pool_count_is_checked(self):
        for table in ('pool_items', 'pool_sources', 'pool_occurrences'):
            with self.subTest(table=table):
                with sqlite3.connect(self.pool) as db:
                    value = db.execute('SELECT max(id) FROM ' + table).fetchone()[0]
                    db.execute('DELETE FROM ' + table + ' WHERE id=?', (value,))
                self.assert_blocked()
                with sqlite3.connect(self.pool) as db:
                    db.execute('INSERT INTO ' + table + ' VALUES(?)', (value,))

    def test_both_required_review_counts_are_checked(self):
        with sqlite3.connect(self.review) as db:
            db.execute('UPDATE review_items SET primary_id=NULL WHERE item_id=0')
        self.assert_blocked()
        with sqlite3.connect(self.review) as db:
            db.execute('UPDATE review_items SET primary_id=1 WHERE item_id=0')
            db.execute('DELETE FROM review_items WHERE item_id=23254')
        self.assert_blocked()

    def test_batch_must_exist_even_when_other_snapshots_are_present(self):
        with sqlite3.connect(self.review) as db:
            db.execute('UPDATE review_runs SET run_id=?', ('different-run',))
        self.assert_blocked()

    def test_missing_database_or_schema_fails_clearly_without_creating_database(self):
        self.pool.unlink()
        self.assert_blocked()
        self.assertFalse(self.pool.exists())
        with sqlite3.connect(self.pool) as db:
            db.execute('CREATE TABLE wrong_schema(id INTEGER)')
        self.assert_blocked()

    def test_committed_wal_rows_are_seen_without_immutable_mode(self):
        with sqlite3.connect(self.pool) as db:
            db.execute('DELETE FROM pool_items WHERE id=23254')
        connection = sqlite3.connect(self.pool)
        self.addCleanup(connection.close)
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('PRAGMA wal_autocheckpoint=0')
        connection.execute('INSERT INTO pool_items VALUES(23254)')
        connection.commit()
        self.assertTrue(Path(str(self.pool) + '-wal').is_file())
        result = self.gate()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_database_symlink_is_rejected(self):
        saved = self.root / 'elsewhere.db'
        self.pool.rename(saved)
        self.pool.symlink_to(saved)
        self.assert_blocked()


class SyncMaintenanceGuardTests(unittest.TestCase):
    def test_real_owner_path_guard_accepts_only_default_owner_storage(self):
        marker = "systemctl show study-agent -p ExecStart -p Environment --value | python3 -c '\n"
        start = SCRIPT.index(marker) + len(marker)
        guard = SCRIPT[start:SCRIPT.index("\n'\nif systemctl cat", start)]
        for environment, allowed in (("", True), ("STUDY_OWNER_DATA_DIR=/opt/study-agent", True),
                                     ("STUDY_AUTH_ENABLED=1 STUDY_OWNER_DATA_DIR=/srv/outside-owner", False),
                                     ("STUDY_OWNER_DATA_DIR=/opt/study-agent/other", False),
                                     ("STUDY_OWNER_DATA_DIR=/opt/study-agent STUDY_OWNER_DATA_DIR=/srv/another", False)):
            with self.subTest(environment=environment):
                unit = "backend.main:app --host 127.0.0.1 --port 8000 --workers 1\n" + environment + "\n"
                result = subprocess.run([sys.executable, '-c', guard], input=unit, capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, allowed, result.stderr)
                if not allowed:
                    self.assertIn('当前脚本只支持默认目录', result.stderr)

    def test_initial_state_must_be_valid_and_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'status.json'
            for state, ready in (({'draining':False, 'active_requests':0, 'active_jobs':0}, True),
                                 ({'draining':True, 'active_requests':0, 'active_jobs':0}, False),
                                 ({'draining':0, 'active_requests':0, 'active_jobs':0}, False),
                                 ({'active_requests':0, 'active_jobs':0}, False),
                                 ({'draining':False, 'active_requests':True, 'active_jobs':0}, False)):
                path.write_text(json.dumps(state))
                result = subprocess.run([sys.executable, '-c', STATUS, str(path)], capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, ready, result.stderr)

    @unittest.skipUnless(os.name == 'posix', 'Bash guard test')
    def test_leftover_question_import_dropin_blocks_before_synchronization(self):
        with tempfile.TemporaryDirectory() as directory:
            block = SCRIPT[SCRIPT.index('dropin() {'):SCRIPT.index('verify_demo_tree() {')]
            block = block.replace('/run/systemd/system', directory)
            result = subprocess.run(['bash', '-c', 'set -Eeuo pipefail\n' + block + '\nassert_no_dropins'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            dropin = Path(directory) / 'study-agent.service.d/91-study-agent-data-import.conf'
            dropin.parent.mkdir()
            dropin.write_text('[Service]\nEnvironment=STUDY_DEPLOY_DRAIN=1\n')
            result = subprocess.run(['bash', '-c', 'set -Eeuo pipefail\n' + block + '\nassert_no_dropins'], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('题库导入维护配置', result.stderr)

    def test_optional_gate_precedes_fetch_and_drain_after_lock_and_path_checks(self):
        gate = SCRIPT.index(GATE_MARKER)
        self.assertLess(SCRIPT.index('flock -n 9'), gate)
        self.assertLess(SCRIPT.index('STUDY_AGENT_(?:DATA|JOB)_DIR'), gate)
        self.assertLess(gate, SCRIPT.index('# The offline bootstrap passes'))
        self.assertLess(gate, SCRIPT.index('set_drain "$port" true'))
        self.assertIn('STUDY_SYNC_REQUIRE_QUESTION_IMPORT:-0', SCRIPT[:gate + 500])


if __name__ == '__main__':
    unittest.main()
