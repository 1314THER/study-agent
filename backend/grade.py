"""AI 改题：文字作答判分。

选择题/多选题/填空题直接比对参考答案；大题交给 AI 按标准步骤判分。
每次判分尽量写入 practice_records，留下作答来源与防欺骗信号。
"""

import json
import math
import os
import re
from fractions import Fraction

import backend.settings as runtime_settings
from backend.solver import call_deepseek, _extract_json
from backend.database import (
    MISTAKE_TYPES,
    add_practice_record,
    find_question,
    find_question_id,
    get_question_by_id,
)


PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")
with open(os.path.join(PROMPTS_DIR, "grade.md"), encoding="utf-8") as _f:
    GRADE_PROMPT = _f.read().strip()

_VALID_TYPES = {"选择题", "多选题", "填空题", "大题"}
_TYPE_ALIASES = {
    "单选题": "选择题",
    "多选": "多选题",
    "填空": "填空题",
    "解答题": "大题",
    "计算题": "大题",
    "证明题": "大题",
}


def _resolve_question_type(answer_json: dict, requested=None) -> str:
    if requested in _TYPE_ALIASES:
        return _TYPE_ALIASES[requested]
    if requested in _VALID_TYPES:
        return requested
    aj = answer_json or {}
    aj_type = _TYPE_ALIASES.get(aj.get("question_type"), aj.get("question_type"))
    if aj_type in _VALID_TYPES:
        return aj_type
    chunk_results = aj.get("chunk_results") or []
    if chunk_results and isinstance(chunk_results[0], dict):
        chunk_type = _TYPE_ALIASES.get(
            chunk_results[0].get("chunk_type"), chunk_results[0].get("chunk_type")
        )
        if chunk_type in _VALID_TYPES:
            return chunk_type
    return "大题"


def _final_answer(answer_json: dict) -> str:
    aj = answer_json or {}
    top = aj.get("final_answer")
    if top and str(top).strip():
        return str(top).strip()
    parts = []
    for cr in aj.get("chunk_results") or []:
        fa = cr.get("final_answer")
        if fa and str(fa).strip():
            parts.append(str(fa).strip())
    return " | ".join(parts)


def _collect_steps(answer_json: dict) -> list:
    steps = []
    used_ids = set()
    for cr in answer_json.get("chunk_results") or []:
        chunk_id = cr.get("chunk_id", 1)
        for s in cr.get("steps") or []:
            base = s.get("step_number") or (len(steps) + 1)
            sid = f"{chunk_id}-{base}"
            n = 2
            while sid in used_ids:
                sid = f"{chunk_id}-{base}-{n}"
                n += 1
            used_ids.add(sid)
            steps.append({
                "id": sid,
                "chunk_id": chunk_id,
                "step_number": base,
                "title": s.get("title") or s.get("step_level1") or "步骤",
                "standard_writing": s.get("standard_writing")
                or s.get("detailed_writing")
                or "",
                "knowledge_point": s.get("knowledge_point") or "",
                "depends_on": s.get("depends_on") or [],
            })
        fa = cr.get("final_answer")
        if fa and str(fa).strip():
            steps.append({
                "id": f"{chunk_id}-999",
                "chunk_id": chunk_id,
                "step_number": 999,
                "title": "最终答案",
                "standard_writing": str(fa).strip(),
            })
    return steps


def _normalize_fill(text) -> str:
    text = str(text or "").strip().lower()
    text = re.sub(r"^(?:最终答案|正确答案|答案|答)\s*[:：]\s*", "", text)
    for src, dst in [
        ("，", ","),
        ("；", ";"),
        ("：", ":"),
        ("（", "("),
        ("）", ")"),
    ]:
        text = text.replace(src, dst)
    text = text.replace("$", "")
    text = text.replace("\\ ", "")
    text = text.replace("\\;", "")
    text = text.replace("\\,", "")
    text = text.replace("\\mid", "|")
    text = text.replace("\\{", "{")
    text = text.replace("\\}", "}")
    text = re.sub(r"\\[d]?frac\s*\{(.+?)\}\s*\{(.+?)\}", r"\1/\2", text)
    return re.sub(r"\s+", "", text)


def _to_number(text) -> Fraction:
    t = _normalize_fill(text)
    try:
        return Fraction(t)
    except (ValueError, ZeroDivisionError):
        pass
    try:
        return Fraction(float(t))
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


def _fill_equivalent(expected, student) -> bool:
    return _fill_relation(expected, student) is True


def _fill_relation(expected, student):
    e = _normalize_fill(expected)
    s = _normalize_fill(student)
    if e == s:
        return True
    en = _to_number(e)
    sn = _to_number(s)
    if en is not None and sn is not None:
        return en == sn
    structured = re.compile(r"(?:\\in|\\notin|[\[\]{}|∪∩∞≤≥<>])")
    if structured.search(e) or structured.search(s):
        return None
    return False


def _choice_set(value):
    text = str(value or "").strip().upper()
    text = re.sub(r"^(?:最终答案|正确答案|答案|答)\s*[:：]\s*", "", text)
    text = re.sub(r"[（）()]", "", text)
    if not re.fullmatch(r"[A-H](?:\s*[,，、/\s]*\s*[A-H])*", text):
        return None
    return sorted(set(re.findall(r"[A-H]", text)))


def _compare_choice(expected, student) -> bool:
    exp = _choice_set(expected)
    stu = _choice_set(student)
    if exp is not None and stu is not None:
        return exp == stu
    return _normalize_fill(expected) == _normalize_fill(student)


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in ("true", "1", "yes", "对", "正确")


def _sanitize_ai_grade(data: dict, steps: list, full_score, scoring_rubric=None) -> dict:
    valid_ids = {s["id"] for s in steps}
    valid_statuses = {"correct", "partial", "missing", "not_applicable"}
    by_id = {
        str(s.get("id")): s
        for s in data.get("steps") or []
        if isinstance(s, dict)
    }
    rubric = {str(row["step_id"]): max(0.0, float(row["max_points"]))
              for row in scoring_rubric or []}
    rubric_missing = False

    step_results = []
    for std in steps:
        match = by_id.get(std["id"], {})
        status = match.get("status")
        if status not in valid_statuses:
            status = "missing"
        error_types = [
            t for t in (match.get("error_types") or []) if t in MISTAKE_TYPES
        ][:3]
        # A missing step is an observation, not proof of a particular cause.
        # Keep unknown causes empty so aggregate diagnostics cannot mistake it
        # for a knowledge or reasoning error.
        error_detail = str(match.get("error_detail") or "")
        answer_evidence = str(match.get("answer_evidence") or "")
        score = None
        max_points = rubric.get(std["id"])
        if max_points is not None:
            try:
                candidate_score = match.get("earned_points")
                score = max(0.0, min(max_points, float(candidate_score))) if candidate_score is not None else None
            except (TypeError, ValueError):
                score = None
            rubric_missing = rubric_missing or score is None
        step_results.append({
            "id": std["id"],
            "chunk_id": std["chunk_id"],
            "step_number": std["step_number"],
            "title": std["title"],
            "standard_writing": std.get("standard_writing") or "",
            "status": status,
            "comment": str(match.get("comment") or ""),
            "error_types": error_types,
            "error_detail": error_detail,
            "answer_evidence": answer_evidence,
            "cause_confidence": match.get("cause_confidence")
            if match.get("cause_confidence") in ("low", "medium", "high") else "unknown",
            "review_required": bool(match.get("review_required")) or
            (status == "missing" and not error_types),
            "earned_points": score,
            "max_points": max_points,
        })

    def _ids(key: str) -> list:
        out = []
        for v in data.get(key) or []:
            v = str(v)
            if v in valid_ids and v not in out:
                out.append(v)
        return out

    approach = data.get("approach")
    if approach not in ("same", "different"):
        approach = "same"
    overall = data.get("overall") or {}
    is_correct = _as_bool(overall.get("is_correct"))
    if approach == "same" and any(step["status"] == "missing" for step in step_results):
        is_correct = False
    earned_score = None
    if rubric and not rubric_missing:
        earned_score = round(sum(float(step["earned_points"] or 0) for step in step_results), 2)
    elif full_score is not None and not rubric:
        try:
            value = overall.get("earned_score")
            earned_score = float(value) if value is not None else None
        except (TypeError, ValueError):
            earned_score = None
        if earned_score is not None:
            earned_score = max(0.0, min(float(full_score), earned_score))
    feedback = str(overall.get("feedback") or "")
    suggested = str(data.get("suggested_approach") or "").strip()
    if approach == "different" and suggested:
        feedback = (feedback + "\n\n" if feedback else "") + f"你可以参考我的新思路：{suggested}"

    error_suggestions = []
    for sr in step_results:
        if sr["status"] not in ("partial", "missing"):
            continue
        for et in sr["error_types"]:
            error_suggestions.append({
                "chunk_id": sr["chunk_id"],
                "step_number": sr["step_number"],
                "step_id": sr["id"],
                "title": sr["title"],
                "mistake_type": et,
                "mistake_detail": sr["error_detail"],
                "answer_evidence": sr["answer_evidence"],
                "cause_confidence": sr["cause_confidence"],
            })

    return {
        "approach": approach,
        "result_matched": _as_bool(data.get("result_matched")),
        "steps": step_results,
        "missing_steps": _ids("missing_steps"),
        "not_rigorous_steps": _ids("not_rigorous_steps"),
        "error_suggestions": error_suggestions,
        "is_correct": is_correct,
        "earned_score": earned_score,
        "feedback": feedback,
        "suggested_approach": suggested,
        "grading_confidence": data.get("grading_confidence")
        if data.get("grading_confidence") in ("low", "medium", "high") else "unknown",
        "rubric_incomplete": rubric_missing,
    }


def _ai_grade_essay(question: str, student_answer: str, steps: list,
                    final_answer: str, full_score, teacher=None,
                    scoring_rubric=None) -> dict:
    payload = {
        "question": question,
        "student_answer": student_answer,
        "standard_steps": steps,
        "standard_final_answer": final_answer,
        "full_score": full_score,
        "scoring_rubric": scoring_rubric or [],
    }
    cfg = runtime_settings.get_teacher_config(teacher)
    grade_cfg = cfg.get("grade") or {}
    grade_model = grade_cfg.get("model") or cfg.get("verifier", {}).get("model", "deepseek-flash")
    grade_effort = grade_cfg.get("reasoning_effort") or cfg.get("verifier", {}).get("reasoning_effort")
    content, _ = call_deepseek(
        GRADE_PROMPT,
        json.dumps(payload, ensure_ascii=False, indent=2),
        temperature=0.2,
        model=grade_model,
        reasoning_effort=grade_effort,
    )
    data = json.loads(_extract_json(content))
    return _sanitize_ai_grade(data, steps, full_score, scoring_rubric)


def grade_prepared(question: str, answer_json: dict, student_answer: str, *,
                   question_type=None, full_score=None, teacher=None,
                   scoring_rubric=None, objective_rule=None, input_type="text") -> dict:
    """Grade supplied assessment material without looking up or writing to the bank.

    Exam attempts call this same pure grading path as the legacy single-question
    route, then persist their own provenance and edits in their attempt record.
    """
    if input_type not in ("text", "ocr"):
        return {"error": "unsupported_input_type", "detail": "作答输入类型不支持。"}
    student_answer = str(student_answer or "").strip()
    if not student_answer:
        return {"error": "empty_answer", "detail": "学生作答为空，请确认是否确实未作答。"}
    answer_json = answer_json if isinstance(answer_json, dict) else {}
    question = str(question or "").strip()
    resolved_type = _resolve_question_type(answer_json, question_type)
    reference = _final_answer(answer_json)
    if not reference:
        return {"error": "no_answer", "detail": "此题没有可用的参考答案。"}
    standard_steps = _collect_steps(answer_json)
    if resolved_type in ("选择题", "多选题", "填空题"):
        if resolved_type == "填空题":
            relation = _fill_relation(reference, student_answer)
            correct = relation if relation is not None else None
        else:
            expected_options, student_options = _choice_set(reference), _choice_set(student_answer)
            if expected_options is None or student_options is None:
                correct = _compare_choice(reference, student_answer)
                expected_options = student_options = None
            else:
                correct = expected_options == student_options
        earned_score, score_basis = None, "unscored"
        if full_score is not None and correct is not None:
            if resolved_type == "多选题" and objective_rule and objective_rule.get("mode") == "per_option":
                if not expected_options or student_options is None:
                    correct = None
                else:
                    try:
                        penalty = float(objective_rule.get("wrong_option_penalty", 0))
                    except (TypeError, ValueError):
                        return {"error": "invalid_objective_rule", "detail": "多选题扣分规则无效。"}
                    if not math.isfinite(penalty) or penalty < 0 or penalty > float(full_score):
                        return {"error": "invalid_objective_rule", "detail": "多选题扣分规则无效。"}
                    point_per_correct = float(full_score) / len(expected_options)
                    earned_score = max(0.0, min(float(full_score),
                        len(set(expected_options) & set(student_options)) * point_per_correct -
                        len(set(student_options) - set(expected_options)) * penalty))
                    score_basis = "confirmed_multi_select_rule"
            if earned_score is None and correct is not None:
                earned_score = float(full_score) if correct else 0.0
                score_basis = "exact_answer"
        return {
            "mode": "answer_match", "question_id": None,
            "question_type": resolved_type, "input_type": input_type,
            "is_correct": correct, "result_matched": correct,
            "expected_answer": reference, "student_answer": student_answer,
            "earned_score": earned_score, "full_score": full_score,
            "score_basis": score_basis,
            "step_results": [], "missing_steps": [], "not_rigorous_steps": [],
            "error_suggestions": [], "standard_steps": standard_steps,
            "feedback": "等价关系无法自动确认，请人工复核。" if correct is None else
            "回答正确。" if correct else "答案未匹配，请核对题目和评分标准。",
            "suggested_approach": "", "review_required": correct is None,
        }
    if not standard_steps:
        return {"error": "no_steps", "detail": "题目没有可用的参考解答，无法自动批改。"}
    if scoring_rubric:
        valid_ids = {step["id"] for step in standard_steps}
        rubric_ids = [row.get("step_id") for row in scoring_rubric if isinstance(row, dict)]
        try:
            total = sum(float(row["max_points"]) for row in scoring_rubric)
        except (KeyError, TypeError, ValueError):
            return {"error": "invalid_rubric", "detail": "评分点格式无效，请核对评分标准。"}
        if (not scoring_rubric or len(rubric_ids) != len(scoring_rubric) or
                len(set(rubric_ids)) != len(rubric_ids) or not set(rubric_ids) <= valid_ids or
                any(not math.isfinite(float(row["max_points"])) or float(row["max_points"]) < 0
                    for row in scoring_rubric) or full_score is None or
                abs(total - float(full_score)) > 0.01):
            return {"error": "invalid_rubric", "detail": "评分点分值须有效且总和等于题目满分。"}
    try:
        ai = _ai_grade_essay(question, student_answer, standard_steps, reference,
                             full_score, teacher, scoring_rubric)
    except Exception as exc:
        return {"error": "ai_failed", "detail": str(exc)[:200]}
    needs_review = any(step["review_required"] for step in ai["steps"]) or ai["rubric_incomplete"]
    needs_review = needs_review or ai["grading_confidence"] != "high"
    return {
        "mode": "step_ai", "question_id": None, "question_type": resolved_type,
        "input_type": input_type, "is_correct": ai["is_correct"],
        "result_matched": ai["result_matched"], "expected_answer": reference,
        "student_answer": student_answer, "earned_score": ai["earned_score"],
        "full_score": full_score, "step_results": ai["steps"],
        "missing_steps": ai["missing_steps"],
        "not_rigorous_steps": ai["not_rigorous_steps"],
        "error_suggestions": ai["error_suggestions"],
        "standard_steps": standard_steps,
        "feedback": ai["feedback"] or "批改完成。",
        "suggested_approach": ai["suggested_approach"],
        "review_required": needs_review,
        "grading_confidence": ai["grading_confidence"],
        "scoring_rubric": scoring_rubric or [],
        "score_basis": "confirmed_rubric" if scoring_rubric and not ai["rubric_incomplete"] else
        "provisional_ai" if full_score is not None and ai["earned_score"] is not None else "unscored",
    }


def grade_text(question_id=None, question=None, student_answer="",
               question_type=None, full_score=None, teacher=None,
               source=None, duration_seconds=None,
               viewed_answer=False, skipped=False,
               input_type="text", scoring_rubric=None, objective_rule=None) -> dict:
    if input_type != "text":
        return {
            "error": "unsupported_input_type",
            "detail": "当前仅支持 input_type=text，手写识别后续接入",
        }
    student_answer = str(student_answer or "").strip()
    if not student_answer:
        return {"error": "empty_answer", "detail": "学生作答不能为空"}

    qid = question_id
    answer_json = None
    question_text = str(question or "").strip()

    if qid is not None:
        row = get_question_by_id(qid)
        if not row:
            return {"error": "not_found", "detail": f"题目不存在: {qid}"}
        question_text = row.get("content") or question_text
        answer_json = row.get("answer_json") or {}
        if isinstance(answer_json, str):
            try:
                answer_json = json.loads(answer_json)
            except (json.JSONDecodeError, TypeError):
                answer_json = {}
    elif question_text:
        found = find_question(question_text)
        if found:
            answer_json = found
            qid = find_question_id(question_text)
        else:
            from backend.teach import teach_start
            start = teach_start(question_text, teacher=teacher)
            if start.get("error"):
                return {
                    "error": "solve_failed",
                    "detail": start.get("detail") or start.get("error"),
                }
            answer_json = {
                "chunk_results": start.get("chunk_results") or [],
                "question_type": _resolve_question_type(
                    {"chunk_results": start.get("chunk_results") or []}, None
                ),
            }
            qid = find_question_id(question_text)
    else:
        return {"error": "missing_question", "detail": "需要提供 question_id 或 question"}

    anti_cheat = {
        "viewed_answer": bool(viewed_answer),
        "skipped": bool(skipped),
        "duration_seconds": duration_seconds,
    }
    result = grade_prepared(
        question_text, answer_json, student_answer,
        question_type=question_type, full_score=full_score, teacher=teacher,
        scoring_rubric=scoring_rubric, objective_rule=objective_rule, input_type=input_type,
    )
    if result.get("error"):
        return result
    result["question_id"] = qid
    result["anti_cheat"] = anti_cheat

    if qid is not None:
        try:
            record_id = add_practice_record(
                question_id=qid,
                correct=bool(result["is_correct"]),
                duration_seconds=duration_seconds,
                source_type=source,
                student_answer=student_answer,
                grade_json=result,
                viewed_answer=bool(viewed_answer),
                skipped=bool(skipped),
            )
            result["practice_record_id"] = record_id
        except Exception:
            result["practice_record_id"] = None
    else:
        result["practice_record_id"] = None
    return result
