"""Standalone runner for the same online collection feature used by the web UI."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    from backend.question_source_collector import collect
    from backend.source_policy import default_mock_years
    parser = argparse.ArgumentParser(description="批量找新模考、导数和概率题源；自动下载、缓存、切题，不解题")
    parser.add_argument("--years", type=int, nargs="+", default=default_mock_years(), help="默认最近两个年份")
    parser.add_argument("--root", type=Path, default=ROOT / ".runtime/question-pool/collections")
    parser.add_argument("--report", type=Path, help="另存本次完整报告，便于对比多次运行")
    parser.add_argument("--quiet", action="store_true", help="仅输出最终摘要，完整进度仍写入 progress.json")
    parser.add_argument("--max-pages", type=int, default=32, help="每个目录最多搜索页数")
    parser.add_argument("--concurrency", type=int, choices=range(1, 21), default=20)
    parser.add_argument("--no-ocr", dest="ocr", action="store_false", default=True)
    parser.add_argument("--download-only", dest="convert", action="store_false", default=True)
    parser.add_argument("--cached-only", action="store_true", help="只转换已下载文件，不再搜索网页")
    parser.add_argument("--no-retry-failed", dest="retry_failed", action="store_false", default=True,
                        help="保留失败页缓存，不再次请求；成功页始终复用")
    parser.add_argument("--no-import", dest="import_pool", action="store_false", default=True)
    parser.add_argument("--no-structured", dest="structured", action="store_false", default=True)
    parser.add_argument("--no-topics", dest="topics", action="store_false", default=True)
    args = parser.parse_args()
    def progress(report):
        if not args.quiet:
            print(report["message"], file=sys.stderr, flush=True)
    report = collect(vars(args), args.root, progress)
    report_path = args.report or args.root / "collection-report.json"
    if args.report:
        from backend.source_conversion import atomic_json
        atomic_json(args.report, report)
    summary = {key: report[key] for key in ("run_id", "discovered", "downloaded", "converted", "verified_papers",
               "unverified_papers", "question_records", "added_occurrences", "ocr_requests", "failed_pages", "solver_requests", "elapsed_seconds")}
    print(json.dumps({**summary, "report": str(report_path.resolve())}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
