"""AI 仿题：基于题库原题与学生错因生成变式题，并并发跑完整解题流水线。"""

import json
import logging
import os
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from backend import difficulty as diff
import backend.settings as runtime_settings
from backend.solver import (
    TEACHER_CONFIG,
    _is_well_formed_chunk_results,
    call_deepseek,
    step_solver_only,
    step_verify_all,
    step_final_check,
    _extract_json,
)
from backend.database import (
    find_question,
    get_question_by_id,
    get_step_errors,
    looks_like_choice_question,
    looks_like_multi_choice_question,
    save_question,
)

logger = logging.getLogger(__name__)

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")


def _read_prompt(name: str) -> str:
    with open(os.path.join(PROMPTS_DIR, f"{name}.md"), encoding="utf-8") as f:
        return f.read().strip()


GENERATE_PROMPT = _read_prompt("generate")


def _add_usage(total: dict, usage: dict) -> None:
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        total[key] = total.get(key, 0) + (usage or {}).get(key, 0)


def _normalize_step_name(name: str) -> str:
    return re.sub(r"\s+", "", name or "").strip("：:，,。.")


def _collect_step_titles(chunk_results: list) -> list:
    titles = []
    for cr in chunk_results or []:
        for step in cr.get("steps", []) or []:
            title = step.get("title") or step.get("step_level1") or ""
            title = _normalize_step_name(title)
            if title and title not in titles:
                titles.append(title)
    return titles


def _collect_knowledge_points(result: dict) -> list:
    points = list(result.get("knowledge_points", []) or [])
    for cr in result.get("chunk_results", []) or []:
        for kp in cr.get("knowledge_points", []) or []:
            if kp and kp not in points:
                points.append(kp)
    return points


def _load_reference(qid: int) -> dict:
    question = get_question_by_id(qid)
    if not question:
        raise ValueError(f"题目不存在: {qid}")
    aj = question.get("answer_json") or {}
    if not isinstance(aj, dict):
        aj = {}

    category = question.get("category_level1")
    if not category:
        raw_cat = aj.get("category")
        if isinstance(raw_cat, dict):
            category = raw_cat.get("level1")
        elif isinstance(raw_cat, str):
            category = raw_cat
    if not category and aj.get("chunk_results"):
        category = aj["chunk_results"][0].get("category")
        if isinstance(category, dict):
            category = category.get("level1")

    question_type = question.get("question_type")
    if not question_type and aj.get("chunk_results"):
        question_type = aj["chunk_results"][0].get("chunk_type")
    if question_type not in ("选择题", "填空题", "多选题"):
        question_type = "大题"
    if looks_like_multi_choice_question(question.get("content", ""), aj):
        question_type = "多选题"
    elif question_type == "大题" and looks_like_choice_question(question.get("content", "")):
        question_type = "选择题"

    difficulty = aj.get("overall_difficulty") or aj.get("difficulty") or {}
    if not isinstance(difficulty, dict):
        difficulty = {}
    chunk_results = aj.get("chunk_results")
    if isinstance(chunk_results, list) and chunk_results and diff.has_step_dimensions(chunk_results):
        _, overall = diff.aggregate_chunk_results(chunk_results)
        difficulty = overall
    elif isinstance(difficulty, dict):
        dims = diff.normalize_dims(difficulty.get("dimensions"))
        difficulty = diff.difficulty_from_dims(dims) if dims else {}

    step_index = {}
    steps = []
    for cr in aj.get("chunk_results", []) or []:
        chunk_id = cr.get("chunk_id", 1)
        for step in cr.get("steps", []) or []:
            step_number = step.get("step_number")
            step_index[(chunk_id, step_number)] = step
            steps.append({
                "chunk_id": chunk_id,
                "step_number": step_number,
                "title": step.get("title", ""),
                "step_level1": step.get("step_level1", ""),
                "standard_writing": step.get("standard_writing", ""),
            })

    student_errors = []
    for err in get_step_errors(qid):
        step = step_index.get((err.get("chunk_id"), err.get("step_number")), {})
        student_errors.append({
            "chunk_id": err.get("chunk_id"),
            "step_number": err.get("step_number"),
            "step_title": step.get("title", ""),
            "mistake_type": err.get("mistake_type", ""),
            "mistake_detail": err.get("mistake_detail", ""),
            "student_input": err.get("student_input", ""),
            "standard_writing": step.get("standard_writing", ""),
        })

    return {
        "id": qid,
        "question": question.get("content", ""),
        "question_type": question_type,
        "category": category or "函数与导数",
        "difficulty": difficulty or {},
        "answer_json": aj,
        "steps": steps,
        "student_errors": student_errors,
    }


def _build_user_prompt(reference: dict, count: int) -> str:
    payload = {
        "reference_question_id": reference["id"],
        "reference_question": reference["question"],
        "question_type": reference["question_type"],
        "category": reference["category"],
        "difficulty": reference["difficulty"],
        "steps": reference["steps"],
        "student_errors": reference["student_errors"],
        "requested_count": count,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _parse_candidates(content: str, count: int) -> list:
    data = json.loads(_extract_json(content))
    candidates = data.get("candidates") or data.get("questions") or []
    candidates = [
        c for c in candidates
        if isinstance(c, dict) and isinstance(c.get("question"), str) and c["question"].strip()
    ]
    if not candidates:
        raise ValueError("AI 没有返回任何有效题目")
    logger.info("拿到 %s 个候选（期望 %s）", len(candidates), count)
    return candidates[:count]


def _call_generation(reference: dict, count: int, teacher: str) -> list:
    config = runtime_settings.get_teacher_config(teacher)

    def request_once(temperature):
        content, _ = call_deepseek(
            GENERATE_PROMPT,
            _build_user_prompt(reference, count),
            temperature=temperature,
            model=config["solver"]["model"],
            reasoning_effort=config["solver"].get("reasoning_effort"),
        )
        return _parse_candidates(content, count)

    candidates = []
    try:
        candidates = request_once(0.6)
    except (json.JSONDecodeError, ValueError):
        candidates = []
    if len(candidates) < count:
        try:
            candidates = request_once(0.4)
        except (json.JSONDecodeError, ValueError):
            candidates = []
    if not candidates:
        raise ValueError("AI 生成结果无法解析")
    return candidates


def _is_duplicate(question_text: str) -> bool:
    try:
        return find_question(question_text) is not None
    except Exception:
        return False


def _solve_candidate(candidate: dict, teacher: str, on_phase=None) -> dict:
    question = candidate.get("question", "").strip()
    def _phase(phase):
        if on_phase:
            try:
                on_phase(phase)
            except Exception:
                pass
    result = {
        "question": question,
        "status": "rejected",
        "rejected_reason": "",
        "design_focus": candidate.get("design_focus", ""),
        "target_difficulty": candidate.get("target_difficulty"),
        "target_steps": candidate.get("target_steps", []),
        "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
    try:
        if _is_duplicate(question):
            result["rejected_reason"] = "题目已存在于题库"
            _phase("solver")
            _phase("verifier")
            _phase("formatter")
            return result

        solver = step_solver_only(question, teacher=teacher)
        _phase("solver")
        if solver.get("error"):
            result["rejected_reason"] = solver.get("status") or solver.get("detail") or "Solver 无法解题"
            return result
        _add_usage(result["token_usage"], solver.get("token_usage"))

        verified = step_verify_all(
            solver["content"],
            question,
            solver.get("category"),
            teacher=teacher,
        )
        _phase("verifier")
        if verified.get("error"):
            result["rejected_reason"] = verified.get("detail") or verified.get("status") or "Verifier 校验失败"
            return result
        _add_usage(result["token_usage"], verified.get("token_usage"))

        final = step_final_check(
            question,
            verified["chunk_results"],
            [],
            result["token_usage"],
            teacher=teacher,
            solver_content=solver["content"],
            verifier_category=solver.get("category"),
        )
        _phase("formatter")
        if final.get("error") or not _is_well_formed_chunk_results(final.get("chunk_results")):
            result["rejected_reason"] = (
                final.get("formatter_note")
                or final.get("reason")
                or final.get("detail")
                or "Formatter 未通过校验"
            )
            return result

        result["status"] = "accepted"
        result["result"] = final
        result["token_usage"] = final.get("token_usage", result["token_usage"])
    except Exception as e:
        result["rejected_reason"] = f"校验异常: {str(e)[:200]}"
    return result


def _fit_score(reference: dict, result: dict) -> tuple:
    final = result.get("result") or {}
    ref_diff = reference.get("difficulty") or {}
    cand_diff = final.get("overall_difficulty") or {}
    ref_total = ref_diff.get("total_score") or 0
    cand_total = cand_diff.get("total_score") or 0
    diff_base = max(ref_total, 1)
    diff_ratio = max(0.0, 1.0 - abs(ref_total - cand_total) / diff_base)

    ref_steps = _collect_step_titles(reference.get("chunk_results"))
    if not ref_steps:
        ref_steps = [_normalize_step_name(s.get("title", "")) for s in reference.get("steps", []) if s.get("title")]
    cand_steps = _collect_step_titles(final.get("chunk_results", []))
    if not ref_steps and not cand_steps:
        step_ratio = 1.0
    elif not ref_steps or not cand_steps:
        step_ratio = 0.5
    else:
        from difflib import SequenceMatcher
        step_ratio = SequenceMatcher(None, ref_steps, cand_steps).ratio()

    ref_kps = set(_collect_knowledge_points(reference.get("answer_json") or {}))
    cand_kps = set(_collect_knowledge_points(final))
    if not ref_kps and not cand_kps:
        kp_ratio = 1.0
    else:
        kp_ratio = len(ref_kps & cand_kps) / max(len(ref_kps | cand_kps), 1)

    ref_type = (reference.get("question_type") or "").strip()
    cand_type = ((final.get("chunk_results") or [{}])[0].get("chunk_type") or "").strip()
    same_type = (ref_type == cand_type) or (ref_type in ("大题", "子问") and cand_type in ("大题", "子问"))
    type_ratio = 1.0 if same_type else 0.0

    score = round(45 * diff_ratio + 30 * step_ratio + 15 * kp_ratio + 10 * type_ratio, 1)
    detail = {
        "difficulty_ratio": round(diff_ratio, 2),
        "step_ratio": round(step_ratio, 2),
        "knowledge_ratio": round(kp_ratio, 2),
        "type_ratio": round(type_ratio, 2),
    }
    return score, detail


def _save_accepted(reference: dict, result: dict) -> int:
    final = dict(result.get("result") or {})
    chunk_results = final.get("chunk_results", [])
    first = chunk_results[0] if chunk_results else {}
    final["category"] = final.get("category") or first.get("category")
    final["difficulty"] = final.get("overall_difficulty") or first.get("difficulty")
    final["question_type"] = final.get("question_type") or first.get("chunk_type")
    final["source_type"] = "ai生成"
    final["source_meta"] = {"reference_id": str(reference["id"])}
    if final.get("question_type") == "多选题" or looks_like_multi_choice_question(result["question"], final):
        final["question_type"] = "多选题"
        from backend.database import _ensure_multi_choice_marker
        result["question"] = _ensure_multi_choice_marker(result["question"])
    return save_question(result["question"], final)


def generate_variants(qid: int, count: Optional[int] = None, teacher: str = "liangliang",
                      progress_callback=None) -> dict:
    if count is None:
        count = int(runtime_settings.get_limits().get("generate_count", 3))
    count = max(1, min(10, int(count)))
    reference = _load_reference(qid)
    reference["chunk_results"] = (reference.get("answer_json") or {}).get("chunk_results", [])
    candidates = _call_generation(reference, count, teacher)
    unique_candidates = []
    seen = set()
    for cand in candidates:
        key = re.sub(r"\s+", "", cand.get("question", "") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        unique_candidates.append(cand)
    candidates = unique_candidates
    if progress_callback:
        try:
            progress_callback("generating")
        except Exception:
            pass

    total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    solved = []
    workers = int(runtime_settings.get_limits().get("generate_concurrency", 5))
    with ThreadPoolExecutor(max_workers=max(1, min(len(candidates), workers))) as pool:
        futures = [pool.submit(_solve_candidate, cand, teacher, on_phase=progress_callback) for cand in candidates]
        solved = [f.result() for f in futures]

    accepted = []
    rejected = []
    for cand in solved:
        _add_usage(total_usage, cand.get("token_usage"))
        if cand.get("status") == "accepted":
            try:
                cand["question_id"] = _save_accepted(reference, cand)
            except Exception as e:
                cand["status"] = "rejected"
                cand["rejected_reason"] = f"入库失败: {str(e)[:200]}"
        if cand.get("status") == "accepted":
            score, detail = _fit_score(reference, cand)
            cand["fit_score"] = score
            cand["fit_detail"] = detail
            cand["difficulty"] = (cand.get("result") or {}).get("overall_difficulty")
            cand.pop("result", None)
            accepted.append(cand)
        else:
            rejected.append(cand)

    logger.info("参考题 #%s: 候选 %s 道，通过 %s 道，淘汰 %s 道", qid, len(solved), len(accepted), len(rejected))
    for cand in rejected:
        logger.info("淘汰原因: %s", cand.get("rejected_reason"))

    accepted.sort(key=lambda c: c.get("fit_score", 0), reverse=True)
    return {
        "reference_question_id": qid,
        "teacher": teacher,
        "accepted": len(accepted),
        "rejected": len(rejected),
        "candidates": accepted + rejected,
        "token_usage": total_usage,
    }


_GENERATE_JOB_LOCK = threading.Lock()
_GENERATE_JOBS = {}


def _job_snapshot(job: dict) -> dict:
    snap = dict(job)
    if isinstance(snap.get("result"), dict):
        snap["result"] = dict(snap["result"])
    return snap


def _progress_text(phase: str, done: int, total: int) -> str:
    if phase == "generating":
        return f"{total} 道题已全部生成，开始校验"
    if phase == "solver":
        return f"第 {done}/{total} 道题 Solver 完成"
    if phase == "verifier":
        return f"第 {done}/{total} 道题 Verifier 完成"
    if phase == "formatter":
        return f"第 {done}/{total} 道题 Formatter 完成"
    return ""


def start_generate_job(qid: int, count: Optional[int] = None, teacher: str = "liangliang") -> dict:
    if not get_question_by_id(qid):
        raise ValueError(f"题目不存在: {qid}")
    if count is None:
        count = int(runtime_settings.get_limits().get("generate_count", 3))
    count = max(1, min(10, int(count)))
    job_id = uuid.uuid4().hex
    job = {
        "job_id": job_id,
        "status": "running",
        "stage": "generating",
        "progress": 0,
        "detail": "AI 正在生成题目",
        "solver_done": 0,
        "verifier_done": 0,
        "formatter_done": 0,
        "result": None,
        "error": None,
    }
    with _GENERATE_JOB_LOCK:
        _GENERATE_JOBS[job_id] = job

    def run_job():
        def on_phase(phase: str) -> None:
            with _GENERATE_JOB_LOCK:
                if phase == "generating":
                    job["stage"] = "generating"
                    job["progress"] = 13
                    job["detail"] = _progress_text("generating", 0, count)
                elif phase == "solver":
                    job["solver_done"] = job.get("solver_done", 0) + 1
                    done = job["solver_done"]
                    job["stage"] = "solver"
                    job["progress"] = round(13 + 65 * done / count)
                    job["detail"] = _progress_text("solver", done, count)
                elif phase == "verifier":
                    job["verifier_done"] = job.get("verifier_done", 0) + 1
                    done = job["verifier_done"]
                    job["stage"] = "verifier"
                    job["progress"] = round(78 + 13 * done / count)
                    job["detail"] = _progress_text("verifier", done, count)
                elif phase == "formatter":
                    job["formatter_done"] = job.get("formatter_done", 0) + 1
                    done = job["formatter_done"]
                    job["stage"] = "formatter"
                    job["progress"] = min(99, round(91 + 9 * done / count))
                    job["detail"] = _progress_text("formatter", done, count)

        try:
            result = generate_variants(qid, count=count, teacher=teacher,
                                       progress_callback=on_phase)
            with _GENERATE_JOB_LOCK:
                job["status"] = "done"
                job["stage"] = "done"
                job["progress"] = 100
                job["detail"] = "生成完成"
                job["result"] = result
        except Exception as e:
            with _GENERATE_JOB_LOCK:
                job["status"] = "error"
                job["detail"] = f"生成失败: {str(e)[:300]}"
                job["error"] = str(e)[:500]

    threading.Thread(target=run_job, daemon=True).start()
    return _job_snapshot(job)


def get_generate_job(job_id: str) -> dict:
    with _GENERATE_JOB_LOCK:
        job = _GENERATE_JOBS.get(job_id)
        if not job:
            return None
        return _job_snapshot(job)
