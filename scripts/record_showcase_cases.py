"""Record national-exam showcase cases with the application's real model calls.

The default only writes the fixed inputs and truthful pending states. ``--run``
uses the configured provider; completed records are reused, never resampled to
manufacture a comparison. All mutable teaching/generation data stays temporary.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DESTINATION = ROOT / "frontend/showcase/recordings.json"
BASELINE_PROMPT = """你是一位认真、耐心的高中数学教师。请批改给定学生作答，指出最早错误位置、原文依据、后续受影响的步骤、可确认与不能确认的原因，并给出具体的下一步学习建议。尊重与参考答案不同的正确解法。不能由缺步或单次错误推断学生必然不会相关知识；证据不足时明确保留判断。提示后答对不等于长期独立掌握。请用中文具体说明，不要编造学生没有写过的内容或不存在的历史。"""
TRACE = ContextVar("showcase_recording_calls", default=None)


def trace_records():
    records = TRACE.get()
    if records is None:
        records = []
        TRACE.set(records)
    return records


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256((value if isinstance(value, str) else canonical(value)).encode()).hexdigest()


def now():
    return datetime.now().astimezone().isoformat()


def material(example_id, first_part=False):
    from backend.demo_presets import get_preset
    preset = get_preset(example_id)
    pipeline = json.loads((ROOT / "frontend/showcase/pipeline.json").read_text())
    run = deepcopy(pipeline["examples"][example_id]["liangliang"])
    answer = run["answer_json"]
    question = preset["question"]
    if first_part:
        question = question.split("\n(2)")[0]
        answer["chunk_results"] = answer["chunk_results"][:1]
        answer["final_answer"] = answer["chunk_results"][0]["final_answer"]
    return question, answer, run


def fixed_cases():
    triangle, _, _ = material("national-2023-q17", True)
    complete_triangle, _, _ = material("national-2023-q17")
    sequence, _, _ = material("national-2025-q16")
    rows = [
        ("propagation", "首错与连带错误", triangle, "national-2023-q17", True,
         r"由 A+B=3C 和 A+B+C=π，得 C=π/3。于是 B=2π/3-A。代入 2sin(A-C)=sinB，展开得 sinA-√3cosA=(sinA+√3cosA)/2，所以 tanA=3√3，sinA=3√21/14。",
         [], "角 C 的计算先出错，后续推导沿用了该值。", "核对 C=π/3 的首错；区分后续条件性计算与新的独立错误，不把连带结果当成多个独立知识缺陷。"),
        ("omission", "答案正确但省略推理", triangle, "national-2023-q17", True,
         r"sin A=3√10/10。", [], "只写了正确的最终答案。", "最终结果匹配，但关键推理没有呈现。不能从这份作答确认全部过程掌握，也不能确定学生完全不会。"),
        ("alternative", "正确的替代解法", complete_triangle, "national-2023-q17", False,
         r"由 A+B+C=π、A+B=3C 得 C=π/4。sinB=sin(A+C)，代入条件得 sinA cosC=3cosA sinC，所以 tanA=3。A∈(0,π)，故 A 是锐角，sinA=3/√10，cosA=1/√10。sinB=sin(A+π/4)=2/√5。由正弦定理，BC=AB·sinA/sinC=3√5。作 CD⊥AB，则 CD=BC·sinB=6。",
         [], "第二问通过 BC 与角 B 求高，不沿用参考的 AC 与角 A 路径。", "独立核验数学等价性，不能因参考路径中 AC 未出现而判为关键步骤缺失。"),
        ("uncertain-cause", "错误可见，原因不明", triangle, "national-2023-q17", True,
         r"由内角和得 C=π/4，B=3π/4-A。代入可得 sinA=3cosA。令 cosA=k，sinA=3k，则 k²+9k²=1，k=1/√10，所以 sinA=√10/10。",
         [], "前面得到 sinA=3k，最后一行漏掉系数 3。", "可以指出不一致，但单次作答不足以区分笔误、代入失误或知识理解问题，不能确定为粗心或心态问题。"),
        ("assisted", "提示后答对不等于独立掌握", triangle, "national-2023-q17", True,
         r"A+B+C=π，A+B=3C，因此 C=π/4。由 2sin(A-π/4)=sin(A+π/4)，得 sinA=3cosA，故 tanA=3。A 是锐角，由 sin²A+cos²A=1 得 sinA=3√10/10。",
         [{"type": "hint", "content": "本次作答前已查看提示：结合内角和求 C，再展开两角和差公式，得到 sinA=3cosA。"}, {"type": "independence", "content": "没有未见新题或延迟复测记录。"}],
         "作答数学正确，但本次接受过关键提示。", "批改可以判本次过程正确；对独立识别方法、长期保持和新题迁移应保留判断。"),
        ("method-boundary", "表象相似但不能直接套公式", sequence, "national-2025-q16", False,
         r"两边同乘 n(n+1)，得 (n+1)a_(n+1)=na_n+1，令 b_n=na_n，则 b_n=n+2，a_n=1+2/n。求导可得 f′(-2)=Σ_(k=1)^m (k+2)(-2)^(k-1)。这里有 (-2) 的幂，所以是首项为3、公比为-2的等比数列，故 f′(-2)=1-(-2)^m。",
         [{"type": "prior-example", "content": "构造的学习情境：学生此前能正确计算 Σ 3(-2)^(k-1)，但本次将含变化系数 k+2 的求和也认作等比求和。此情境不是真实学生历史。"}],
         "乘积项中的系数随 k 变化，不能仅因出现 (-2) 的幂就认作等比数列。", "区分已经正确构造数列、求导与求和方法误用；说明适用条件，不能由旧任务通过直接确认新任务掌握。"),
    ]
    cases = []
    for cid, title, question, example, first, answer, history, observation, expected in rows:
        cases.append(dict(id=cid, title=title, question=question, example_id=example,
                          first_part=first, student_answer=answer, history=history,
                          observation=observation, expected=expected, constructed_student=True,
                          basic={"status": "pending", "content": ""},
                          same_information={"status": "pending", "content": ""},
                          system={"status": "pending", "content": ""}))
    return cases


def build_pending():
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    return {"version": 1, "provenance": {"execution_origin": "local_production_code",
            "source_commit": commit, "prepared_at": now(), "recorded_at": None,
            "notes": ["学生作答和情境为预先构造的演示输入，不是真实学生研究数据。",
                      "调用本地仓库正式业务函数和实际模型 API；不是线上正式站 HTML 抓取。",
                      "不对结果挑选性重跑；比较仅用于案例说明，不提供准确率或学习增益结论。",
                      "系统当前批改函数没有独立历史参数；存在历史时，录制器将客观过程说明附于作答文本，并向同信息基线提供同等内容。",
                      "不设置没有教师确认的分值量规，不把 AI 暂定分数作为考试得分。"],
            "source_hashes": {str(p.relative_to(ROOT)): digest(p.read_text()) for p in
                [ROOT / "backend/grade.py", ROOT / "backend/teach.py", ROOT / "backend/generate.py", ROOT / "backend/prompts/grade.md"]}},
            "baseline_prompt": BASELINE_PROMPT, "cases": fixed_cases(),
            "teaching": {"status": "pending", "frames": []},
            "generation": {"status": "pending", "question": ""}}


def trace_call(original, *args, **kwargs):
    from backend import solver
    began = time.monotonic()
    content, usage = original(*args, **kwargs)
    system = args[0] + ("\n\n" + solver._LATEX_RULES if solver._LATEX_RULES else "")
    trace_records().append({"system_prompt": system, "user_prompt": args[1],
        "model": kwargs.get("model", "deepseek-flash"),
        "reasoning_effort": kwargs.get("reasoning_effort"),
        "temperature": kwargs.get("temperature", 0.3), "content": content,
        "usage": usage, "seconds": round(time.monotonic() - began, 3)})
    return content, usage


def captured(operation, model_config, input_value):
    TRACE.set([])
    began = time.monotonic()
    try:
        structured = operation()
        if isinstance(structured, dict) and structured.get("error"):
            raise RuntimeError(structured.get("error"))
        content = trace_records()[-1]["content"] if trace_records() else canonical(structured)
        return {"status": "recorded", "content": content, "structured": structured,
                "model": model_config.get("model"), "config": model_config,
                "recorded_at": now(), "seconds": round(time.monotonic() - began, 3),
                "input_sha256": digest(input_value), "response_sha256": digest(content),
                "calls": deepcopy(trace_records())}
    except Exception as error:
        # Exception text can contain provider diagnostics; expose only its type.
        return {"status": "failed", "content": "", "error": type(error).__name__,
                "recorded_at": now(), "input_sha256": digest(input_value), "calls": deepcopy(trace_records())}


def record_case(case, condition, teacher, config):
    from backend import grade, solver
    _, reference, _ = material(case["example_id"], case["first_part"])
    context = {"question": case["question"], "student_answer": case["student_answer"]}
    full_context = {**context, "reference_answer": reference, "history": case["history"]}
    if condition != "system":
        supplied = context if condition == "basic" else full_context
        text = json.dumps(supplied, ensure_ascii=False, indent=2)
        return captured(lambda: solver.call_deepseek(BASELINE_PROMPT, text, temperature=0.2,
            model=config["model"], reasoning_effort=config.get("reasoning_effort")), config, supplied)
    student = case["student_answer"]
    if case["history"]:
        student += "\n\n【本次作答的客观过程说明，不是学生答案的一部分】\n" + json.dumps(case["history"], ensure_ascii=False)
    return captured(lambda: grade.grade_prepared(case["question"], reference, student,
                    question_type="大题", teacher=teacher), config, full_context)


def save(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Separate ``--only`` processes may finish out of order. Never let their
    # older pending snapshot erase an already captured, paid response.
    lock_path = Path(tempfile.gettempdir()) / ("study-showcase-" + digest(str(path.resolve())) + ".lock")
    with lock_path.open("a+") as lock:
        try:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        except ImportError:  # Windows: runs should remain sequential.
            pass
        if path.exists():
            existing = json.loads(path.read_text())
            previous = {c["id"]: c for c in existing.get("cases", [])}
            for case in payload.get("cases", []):
                old = previous.get(case["id"], {})
                if old.get("question") != case.get("question") or old.get("student_answer") != case.get("student_answer"):
                    continue
                for condition in ("basic", "same_information", "system"):
                    if case[condition]["status"] == "pending" and old.get(condition, {}).get("status") in ("recorded", "failed"):
                        case[condition] = old[condition]
                    elif old.get(condition, {}).get("recorded_at", "") > case[condition].get("recorded_at", ""):
                        case[condition] = old[condition]
            for name in ("teaching", "generation"):
                if payload.get(name, {}).get("status") == "pending" and existing.get(name, {}).get("status") in ("recorded", "failed"):
                    payload[name] = existing[name]
                elif max(existing.get(name, {}).get("recorded_at", ""), existing.get(name, {}).get("continued_at", "")) > max(payload.get(name, {}).get("recorded_at", ""), payload.get(name, {}).get("continued_at", "")):
                    payload[name] = existing[name]
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(path)


@contextmanager
def isolated_workspace():
    from backend import settings
    from backend.data_paths import workspace
    config = deepcopy(settings.get_settings())
    config["api"]["deepseek"]["api_key"] = settings.get_api_key("deepseek")
    # Isolated copies use the same official endpoint/config; never owner DBs.
    with tempfile.TemporaryDirectory(prefix="showcase-recording-") as directory:
        path = Path(directory) / "settings.json"
        path.write_text(json.dumps(config, ensure_ascii=False))
        path.chmod(0o600)
        with workspace(directory):
            from backend.database import init_db
            init_db()
            yield directory


def record_teaching(teacher, config):
    from backend import database, teach
    question, reference, _ = material("national-2023-q17", True)
    with isolated_workspace():
        database.save_question(question, reference, match_existing=False)
        start = teach.teach_session_start(question, teacher)
        if start.get("error"):
            return {"status": "failed", "frames": [], "error": start["error"]}
        sid = start["session_id"]
        frames = [{"input": None, "output": start.get("message", ""), "structured": deepcopy(start)}]
        for answer in ["C=π/3", "请给我提示", "A+B+C=π，且A+B=3C，所以4C=π，C=π/4。"]:
            turn = teach.teach_session_chat(sid, answer)
            frames.append({"input": answer, "output": turn.get("message", ""), "structured": deepcopy(turn)})
        session = teach.teach_get_session(sid)
        return {"status": "recorded", "question": question, "frames": frames,
                "session": deepcopy(session), "model": config["model"], "config": config,
                "recorded_at": now(), "calls": deepcopy(trace_records()),
                "execution_origin": "local_production_code"}


def record_generation(teacher):
    from backend import database, generate
    question, reference, _ = material("national-2023-q17", True)
    with isolated_workspace():
        qid = database.save_question(question, reference, match_existing=False)
        result = generate.generate_variants(qid, count=1, teacher=teacher)
        for candidate in result.get("candidates", []):
            if candidate.get("question_id"):
                row = database.get_question_by_id(candidate["question_id"])
                candidate["answer_json"] = row["answer_json"]
        first = next((c for c in result.get("candidates", []) if c.get("status") == "accepted"), None)
        return {"status": "recorded", "question": first["question"] if first else "",
                "answer_json": first.get("answer_json") if first else None, "structured": result,
                "recorded_at": now(), "calls": deepcopy(trace_records()),
                "execution_origin": "local_production_code", "reference_question": question,
                "note": "真实变式生成与三阶段检查结果；若无通过候选，保留实际拒绝结果。"}


def continue_teaching(recording):
    """Continue the captured session with a new, complete student attempt."""
    from backend import database, teach
    if any(frame.get("structured", {}).get("action") == "advance" for frame in recording.get("frames", [])):
        return recording

    question, reference, _ = material("national-2023-q17", True)
    with isolated_workspace():
        database.save_question(question, reference, match_existing=False)
        session = deepcopy(recording["session"])
        session["attempt_count"] = sum(m.get("role") == "student" and m.get("step_index") == session["current_step"] for m in session["messages"])
        teach._session_manager._store(session)
        answer = r"A+B+C=π，A+B=3C，所以C=π/4，B=3π/4-A。将其代入2sin(A-C)=sinB，展开后约去√2/2，得2(sinA-cosA)=sinA+cosA，即sinA=3cosA。A为三角形内角，sinA>0，故cosA>0，可以相除得到tanA=3。"
        turn = teach.teach_session_chat(session["session_id"], answer)
        recording["frames"].append({"input": answer, "output": turn.get("message", ""), "structured": deepcopy(turn)})
        recording["session"] = deepcopy(teach.teach_get_session(session["session_id"]))
        recording["calls"].extend(deepcopy(trace_records()))
        recording["continued_at"] = now()
        return recording


def resume_generation(recording, teacher):
    """Check the exact already-generated candidate after a recorder failure."""
    from backend import database, generate
    candidates = recording.get("structured", {}).get("candidates", [])
    if not candidates or not any("_thread._local" in c.get("rejected_reason", "") for c in candidates):
        raise ValueError("Only a recorder trace failure can be resumed; mathematical rejection is final.")
    question, reference, _ = material("national-2023-q17", True)
    with isolated_workspace():
        qid = database.save_question(question, reference, match_existing=False)
        candidate = deepcopy(candidates[0])
        checked = generate._solve_candidate(candidate, teacher)
        answer_json = None
        if checked.get("status") == "accepted":
            answer_json = deepcopy(checked["result"])
            checked["question_id"] = generate._save_accepted(generate._load_reference(qid), checked)
            checked.pop("result", None)
        accepted = int(checked.get("status") == "accepted")
        return {"status": "recorded", "question": checked["question"] if accepted else "",
                "answer_json": answer_json,
                "structured": {"reference_question_id": qid, "teacher": teacher,
                               "accepted": accepted, "rejected": 1 - accepted, "candidates": [checked]},
                "recorded_at": now(), "calls": recording["calls"] + deepcopy(trace_records()),
                "execution_origin": "local_production_code", "reference_question": question,
                "recording_incident": "原始候选已生成；录制器子线程 trace 故障后修复，对同一候选继续校验，未重新生成候选。",
                "previous_attempt": recording,
                "note": "真实生成候选与三阶段校验；保留录制故障及同一候选的恢复记录。"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="实际调用已配置的模型 API")
    parser.add_argument("--workers", type=int, default=3, choices=range(1, 5))
    parser.add_argument("--teacher", default="liangliang", choices=["liangliang", "taotao", "xuefeng", "ji"])
    parser.add_argument("--only", choices=["comparisons", "teaching", "generation"])
    parser.add_argument("--continue-teaching", action="store_true", help="继续已录制会话，补充新的完整作答，不重跑既有分支")
    parser.add_argument("--resume-generation", action="store_true", help="修复录制器故障后，只校验原始候选，不重新出题")
    parser.add_argument("--output", type=Path, default=DESTINATION)
    args = parser.parse_args()
    payload = json.loads(args.output.read_text()) if args.output.exists() else build_pending()
    save(args.output, payload)
    if not args.run:
        print("Prepared six fixed inputs; no model requests made.")
        return
    from backend import grade, solver, teach, generate, settings
    if not settings.get_api_key("deepseek"):
        raise SystemExit("No configured provider key; pending records retained.")
    original = solver.call_deepseek
    wrapped = lambda *a, **kw: trace_call(original, *a, **kw)
    solver.call_deepseek = grade.call_deepseek = teach.call_deepseek = generate.call_deepseek = wrapped
    cfg = settings.get_teacher_config(args.teacher)
    grade_cfg = cfg.get("grade") or cfg["verifier"]
    if args.resume_generation:
        TRACE.set([])
        payload["generation"] = resume_generation(payload["generation"], args.teacher)
        save(args.output, payload)
        print("generation resumed", flush=True)
        return
    if args.continue_teaching:
        if payload["teaching"]["status"] != "recorded":
            raise SystemExit("No recorded teaching session to continue.")
        TRACE.set([])
        payload["teaching"] = continue_teaching(payload["teaching"])
        save(args.output, payload)
        print("teaching continued", flush=True)
        return
    if args.only in (None, "comparisons"):
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            tasks = {pool.submit(copy_context().run, record_case, case, condition, args.teacher, grade_cfg): (case, condition)
                     for case in payload["cases"] for condition in ("basic", "same_information", "system")
                     if case[condition]["status"] == "pending"}
            for future in as_completed(tasks):
                case, condition = tasks[future]
                case[condition] = future.result()
                save(args.output, payload)
                print(case["id"], condition, case[condition]["status"], flush=True)
    for name, operation in [("teaching", lambda: record_teaching(args.teacher, cfg["verifier"])),
                            ("generation", lambda: record_generation(args.teacher))]:
        if args.only not in (None, name) or payload[name]["status"] != "pending":
            continue
        TRACE.set([])
        try:
            payload[name] = operation()
        except Exception as error:
            payload[name] = {"status": "failed", "error": type(error).__name__, "frames": [], "question": "", "calls": deepcopy(trace_records())}
        save(args.output, payload)
        print(name, payload[name]["status"], flush=True)
    payload["provenance"]["recorded_at"] = now()
    save(args.output, payload)


if __name__ == "__main__":
    main()
