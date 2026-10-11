"""Preview/apply one human decision to an independent offline catalogue copy."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend import routine_classification as rc
from backend.routine_matching import apply_review_decision


def main(argv=None):
    parser = argparse.ArgumentParser(description="人工审核套路候选；默认只预览，--apply 写扩展目录副本")
    parser.add_argument("--catalog", type=Path, default=rc.DEFAULT_CATALOG)
    parser.add_argument("--queue", required=True, type=Path, help="分类报告的 unmatched.json")
    parser.add_argument("--decision", required=True, type=Path, help="一个人工决定 JSON 对象")
    parser.add_argument("--overrides", type=Path, help="已有人工修正，合并保留其他题目的修正")
    parser.add_argument("--output", required=True, type=Path, help="独立的新目录；不覆盖已有输出")
    parser.add_argument("--apply", action="store_true", help="将已明确确认的决定写入独立目录")
    args = parser.parse_args(argv)
    try:
        catalog, queue, decision = rc.load_catalog(args.catalog), rc.read_json(args.queue), rc.read_json(args.decision)
        if not isinstance(queue, dict) or queue.get("schema_version") != 1 or not isinstance(queue.get("entries"), list):
            raise ValueError("审核队列格式无效")
        if queue.get("catalog_hash") != rc.digest(catalog):
            raise ValueError("队列与目录不一致，请重新生成分类报告")
        if not isinstance(decision, dict):
            raise ValueError("人工决定须为一个 JSON 对象")
        entries = [e for e in queue["entries"] if e.get("review_id") == decision.get("review_id")]
        if len(entries) != 1:
            raise ValueError("审核编号不存在或重复")
        updated, record, override = apply_review_decision(catalog, entries[0], decision)
        overrides = rc.load_overrides(args.overrides, updated)
        overrides[override["id"]] = override
        sources = {p.resolve() for p in (args.catalog, args.queue, args.decision, args.overrides) if p is not None}
        targets = [args.output / name for name in ("catalog.json", "overrides.json", "decision.json")]
        if any(path.resolve() in sources or path.exists() or path.is_symlink() for path in targets):
            raise ValueError("输出会覆盖输入或已有审核结果，请使用新的独立输出目录")
        preview = {"mode": "apply" if args.apply else "dry_run", "decision": record,
                   "catalog_version": updated["version"], "catalog_total": len(updated["routines"]),
                   "output": str(args.output.resolve()), "formal_pattern_created": False}
        if args.apply:
            rc.write_json(targets[0], updated)
            rc.write_json(targets[1], list(overrides.values()))
            rc.write_json(targets[2], record)
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
