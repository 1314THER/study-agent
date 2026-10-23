"""Single-process workers with a PostgreSQL ledger; restart never repeats AI calls."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from pathlib import Path
from types import SimpleNamespace
import threading
import time
from sqlalchemy import update
from fastapi import HTTPException
from backend.storage import models as m
from backend.storage.repository import uid
from backend.identity import current_user_id, require_catalog_editor


class CloudJobs:
    kinds = {"solve", "grade", "ocr", "parse_file", "teach_start", "teach_chat", "teach_ack", "teach_finish", "pool_prepare"}

    def __init__(self, repository, asset_root, *, workers=2):
        self.repo, self.asset_root = repository, Path(asset_root)
        self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="study-cloud")
        self.capacity = threading.BoundedSemaphore(64)
        self.futures = {}
        self.lock = threading.RLock()

    def recover(self):
        with self.repo.db.transaction() as c:
            c.execute(update(m.jobs).where(m.jobs.c.status.in_(["queued", "running"])).values(status="interrupted", stage="服务已重启，请确认后重试", updated_at=time.time()))
            c.execute(update(m.teaching_sessions).values(pending_job=None))

    def submit(self, kind, args, request_id):
        if kind not in self.kinds:
            raise HTTPException(422, "任务类型不支持")
        args = dict(args)
        # Only documented parameters enter workers; never accept file paths,
        # prepared results, provider credentials or saved grading outcomes.
        allowed = {"question", "question_id", "question_revision", "student_answer", "teacher", "session_id", "expected_revision", "message", "asset_id", "record_id"}
        if set(args) - allowed:
            raise HTTPException(422, "任务包含未支持的参数")
        for key in ("question", "student_answer", "message"):
            if key in args and (not isinstance(args[key], str) or len(args[key]) > 100000):
                raise HTTPException(422, "文本参数无效")
        if args.get("teacher") not in (None, "liangliang", "xuefeng", "ji"):
            raise HTTPException(422, "教师参数无效")
        if "question_id" in args:
            q = self.repo.question(args["question_id"])
            if not q["active"]:
                raise HTTPException(409, "题目已撤下")
            args.setdefault("question_revision", q["revision"])
            if type(args["question_revision"]) is not int or args["question_revision"] < 1:
                raise HTTPException(422, "题目版本号无效")
        if kind == "grade" and not args.get("question_id"):
            raise HTTPException(422, "批改需要题目编号")
        if "asset_id" in args:
            self.repo.asset(args["asset_id"])
        if kind in {"ocr", "parse_file"} and not args.get("asset_id"):
            raise HTTPException(422, "请先上传附件")
        if kind in {"solve", "teach_start"} and not (args.get("question_id") or (args.get("question") or "").strip()):
            raise HTTPException(422, "请填写题目")
        if kind == "pool_prepare":
            require_catalog_editor()
            with self.repo.db.transaction() as c:
                record = c.execute(m.admin_records.select().where(m.admin_records.c.id == args.get("record_id"), m.admin_records.c.kind == "pool.pool_items")).first()
            if not record:
                raise HTTPException(404, "原题记录不存在")
            if args.get("expected_revision") != record.data.get("_revision", 0):
                raise HTTPException(409, "原题记录已更新，请刷新")
            from backend.question_assets import has_pool_graphics
            if has_pool_graphics(record.data) and not record.data.get("asset_refs"):
                raise HTTPException(409, "请先为此题补齐原题图，再准备解析")
        if kind in {"teach_chat", "teach_ack", "teach_finish"}:
            state = self.repo.teaching(args.get("session_id"))
            if type(args.get("expected_revision")) is not int:
                raise HTTPException(422, "教学操作必须携带版本号")
            if args["expected_revision"] != state["revision"]:
                # An identical retry can still retrieve its original job.
                with self.repo.db.transaction() as c:
                    old = c.execute(m.jobs.select().where(m.jobs.c.user_id == current_user_id(), m.jobs.c.request_id == request_id)).first()
                if not old:
                    raise HTTPException(409, "教学已更新，请刷新")
        with self.lock:
            if not self.capacity.acquire(blocking=False):
                raise HTTPException(429, "后台任务较多，请稍后重试")
            try:
                job_id, fresh = self.repo.submit_job(kind, args, request_id)
                if not fresh:
                    self.capacity.release()
                    return self.repo.job(job_id)
                ctx = copy_context()
                future = self.executor.submit(ctx.run, self._run, job_id, kind, args, request_id)
                self.futures[job_id] = future
                future.add_done_callback(lambda _: self._finished(job_id))
            except Exception:
                self.capacity.release()
                raise
        return self.repo.job(job_id)

    def _finished(self, job_id):
        with self.lock:
            self.futures.pop(job_id, None)
            self.capacity.release()

    def _run(self, job_id, kind, args, request_id):
        from backend.jobs import _CURRENT, _solve
        from backend.teach import (teach_session_start, teach_session_chat, teach_ack_prompt,
                                   teach_finish_session, reserve_teaching_job, release_teaching_job)
        runtime = SimpleNamespace(job_id=job_id, finished=threading.Event(), deadline=time.monotonic() + 900, reserved_provider=None)
        runtime.progress = lambda stage, progress, detail: self.repo.update_job(job_id, stage=detail, progress=progress)
        token = _CURRENT.set(runtime)
        session_id = args.get("session_id")
        try:
            if not self.repo.update_job(job_id, status="running", stage="正在处理", progress=5):
                return
            q = self.repo.question(args["question_id"]) if args.get("question_id") else None
            if q and args.get("question_revision"):
                q = self.repo.question_version(q["id"], args["question_revision"])
            if kind == "grade":
                from backend.grade import grade_prepared
                answer = args.get("student_answer", "")
                if args.get("asset_id"):
                    asset = self.repo.asset(args["asset_id"])
                    recognized = self._ocr_asset(asset)
                    recognized_text = recognized.get("text") or ""
                    answer = "\n".join(part for part in (answer.strip(), recognized_text.strip()) if part)
                result = grade_prepared(q["content"], q["answer_json"], answer, teacher=args.get("teacher"), input_type="ocr" if args.get("asset_id") else "text")
                if result.get("error"):
                    raise ValueError(result.get("detail") or result["error"])
                result = self.repo.save_attempt(q["id"], answer, result, request_id, [args["asset_id"]] if args.get("asset_id") else [], q["revision"])
            elif kind == "pool_prepare":
                with self.repo.db.transaction() as c:
                    record = c.execute(m.admin_records.select().where(m.admin_records.c.id == args["record_id"])).first()
                outcome = _solve({"question": record.data["question"], "teacher": args.get("teacher"), "save": False,
                                  "asset_refs": record.data.get("asset_refs") or []}, runtime)
                if outcome.value.get("formatter_fallback"):
                    raise ValueError("解析尚未通过检查")
                with self.repo.db.transaction() as c:
                    fresh = c.execute(m.admin_records.select().where(m.admin_records.c.id == args["record_id"]).with_for_update()).first()
                    if fresh.data.get("_revision", 0) != args["expected_revision"]:
                        raise ValueError("准备期间原题已被修改")
                    data = {**fresh.data, "prepared_json": outcome.value, "prepared_version": fresh.data.get("version", 1), "_revision": args["expected_revision"] + 1}
                    c.execute(update(m.admin_records).where(m.admin_records.c.id == args["record_id"]).values(data=data))
                result = {"record_id": args["record_id"], "prepared": True}
            elif kind == "solve":
                result = _solve({"question": q["content"] if q else args["question"], "teacher": args.get("teacher"), "save": True}, runtime)
                if result.commit:
                    result.commit(result.value)
                result = result.value
            elif kind == "teach_start":
                result = teach_session_start(q["content"] if q else args["question"], args.get("teacher"))
            elif kind.startswith("teach_"):
                reserve_teaching_job(session_id, job_id, args["expected_revision"])
                if kind == "teach_chat":
                    if not (args.get("message") or "").strip():
                        raise ValueError("请输入回答")
                    result = teach_session_chat(session_id, args["message"], args["expected_revision"])
                elif kind == "teach_ack":
                    result = teach_ack_prompt(session_id, args["expected_revision"])
                else:
                    result = teach_finish_session(session_id, expected_revision=args["expected_revision"])
            else:
                asset = self.repo.asset(args["asset_id"])
                path = self.asset_root / asset["storage_key"]
                if kind == "ocr":
                    result = self._ocr_asset(asset)
                else:
                    from backend.multimodal import parse_file
                    result = {"questions": parse_file(str(path), asset["filename"])}
            if isinstance(result, dict) and result.get("error"):
                raise ValueError(result.get("detail") or result["error"])
            self.repo.update_job(job_id, status="done", stage="已完成", progress=100, result=result)
        except Exception as exc:
            from backend.teach import TeachingConflict
            status = "conflict" if isinstance(exc, TeachingConflict) else "failed"
            # Do not expose provider responses, credentials or filesystem paths.
            import logging
            logging.getLogger(__name__).warning("Cloud job %s failed (%s)", job_id, type(exc).__name__)
            self.repo.update_job(job_id, status="error", stage="任务未完成", error={"code": status, "detail": "教学状态已更新，请刷新后重试。" if status == "conflict" else "任务未完成，请检查配置或输入后重试。"})
        finally:
            if session_id:
                release_teaching_job(session_id, job_id)
            runtime.finished.set()
            _CURRENT.reset(token)

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=False)

    def _ocr_asset(self, asset):
        from backend.multimodal import recognize_answer_image, _pdf_render_scale
        path = self.asset_root / asset["storage_key"]
        if asset["media_type"] != "application/pdf":
            if asset["media_type"] not in ("image/png", "image/jpeg"):
                raise ValueError("请使用 JPG、PNG 或 PDF 作答")
            return recognize_answer_image(str(path))
        import fitz
        import tempfile
        texts = []
        with fitz.open(path) as doc, tempfile.TemporaryDirectory(prefix="study-ocr-") as folder:
            if len(doc) > 20:
                raise ValueError("请将作答 PDF 控制在 20 页内")
            for index, page in enumerate(doc):
                target = Path(folder) / f"{index}.png"
                page.get_pixmap(matrix=fitz.Matrix(_pdf_render_scale(page, 150), _pdf_render_scale(page, 150))).save(target)
                texts.append(recognize_answer_image(str(target)).get("text", ""))
        return {"text": "\n\n".join(texts), "confidence": "medium"}
