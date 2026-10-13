"""Exercise the importer's actual process and live-state checks."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = (Path(__file__).resolve().parents[1] / 'deploy/import-question-data.sh').read_text()
PROCESS_CHECK = SCRIPT.split('"$PYTHON" - "$OWNER_PID" "$APP_DIR" <<\'PY\'\n', 1)[1].split('\nPY\n', 1)[0]
STATUS_FUNCTION = SCRIPT[SCRIPT.index('check_status() {'):SCRIPT.index('assert_no_dropins() {')]


class QuestionDataImportGuardTests(unittest.TestCase):
    def process_check(self, entries):
        payload = b'\0'.join(key.encode() + b'=' + value.encode() for key, value in entries.items()) + b'\0'
        with patch.object(sys, 'argv', ['process-check', '123', '/opt/study-agent']), patch.object(Path, 'read_bytes', return_value=payload):
            exec(compile(PROCESS_CHECK, 'actual-import-process-check', 'exec'), {})

    def status_check(self, state):
        import json
        with tempfile.TemporaryDirectory() as directory:
            status = Path(directory) / 'status.json'; status.write_text(json.dumps(state))
            return subprocess.run(['bash', '-c', 'set -Eeuo pipefail\n' + STATUS_FUNCTION + '\ncheck_status "$STATUS" ready'],
                                  env={**os.environ, 'PYTHON':sys.executable, 'STATUS':str(status)}, text=True, capture_output=True)

    def test_completed_release_startup_flag_does_not_block_live_ready_service(self):
        self.process_check({'STUDY_DEPLOY_DRAIN':'1'})
        result = self.status_check({'draining':False, 'active_requests':0, 'active_jobs':0})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_live_maintenance_still_blocks_import(self):
        self.process_check({'STUDY_DEPLOY_DRAIN':'1'})
        result = self.status_check({'draining':True, 'active_requests':0, 'active_jobs':0})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('已处于维护状态', result.stderr)

    def test_custom_data_path_still_blocks_import(self):
        with self.assertRaises(SystemExit):
            self.process_check({'STUDY_AGENT_DATA_DIR':'/opt/study-agent'})

    def test_invalid_live_status_still_blocks_import(self):
        result = self.status_check({'draining':False, 'active_requests':True, 'active_jobs':0})
        self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
