"""Measure serial OCR, two concurrent pages, then a cache-only replay.

Uses identical pages, render settings and transcription prompt in both runs.
Serial mode represents the original scheduling; parser changes are held constant.
This calls the configured cloud OCR. All outputs remain review candidates.
"""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    from backend.pool_sources import iter_source_records
    from backend.source_conversion import parse_pages, atomic_json, file_hash
    parser = argparse.ArgumentParser(description="同页实测串行/双并发/缓存重跑；会调用现有云 OCR")
    parser.add_argument("file", type=Path)
    parser.add_argument("--pages", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--ocr", choices=("auto", "force"), default="force")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    report = {"file": str(args.file.resolve()), "file_sha256": file_hash(args.file), "pages": parse_pages(args.pages),
              "method": "同一提示词与切题程序，只比较原有串行调度、两页并发与缓存重跑；云端延迟随负载变化", "runs": []}
    for name, concurrency, reuse in (("serial", 1, False), ("parallel", 2, False), ("cached_replay", 2, True)):
        cache = args.output_dir / ("parallel-cache" if reuse else name + "-cache")
        stats = {}
        def progress(current):
            print(f"{name}: 完成页 {current['completed_pages']}/{current['total_pages']} · 请求 {current['ocr_requests']} · 缓存 {current['cache_hits']} · 失败 {current['failed_pages']}", file=sys.stderr, flush=True)
        options = {"ocr_mode": args.ocr, "page_numbers": report["pages"], "concurrency": concurrency,
                   "cache_dir": cache, "stats": stats, "resume": True, "retry_failed": True, "progress": progress}
        started = time.perf_counter()
        records = list(iter_source_records(args.file, "pdf", options))
        elapsed = round(time.perf_counter() - started, 3)
        path = args.output_dir / (name + ".jsonl")
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
        path.chmod(0o600)
        run = {"name": name, "elapsed_seconds": elapsed, "records": len(records), "needs_review": sum(r["completeness"] != "complete" for r in records),
               "failed_records": sum(r["completeness"] == "failed" for r in records), "conversion": stats, "output": str(path.resolve())}
        report["runs"].append(run)
        atomic_json(args.output_dir / "benchmark-report.json", report)
        if run["failed_records"]:
            print("存在失败页面，请检查报告；成功页已缓存，重跑只重试失败页。", file=sys.stderr)
            return 1
    serial, parallel = report["runs"][:2]
    report["speedup"] = round(serial["elapsed_seconds"] / parallel["elapsed_seconds"], 3) if parallel["elapsed_seconds"] else None
    atomic_json(args.output_dir / "benchmark-report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
