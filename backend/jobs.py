"""Workspace-scoped, durable background tasks for the owner and visitor apps.

HTTP acceptance is independent of the page that submitted a task. Two daemon
workers run domain functions directly; SQLite records restore progress/results
after navigation and mark unfinished work interrupted after a process restart.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from dataclasses import dataclass, field
from hashlib import sha256
import inspect
import json
import logging
import math
import os
from pathlib import Path
import queue
import shutil
import sqlite3
import threading
import time
import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from backend.data_paths import acquire_background_lease, data_path, workspace_directory

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent
KINDS = {"solve", "teach_start", "teach_legacy_start", "teach_chat", "teach_check", "teach_ack", "teach_finish",
         "generate", "grade", "parse_file", "ocr_file", "batch_solve", "agent",
         "pattern_check", "pattern_variants", "provider_test", "pool_prepare", "pool_import", "pool_collect", "routine_match"}
TERMINAL = {"done", "error", "interrupted"}
PRESET_TIMEOUT_SECONDS = 300
_CURRENT = ContextVar("study_background_job", default=None)
PROVIDER_CONCURRENCY = 20
_SHARED_PROVIDER_LIMIT = threading.BoundedSemaphore(PROVIDER_CONCURRENCY)
_PROVIDERS = {name: _SHARED_PROVIDER_LIMIT for name in ("deepseek", "codex")}
_PROVIDER_LOCK = threading.Lock()
_PROVIDER_ACTIVE = 0


def _history_ttl():
    from backend.identity import current_identity
    identity = current_identity()
    visitor = identity and identity.get("role") == "guest"
    legacy_visitor = identity is None and workspace_directory() is not None
    return 7200 if visitor or legacy_visitor else 7 * 86400


def _valid_id(value):
    return isinstance(value, int) and not isinstance(value, bool) and value != 0


class JobConflict(ValueError):
    pass


class JobBusy(RuntimeError):
    pass


class JobStopped(RuntimeError):
    pass


def current_job_id():
    ctx = _CURRENT.get()
    return ctx.job_id if ctx else None


def ensure_active():
    ctx = _CURRENT.get()
    if ctx and (ctx.finished.is_set() or (ctx.deadline is not None and time.monotonic() >= ctx.deadline)):
        raise JobStopped("任务已经结束，停止后续 AI 调用。")


def request_timeout(default):
    ensure_active()
    ctx = _CURRENT.get()
    if ctx and ctx.deadline is not None:
        return max(0.1, min(float(default), ctx.deadline - time.monotonic()))
    return float(default)


@contextmanager
def provider_slot(provider):
    """One limit shared by all tasks, their child threads and legacy requests."""
    global _PROVIDER_ACTIVE
    slot = _PROVIDERS[provider]
    ctx = _CURRENT.get()
    reserved = bool(ctx and ctx.reserved_provider == provider)
    if reserved:
        ctx.reserved_provider = None
    else:
        while not slot.acquire(timeout=0.2):
            ensure_active()
    entered = False
    try:
        ensure_active()
        with _PROVIDER_LOCK:
            _PROVIDER_ACTIVE += 1
            entered = True
        yield
    finally:
        with _PROVIDER_LOCK:
            # ensure_active may raise before the counter is incremented.
            if entered:
                _PROVIDER_ACTIVE -= 1
        slot.release()


def storage_path():
    owner_dir = Path(os.environ.get("STUDY_AGENT_JOB_DIR", str(ROOT / ".runtime")))
    return Path(data_path("jobs.sqlite3", owner_dir / "jobs.sqlite3"))


def _safe_upload_directory(ledger_path, directory):
    """Return only a real upload child of this ledger's private upload root."""
    if not directory:
        return None
    base = Path(ledger_path).parent.resolve() / "job-uploads"
    candidate = Path(os.path.abspath(os.fspath(directory)))
    if (base.is_symlink() or candidate.parent.resolve() != base or not candidate.name.startswith("upload-")
            or candidate.is_symlink() or not candidate.is_dir()):
        return None
    resolved = candidate.resolve()
    return resolved if resolved.parent == base else None


def _remove_upload_directory(ledger_path, directory):
    candidate = _safe_upload_directory(ledger_path, directory)
    if candidate is not None:
        shutil.rmtree(candidate, ignore_errors=True)


def storage_connection():
    """Also used by teaching persistence, in the identical workspace scope."""
    path = storage_path()
    _manager.prepare(path)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


@dataclass
class Outcome:
    value: dict
    commit: object = None
    source: str = "live_ai"


@dataclass
class Runtime:
    manager: object
    job_id: str
    path: Path
    kind: str
    args: dict
    release: object
    deadline: object = None
    prepared: object = None
    finished: object = field(default_factory=threading.Event)
    timer: object = None
    upload_dir: object = None
    reserved_provider: object = None
    children: int = 0
    worker_done: bool = False
    released: bool = False

    def progress(self, stage, progress, detail):
        ensure_active()
        self.manager.progress(self, stage, progress, detail)


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _public(row, full=True):
    result = dict(row)
    args = json.loads(result.pop("args_json"))
    args.pop("_upload_path", None)
    args.pop("_upload_dir", None)
    result["args"] = args
    result.pop("fingerprint", None)
    result.pop("runtime_id", None)
    result.pop("request_id", None)
    stored_result = result.pop("result_json")
    stored_error = result.pop("error_json")
    if full:
        result["result"] = json.loads(stored_result) if stored_result else None
    result["error"] = json.loads(stored_error) if stored_error else None
    return result


class JobManager:
    def __init__(self, *, workers=2, runners=None):
        self.lock = threading.RLock()
        # Teaching persistence may initialize its ledger while holding the
        # teaching lock. Initialization must never wait for the submission lock,
        # since submission holds that lock before reserving a teaching turn.
        self.prepare_lock = threading.RLock()
        self.runtime_id = uuid.uuid4().hex
        self.prepared_paths = set()
        self.runtimes = {}
        self.pending = queue.Queue(maxsize=40)
        self.workers = max(1, min(2, workers))
        self.threads = []
        self.draining = False
        self.runners = runners

    def prepare(self, path):
        path = Path(path)
        if str(path) in self.prepared_paths:
            return
        with self.prepare_lock:
            if str(path) in self.prepared_paths:
                return
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with sqlite3.connect(str(path), timeout=10) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("CREATE TABLE IF NOT EXISTS jobs (job_id TEXT PRIMARY KEY, kind TEXT NOT NULL, "
                             "request_id TEXT NOT NULL UNIQUE, fingerprint TEXT NOT NULL, args_json TEXT NOT NULL, "
                             "status TEXT NOT NULL, stage TEXT NOT NULL, progress INTEGER NOT NULL, detail TEXT NOT NULL, "
                             "created_at REAL NOT NULL, updated_at REAL NOT NULL, result_json TEXT, error_json TEXT, "
                             "source TEXT, runtime_id TEXT NOT NULL)")
                conn.execute("CREATE TABLE IF NOT EXISTS teaching_sessions (session_id TEXT PRIMARY KEY, "
                             "state_json TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0, pending_job TEXT, "
                             "created_at REAL NOT NULL, updated_at REAL NOT NULL)")
                conn.execute("UPDATE jobs SET status='interrupted', stage='interrupted', "
                             "detail='服务已重启，请查看已保存的结果或重新开始任务。', "
                             "error_json=?, updated_at=? WHERE status IN ('queued','running') AND runtime_id<>?",
                             (_dump({"code": "interrupted", "detail": "服务重启，未自动重试，以免重复调用或保存。"}),
                              time.time(), self.runtime_id))
                conn.execute("UPDATE teaching_sessions SET pending_job=NULL WHERE pending_job IN "
                             "(SELECT job_id FROM jobs WHERE status IN ('interrupted','error','done'))")
                active_uploads = set()
                for (args_json,) in conn.execute("SELECT args_json FROM jobs WHERE status IN ('queued','running')"):
                    try:
                        directory = _safe_upload_directory(path, json.loads(args_json).get("_upload_dir"))
                        if directory is not None:
                            active_uploads.add(directory)
                    except (ValueError, TypeError, AttributeError):
                        continue
            # The old process cannot finish interrupted recognition tasks.
            # Reclaim their bodies and uploads abandoned before job acceptance,
            # while leaving this runtime's accepted files and symlinks alone.
            upload_root = path.parent.resolve() / "job-uploads"
            if upload_root.is_dir() and not upload_root.is_symlink():
                for directory in upload_root.iterdir():
                    if directory not in active_uploads:
                        _remove_upload_directory(path, directory)
            os.chmod(path, 0o600)
            self.prepared_paths.add(str(path))

    def _connection(self, path):
        self.prepare(path)
        conn = sqlite3.connect(str(path), timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _start_workers(self):
        if self.threads:
            return
        for n in range(self.workers):
            worker = threading.Thread(target=self._worker, name=f"study-ai-job-{n}", daemon=True)
            worker.start()
            self.threads.append(worker)

    def submit(self, kind, args, request_id, *, fingerprint_args=None):
        if kind not in KINDS:
            raise ValueError("未知任务类型")
        if not isinstance(request_id, str) or not 8 <= len(request_id) <= 128:
            raise ValueError("request_id 必须是 8 至 128 字符的唯一请求编号")
        args = validate_args(kind, args)
        path = storage_path()
        fingerprint = sha256(_dump({"kind": kind, "args": fingerprint_args if fingerprint_args is not None else args}).encode()).hexdigest()
        with self.lock:
            with self._connection(path) as conn:
                previous = conn.execute("SELECT * FROM jobs WHERE request_id=?", (request_id,)).fetchone()
                if previous:
                    if previous["fingerprint"] != fingerprint:
                        raise JobConflict("同一请求编号不能用于不同任务，请刷新任务状态。")
                    return _public(previous)
                if self.draining:
                    raise JobBusy("服务器正在更新，现有任务会继续，请稍后提交新任务。")
                if len(self.runtimes) >= 40:
                    raise JobBusy("后台任务较多，请稍后再试。")
                self._start_workers()
                job_id = uuid.uuid4().hex
                if kind in ("teach_chat", "teach_ack", "teach_finish"):
                    from backend.teach import reserve_teaching_job, TeachingConflict
                    try:
                        reserve_teaching_job(args["session_id"], job_id, args.get("expected_revision"))
                    except TeachingConflict as exc:
                        raise JobConflict(str(exc)) from exc
                if kind == "grade" and args.get("loop"):
                    from backend.patterns import reserve_loop_grade, LoopConflict
                    try:
                        reserve_loop_grade(args["loop"], args["question_id"], job_id)
                    except LoopConflict as exc:
                        raise JobConflict(str(exc)) from exc
                try:
                    release = acquire_background_lease()
                except BaseException:
                    self._release_reservation(kind, args, job_id)
                    raise JobBusy("当前 AI 任务较多，请稍后再试。")
                now = time.time()
                runtime = Runtime(self, job_id, path, kind, args, release,
                                  upload_dir=args.get("_upload_dir"))
                if kind == "solve":
                    runtime.prepared = _matching_prepared(args)
                    if runtime.prepared:
                        runtime.deadline = time.monotonic() + PRESET_TIMEOUT_SECONDS
                        # Demonstrations must start a real call immediately,
                        # rather than time out while waiting behind a long batch.
                        if len(self.runtimes) >= self.workers or not _PROVIDERS["deepseek"].acquire(blocking=False):
                            release()
                            raise JobBusy("AI 正在处理其他任务，请稍后开始真题体验。")
                        runtime.reserved_provider = "deepseek"
                try:
                    conn.execute("INSERT INTO jobs VALUES (?,?,?,?,?,'queued','queued',0,?,?,?,NULL,NULL,NULL,?)",
                                 (job_id, kind, request_id, fingerprint, _dump(args), "已进入后台队列", now, now, self.runtime_id))
                    conn.commit()
                    self.runtimes[job_id] = runtime
                    context = copy_context()
                    if runtime.deadline is not None:
                        timer_context = copy_context()
                        runtime.timer = threading.Timer(PRESET_TIMEOUT_SECONDS, lambda: timer_context.run(self._fallback, runtime, "deadline"))
                        runtime.timer.daemon = True
                        runtime.timer.start()
                    self.pending.put_nowait((context, runtime))
                except BaseException:
                    self.runtimes.pop(job_id, None)
                    if runtime.timer:
                        runtime.timer.cancel()
                    if runtime.reserved_provider:
                        _PROVIDERS[runtime.reserved_provider].release()
                        runtime.reserved_provider = None
                    conn.execute("DELETE FROM jobs WHERE job_id=?", (job_id,))
                    conn.commit()
                    self._release_reservation(kind, args, job_id)
                    release()
                    raise
                row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
                return _public(row)

    @staticmethod
    def _release_reservation(kind, args, job_id):
        if kind in ("teach_chat", "teach_ack", "teach_finish"):
            from backend.teach import release_teaching_job
            release_teaching_job(args["session_id"], job_id)
        if kind == "grade" and args.get("loop"):
            from backend.patterns import release_loop_grade
            release_loop_grade(args["loop"], job_id)

    def _worker(self):
        while True:
            context, runtime = self.pending.get()
            try:
                context.run(self._run, runtime)
            except BaseException:
                logger.exception("后台任务执行器异常 job=%s", runtime.job_id)
            finally:
                self.pending.task_done()

    def _run(self, runtime):
        token = _CURRENT.set(runtime)
        try:
            if runtime.finished.is_set():
                return
            self.progress(runtime, "starting", 1, "后台处理中")
            runner = (self.runners or RUNNERS)[runtime.kind]
            outcome = runner(runtime.args, runtime)
            if not isinstance(outcome, Outcome):
                outcome = Outcome(outcome)
            if isinstance(outcome.value, dict) and outcome.value.get("error") and not outcome.value.get("chunk_results"):
                raise RuntimeError(outcome.value.get("detail") or str(outcome.value["error"]))
            if runtime.deadline is not None and time.monotonic() >= runtime.deadline:
                self._fallback(runtime, "deadline")
            else:
                self.finish(runtime, outcome)
        except Exception as exc:
            if runtime.prepared and (isinstance(exc, JobStopped) or time.monotonic() >= runtime.deadline):
                self._fallback(runtime, "deadline")
            else:
                self._release_reservation(runtime.kind, runtime.args, runtime.job_id)
                self.fail(runtime, exc)
        finally:
            if runtime.timer:
                runtime.timer.cancel()
            if runtime.reserved_provider:
                _PROVIDERS[runtime.reserved_provider].release()
                runtime.reserved_provider = None
            self._release_reservation(runtime.kind, runtime.args, runtime.job_id)
            with self.lock:
                runtime.worker_done = True
            _CURRENT.reset(token)
            self.release_runtime(runtime)

    def release_runtime(self, runtime):
        # A batch may publish a prepared leaf while its original HTTP call is
        # still returning. Keep the parent's workspace lease and active-task
        # entry until every such call has actually stopped.
        with self.lock:
            if runtime.released or not runtime.worker_done or runtime.children:
                return
            runtime.released = True
        if runtime.upload_dir:
            _remove_upload_directory(runtime.path, runtime.upload_dir)
        with self.lock:
            self.runtimes.pop(runtime.job_id, None)
        runtime.release()

    def progress(self, runtime, stage, progress, detail):
        with self.lock:
            if runtime.finished.is_set():
                return
            with self._connection(runtime.path) as conn:
                conn.execute("UPDATE jobs SET status='running', stage=?, progress=?, detail=?, updated_at=? "
                             "WHERE job_id=? AND status NOT IN ('done','error','interrupted')",
                             (str(stage), max(0, min(99, int(progress))), str(detail)[:300], time.time(), runtime.job_id))

    def partial(self, ctx, result):
        with self.lock, self._connection(ctx.path) as conn:
            if not ctx.finished.is_set():
                conn.execute("UPDATE jobs SET result_json=?, updated_at=? WHERE job_id=?",
                             (_dump(result), time.time(), ctx.job_id))

    def finish(self, runtime, outcome):
        # The deadline timer and worker share this commit gate. Only its winner
        # saves a question/result; late responses cannot overwrite prepared data.
        with self.lock:
            if runtime.finished.is_set():
                return False
            value = outcome.value
            if outcome.commit:
                outcome.commit(value)
            with self._connection(runtime.path) as conn:
                conn.execute("UPDATE jobs SET status='done', stage='done', progress=100, detail=?, "
                             "updated_at=?, result_json=?, source=? WHERE job_id=?",
                             ("示例解析已就绪" if outcome.source == "prepared_cache" else "处理完成",
                              time.time(), _dump(value), outcome.source, runtime.job_id))
            runtime.finished.set()
            return True

    def _fallback(self, runtime, reason):
        if (not runtime.prepared or (reason == "deadline" and
                (runtime.deadline is None or time.monotonic() < runtime.deadline))):
            return False
        outcome = _prepared_outcome(runtime.args, runtime.prepared, reason)
        try:
            return self.finish(runtime, outcome)
        except Exception as exc:
            self.fail(runtime, exc)

    def fail(self, runtime, exc):
        with self.lock:
            if runtime.finished.is_set():
                return
            detail = str(exc)[:300] or "后台处理失败"
            with self._connection(runtime.path) as conn:
                conn.execute("UPDATE jobs SET status='error', stage='error', detail=?, updated_at=?, error_json=? WHERE job_id=?",
                             (detail, time.time(), _dump({"code": "job_failed", "detail": detail}), runtime.job_id))
            runtime.finished.set()
            logger.warning("后台任务失败 kind=%s id=%s detail=%s", runtime.kind, runtime.job_id, detail)

    def get(self, job_id):
        with self.lock, self._connection(storage_path()) as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            ttl = _history_ttl()
            if row and row["status"] in TERMINAL and row["updated_at"] < time.time() - ttl:
                conn.execute("DELETE FROM jobs WHERE job_id=?", (job_id,))
                return None
            return _public(row) if row else None

    def list(self, limit=50):
        path = storage_path()
        ttl = _history_ttl()
        with self.lock, self._connection(path) as conn:
            conn.execute("DELETE FROM jobs WHERE status IN ('done','error','interrupted') AND updated_at<?",
                         (time.time() - ttl,))
            rows = conn.execute("SELECT * FROM jobs ORDER BY CASE WHEN status IN ('queued','running') THEN 0 ELSE 1 END, "
                                "created_at DESC LIMIT ?", (max(1, min(100, int(limit))),)).fetchall()
            return {"jobs": [_public(row, full=False) for row in rows], "total": len(rows)}


def _text(args, key, required=True):
    value = args.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or (required and not value.strip()):
        raise ValueError(f"{key} 不能为空")
    return value.strip()


def validate_args(kind, args):
    if kind == "routine_match":
        from backend.routine_review import validate_job_args
        return validate_job_args(args)
    if not isinstance(args, dict):
        raise ValueError("args 必须是对象")
    args = json.loads(_dump(args))
    if len(_dump(args).encode()) > 1024 * 1024:
        raise ValueError("提交内容超过 1 MiB")
    if args.get("engine") == "codex_cli" and kind != "pool_prepare":
        raise ValueError("此入口暂不支持本地 Codex，请从原题池准备解析。")
    if kind == "pool_prepare":
        from backend.question_pool import validate_prepare_args
        return validate_prepare_args(args)
    if kind == "pool_import":
        from backend.question_pool import validate_import_args
        return validate_import_args(args)
    if kind == "pool_collect":
        from backend.question_pool import validate_collect_args
        return validate_collect_args(args)
    if kind in ("solve", "teach_start", "teach_legacy_start", "teach_check"):
        args["question"] = _text(args, "question")
        if args.get("asset_refs"):
            from backend.question_assets import validate_refs
            args["asset_refs"] = validate_refs(args["asset_refs"])
    if kind in ("teach_chat", "teach_ack", "teach_finish"):
        args["session_id"] = _text(args, "session_id")
        revision = args.get("expected_revision")
        if revision is not None and (not isinstance(revision, int) or revision < 0):
            raise ValueError("expected_revision 必须是非负整数")
    if kind == "teach_chat":
        args["message"] = _text(args, "message")
    if kind == "teach_check":
        for key in ("step_prompt", "step_answer", "user_answer"):
            args[key] = _text(args, key)
    if kind in ("generate", "pattern_check", "pattern_variants"):
        key = "question_id" if kind == "generate" else "pattern_id"
        if key not in args and kind == "generate":
            args[key] = args.pop("qid", None)
        if not _valid_id(args.get(key)):
            raise ValueError(f"{key} 必须是题库中的非零整数 ID")
        if kind == "pattern_check" and not _valid_id(args.get("question_id")):
            raise ValueError("question_id 必须是题库中的非零整数 ID")
    if kind == "grade":
        args["student_answer"] = _text(args, "student_answer")
        if args.get("question_id") is not None and not _valid_id(args["question_id"]):
            raise ValueError("question_id 必须是题库中的非零整数 ID")
        if not args.get("question_id"):
            args["question"] = _text(args, "question")
        if args.get("loop") is not None:
            loop = args["loop"]
            if not isinstance(loop, dict) or not _valid_id(args.get("question_id")):
                raise ValueError("套路作答需要有效的题目及挑战信息")
            loop["round_id"] = _text(loop, "round_id")
            if not 8 <= len(loop["round_id"]) <= 128:
                raise ValueError("round_id 必须是 8 至 128 字符")
            if not _valid_id(loop.get("pattern_id")):
                raise ValueError("pattern_id 必须是非零整数")
            if not isinstance(loop.get("queue_index"), int) or loop["queue_index"] < 0:
                raise ValueError("queue_index 必须是非负整数")
            queue = loop.get("queue")
            if not isinstance(queue, list) or not 1 <= len(queue) <= 4 or loop["queue_index"] >= len(queue):
                raise ValueError("挑战队列不合法")
            for item in queue:
                if (not isinstance(item, dict) or item.get("role") not in ("mother", "variant1", "variant2", "variant3")
                        or not _valid_id(item.get("question_id"))):
                    raise ValueError("挑战题目和角色不合法")
            if not isinstance(loop.get("mother_only"), bool):
                raise ValueError("mother_only 必须是布尔值")
            elapsed = loop.get("elapsed_seconds", args.get("duration_seconds") or 0)
            if not isinstance(elapsed, (int, float)) or not math.isfinite(elapsed) or elapsed < 0:
                raise ValueError("作答用时不合法")
            loop["elapsed_seconds"] = float(elapsed)
    if kind == "agent":
        args["message"] = _text(args, "message")
        args["history"] = (args.get("history") or [])[-20:]
    if kind == "provider_test" and args.get("provider") not in ("deepseek",):
        raise ValueError("未知 provider")
    if kind in ("parse_file", "ocr_file") and not args.get("_upload_path"):
        raise ValueError("请通过文件上传接口提交此任务")
    if kind == "batch_solve":
        questions = args.get("questions")
        if not isinstance(questions, list) or not 1 <= len(questions) <= 20:
            raise ValueError("每批请选择 1 至 20 道题")
        args["questions"] = [validate_args("solve", item if isinstance(item, dict) else {"question": item}) for item in questions]
    return args


def _matching_prepared(args):
    if not args.get("preset_id"):
        return None
    from backend.demo_presets import get_preset, prepared_result
    preset = get_preset(args["preset_id"])
    if preset and preset["question"].strip() == args["question"].strip():
        return prepared_result(args["preset_id"])
    return None


def _prepared_outcome(args, prepared, reason="deadline"):
    value = json.loads(_dump(prepared))
    value.update(source="prepared_cache", fallback_reason=reason, prepared_example=True,
                 fallback_note="AI 解答超过 5 分钟，现展示预先准备并核对的示例解析。" if reason == "deadline" else
                 "本次 AI 连接暂未成功，现展示预先准备并核对的示例解析。")
    return Outcome(value, _solve_commit(args), "prepared_cache")


def _solve_commit(args):
    if not args.get("save", True):
        return None
    def commit(result):
        from backend.database import save_question
        aj = dict(result)
        chunks = aj.get("chunk_results") or []
        first = chunks[0] if chunks else {}
        aj["category"] = first.get("category")
        aj["difficulty"] = aj.get("overall_difficulty") or first.get("difficulty")
        aj["question_type"] = args.get("question_type") or first.get("chunk_type")
        if args.get("source_type"):
            aj["source_type"] = args["source_type"]
        if args.get("source_meta") is not None:
            aj["source_meta"] = args["source_meta"]
        aj.pop("error", None)
        result["saved_question_id"] = save_question(args["question"], aj)
    return commit


def _solve(args, ctx):
    from backend.solver import step_solver_only, step_verify_all, step_final_check
    question, teacher, question_type = args["question"], args.get("teacher"), args.get("question_type")
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    def add(data):
        for key in usage:
            usage[key] += (data.get("token_usage") or {}).get(key, 0)
        if data.get("error") and not data.get("chunk_results"):
            raise RuntimeError(data.get("detail") or data.get("status") or data["error"])
    ctx.progress("solver", 13, "AI 正在解答")
    assets = {"asset_refs": args["asset_refs"]} if args.get("asset_refs") else {}
    solver_assets = {**assets, "asset_labels": args["asset_labels"]} if args.get("asset_labels") else assets
    solved = step_solver_only(question, question_type, teacher=teacher, **solver_assets)
    add(solved)
    ctx.progress("verifier", 78, "AI 正在拆分步骤与知识点")
    verified = step_verify_all(solved["content"], question, solved.get("category"), question_type=question_type, teacher=teacher)
    add(verified)
    ctx.progress("formatter", 91, "AI 正在检查解析与预制几何演示")
    final = step_final_check(question, verified["chunk_results"], [], usage, teacher=teacher,
                             solver_content=solved["content"], verifier_category=solved.get("category"), question_type=question_type, **assets)
    final.update(source="live_ai", prepared_example=False)
    if args.get("preset_id"):
        from backend.demo_presets import get_preset, prepared_result
        preset = get_preset(args["preset_id"])
        if preset and preset["question"].strip() == question.strip():
            final["preset_id"] = args["preset_id"]
            final.setdefault("source_type", "高考题")
            final.setdefault("source_meta", (prepared_result(args["preset_id"]) or {}).get("source_meta") or preset["source"])
    return Outcome(final, _solve_commit(args))


def _teach_start(args, ctx):
    from backend.teach import teach_session_start
    ctx.progress("teaching", 15, "准备教学步骤与引导")
    return teach_session_start(args["question"], args.get("teacher"), **({"asset_refs": args["asset_refs"]} if args.get("asset_refs") else {}))


def _teach_legacy_start(args, ctx):
    from backend.teach import teach_start
    return teach_start(args["question"], args.get("teacher"), **({"asset_refs": args["asset_refs"]} if args.get("asset_refs") else {}))


def _teach_chat(args, ctx):
    from backend.teach import teach_session_chat
    ctx.progress("teaching", 30, "老师正在检查这一步的思路")
    return teach_session_chat(args["session_id"], args["message"], expected_revision=args.get("expected_revision"))


def _teach_ack(args, ctx):
    from backend.teach import teach_ack_prompt
    return teach_ack_prompt(args["session_id"], expected_revision=args.get("expected_revision"))


def _teach_finish(args, ctx):
    from backend.teach import teach_finish_session
    return teach_finish_session(args["session_id"], args.get("step_errors") or [], expected_revision=args.get("expected_revision"))


def _teach_check(args, ctx):
    from backend.teach import teach_check
    return teach_check(args["question"], args["step_prompt"], args["step_answer"], args["user_answer"], args.get("teacher"))


def _generate(args, ctx):
    from backend.generate import generate_variants
    counts = {"solver": 0, "verifier": 0, "formatter": 0}
    def progress(phase):
        if phase in counts:
            counts[phase] += 1
        ctx.progress(phase, min(95, 10 + sum(counts.values()) * 6), "AI 正在生成并校验变式题")
    return generate_variants(args["question_id"], args.get("count"), args.get("teacher") or "liangliang", progress_callback=progress)


def _grade(args, ctx):
    from backend.grade import grade_text
    ctx.progress("grading", 30, "AI 正在判分")
    loop = args.get("loop")
    if loop:
        from backend.patterns import get_pattern, commit_loop_grade
        maximum = (get_pattern(loop["pattern_id"]) or {}).get("max_time_seconds") or 120
    if loop and loop["elapsed_seconds"] > maximum:
        value = {"is_correct": False, "timed_out": True, "question_id": args["question_id"],
                 "feedback": f"超时：用时 {loop['elapsed_seconds']:.1f}s，超过了限时 {maximum}s。"}
    else:
        accepted = inspect.signature(grade_text).parameters
        value = grade_text(**{k: v for k, v in args.items() if k in accepted})
    if not loop:
        return value
    def commit(result):
        result["loop"] = commit_loop_grade(loop, args["question_id"], ctx.job_id,
                                           bool(result["is_correct"]), args.get("duration_seconds") or 0)
    return Outcome(value, commit)


def _parse_file(args, ctx):
    from backend.multimodal import parse_file
    questions = parse_file(args["_upload_path"], args.get("filename", ""),
                           progress=lambda page, total: ctx.progress("recognizing", round(5 + 90 * page / max(total, 1)), f"正在识别第 {page}/{total} 页"))
    return {"questions": questions, "total": len(questions)}


def _ocr_file(args, ctx):
    from backend.multimodal import recognize_answer_image
    ctx.progress("recognizing", 20, "正在识别手写作答")
    return recognize_answer_image(args["_upload_path"])


def _solve_batch_leaf(args, parent):
    prepared = _matching_prepared(args)
    if not prepared:
        outcome = _solve(args, parent)
        ensure_active()
        if outcome.commit:
            outcome.commit(outcome.value)
        return outcome.value

    # Wait for the shared provider before starting this leaf's 300-second
    # window: a queued question must never receive a cache without an AI call.
    slot = _PROVIDERS["deepseek"]
    while not slot.acquire(timeout=0.2):
        ensure_active()
    child = Runtime(parent.manager, parent.job_id, parent.path, "solve", args,
                    lambda: None, prepared=prepared, reserved_provider="deepseek")
    child.deadline = time.monotonic() + PRESET_TIMEOUT_SECONDS
    state = {}

    def publish(outcome=None, error=None):
        with parent.manager.lock:
            if child.finished.is_set():
                return False
            if parent.finished.is_set():
                child.finished.set()
                return False
            try:
                if error is not None:
                    state["error"] = error
                else:
                    if outcome.commit:
                        outcome.commit(outcome.value)
                    state["result"] = outcome.value
            except Exception as exc:
                state["error"] = exc
            child.finished.set()
            return True

    def fallback():
        if time.monotonic() < child.deadline:
            return False
        return publish(_prepared_outcome(args, prepared))

    def solve():
        token = _CURRENT.set(child)
        try:
            outcome = _solve(args, child)
            if time.monotonic() >= child.deadline:
                fallback()
            else:
                ensure_active()
                publish(outcome)
        except Exception as exc:
            if time.monotonic() >= child.deadline:
                fallback()
            else:
                publish(error=exc)
        finally:
            child.timer.cancel()
            if child.reserved_provider:
                slot.release()
                child.reserved_provider = None
            with parent.manager.lock:
                parent.children -= 1
            _CURRENT.reset(token)
            parent.manager.release_runtime(parent)

    timer_context, worker_context = copy_context(), copy_context()
    child.timer = threading.Timer(PRESET_TIMEOUT_SECONDS, lambda: timer_context.run(fallback))
    child.timer.daemon = True
    worker = threading.Thread(target=lambda: worker_context.run(solve),
                              name=f"study-preset-{parent.job_id[:8]}", daemon=True)
    with parent.manager.lock:
        parent.children += 1
    try:
        # Starting the worker first also lets a fast live result cancel the
        # timer before it is scheduled. Both publish through the same gate.
        worker.start()
    except BaseException:
        with parent.manager.lock:
            parent.children -= 1
        slot.release()
        raise
    try:
        child.timer.start()
    except Exception as exc:
        # The live thread already holds a lease through its parent. Stop its
        # later stages even if the OS cannot create the deadline timer thread.
        publish(error=exc)
    while not child.finished.wait(0.2):
        ensure_active()
    if "error" in state:
        raise state["error"]
    ensure_active()
    return state["result"]


def _batch_solve(args, ctx):
    # Schedule leaves sequentially without nesting jobs in the worker pool.
    # Preset leaves have a private response gate so an expired HTTP call can
    # finish safely after its prepared result, then the next leaf can begin.
    items = []
    total = len(args["questions"])
    for index, question in enumerate(args["questions"]):
        ensure_active()
        try:
            result = _solve_batch_leaf(question, ctx)
            items.append({"index": index, "question": question["question"], "status": "done", "result": result, "error": None})
        except Exception as exc:
            items.append({"index": index, "question": question["question"], "status": "error", "result": None,
                          "error": {"detail": str(exc)[:300]}})
        ctx.progress("batch", round(100 * (index + 1) / total), f"已完成 {index+1}/{total} 道题")
        ctx.manager.partial(ctx, {"items": items, "total": total, "done": len(items), "failed": sum(x["status"] == "error" for x in items)})
    return {"items": items, "total": total, "done": len(items), "failed": sum(x["status"] == "error" for x in items)}


def _agent(args, ctx):
    from backend.agent import agent_act
    return agent_act(args["message"], args.get("history"), on_progress=lambda detail: ctx.progress("agent", 30, detail))


def _pattern_check(args, ctx):
    from backend.patterns import check_pattern_answer
    return check_pattern_answer(args["pattern_id"], args["question_id"], args.get("user_answer", ""), args.get("teacher") or "liangliang")


def _pattern_variants(args, ctx):
    from backend.patterns import ensure_variants
    return ensure_variants(args["pattern_id"], args.get("teacher") or "liangliang")


def _provider_test(args, ctx):
    import httpx
    from backend import settings
    provider = args["provider"]
    cfg = settings.get_api().get(provider) or {}
    key = settings.get_api_key(provider)
    if not key:
        return {"ok": False, "provider": provider, "error": "未配置 API Key"}
    with provider_slot(provider):
        response = httpx.get(str(cfg.get("base_url") or "").rstrip("/") + "/models",
                             headers={"Authorization": "Bearer " + key}, timeout=request_timeout(15))
    return {"ok": response.status_code == 200, "provider": provider,
            **({} if response.status_code == 200 else {"error": f"HTTP {response.status_code}"})}


def _pool_prepare(args, ctx):
    from backend.question_pool import prepare_items
    from backend.local_models import pipeline
    with pipeline(args.get("engine", "deepseek")):
        return prepare_items(args, ctx)


def _pool_import(args, ctx):
    from backend.question_pool import import_source_job
    return import_source_job(args, ctx)


def _pool_collect(args, ctx):
    from backend.question_pool import collect_sources_job
    return collect_sources_job(args, ctx)


def _routine_match(args, ctx):
    from backend.routine_review import run_job
    return run_job(args, ctx)


RUNNERS = {"solve": _solve, "teach_start": _teach_start, "teach_legacy_start": _teach_legacy_start,
           "teach_chat": _teach_chat, "teach_ack": _teach_ack,
           "teach_finish": _teach_finish, "teach_check": _teach_check, "generate": _generate, "grade": _grade,
           "parse_file": _parse_file, "ocr_file": _ocr_file, "batch_solve": _batch_solve, "agent": _agent,
           "pattern_check": _pattern_check, "pattern_variants": _pattern_variants, "provider_test": _provider_test,
           "pool_prepare": _pool_prepare, "pool_import": _pool_import, "pool_collect": _pool_collect, "routine_match": _routine_match}
_manager = JobManager()


def submit_job(kind, args, request_id):
    return _manager.submit(kind, args, request_id)


def get_job(job_id):
    return _manager.get(job_id)


def active_count(workspace=None):
    with _manager.lock:
        return sum(1 for runtime in _manager.runtimes.values() if workspace is None or runtime.path.parent == Path(workspace))


def provider_active_count():
    with _PROVIDER_LOCK:
        return _PROVIDER_ACTIVE


def set_draining(draining):
    with _manager.lock:
        _manager.draining = bool(draining)


def cleanup_workspace(directory):
    # Called by the visitor store only after every lease has ended. Do not take
    # the submission lock while the visitor store holds its own cleanup lock.
    with _manager.prepare_lock:
        _manager.prepared_paths.discard(str(Path(directory) / "jobs.sqlite3"))


class JobRequest(BaseModel):
    kind: str
    args: dict = Field(default_factory=dict)
    request_id: str = Field(..., min_length=8, max_length=128)


router = APIRouter()


def _submission_error(exc):
    if isinstance(exc, JobConflict):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, JobBusy):
        return HTTPException(status_code=503 if _manager.draining else 429, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@router.post("/jobs", status_code=202)
async def api_submit_job(req: JobRequest):
    # Never accept administrator file paths in a JSON request.
    if req.kind in ("parse_file", "ocr_file") or any(k.startswith("_") for k in req.args):
        raise HTTPException(status_code=400, detail="文件识别任务请使用上传入口")
    try:
        return await run_in_threadpool(submit_job, req.kind, req.args, req.request_id)
    except (ValueError, RuntimeError) as exc:
        raise _submission_error(exc)


@router.post("/jobs/uploads", status_code=202)
async def api_upload_job(kind: str = Form(...), request_id: str = Form(...), file: UploadFile = File(...)):
    import tempfile
    from backend.multimodal import get_supported_extensions
    ext = Path(file.filename or "upload").suffix.lower()
    allowed = get_supported_extensions() if kind == "parse_file" else [".jpg", ".jpeg", ".png"]
    if kind not in ("parse_file", "ocr_file") or ext not in allowed:
        raise HTTPException(status_code=400, detail="文件类型不支持")
    path = storage_path()
    # Initialize and recover the ledger before making an unaccepted upload
    # directory, so first-use orphan recovery cannot remove this new body.
    await run_in_threadpool(_manager.prepare, path)
    base = path.parent.resolve() / "job-uploads"
    if base.is_symlink():
        await file.close()
        raise HTTPException(status_code=500, detail="上传暂存目录不可用")
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory = Path(tempfile.mkdtemp(prefix="upload-", dir=str(base)))
    target = directory / ("input" + ext)
    digest = sha256()
    total = 0
    accepted = False
    try:
        with target.open("wb") as stream:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > 16 * 1024 * 1024:
                    raise HTTPException(status_code=413, detail="文件过大：最多 16 MiB")
                stream.write(chunk)
                digest.update(chunk)
        if not total:
            raise HTTPException(status_code=400, detail="文件为空")
        public = {"filename": Path(file.filename or "upload").name, "size": total, "sha256": digest.hexdigest()}
        args = {**public, "_upload_path": str(target), "_upload_dir": str(directory)}
        result = await run_in_threadpool(lambda: _manager.submit(kind, args, request_id, fingerprint_args=public))
        accepted = result["args"].get("sha256") == digest.hexdigest() and result["status"] not in TERMINAL
        # Idempotent upload retries attach to the old task; only its original
        # directory is retained, not the redundant body just received.
        with _manager.lock:
            runtime = _manager.runtimes.get(result["job_id"])
            accepted = bool(runtime and runtime.upload_dir == str(directory))
        return result
    except (ValueError, RuntimeError) as exc:
        raise _submission_error(exc)
    finally:
        await file.close()
        if not accepted:
            _remove_upload_directory(path, directory)


@router.get("/jobs")
def api_list_jobs(limit: int = 50):
    return _manager.list(limit)


@router.get("/jobs/{job_id}")
def api_get_job(job_id: str):
    if not isinstance(job_id, str) or len(job_id) != 32:
        raise HTTPException(status_code=404, detail="任务不存在")
    result = get_job(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return result
