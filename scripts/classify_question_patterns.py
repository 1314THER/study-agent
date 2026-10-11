"""Prepare advisory routine groups from an explicit offline JSONL export."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import routine_classification as rc


def main(argv=None, caller=None):
    parser = argparse.ArgumentParser(description="离线套路整理；默认预演，无题库读写，无自动入库")
    parser.add_argument("--catalog", type=Path, default=rc.DEFAULT_CATALOG)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--validate-catalog", action="store_true", help="只校验独立套路目录")
    mode.add_argument("--classify", action="store_true", help="显式调用 AI 分类；仅写独立报告")
    mode.add_argument("--report-only", action="store_true", help="从已有缓存和人工修正重建报告，不调用 AI")
    parser.add_argument("--input", type=Path, help="明确指定的 .jsonl/.ndjson 离线题目文件")
    parser.add_argument("--output", type=Path, default=ROOT / ".runtime" / "routine-classification")
    parser.add_argument("--overrides", type=Path, help="人工修正 JSON；默认读取输出目录的 overrides.json")
    parser.add_argument("--limit", type=int, default=100, help="最多新处理题数；0 表示全部；缓存不占额度")
    parser.add_argument("--retry-failed", action="store_true", help="重新处理已缓存的失败项")
    parser.add_argument("--attempts", type=int, choices=(1, 2, 3), default=2)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--model", default="deepseek-flash")
    parser.add_argument("--base-url", default="https://api.deepseek.com/v1")
    parser.add_argument("--max-tokens", type=int, default=4096)
    args = parser.parse_args(argv)
    try:
        if args.limit < 0 or args.timeout < 1 or args.max_tokens < 1:
            raise ValueError("limit 不能为负，timeout 与 max-tokens 必须为正")
        catalog = rc.load_catalog(args.catalog)
        if args.validate_catalog:
            from collections import Counter
            print(json.dumps({"valid": True, "version": catalog["version"], "total": len(catalog["routines"]),
                              "categories": dict(Counter(r["category"] for r in catalog["routines"]))}, ensure_ascii=False, indent=2))
            return 0
        if args.input is None:
            parser.error("请指定 --input 离线文件，或使用 --validate-catalog")
        items = rc.load_items(args.input)
        # Reject report outputs that could replace an input/catalog/override.
        override_path = args.overrides or args.output / "overrides.json"
        sources = {p.resolve() for p in (args.input, args.catalog, override_path)}
        if any((args.output / name).resolve() in sources for name in rc.REPORT_FILES):
            raise ValueError("报告路径与输入、目录或人工修正文件冲突")
        if any(p.is_relative_to((args.output / "cache").resolve()) for p in sources):
            raise ValueError("输入、目录和人工修正文件必须位于分类缓存目录之外")
        config = {"model": args.model, "base_url": args.base_url, "temperature": 0.1,
                  "max_tokens": args.max_tokens}
        overrides = rc.load_overrides(override_path, catalog)
        preview = rc.plan_run(items, catalog, args.output, config, overrides)
        if not args.classify and not args.report_only:
            print(json.dumps(preview, ensure_ascii=False, indent=2))
            return 0
        if args.classify and caller is None:
            queued = preview["counts"].get("pending", 0) + preview["counts"].get("matching", 0) + (preview["counts"].get("error", 0) if args.retry_failed else 0)
            if queued:
                caller = rc.make_http_caller(config, api_key=os.environ.get("DEEPSEEK_API_KEY", ""), timeout=args.timeout)
        if args.report_only:
            caller = None
        def progress(done, total, row):
            if args.classify:
                print(f"{done}/{total} · 原题 {row['id']} · {row['status']}", file=sys.stderr)
        try:
            rows, manifest = rc.classify_items(items, catalog, args.output, config, caller,
                                              limit=args.limit, retry_failed=args.retry_failed,
                                              attempts=args.attempts, overrides=overrides, progress=progress)
        except KeyboardInterrupt:
            # A signal between requests/progress callbacks still recovers cache.
            rows, manifest = rc.classify_items(items, catalog, args.output, config, None,
                                              overrides=overrides)
            manifest.update(interrupted=True, api_attempts=None)
        manifest["mode"] = "classify" if args.classify else "report_only"
        rc.write_reports(args.output, rows, catalog, manifest)
        print(json.dumps({**manifest, "output": str(args.output.resolve()), "advisory_only": True}, ensure_ascii=False, indent=2))
        if manifest["interrupted"]:
            return 130
        return 1 if manifest["counts"].get("error", 0) else 0
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
