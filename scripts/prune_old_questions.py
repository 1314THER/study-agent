"""Generate an evidence manifest; --apply backs up and removes known pre-2016 questions."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    from backend.question_pool_maintenance import build_plan, backup_databases, write_report, apply_plan
    parser = argparse.ArgumentParser(description="删除能够证实为 2015 年及以前的题，未知年份保留")
    parser.add_argument("--pool", type=Path, default=ROOT / ".runtime/question_pool.db")
    parser.add_argument("--formal", type=Path, default=ROOT / "study_agent.db")
    parser.add_argument("--mastery", type=Path, default=ROOT / "mastery.db")
    parser.add_argument("--output", type=Path, default=ROOT / ".runtime/question-pool/cleanup")
    parser.add_argument("--apply", action="store_true", help="明确执行：先备份、保存删除清单，再在事务内删除")
    args = parser.parse_args()
    directory = args.output / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    if args.apply:
        backup_databases([args.pool, args.formal, args.mastery], directory / "backup")
    plan = build_plan(args.pool, args.formal, args.mastery)
    write_report(directory / "deletion-manifest.json", plan)
    result = apply_plan(args.pool, args.formal, args.mastery, plan) if args.apply else {"dry_run": True}
    write_report(directory / "result.json", result)
    print(json.dumps({"directory": str(directory.resolve()), "delete_items": len(plan["delete_items"]),
                      "delete_occurrences": len(plan["delete_occurrences"]), "delete_formal_questions": len(plan["delete_formal_questions"]),
                      "result": result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
