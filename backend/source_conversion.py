"""Sequential PDF reads/renders, bounded concurrent cloud OCR, durable page cache."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import base64
import json
from pathlib import Path
import re
import time
import threading
import uuid

from backend.data_paths import data_path

ROOT = Path(__file__).resolve().parent.parent
CACHE_VERSION = 1
_PDF_LOCK = threading.RLock()


def file_hash(path):
    digest = sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("x", encoding="utf-8") as stream:
            temp.chmod(0o600)
            json.dump(value, stream, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            # A successful page survives process interruption before aggregation.
            import os
            os.fsync(stream.fileno())
        temp.replace(path)
    finally:
        if temp.exists():
            temp.unlink()


def parse_pages(value):
    """1-based comma/range notation, rejecting zero, descending and giant ranges."""
    if not value:
        return []
    numbers = set()
    for part in str(value).split(","):
        bounds = part.strip().split("-")
        if len(bounds) not in (1, 2) or any(not b.isdigit() for b in bounds):
            raise ValueError("页码应为 1,3-5 这样的格式")
        start, end = int(bounds[0]), int(bounds[-1])
        if not 1 <= start <= end <= 100000:
            raise ValueError("页码范围无效")
        numbers.update(range(start, end + 1))
    return sorted(numbers)


def usable_text(text, language=None):
    """Reject broken PDF character maps while keeping ordinary formula text."""
    chars = [char for char in text if not char.isspace()]
    if not chars:
        return False
    if len(chars) < 80:
        return True
    count = len(chars)
    private = sum("\ue000" <= char <= "\uf8ff" or char == "\ufffd" for char in chars)
    if private / count > .12:
        return False
    chinese = len(re.findall(r"[\u3400-\u9fff]", text))
    if language == "zh" and len(chars) >= 100 and chinese < 3:
        return False
    letters = sum(char.isalpha() for char in chars)
    symbols = sum(not char.isalnum() for char in chars)
    return not (chinese / count < .01 and letters / count < .25 and symbols / count > .60)


def read_pdf_pages(file, options, ocr_callback, prompt):
    """Return ordered cached page units. No worker ever sees a PyMuPDF object."""
    import fitz
    from backend.jobs import ensure_active, JobStopped
    from backend.multimodal import _pdf_render_scale, resolve_multimodal_model

    file = Path(file)
    filename = options.get("filename") or file.name
    mode = options.get("ocr_mode") or ("auto" if options.get("ocr") is True else "off")
    if mode not in ("auto", "off", "force"):
        raise ValueError("OCR 模式应为 auto/off/force")
    concurrency = options.get("concurrency", 20)
    if type(concurrency) is not int or not 1 <= concurrency <= 20:
        raise ValueError("OCR 并发应为 1 至 20")
    dpi = options.get("dpi", 180)
    if type(dpi) is not int or not 72 <= dpi <= 300:
        raise ValueError("渲染 DPI 应为 72 至 300")
    teacher = options.get("teacher") or "liangliang"
    model, _ = resolve_multimodal_model(teacher, has_image=True)
    if options.get("model") and options["model"] != model:
        raise ValueError("OCR 模型由所选老师决定，请调整老师模型设置")
    config = {"version": CACHE_VERSION, "model": model, "teacher": teacher, "ocr_mode": mode, "dpi": dpi,
              "prompt_sha256": sha256(prompt.encode()).hexdigest()}
    digest = file_hash(file)
    signature = sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    default_cache = Path(data_path("question-pool", ROOT / ".runtime/question-pool")) / "conversion-cache"
    cache = Path(options.get("cache_dir") or default_cache) / digest / signature
    resume = options.get("resume", True)
    retry_failed = options.get("retry_failed", True)
    stats = options.get("stats")
    if stats is None:
        stats = {}
    stats.update(file_sha256=digest, model=model, ocr_mode=mode, concurrency=concurrency,
                 completed_pages=0, cache_hits=0, failed_pages=0, ocr_requests=0, text_pages=0)
    started = time.perf_counter()
    output, pending = {}, []
    executor = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="pool-ocr")

    def notify(unit, hit=False):
        output[unit["page"]] = unit
        stats["completed_pages"] += 1
        stats["cache_hits"] += int(hit)
        stats["failed_pages"] += int(unit["status"] == "failed")
        stats["text_pages"] += int(unit.get("kind") == "text")
        stats["elapsed_seconds"] = round(time.perf_counter() - started, 4)
        if options.get("progress"):
            options["progress"](dict(stats))

    def recognize(encoded, number, metadata, target):
        # copy_context propagates owner/workspace/cancellation into this worker.
        ensure_active()
        try:
            records = list(ocr_callback(encoded, filename, number))
            if any(r.get("completeness") == "failed" for r in records):
                raise ValueError("OCR 包含格式错误条目，请重试本页")
            unit = {"page": number, "status": "success", "kind": "ocr", "records": records, "metadata": metadata}
        except JobStopped:
            raise  # Cancellation is unfinished work, not a cached failed page.
        except Exception as exc:
            unit = {"page": number, "status": "failed", "kind": "ocr", "error": str(exc)[:1000], "metadata": metadata}
        atomic_json(target, unit)
        return unit

    def drain():
        _, future = pending.pop(0)
        notify(future.result())
        ensure_active()

    def extract_page(document, number):
        page = document[number - 1]
        text = page.get_text("text", sort=True).strip()
        rects = []
        try:
            rects = [list(rect) for img in page.get_images() for rect in page.get_image_rects(img[0])]
        except Exception:
            pass
        metadata = {"text_blocks": [list(b) for b in page.get_text("blocks", sort=True) if len(b) < 7 or b[6] == 0],
                    "image_rects": rects, "extracted_text": text}
        if hasattr(page, "find_tables"):
            try:
                metadata["tables"] = [table.extract() for table in page.find_tables().tables]
            except Exception as exc:
                metadata["table_extraction_error"] = str(exc)[:200]
        area = page.rect.width * page.rect.height
        metadata["text_usable"] = usable_text(text, options.get("language"))
        scan = not metadata["text_usable"] or any((r[2]-r[0]) * (r[3]-r[1]) > area * .65 for r in rects)
        return page, text, metadata, scan

    @contextmanager
    def open_document():
        with _PDF_LOCK:
            document = fitz.open(file)
        try:
            yield document
        finally:
            with _PDF_LOCK:
                document.close()

    try:
        with open_document() as document:
            with _PDF_LOCK:
                page_count = len(document)
            selected = options.get("page_numbers") or list(range(1, page_count + 1))
            if any(type(n) is not int or not 1 <= n <= page_count for n in selected):
                raise ValueError(f"指定页码超出 PDF 的 {page_count} 页范围")
            selected = sorted(set(selected))
            stats["total_pages"] = len(selected)
            for number in selected:
                ensure_active()
                target = cache / f"page-{number}.json"
                saved = None
                if resume and target.is_file():
                    try:
                        saved = json.loads(target.read_text(encoding="utf-8"))
                        if saved.get("page") != number or saved.get("status") not in ("success", "failed"):
                            saved = None
                        elif saved.get("kind") == "text" and not usable_text(saved.get("text", ""), options.get("language")):
                            # Reclassify only damaged text caches; successful
                            # OCR pages remain valid and require no new request.
                            saved = None
                    except (ValueError, OSError, AttributeError):
                        saved = None
                if saved and (saved["status"] == "success" or not retry_failed):
                    saved = deepcopy(saved)
                    for record in saved.get("records", []):
                        record["source_key"] = filename + "#" + record["source_key"].split("#", 1)[-1]
                        record.setdefault("raw", {})["file"] = filename
                    notify(saved, hit=True)
                    continue
                metadata = {}
                try:
                    with _PDF_LOCK:
                        page, text, metadata, scan = extract_page(document, number)
                        # MuPDF calls remain serial even for multi-file collection.
                        encoded = None
                        if mode == "force" or (scan and mode == "auto"):
                            scale = _pdf_render_scale(page, dpi)
                            png = page.get_pixmap(matrix=fitz.Matrix(scale, scale)).tobytes("png")
                            encoded = base64.b64encode(png).decode()
                except JobStopped:
                    raise
                except Exception as exc:
                    unit = {"page": number, "status": "failed", "kind": "render", "error": str(exc)[:1000], "metadata": metadata}
                    atomic_json(target, unit)
                    notify(unit)
                    continue
                if mode == "force" or (scan and mode == "auto"):
                    # All reads and rendering stay in this one thread.
                    stats["ocr_requests"] += 1
                    ctx = copy_context()
                    pending.append((number, executor.submit(ctx.run, recognize, encoded, number, metadata, target)))
                    if len(pending) >= concurrency:
                        drain()
                else:
                    unit = {"page": number, "status": "success", "kind": "scan" if scan else "text",
                            "text": text, "metadata": metadata}
                    atomic_json(target, unit)
                    notify(unit)
            while pending:
                drain()
        stats["failed_page_numbers"] = sorted(n for n, u in output.items() if u["status"] == "failed")
        stats["processed_page_numbers"] = sorted(output)
        stats["elapsed_seconds"] = round(time.perf_counter() - started, 4)
        return [output[n] for n in sorted(output)]
    finally:
        # Already-started successful calls may still save their page cache.
        for _, future in pending:
            future.cancel()
        executor.shutdown(wait=True)
