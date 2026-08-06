"""母题入库脚本。

用法：
  python3 backend/import_mother.py --question-id 1 --category 解析几何 --name "直线与圆锥曲线联立"
"""

import argparse
import os
import sys


def main():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from backend.patterns import add_mother_question, init_mastery_db

    parser = argparse.ArgumentParser(description="将一道题登记为母题并写入 patterns.yaml / mastery.db")
    parser.add_argument("--question-id", type=int, required=True, help="题目在 study_agent.db 中的 ID")
    parser.add_argument("--category", required=True, help="板块，必须与 categories.yaml 一级标题一致")
    parser.add_argument("--name", required=True, help="套路名")
    parser.add_argument("--key", help="套路稳定编号；不填则自动生成")
    parser.add_argument("--description", default="", help="套路说明")
    args = parser.parse_args()

    init_mastery_db()
    result = add_mother_question(
        question_id=args.question_id,
        category=args.category,
        name=args.name,
        key=args.key,
        description=args.description,
    )
    print("母题入库成功：")
    for k, v in result.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
