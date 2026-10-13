"""Protect server-owned rows and frozen review references during manual imports."""
from contextlib import closing
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3

import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location("question_data_merge", Path(__file__).resolve().parents[1] / "deploy/question_data_merge.py")
merger = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(merger)

POOL_SCHEMA = """
CREATE TABLE pool_sources(id INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE, name TEXT, options_json TEXT, import_report_json TEXT, created_at TEXT);
CREATE TABLE pool_items(id INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE, question TEXT, answer TEXT, solution TEXT, categories_json TEXT, assignment_json TEXT, prepared_json TEXT, answer_check_json TEXT, formal_question_id INTEGER, preparing_job_id TEXT, status TEXT, version INTEGER, completeness TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE pool_categories(item_id INTEGER REFERENCES pool_items(id), category TEXT, PRIMARY KEY(item_id,category));
CREATE TABLE pool_occurrences(id INTEGER PRIMARY KEY, item_id INTEGER REFERENCES pool_items(id), source_id INTEGER REFERENCES pool_sources(id), source_key TEXT, raw_json TEXT, year_evidence_json TEXT, UNIQUE(source_id,source_key));
CREATE TABLE pool_commits(request_id TEXT PRIMARY KEY, fingerprint TEXT, result_json TEXT, created_at TEXT);
"""
REVIEW_SCHEMA = """
CREATE TABLE review_runs(run_id TEXT PRIMARY KEY, request_id TEXT UNIQUE, catalog_json TEXT, config_json TEXT, status TEXT, job_id TEXT, worker_pid INTEGER, stop INTEGER, reason TEXT);
CREATE TABLE review_items(run_id TEXT REFERENCES review_runs(run_id), item_id INTEGER, item_json TEXT, provenance_json TEXT, content_hash TEXT, cache_key TEXT, status TEXT, result_json TEXT, primary_id TEXT, secondary_json TEXT, review_status TEXT, marks_json TEXT, note TEXT, human_json TEXT, catalog_json TEXT, PRIMARY KEY(run_id,item_id));
CREATE TABLE review_cache(cache_key TEXT PRIMARY KEY,result_json TEXT,status TEXT);
CREATE TABLE review_humans(item_id INTEGER,content_hash TEXT,decision_json TEXT,PRIMARY KEY(item_id,content_hash));
CREATE TABLE review_history(id INTEGER PRIMARY KEY,run_id TEXT,item_id INTEGER,decision_json TEXT,created_at REAL);
CREATE TABLE review_usage(id INTEGER PRIMARY KEY,run_id TEXT,item_id INTEGER,stage TEXT,usage_json TEXT,created_at REAL);
CREATE TABLE review_configs(id INTEGER PRIMARY KEY,run_id TEXT,config_json TEXT,created_at REAL);
CREATE TABLE review_batch_responses(id INTEGER PRIMARY KEY,run_id TEXT,item_ids_json TEXT,response_text TEXT,validation_errors_json TEXT,created_at REAL);
"""


def db(root, family):
    return root / merger.PATHS[family]


def connect(root, family):
    return sqlite3.connect(db(root, family))


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def add_pool_item(conn, item_id=1, text="private question text", source_id=1, source_key="one"):
    conn.execute("INSERT INTO pool_sources VALUES(?,?,?,?,?,?)", (source_id, digest("source" + str(source_id)), "source", "{}", "{}", "now"))
    conn.execute("INSERT INTO pool_items VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (item_id, digest(text), text, "answer", "solution", '["category"]', '{"role":"question"}', None, None, None, None, "unreviewed", 1, "complete", "now", "now"))
    conn.execute("INSERT INTO pool_categories VALUES(?,?)", (item_id, "category"))
    conn.execute("INSERT INTO pool_occurrences VALUES(?,?,?,?,?,?)", (item_id, item_id, source_id, source_key, "{}", "{}"))


def build(root, run_id="run-one"):
    (root / ".runtime").mkdir(parents=True)
    with connect(root, "pool") as conn:
        conn.executescript(POOL_SCHEMA)
        add_pool_item(conn)
    item = {"id": 1, "version": 1, "question": "private question text", "answer": "answer", "solution": "solution", "categories": ["category"], "completeness": "complete"}
    with connect(root, "review") as conn:
        conn.executescript(REVIEW_SCHEMA)
        conn.execute("INSERT INTO review_runs VALUES(?,?,?,?,?,?,?,?,?)", (run_id, "request-one", '{"routines":[]}', '{"engine":"codex_luna"}', "done", "old-job", 999, 0, ""))
        conn.execute("INSERT INTO review_items VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (run_id, 1, json.dumps(item), '[{"source_id":1,"source_key":"one"}]', merger._digest(item), "cache-key", "classified", '{"classification":{}}', None, "[]", "pending", "[]", "", None, None))
        conn.execute("INSERT INTO review_cache VALUES(?,?,?)", ("cache-key", '{"classification":{}}', "classified"))


def main_hashes(*roots):
    return {(str(root), family): hashlib.sha256(db(root, family).read_bytes()).hexdigest() for root in roots for family in merger.PATHS if db(root, family).exists()}


def clone(source, target):
    shutil.copytree(source, target, dirs_exist_ok=True)


def parameter_cases(name, values):
    def decorate(function):
        function.parameter_values = values
        return function
    return decorate


class raises:
    def __init__(self, kind, match=None):
        self.kind, self.match, self.value = kind, match, None

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        if kind is None:
            raise AssertionError("expected " + self.kind.__name__)
        if not issubclass(kind, self.kind):
            return False
        self.value = value
        if self.match is not None and self.match not in str(value):
            raise AssertionError("expected diagnostic: " + self.match)
        return True


def test_empty_server_import_keeps_ids_and_inputs_unchanged(roots):
    source, target, candidate = roots
    before = main_hashes(source, target)
    report = merger.merge(source, target, candidate)
    assert report["tables"]["pool_items"] == {"added": 1, "total": 1}
    assert report["tables"]["review_items"] == {"added": 1, "total": 1}
    with connect(candidate, "review") as conn:
        assert conn.execute("SELECT run_id,item_id FROM review_items").fetchone() == ("run-one", 1)
        assert conn.execute("SELECT status,worker_pid,job_id FROM review_runs").fetchone() == ("done", None, None)
    assert main_hashes(source, target) == before
    assert not (target / ".runtime").exists()


def test_server_only_items_and_manual_results_survive(roots):
    source, target, candidate = roots
    clone(source, target)
    with connect(target, "pool") as conn:
        add_pool_item(conn, 2, "server-only question", 2, "two")
    with connect(target, "review") as conn:
        conn.execute("UPDATE review_items SET review_status='confirmed',note='server correction',result_json='{}',human_json='{}'")
    before = main_hashes(source, target)
    report = merger.merge(source, target, candidate)
    assert report["tables"]["pool_items"] == {"added": 0, "total": 2}
    with connect(candidate, "pool") as conn:
        assert conn.execute("SELECT question FROM pool_items WHERE id=2").fetchone()[0] == "server-only question"
    with connect(candidate, "review") as conn:
        assert conn.execute("SELECT review_status,note,result_json FROM review_items").fetchone() == ("confirmed", "server correction", "{}")
    assert main_hashes(source, target) == before


@parameter_cases("mutation", [
    "UPDATE pool_items SET question='secret conflict content' WHERE id=1",
    "UPDATE pool_sources SET fingerprint='different' WHERE id=1",
    "UPDATE pool_occurrences SET source_key='different' WHERE id=1",
])
def test_same_id_conflicts_fail_closed_without_echoing_private_rows(roots, mutation):
    source, target, candidate = roots
    clone(source, target)
    with connect(target, "pool") as conn:
        conn.execute(mutation)
    before = main_hashes(source, target)
    with raises(merger.MergeConflict) as error:
        merger.merge(source, target, candidate)
    assert "secret conflict content" not in str(error.value)
    assert main_hashes(source, target) == before
    assert list(candidate.iterdir()) == []


def test_same_fingerprint_under_another_id_requires_mapping(roots):
    source, target, candidate = roots
    build(target)
    with connect(target, "pool") as conn:
        conn.execute("UPDATE pool_items SET id=8")
        conn.execute("UPDATE pool_categories SET item_id=8")
        conn.execute("UPDATE pool_occurrences SET item_id=8")
    with connect(target, "review") as conn:
        conn.execute("DELETE FROM review_items")
        conn.execute("DELETE FROM review_runs")
    with raises(merger.MergeConflict, match="自然键"):
        merger.merge(source, target, candidate)
    assert list(candidate.iterdir()) == []


def test_distinct_nonarchived_run_is_never_silently_replaced(roots):
    source, target, candidate = roots
    build(target, run_id="server-run")
    with raises(merger.MergeConflict, match="非归档"):
        merger.merge(source, target, candidate)
    with connect(target, "review") as conn:
        assert conn.execute("SELECT run_id,status FROM review_runs").fetchone() == ("server-run", "done")


@parameter_cases("mutation", [
    "UPDATE review_items SET content_hash='invalid'",
    "UPDATE review_items SET provenance_json='[{\"source_id\":1,\"source_key\":\"absent\"}]'",
    "UPDATE review_items SET item_json='{\"id\":2}'",
    "INSERT INTO review_usage VALUES(1,'run-one',99,'matching','{}',1)",
])
def test_invalid_json_and_cross_database_references_are_rejected(roots, mutation):
    source, target, candidate = roots
    with connect(source, "review") as conn:
        conn.execute(mutation)
    with raises(merger.MergeConflict):
        merger.merge(source, target, candidate)
    assert list(candidate.iterdir()) == []
    assert not (target / ".runtime").exists()


def test_formal_question_dependency_requires_a_different_migration(roots):
    source, target, candidate = roots
    with connect(source, "pool") as conn:
        conn.execute("UPDATE pool_items SET formal_question_id=10,status='imported'")
    with raises(merger.MergeConflict, match="正式题库"):
        merger.merge(source, target, candidate)


def test_old_worker_is_paused_without_importing_a_job_ledger(roots):
    source, target, candidate = roots
    with connect(source, "review") as conn:
        conn.execute("UPDATE review_runs SET status='running'")
    merger.merge(source, target, candidate)
    with connect(candidate, "review") as conn:
        assert conn.execute("SELECT status,stop,worker_pid,job_id FROM review_runs").fetchone() == ("paused", 1, None, None)
    assert set(path.name for path in (candidate / ".runtime").iterdir()) == {"question_pool.db", "routine-review.sqlite3"}


def test_nonempty_candidate_and_inputs_are_preserved(roots):
    source, target, candidate = roots
    sentinel = candidate / "keep.txt"
    sentinel.write_text("keep")
    with raises(merger.MergeConflict, match="为空"):
        merger.merge(source, target, candidate)
    assert sentinel.read_text() == "keep"


def test_readonly_backup_includes_committed_server_wal_rows(roots):
    source, target, candidate = roots
    clone(source, target)
    with closing(connect(target, "pool")) as live:
        live.execute("PRAGMA journal_mode=WAL")
        live.execute("PRAGMA wal_autocheckpoint=0")
        add_pool_item(live, 2, "arrived in WAL", 2, "two")
        live.commit()
        assert Path(str(db(target, "pool")) + "-wal").stat().st_size > 0
        before = main_hashes(source, target)
        merger.merge(source, target, candidate)
        assert main_hashes(source, target) == before
        with connect(candidate, "pool") as conn:
            assert conn.execute("SELECT question FROM pool_items WHERE id=2").fetchone()[0] == "arrived in WAL"


def test_identical_named_columns_in_different_orders_are_compatible(roots):
    source, target, candidate = roots
    schema = "CREATE TABLE review_web_packets(packet_id TEXT PRIMARY KEY,run_id TEXT,status TEXT,snapshot_json TEXT,prompt_text TEXT,response_digest TEXT,response_json TEXT,imported_at REAL,created_at REAL)"
    with connect(source, "review") as conn:
        conn.execute(schema)
    clone(source, target)
    with connect(target, "review") as conn:
        conn.execute("DROP TABLE review_web_packets")
        conn.execute(schema.replace("response_json TEXT,imported_at REAL,created_at REAL", "imported_at REAL,created_at REAL,response_json TEXT"))
    report = merger.merge(source, target, candidate)
    assert report["tables"]["review_web_packets"] == {"added": 0, "total": 0}


def test_missing_named_column_is_rejected(roots):
    source, target, candidate = roots
    clone(source, target)
    with connect(target, "review") as conn:
        conn.execute("ALTER TABLE review_items DROP COLUMN note")
    with raises(merger.MergeConflict, match="字段结构"):
        merger.merge(source, target, candidate)
    assert list(candidate.iterdir()) == []


def test_batch_validation_error_objects_are_preserved(roots):
    source, target, candidate = roots
    with connect(source, "review") as conn:
        conn.execute("INSERT INTO review_batch_responses VALUES(?,?,?,?,?,?)", (1, "run-one", "[1]", "historical response", '{"1":["failed validation"]}', 1))
    merger.merge(source, target, candidate)
    with connect(candidate, "review") as conn:
        assert json.loads(conn.execute("SELECT validation_errors_json FROM review_batch_responses").fetchone()[0]) == {"1": ["failed validation"]}


class QuestionDataMergeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        source, target, candidate = (root / name for name in ("source", "target", "candidate"))
        build(source)
        target.mkdir()
        candidate.mkdir()
        self.roots = source, target, candidate


def _install_test(function, value=None, parameterized=False):
    def run(self):
        if parameterized:
            function(self.roots, value)
        else:
            function(self.roots)
    return run


for _name, _function in list(globals().items()):
    if not _name.startswith("test_") or not callable(_function):
        continue
    if hasattr(_function, "parameter_values"):
        for _index, _value in enumerate(_function.parameter_values):
            setattr(QuestionDataMergeTests, _name + "_" + str(_index), _install_test(_function, _value, True))
    else:
        setattr(QuestionDataMergeTests, _name, _install_test(_function))


if __name__ == "__main__":
    unittest.main()
