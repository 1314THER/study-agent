"""Batch files/directories -> reviewable question-pool JSONL, with durable resume.

Example: python scripts/convert_question_sources.py books/ --output candidates.jsonl
         --ocr auto --pages 1-8 --retry-failed
"""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
KINDS = {".json": "jsonl", ".jsonl": "jsonl", ".tex": "compilation", ".docx": "docx",
         ".pdf": "pdf", ".txt": "txt", ".png": "image", ".jpg": "image", ".jpeg": "image"}


def main():
    from backend.pool_sources import SOURCE_KINDS, iter_source_records, _OCR_PROMPT
    from backend.source_conversion import file_hash, atomic_json, parse_pages, CACHE_VERSION
    from backend.multimodal import resolve_multimodal_model
    from backend.source_policy import MIN_YEAR, is_old, apply_year_policy
    parser = argparse.ArgumentParser(description="批量转录题源，不解题；默认自动识别扫描页并调用现有云 OCR")
    parser.add_argument("inputs", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--kind", choices=SOURCE_KINDS)
    parser.add_argument("--pages", default="", help="PDF 页码，例如 1,3-8")
    parser.add_argument("--ocr", choices=("auto", "off", "force"), default="auto")
    parser.add_argument("--teacher", choices=("liangliang", "taotao", "xuefeng", "ji"), default="liangliang",
                        help="选择题目识别模型的老师")
    parser.add_argument("--concurrency", type=int, choices=range(1, 21), default=20)
    parser.add_argument("--cache-dir", type=Path, default=ROOT / ".runtime/question-pool/conversion-cache")
    parser.add_argument("--no-resume", dest="resume", action="store_false", default=True)
    parser.add_argument("--retry-failed", action="store_true", help="重试失败页，已成功页始终复用")
    parser.add_argument("--answers", type=Path, help="原卷答案 JSON/JSONL，按 paperId + qNo 关联")
    parser.add_argument("--all-papers", action="store_true", help="gaokao_related 保留其他卷；仍执行最低年份规则并标记结构核验结果")
    args = parser.parse_args()
    try:
        pages = parse_pages(args.pages)
    except ValueError as exc:
        parser.error(str(exc))
    output = args.output.resolve()
    files = set()
    for path in args.inputs:
        if not path.exists():
            parser.error("输入不存在：" + str(path))
        candidates = path.rglob("*") if path.is_dir() else [path]
        for file in candidates:
            if (file.is_file() and file.suffix.lower() in KINDS and file.resolve() != output
                    and not file.name.endswith(("manifest.json", ".report.json"))
                    and file.resolve() != (args.report or output.with_name(output.name + ".report.json")).resolve()):
                if args.cache_dir.resolve() not in file.resolve().parents:
                    files.add(file.resolve())
    if not files:
        parser.error("没有找到支持的题源文件")
    model, _ = resolve_multimodal_model(args.teacher, has_image=True)
    config = {"version": 4, "page_cache_version": CACHE_VERSION, "model": model, "teacher": args.teacher,
              "prompt_sha256": sha256(_OCR_PROMPT.encode()).hexdigest(), "kind": args.kind, "ocr_mode": args.ocr, "page_numbers": pages,
              "minimum_year": MIN_YEAR, "mock_profile": not args.all_papers,
              "answers_sha256": file_hash(args.answers) if args.answers else ""}
    signature = sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    started = time.perf_counter()
    report = {"minimum_year": MIN_YEAR, "files": [], "total_records": 0, "skipped_old": 0,
              "unknown_year": 0, "ocr_requests": 0, "cache_hits": 0, "failed_pages": 0, "completed_pages": 0}
    totals = Counter()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as dest:
            temporary.chmod(0o600)
            for file in sorted(files):
                digest = file_hash(file)
                # File-level spool avoids re-parsing successful DOCX/JSON as well.
                identity = sha256(str(file).encode()).hexdigest()[:16]
                base = args.cache_dir / "converted" / digest / signature / identity
                spool, manifest = base / "records.jsonl", base / "manifest.json"
                previous = None
                if args.resume and manifest.is_file() and spool.is_file():
                    try:
                        previous = json.loads(manifest.read_text(encoding="utf-8"))
                        if file_hash(spool) != previous.get("output_sha256") or (args.retry_failed and previous.get("failed_records")):
                            previous = None
                    except (ValueError, OSError):
                        previous = None
                if previous:
                    entry = {**previous, "reused_file": True,
                             "conversion": {**previous.get("conversion", {}), "ocr_requests": 0,
                                            "cache_hits": previous.get("conversion", {}).get("total_pages", 0)}}
                else:
                    stats, source_report = {}, {}
                    entry = {"file": str(file), "file_sha256": digest, "records": 0, "skipped_old": 0,
                             "unknown_year": 0, "failed_records": 0, "completeness": {}, "reused_file": False}
                    counts = Counter()
                    def progress(current):
                        print(f"{file.name}: 完成页 {current['completed_pages']}/{current['total_pages']} · 缓存 {current['cache_hits']} · 失败 {current['failed_pages']}", file=sys.stderr, flush=True)
                    options = {"ocr": args.ocr != "off", "ocr_mode": args.ocr, "concurrency": args.concurrency,
                               "resume": args.resume, "retry_failed": args.retry_failed, "cache_dir": args.cache_dir,
                               "page_numbers": pages, "stats": stats, "progress": progress, "source_report": source_report,
                               "mock_profile": not args.all_papers, "require_19": not args.all_papers, "answers_path": args.answers,
                               "teacher": args.teacher}
                    base.mkdir(parents=True, exist_ok=True, mode=0o700)
                    part = base / ("records-" + uuid.uuid4().hex + ".tmp")
                    try:
                        with part.open("x", encoding="utf-8") as stream:
                            part.chmod(0o600)
                            for record in iter_source_records(file, args.kind or KINDS[file.suffix.lower()], options):
                                if is_old(record, {"filename": file.name}):
                                    entry["skipped_old"] += 1
                                    continue
                                record = apply_year_policy(record, {"filename": file.name})
                                record["raw"].update(original_file=str(file), file_sha256=digest)
                                record["source_key"] = digest[:16] + "/" + record["source_key"]
                                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                                entry["records"] += 1
                                entry["unknown_year"] += int(record["year"] is None)
                                counts[record["completeness"]] += 1
                        part.replace(spool)
                    finally:
                        if part.exists():
                            part.unlink()
                    entry.update(completeness=dict(counts), failed_records=counts["failed"], conversion=stats,
                                 source_report=source_report, output_sha256=file_hash(spool))
                    atomic_json(manifest, entry)
                with spool.open(encoding="utf-8") as stream:
                    for line in stream:
                        dest.write(line)
                report["files"].append(entry)
                report["total_records"] += entry["records"]
                report["skipped_old"] += entry["skipped_old"]
                report["unknown_year"] += entry["unknown_year"]
                totals.update(entry["completeness"])
                for field in ("ocr_requests", "cache_hits", "failed_pages", "completed_pages"):
                    report[field] += entry.get("conversion", {}).get(field, 0)
        temporary.replace(output)  # Rebuild rather than append: resume cannot duplicate questions.
    finally:
        if temporary.exists():
            temporary.unlink()
    report.update(output=str(output), output_sha256=file_hash(output), completeness=dict(totals),
                  needs_review=sum(totals[s] for s in ("needs_review", "deferred_graphic", "failed")),
                  elapsed_seconds=round(time.perf_counter() - started, 4))
    report_path = args.report or output.with_suffix(output.suffix + ".report.json")
    atomic_json(report_path, report)
    print(json.dumps({k: v for k, v in report.items() if k != "files"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
