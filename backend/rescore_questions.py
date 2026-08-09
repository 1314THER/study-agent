"""按新难度管线重跑题库存量题：Solver → Verifier → Formatter，并回写数据库。"""

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import difficulty as diff
from backend.database import get_connection, save_question
from backend.solver import step_final_check, step_solver_only, step_verify_all


def _clean_final(final: dict) -> dict:
    out = dict(final)
    out.pop("error", None)
    out.pop("formatter_note", None)
    return out


def rescore_question(question: str, question_type: str, teacher: str) -> dict:
    token_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    solver = step_solver_only(question, question_type=question_type, teacher=teacher)
    if solver.get("error"):
        return {"status": "failed", "rejected_reason": solver.get("detail") or solver.get("status") or "Solver 失败"}
    for k in token_total:
        token_total[k] += (solver.get("token_usage") or {}).get(k, 0)

    verified = step_verify_all(
        solver["content"],
        question,
        solver.get("category"),
        question_type=question_type,
        teacher=teacher,
    )
    if verified.get("error"):
        return {"status": "failed", "rejected_reason": verified.get("detail") or verified.get("status") or "Verifier 失败"}
    for k in token_total:
        token_total[k] += (verified.get("token_usage") or {}).get(k, 0)

    final = step_final_check(
        question,
        verified["chunk_results"],
        [],
        token_total,
        teacher=teacher,
        solver_content=solver["content"],
        verifier_category=solver.get("category"),
        question_type=question_type,
    )
    if not final.get("chunk_results"):
        return {"status": "failed", "rejected_reason": "没有可用的 chunk_results"}

    first = final["chunk_results"][0] if final["chunk_results"] else {}
    final["category"] = first.get("category")
    final["difficulty"] = final.get("overall_difficulty") or first.get("difficulty")
    final["question_type"] = first.get("chunk_type")
    return {
        "status": "ok" if not final.get("error") else "formatter_failed",
        "final": final,
        "token_usage": token_total,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="重跑题库存量题的三段管线并回写难度")
    parser.add_argument("--teacher", default="taotao", help="老师配置名，默认 taotao")
    parser.add_argument("--ids", default="", help="只重跑指定 ID，逗号分隔；留空表示全部")
    parser.add_argument("--concurrency", type=int, default=4, help="并发重跑数量，默认 4")
    parser.add_argument("--force", action="store_true", help="忽略已有五维，强制重跑")
    args = parser.parse_args()

    conn = get_connection()
    if args.ids:
        ids = [int(x.strip()) for x in args.ids.split(",") if x.strip()]
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT id, content, question_type, source_type, source_meta, answer_json FROM questions WHERE id IN ({placeholders}) ORDER BY id",
            ids,
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, content, question_type, source_type, source_meta, answer_json FROM questions ORDER BY id"
        ).fetchall()
    conn.close()

    todo = []
    for row in rows:
        try:
            aj = json.loads(row["answer_json"]) if row["answer_json"] else {}
        except (json.JSONDecodeError, TypeError):
            aj = {}
        crs = aj.get("chunk_results") if isinstance(aj, dict) else None
        if not args.force and isinstance(crs, list) and crs and diff.has_step_dimensions(crs):
            print(f"跳过 #{row['id']}：已有新五维难度", flush=True)
            continue
        todo.append(row)

    print(f"待重跑 {len(todo)} 道题，teacher={args.teacher}，并发={args.concurrency}", flush=True)
    total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    lock = threading.Lock()

    def work(index: int, row) -> None:
        qid = row["id"]
        print(f"[{index}/{len(todo)}] 开始重跑 #{qid} ...", flush=True)
        result = None
        last_err = None
        for attempt in range(1, 4):
            try:
                result = rescore_question(row["content"], row["question_type"] or "", args.teacher)
                break
            except Exception as e:
                last_err = e
                print(f"[{index}/{len(todo)}] #{qid} 第 {attempt} 次调用异常：{str(e)[:120]}，重试", flush=True)
                time.sleep(2 * attempt)
        if result is None:
            print(f"[{index}/{len(todo)}] #{qid} 失败：{str(last_err)[:200]}", flush=True)
            return
        if result["status"] == "failed":
            print(f"[{index}/{len(todo)}] #{qid} 失败：{result['rejected_reason']}", flush=True)
            return

        final = _clean_final(result["final"])
        first = final["chunk_results"][0] if final.get("chunk_results") else {}
        final["category"] = first.get("category")
        final["difficulty"] = final.get("overall_difficulty") or first.get("difficulty")
        final["question_type"] = first.get("chunk_type")
        final["source_type"] = row["source_type"]
        if row["source_meta"]:
            try:
                final["source_meta"] = json.loads(row["source_meta"])
            except (json.JSONDecodeError, TypeError):
                final["source_meta"] = None
        try:
            save_question(row["content"], final)
            saved = True
        except Exception as e:
            saved = False
            print(f"[{index}/{len(todo)}] #{qid} 入库失败：{str(e)[:200]}", flush=True)

        od = final.get("overall_difficulty") or {}
        print(
            f"[{index}/{len(todo)}] #{qid} {result['status']} "
            f"难度={od.get('level')} {od.get('total_score')}/15 "
            f"入库={saved} tokens={result['token_usage'].get('total_tokens', 0)}",
            flush=True,
        )
        with lock:
            for k in total_usage:
                total_usage[k] += result["token_usage"].get(k, 0)

    if args.concurrency > 1:
        with ThreadPoolExecutor(max_workers=min(args.concurrency, len(todo) or 1)) as pool:
            futures = [pool.submit(work, i, row) for i, row in enumerate(todo, 1)]
            for f in futures:
                f.result()
    else:
        for i, row in enumerate(todo, 1):
            work(i, row)

    print(f"完成。总 token：{json.dumps(total_usage, ensure_ascii=False)}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
