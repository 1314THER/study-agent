"""全局 agent 的服务端工具层：把领域能力封装成可执行工具。

工具统一返回紧凑结构：既能塞进 LLM 上下文，也能作为前端展示块。
"""

import json

from backend.categories import CATEGORIES
from backend.database import get_connection, save_question, search_questions
from backend.grade import grade_text
from backend.patterns import get_pattern_calendar, get_patterns
from backend.planner import apply_plan, build_plan
from backend.solver import step_final_check, step_solver_only, step_verify_all
from backend.teach import teach_session_start


def agent_context():
    """首页与教练共享的学情快照。"""
    conn = get_connection()
    try:
        total = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
        wrong = conn.execute("SELECT COUNT(DISTINCT question_id) FROM step_errors").fetchone()[0]
        practice = conn.execute("SELECT COUNT(*) FROM practice_records").fetchone()[0]
    finally:
        conn.close()
    patterns = get_patterns()
    mastered = sum(1 for p in patterns if (p.get("mastery") or {}).get("state") == "third_pass")
    calendar = get_pattern_calendar()
    recent_wrong = search_questions(error_type="errors", limit=5)
    if isinstance(recent_wrong, dict):
        recent_wrong = recent_wrong.get("data", [])
    return {
        "total_questions": total,
        "wrong_questions": wrong,
        "practice_records": practice,
        "patterns_total": len(patterns),
        "patterns_mastered": mastered,
        "due_reviews": len(calendar.get("today_items", [])),
        "recent_wrong": recent_wrong,
        "categories": list(CATEGORIES.keys()),
    }


def _compact_question(q, max_len=140):
    content = (q.get("content") or "").strip()
    return {
        "id": q.get("id"),
        "question_type": q.get("question_type") or "",
        "category": q.get("category_level1") or "",
        "difficulty": q.get("difficulty_level") or "",
        "source_type": q.get("source_type") or "",
        "knowledge_points": q.get("knowledge_points") or [],
        "content": content[:max_len] + ("…" if len(content) > max_len else ""),
    }


def _split_list(value):
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return []


_CATEGORY_ALIASES = {
    "函数": "函数与导数",
    "导数": "函数与导数",
    "三角": "三角函数",
    "概率": "概率统计",
    "统计": "概率统计",
    "向量": "平面向量",
    "不等式": "不等式",
    "数列": "数列",
    "立体几何": "立体几何",
    "解析几何": "解析几何",
    "集合": "集合与逻辑用语",
    "复数": "复数",
}
_TYPE_ALIASES = {
    "选择": "选择题",
    "多选": "多选题",
    "填空": "填空题",
    "解答": "大题",
    "解答题": "大题",
}


def _normalize_categories(values):
    out = []
    for v in values:
        v = _CATEGORY_ALIASES.get(v, v)
        if v and v not in out:
            out.append(v)
    return out


def _normalize_types(values):
    out = []
    for v in values:
        v = _TYPE_ALIASES.get(v, v)
        if v and v not in out:
            out.append(v)
    return out


def tool_search_questions(args):
    args = args or {}
    filters = args.get("filters") or {}
    if not isinstance(filters, dict):
        filters = {}
    limit = min(max(int(args.get("limit") or 5), 1), 30)
    query = str(args.get("query") or filters.get("query") or "").strip()
    categories = _normalize_categories(_split_list(args.get("category") or filters.get("category")))
    types = _normalize_types(_split_list(args.get("question_type") or filters.get("question_type")))
    difficulties = _split_list(args.get("difficulty") or filters.get("difficulty"))
    error_type = str(args.get("error_type") or filters.get("error_type") or "").strip()
    source_type = str(args.get("source_type") or filters.get("source_type") or "").strip()
    rows = search_questions(
        keywords=[query] if query else None,
        categories=categories or None,
        difficulties=difficulties or None,
        types=types or None,
        limit=limit,
        mode="global",
        error_type=error_type or None,
        source_type=source_type or None,
    )
    items = [_compact_question(q) for q in (rows or [])][:limit]
    return {"count": len(items), "limit": limit, "items": items}


def _solve_pipeline(question, question_type=None, teacher=None):
    sr = step_solver_only(question, question_type=question_type, teacher=teacher)
    if sr.get("error"):
        return {"error": sr.get("error"), "detail": sr.get("detail", "")}
    vr = step_verify_all(
        sr["content"], question, sr.get("category"),
        question_type=question_type, teacher=teacher,
    )
    if vr.get("error"):
        return {"error": vr.get("error"), "detail": vr.get("detail", "")}
    return step_final_check(
        question, vr["chunk_results"], [], {},
        teacher=teacher, solver_content=sr["content"], verifier_category=sr.get("category"),
        question_type=question_type,
    )


def _save_solved(question, final):
    aj = dict(final)
    aj.pop("error", None)
    aj.pop("formatter_note", None)
    aj.setdefault("knowledge_points", [])
    aj.setdefault("final_answer", "")
    chunk_results = aj.get("chunk_results", []) or []
    if not aj.get("category") and chunk_results:
        first_cat = chunk_results[0].get("category")
        if isinstance(first_cat, dict):
            aj["category"] = {
                "level1": first_cat.get("level1"),
                "level2": first_cat.get("level2"),
            }
        elif first_cat:
            aj["category"] = {"level1": first_cat, "level2": ""}
    for c in chunk_results:
        if c.get("final_answer"):
            aj["final_answer"] += (" | " if aj["final_answer"] else "") + c["final_answer"]
        for kp in c.get("knowledge_points", []) or []:
            if kp not in aj["knowledge_points"]:
                aj["knowledge_points"].append(kp)
    try:
        return save_question(question, aj)
    except Exception:
        return None


def _category_name(value):
    if isinstance(value, dict):
        return value.get("level1") or value.get("level2") or ""
    return value or ""


def _compact_solve(question, final, qid):
    chunks = []
    for cr in final.get("chunk_results", []) or []:
        steps = []
        for s in cr.get("steps", []) or []:
            diff = s.get("step_difficulty") or {}
            steps.append({
                "step_number": s.get("step_number"),
                "title": s.get("title") or "",
                "knowledge_point": s.get("knowledge_point") or "",
                "difficulty_level": diff.get("level") if isinstance(diff, dict) else None,
            })
        chunks.append({
            "chunk_id": cr.get("chunk_id"),
            "chunk_type": cr.get("chunk_type") or "",
            "category": _category_name(cr.get("category")),
            "final_answer": cr.get("final_answer") or "",
            "knowledge_points": cr.get("knowledge_points") or [],
            "steps": steps,
        })
    overall = final.get("overall_difficulty") or {}
    return {
        "question": question,
        "saved_id": qid,
        "final_answer": final.get("final_answer") or "",
        "knowledge_points": final.get("knowledge_points") or [],
        "category": chunks[0].get("category") if chunks else "",
        "difficulty_level": overall.get("level") if isinstance(overall, dict) else None,
        "chunks": chunks,
        "formatter_fallback": bool(final.get("formatter_fallback")),
        "formatter_note": final.get("formatter_note") or "",
    }


def tool_solve_question(args):
    args = args or {}
    question = str(args.get("question") or "").strip()
    if not question:
        return {"error": "missing_question", "detail": "缺少题目内容"}
    final = _solve_pipeline(
        question,
        question_type=args.get("question_type"),
        teacher=args.get("teacher"),
    )
    if final.get("error") and not final.get("chunk_results"):
        return {"error": final["error"], "detail": final.get("detail", "")}
    save = bool(args.get("save", True))
    qid = _save_solved(question, final) if save else None
    return _compact_solve(question, final, qid)


def tool_teach_question(args):
    args = args or {}
    question = str(args.get("question") or "").strip()
    if not question:
        return {"error": "missing_question", "detail": "缺少题目内容"}
    result = teach_session_start(question, teacher=args.get("teacher"))
    if result.get("error"):
        return {"error": result.get("error"), "detail": result.get("detail", "")}
    steps = result.get("steps") or []
    chunks = []
    for cr in result.get("chunk_results") or []:
        chunks.append({
            "chunk_type": cr.get("chunk_type") or "",
            "category": _category_name(cr.get("category")),
            "knowledge_points": cr.get("knowledge_points") or [],
            "steps_count": len(cr.get("steps") or []),
        })
    return {
        "session_id": result.get("session_id"),
        "question": question,
        "teacher": result.get("teacher") or args.get("teacher") or "liangliang",
        "message": (result.get("message") or "")[:400],
        "total_steps": result.get("total_steps") or len(steps),
        "step_titles": [
            (s.get("title") or f"步骤 {i + 1}") for i, s in enumerate(steps)
        ],
        "chunks": chunks,
        "question_id": result.get("question_id"),
    }


def tool_grade_answer(args):
    args = args or {}
    student_answer = str(args.get("student_answer") or "").strip()
    if not student_answer:
        return {"error": "empty_answer", "detail": "学生作答不能为空"}
    result = grade_text(
        question_id=args.get("question_id"),
        question=args.get("question"),
        student_answer=student_answer,
        question_type=args.get("question_type"),
        full_score=args.get("full_score"),
        teacher=args.get("teacher"),
    )
    if result.get("error"):
        return {"error": result["error"], "detail": result.get("detail", "")}
    return {
        "mode": result.get("mode"),
        "question_id": result.get("question_id"),
        "question_type": result.get("question_type"),
        "is_correct": result.get("is_correct"),
        "result_matched": result.get("result_matched"),
        "earned_score": result.get("earned_score"),
        "full_score": result.get("full_score"),
        "expected_answer": str(result.get("expected_answer") or "")[:300],
        "student_answer": student_answer[:300],
        "feedback": str(result.get("feedback") or "")[:400],
        "suggested_approach": str(result.get("suggested_approach") or "")[:300],
        "step_results": [
            {
                "step_number": s.get("step_number"),
                "title": s.get("title"),
                "is_correct": s.get("is_correct"),
                "is_partial": s.get("is_partial"),
                "feedback": str(s.get("feedback") or "")[:200],
                "error_type": s.get("error_type"),
            }
            for s in (result.get("step_results") or [])
        ][:8],
        "missing_steps": result.get("missing_steps") or [],
        "not_rigorous_steps": result.get("not_rigorous_steps") or [],
    }


def tool_plan_study(args):
    args = args or {}
    categories = _normalize_categories(_split_list(args.get("categories")))
    plan = build_plan(
        template=args.get("template"),
        per_day=args.get("per_day"),
        start_date=args.get("start_date"),
        categories=categories or None,
    )
    applied = None
    if args.get("apply"):
        applied = apply_plan(plan)
    preview = [
        {
            "date": d.get("date"),
            "patterns": [p.get("name") for p in d.get("patterns", [])],
        }
        for d in (plan.get("plan") or [])[:7]
    ]
    return {
        "total_patterns": plan.get("total_patterns", 0),
        "days": plan.get("days", 0),
        "per_day": plan.get("per_day", 1),
        "start_date": plan.get("start_date", ""),
        "preview": preview,
        "applied_count": applied,
    }


def tool_get_context(_args=None):
    ctx = agent_context()
    return {
        "total_questions": ctx["total_questions"],
        "wrong_questions": ctx["wrong_questions"],
        "practice_records": ctx["practice_records"],
        "patterns_total": ctx["patterns_total"],
        "patterns_mastered": ctx["patterns_mastered"],
        "due_reviews": ctx["due_reviews"],
        "recent_wrong": [_compact_question(q) for q in (ctx.get("recent_wrong") or [])][:5],
        "categories": ctx["categories"],
    }


TOOLS = {
    "search_questions": {
        "description": "从个人题库搜索题目",
        "args_schema": '{"query":"关键词","category":"板块","question_type":"题型","difficulty":"难度","error_type":"错因","source_type":"来源","limit":5}',
        "fn": tool_search_questions,
    },
    "solve_question": {
        "description": "完整解答一道数学题并返回最终答案与步骤摘要",
        "args_schema": '{"question":"题目原文","question_type":"题型(可选)","teacher":"老师(可选)","save":true}',
        "fn": tool_solve_question,
    },
    "teach_question": {
        "description": "为一道题创建手把手教学会话并返回第一步引导",
        "args_schema": '{"question":"题目原文","teacher":"老师(可选)"}',
        "fn": tool_teach_question,
    },
    "grade_answer": {
        "description": "批改学生作答，需要 question_id 或 question 定位题目",
        "args_schema": '{"question_id":1,"question":"题目原文(可选)","student_answer":"学生作答","question_type":"题型(可选)","full_score":10,"teacher":"老师(可选)"}',
        "fn": tool_grade_answer,
    },
    "plan_study": {
        "description": "生成复习规划，明确要求写入日历时 apply=true",
        "args_schema": '{"template":"daily1/daily2/daily3(可选)","per_day":3,"start_date":"2026-08-10","categories":["板块"],"apply":false}',
        "fn": tool_plan_study,
    },
    "get_context": {
        "description": "读取当前学情快照（题库数量、错题、待复习、掌握进度）",
        "args_schema": "{}",
        "fn": tool_get_context,
    },
}


def run_tool(name, args=None):
    tool = TOOLS.get(name)
    if not tool:
        return {"error": "unknown_tool", "detail": f"未知工具：{name}"}
    try:
        result = tool["fn"](args or {}) or {}
    except Exception as exc:  # noqa: BLE001 - 工具失败要反馈给 LLM 而不是中断
        return {"error": "tool_failed", "detail": str(exc)[:200]}
    return result


def tool_descriptions():
    lines = []
    for name, tool in TOOLS.items():
        lines.append(f"- {name}: {tool['description']}。参数：{tool['args_schema']}")
    return "\n".join(lines)
