"""Import a pinned local source into the private question pool, or inspect it.

Example (no AI calls):
  python scripts/import_question_pool.py --source-name HighMATH --kind highmath \
    --path .runtime/question-pool/sources/highmath --revision 0f1a3636 --dry-run
"""

import argparse
from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    from backend.pool_sources import SOURCE_KINDS, iter_source_records
    from backend.source_policy import MIN_YEAR, is_old, apply_year_policy
    from backend.source_conversion import parse_pages
    parser = argparse.ArgumentParser(description="导入主人原题池；默认仅本地保存，不公开，不调用解题 AI")
    parser.add_argument("--source-name", required=True)
    parser.add_argument("--kind", choices=SOURCE_KINDS, required=True)
    parser.add_argument("--path", type=Path, required=True)
    parser.add_argument("--revision", default="")
    parser.add_argument("--url", default="")
    parser.add_argument("--license", default="待核验，未自动授权公开")
    parser.add_argument("--publication-allowed", action="store_true", help="仅在已经核验来源许可时允许后续确认公开")
    parser.add_argument("--ocr", action="store_true", help="显式文件导入使用已配置 DeepSeek 进行付费 OCR；公开仓库数据不需要")
    parser.add_argument("--ocr-mode", choices=("auto", "off", "force"))
    parser.add_argument("--pages", default="")
    parser.add_argument("--concurrency", type=int, choices=range(1, 21), default=20)
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--cache-dir", type=Path, default=ROOT / ".runtime/question-pool/conversion-cache")
    parser.add_argument("--answers", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="核对数量和状态，不写原题池")
    args = parser.parse_args()
    options = {"ocr": args.ocr, "ocr_mode": args.ocr_mode, "concurrency": args.concurrency,
               "page_numbers": parse_pages(args.pages), "retry_failed": args.retry_failed,
               "resume": True, "cache_dir": str(args.cache_dir), "filename": args.path.name,
               "answers_path": str(args.answers) if args.answers else None}
    conversion_stats, source_report = {}, {}
    if args.ocr and args.kind not in ("image", "pdf"):
        parser.error("OCR 只适用于明确导入的图片或扫描 PDF")
    counts = Counter()
    categories = Counter()
    answers = 0
    solutions = 0
    skipped_old, unknown_year = 0, 0
    def records():
        nonlocal answers, solutions, skipped_old, unknown_year
        for record in iter_source_records(args.path, args.kind, {**options, "stats": conversion_stats, "source_report": source_report}):
            if is_old(record, {"filename": args.path.name}):
                skipped_old += 1
                if not args.dry_run:
                    yield record  # The common importer persists the skip report.
                continue
            record = apply_year_policy(record, {"filename": args.path.name})
            unknown_year += int(record["year"] is None)
            counts[record["completeness"]] += 1
            categories.update(record["categories"])
            answers += bool(record["answer"])
            solutions += bool(record["solution"])
            yield record
    if args.dry_run:
        for _ in records():
            pass
        result = {"dry_run": True}
    else:
        from backend.question_pool import files_directory, import_records
        source = {
            "name": args.source_name, "kind": args.kind, "revision": args.revision,
            "url": args.url, "license": args.license, "publication_allowed": args.publication_allowed,
            "options": options,
        }
        if args.path.is_file():
            digest = sha256()
            with args.path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            extension = args.path.suffix.lower().lstrip(".")
            if not extension.isalnum():
                parser.error("原文件需要有效扩展名")
            token = digest.hexdigest() + "." + extension
            directory = files_directory()
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            target = directory / token
            if not target.exists():
                # Exclusive creation avoids following an existing destination symlink.
                with args.path.open("rb") as origin, target.open("xb") as dest:
                    shutil.copyfileobj(origin, dest)
                os.chmod(target, 0o600)
            source.update({"filename": args.path.name, "file_token": token})
        result = import_records(source, records())
    print(json.dumps({"source": args.source_name, "total": sum(counts.values()), "completeness": dict(counts),
                      "categories": dict(categories), "with_original_answer": answers,
                      "with_original_solution": solutions, "minimum_year": MIN_YEAR, "skipped_old": skipped_old,
                      "unknown_year": unknown_year, "conversion": conversion_stats, "source_report": source_report,
                      "result": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
