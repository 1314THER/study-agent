"""全局智能体：把自然语言指令转成标准化动作，并支持多步工具循环。"""

import json
import re
import time

import httpx

from backend.categories import CATEGORIES
from backend.database import MISTAKE_TYPES
from backend.agent_tools import agent_context, run_tool, tool_descriptions
import backend.settings as runtime_settings


PAGES = {
    "home": {"url": "home.html", "name": "首页", "aliases": ["首页", "主页", "主页面", "教练台", "总览", "主界面"]},
    "solve": {"url": "index.html", "name": "单题解答", "aliases": ["单题解答", "单题", "解题", "搜题", "做题", "题目解答", "解答页"]},
    "multimodal": {"url": "multimodal.html", "name": "多模态解答", "aliases": ["多模态", "多模态解答", "切题", "上传题目", "文件切题"]},
    "teach": {"url": "teach.html", "name": "手把手教学", "aliases": ["手把手教学", "教学页", "手把手", "老师教学", "教我做题"]},
    "history": {"url": "history.html", "name": "个人题库", "aliases": ["个人题库", "题库", "题目列表", "错题本", "历史记录", "错题"]},
    "exam": {"url": "exam.html", "name": "组卷", "aliases": ["组卷", "试卷", "组卷页", "购物车", "组卷篮子"]},
    "grade": {"url": "grade.html", "name": "AI 改卷", "aliases": ["AI 改卷", "AI改卷", "改卷", "判分", "批改", "改题"]},
    "settings": {"url": "settings.html", "name": "系统设置", "aliases": ["系统设置", "设置", "配置"]},
    "mother": {"url": "mother.html", "name": "母题看板", "aliases": ["母题看板", "母题", "看板"]},
    "loop": {"url": "loop.html", "name": "套路循环", "aliases": ["套路循环", "套路", "循环"]},
    "calendar": {"url": "calendar.html", "name": "巩固日历", "aliases": ["巩固日历", "日历", "复习日历"]},
    "board": {"url": "board.html", "name": "闯关地图", "aliases": ["闯关地图", "闯关", "地图"]},
}

_PAGE_ALIASES = {}
for _key, _cfg in PAGES.items():
    for _alias in _cfg["aliases"]:
        _PAGE_ALIASES[_alias] = _key

_CATEGORY_ALIASES = {}
for _name in CATEGORIES:
    _CATEGORY_ALIASES[_name] = _name
_CATEGORY_ALIASES.update({
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
})

_QUESTION_TYPES = ("多选题", "选择题", "填空题", "大题")
_DIFFICULTIES = ("极难", "困难", "中等", "容易")
_NAV_WORDS = ("打开", "进入", "跳转", "前往", "转到", "去", "带我去", "看一下", "看看")
_STATS_WORDS = ("我该学什么", "今天学什么", "学情", "学习情况", "学习状态", "统计一下", "数据概览", "总结一下", "当前状态")
_TEACH_WORDS = ("教我做", "手把手", "教学", "教我", "讲解一下")
_SOLVE_WORDS = ("解题", "帮我解", "帮我做", "解一下", "做一下", "求解", "解答")
_GRADE_WORDS = ("改卷", "判分", "批改", "改题", "改一下")
_SEARCH_VERBS = ("拿", "找", "搜", "出", "查", "列", "选", "组", "练习", "复习", "巩固", "想练", "想学")
_TYPE_ALIASES = {
    "选择": "选择题",
    "选择题": "选择题",
    "多选": "多选题",
    "多选题": "多选题",
    "填空": "填空题",
    "填空题": "填空题",
    "解答": "大题",
    "解答题": "大题",
    "大题": "大题",
}
_ACTION_TYPES = (
    "navigate", "search_questions", "open_question", "teach", "solve", "grade",
    "add_to_cart", "context",
    "solve_question", "teach_question", "grade_answer", "plan_study", "get_context",
)
_SERVER_TOOLS = {
    "search_questions", "solve_question", "teach_question",
    "grade_answer", "plan_study", "get_context",
}
_FRONTEND_ACTIONS = {"navigate", "open_question", "add_to_cart", "context", "teach", "solve", "grade"}
_TOOL_LABELS = {
    "search_questions": "搜索题目",
    "solve_question": "解题",
    "teach_question": "准备教学",
    "grade_answer": "批改作答",
    "plan_study": "生成复习规划",
    "get_context": "读取学情",
}
_MAX_TOOL_ROUNDS = 4
_MAX_HISTORY_MESSAGES = 20


def _detect_navigation(message):
    if not any(word in message for word in _NAV_WORDS):
        return None
    for alias, key in sorted(_PAGE_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if alias in message:
            return key
    return None


def _detect_open_question(message):
    patterns = (
        r"(?:打开|查看|看下?|进入)\s*(?:第|#|题号)?\s*(\d{1,6})\s*题?",
        r"(?:第|题号|#)\s*(\d{1,6})\s*题",
        r"(?:题目)\s*(?:#)?\s*(\d{1,6})",
    )
    for pat in patterns:
        m = re.search(pat, message)
        if m:
            return int(m.group(1))
    return None


def _detect_qid(message):
    m = re.search(r"(?:第|题号|题目|#)\s*(\d{1,6})\s*题?", message)
    return int(m.group(1)) if m else None


def _extract_question(message):
    for sep in ("：", ":", "题：", "题目：", "道题"):
        idx = message.find(sep)
        if idx >= 0:
            tail = message[idx + len(sep):].strip()
            if len(tail) >= 4:
                return tail
    return ""


def _detect_search(message):
    has_verb = any(v in message for v in _SEARCH_VERBS)
    has_category = any(alias in message for alias in _CATEGORY_ALIASES)
    has_subject = "题" in message or "卷" in message or has_category
    if not (has_verb or "错题" in message) or not has_subject:
        return None

    filters = {
        "category": [],
        "question_type": [],
        "difficulty": [],
        "error_type": "",
        "source_type": "",
    }
    limit = 5
    m = re.search(r"(\d+)\s*道", message)
    if m:
        limit = max(1, min(int(m.group(1)), 30))

    for alias in sorted(_CATEGORY_ALIASES, key=len, reverse=True):
        if alias in message:
            real = _CATEGORY_ALIASES[alias]
            if real not in filters["category"]:
                filters["category"].append(real)
            message = message.replace(alias, " ", 1)

    for t in _QUESTION_TYPES:
        if t in message:
            filters["question_type"].append(t)
            message = message.replace(t, " ", 1)
    if "解答题" in message:
        filters["question_type"].append("大题")
        message = message.replace("解答题", " ", 1)

    for d in _DIFFICULTIES:
        if d in message:
            filters["difficulty"].append(d)
            message = message.replace(d, " ", 1)

    if "高考" in message:
        filters["source_type"] = "高考题"
    elif "模拟" in message:
        filters["source_type"] = "模拟题"
    elif "母题" in message:
        filters["source_type"] = "精选母题"
    elif "生成" in message or "仿题" in message:
        filters["source_type"] = "ai生成"

    for mt in MISTAKE_TYPES:
        if mt in message:
            filters["error_type"] = mt
            message = message.replace(mt, " ", 1)
            break
    if "错题" in message or "错因" in message:
        if not filters["error_type"]:
            filters["error_type"] = "errors"
        message = re.sub(r"错题|错因", " ", message)

    residual = re.sub(r"[帮我麻烦请一下看看找拿搜出查来点列选给想要]|[：:，,。.！!？?]", " ", message)
    residual = re.sub(r"卷子|试卷|道|题|卷|套|张|份|个|组|的|练习|复习|巩固|相关|部分", " ", residual)
    residual = re.sub(r"\d+", " ", residual)
    residual = re.sub(r"\s+", " ", residual).strip()
    has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in residual)
    query = residual if (has_cjk and len(residual) >= 2) else ""

    return {
        "query": query,
        "filters": {
            "category": ",".join(filters["category"]),
            "question_type": ",".join(filters["question_type"]),
            "difficulty": ",".join(filters["difficulty"]),
            "error_type": filters["error_type"],
            "source_type": filters["source_type"],
        },
        "limit": limit,
    }


def _is_stats(message):
    return any(w in message for w in _STATS_WORDS)


def _is_teach(message):
    return any(w in message for w in _TEACH_WORDS)


def _is_solve(message):
    return any(w in message for w in _SOLVE_WORDS)


def _is_grade(message):
    return any(w in message for w in _GRADE_WORDS)


def _is_cart(message):
    return (
        "组卷" in message
        or "购物车" in message
        or bool(re.search(r"组.{0,8}卷", message))
        or ("卷子" in message and any(v in message for v in ("组", "出", "编")))
    )


def _validate_action(action):
    if not isinstance(action, dict):
        return None
    atype = action.get("type")
    if atype not in _ACTION_TYPES:
        return None
    if atype == "navigate":
        page = action.get("page")
        if page not in PAGES:
            return None
        return {"type": "navigate", "page": page, "params": action.get("params") or {}}
    if atype == "open_question":
        try:
            qid = int(action.get("id"))
        except (TypeError, ValueError):
            return None
        return {"type": "open_question", "id": qid}
    if atype in ("teach", "solve"):
        question = str(action.get("question") or "").strip()
        return {"type": atype, "question": question} if question else None
    if atype == "search_questions":
        f = action.get("filters") or {}
        if not isinstance(f, dict):
            f = {}
        safe = {}
        for key in ("category", "question_type", "difficulty", "error_type", "source_type"):
            val = f.get(key)
            if isinstance(val, list):
                safe[key] = ",".join(str(x) for x in val if str(x).strip())
            elif isinstance(val, str):
                safe[key] = val.strip()
            else:
                safe[key] = ""
        if safe.get("category"):
            cats = [c.strip() for c in safe["category"].split(",") if c.strip()]
            safe["category"] = ",".join(_CATEGORY_ALIASES.get(c, c) for c in cats)
        if safe.get("question_type"):
            types = [t.strip() for t in safe["question_type"].split(",") if t.strip()]
            safe["question_type"] = ",".join(_TYPE_ALIASES.get(t, t) for t in types)
        try:
            limit = max(1, min(int(action.get("limit") or 5), 30))
        except (TypeError, ValueError):
            limit = 5
        return {
            "type": "search_questions",
            "query": str(action.get("query") or "").strip(),
            "filters": safe,
            "limit": limit,
        }
    if atype == "add_to_cart":
        ids = []
        for x in (action.get("ids") or []):
            try:
                ids.append(int(x))
            except (TypeError, ValueError):
                pass
        try:
            limit = max(1, min(int(action.get("limit") or 5), 30))
        except (TypeError, ValueError):
            limit = 5
        return {"type": "add_to_cart", "source": action.get("source") or "search", "ids": ids[:30], "limit": limit}
    if atype == "grade":
        params = action.get("params") or {}
        qid = action.get("question_id") or params.get("question_id")
        return {"type": "grade", "params": {"question_id": qid}}
    if atype == "context":
        return {"type": "context"}
    if atype in ("solve_question", "teach_question"):
        question = str(action.get("question") or "").strip()
        if not question:
            return None
        out = {"type": atype, "question": question}
        for key in ("question_type", "teacher"):
            if action.get(key):
                out[key] = action[key]
        if atype == "solve_question" and action.get("save") is not None:
            out["save"] = bool(action.get("save"))
        return out
    if atype == "grade_answer":
        qid = action.get("question_id")
        try:
            qid = int(qid)
        except (TypeError, ValueError):
            qid = None
        question = str(action.get("question") or "").strip()
        student_answer = str(action.get("student_answer") or "").strip()
        if not student_answer or (qid is None and not question):
            return None
        out = {"type": "grade_answer", "student_answer": student_answer}
        if qid is not None:
            out["question_id"] = qid
        if question:
            out["question"] = question
        for key in ("question_type", "full_score", "teacher"):
            if action.get(key) is not None:
                out[key] = action[key]
        return out
    if atype == "plan_study":
        out = {"type": "plan_study"}
        for key in ("template", "start_date"):
            if action.get(key):
                out[key] = str(action[key])
        try:
            per_day = max(1, min(int(action.get("per_day")), 10))
        except (TypeError, ValueError):
            per_day = None
        if per_day is not None:
            out["per_day"] = per_day
        cats = action.get("categories") or []
        if isinstance(cats, str):
            cats = [c.strip() for c in cats.split(",") if c.strip()]
        elif isinstance(cats, list):
            cats = [str(c).strip() for c in cats if str(c).strip()]
        if cats:
            out["categories"] = cats
        if action.get("apply") is not None:
            out["apply"] = bool(action.get("apply"))
        return out
    if atype == "get_context":
        return {"type": "get_context"}
    return None


def _action_args(action):
    args = {k: v for k, v in action.items() if k != "type"}
    if action.get("type") == "search_questions":
        filters = args.get("filters") or {}
        if isinstance(filters, dict):
            for key in ("category", "question_type", "difficulty", "error_type", "source_type"):
                if not args.get(key) and filters.get(key):
                    args[key] = filters[key]
    return args


def _normalize_history(history):
    """保留最近 10 轮（20 条）user/assistant 消息。"""
    if not isinstance(history, list):
        return []
    out = []
    for item in history:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in ("user", "assistant"):
            continue
        content = str(content or "").strip()
        if content:
            out.append({"role": role, "content": content[:4000]})
    return out[-_MAX_HISTORY_MESSAGES:]


def _agent_system_prompt():
    return (
        "你是高中数学学习系统的全局教练，通过工具完成搜索、解题、教学、改卷、规划等任务。\n"
        "请只返回一个 JSON：{\"reply\":\"给学生的中文回复\",\"actions\":[{\"type\":\"工具名\",\"参数\":...}]}。\n"
        "不要 Markdown 代码块，不要输出其他文字。\n\n"
        "可用工具：\n"
        + tool_descriptions()
        + "\n\n"
        "动作类型只能是：search_questions / solve_question / teach_question / grade_answer / plan_study / get_context / navigate / open_question / add_to_cart。\n"
        "navigate 的 page 只能是：home/solve/multimodal/teach/history/exam/grade/settings/mother/loop/calendar/board。\n"
        "行为规则：\n"
        "1. 学生想练习/复习/巩固某个板块或知识点时，用 search_questions，limit 默认 5。\n"
        "2. 学生给出一段题面并要求解答时，用 solve_question，question 填题面原文；要求手把手教学时用 teach_question。\n"
        "3. 学生给出作答并要求批改时，用 grade_answer，question_id 或 question 必须能定位题目，student_answer 填学生作答。\n"
        "4. 学生问学情或建议时，用 get_context。\n"
        "5. 需要制定复习计划时，用 plan_study；学生明确说安排到日历/写入日历时 apply 设为 true。\n"
        "6. 需要组卷时，先 search_questions，再 add_to_cart。\n"
        "7. 学生只想打开某个页面时，用 navigate。\n"
        "8. 工具会在服务端执行并把结果回传。需要多步时（如先搜题再解题、先看学情再规划）可以连续返回多个动作，"
        "执行结果会追加到对话里，请根据结果继续；任务完成时返回空 actions。\n"
        "9. 回复简洁自然，1-3 句话，基于工具结果给出结论，不要复述 JSON 字段。"
    )


def _tool_result_text(name, result):
    text = json.dumps(result, ensure_ascii=False, default=str)
    return text[:6000]


def _tool_block(name, result):
    if not isinstance(result, dict):
        return None
    if name == "search_questions":
        items = result.get("items") or []
        if not items:
            return {"type": "search", "title": "搜索结果", "items": [], "empty": True}
        return {
            "type": "search",
            "title": f"找到 {result.get('count', len(items))} 道题",
            "items": items,
        }
    if name == "solve_question":
        if result.get("error"):
            return {"type": "solve_error", "title": "解题失败", "detail": result.get("detail") or result.get("error")}
        return {
            "type": "solve",
            "title": "解题结果",
            "question": result.get("question"),
            "qid": result.get("saved_id"),
            "final_answer": result.get("final_answer"),
            "knowledge_points": result.get("knowledge_points"),
            "category": result.get("category"),
            "difficulty_level": result.get("difficulty_level"),
            "chunks": result.get("chunks"),
        }
    if name == "teach_question":
        if result.get("error"):
            return {"type": "solve_error", "title": "教学准备失败", "detail": result.get("detail") or result.get("error")}
        return {
            "type": "teach",
            "title": "手把手教学已准备好",
            "session_id": result.get("session_id"),
            "question": result.get("question"),
            "teacher": result.get("teacher"),
            "message": result.get("message"),
            "total_steps": result.get("total_steps"),
            "step_titles": result.get("step_titles") or [],
            "chunks": result.get("chunks") or [],
        }
    if name == "grade_answer":
        if result.get("error"):
            return {"type": "solve_error", "title": "批改失败", "detail": result.get("detail") or result.get("error")}
        return {"type": "grade", "title": "批改结果", "result": result}
    if name == "plan_study":
        if result.get("error"):
            return {"type": "solve_error", "title": "规划失败", "detail": result.get("detail") or result.get("error")}
        return {"type": "plan", "title": "复习规划", "plan": result}
    return None


def _run_agent_loop_gen(message, history=None):
    """多步工具循环：yield 进度字符串，最后 yield 结果 dict。"""
    hist = _normalize_history(history)
    try:
        ctx = agent_context()
    except Exception:
        ctx = {}
    user_prompt = (
        f"用户指令：{message}\n\n"
        f"题库板块：{'、'.join(CATEGORIES)}\n"
        f"当前学情：个人题库 {ctx.get('total_questions', 0)} 道，错题标记 {ctx.get('wrong_questions', 0)} 道，"
        f"今日待复习 {ctx.get('due_reviews', 0)} 个，套路掌握 {ctx.get('patterns_mastered', 0)}/{ctx.get('patterns_total', 0)}。"
    )
    messages = [
        {"role": "system", "content": _agent_system_prompt()},
        *hist,
        {"role": "user", "content": user_prompt},
    ]
    blocks = []
    final_actions = []
    final_reply = ""
    executed_context = False

    yield "正在理解你的需求…"
    for _round in range(_MAX_TOOL_ROUNDS):
        content = _call_llm_messages(messages, temperature=0.4)
        if not content:
            yield None
            return
        try:
            data = json.loads(_extract_json(content))
            if isinstance(data, dict):
                reply = str(data.get("reply") or "").strip() or "好的，我来安排。"
                raw_actions = data.get("actions")
            else:
                reply = "好的，我来安排。"
                raw_actions = data if isinstance(data, list) else []
        except Exception:
            yield None
            return

        actions = [_validate_action(a) for a in raw_actions if isinstance(a, dict)]
        actions = [a for a in actions if a]
        if reply:
            final_reply = reply
        if not actions:
            break

        ran_tool = False
        for action in actions:
            atype = action["type"]
            if atype in _SERVER_TOOLS:
                yield f"正在调用：{_TOOL_LABELS.get(atype, atype)}…"
                result = run_tool(atype, _action_args(action))
                block = _tool_block(atype, result)
                if block:
                    blocks.append(block)
                messages.append({
                    "role": "user",
                    "content": f"工具 {atype} 的结果：\n{_tool_result_text(atype, result)}",
                })
                if atype == "get_context":
                    executed_context = True
                ran_tool = True
            elif atype in _FRONTEND_ACTIONS:
                final_actions.append(action)

        if not ran_tool:
            break
    else:
        final_reply = final_reply or "好的，已完成。"

    result = {"reply": final_reply, "actions": final_actions, "blocks": blocks}
    if executed_context:
        try:
            result["context"] = agent_context()
        except Exception:
            pass
    yield result


def _fast_path(message):
    if _is_stats(message):
        ctx = agent_context()
        return {"reply": _stats_reply(ctx), "actions": [{"type": "context"}], "context": ctx}
    nav = _detect_navigation(message)
    if nav:
        return {"reply": f"好的，带你打开{PAGES[nav]['name']}。", "actions": [{"type": "navigate", "page": nav, "params": {}}]}
    open_id = _detect_open_question(message)
    if open_id:
        return {"reply": f"好的，打开题目 #{open_id} 的详情。", "actions": [{"type": "open_question", "id": open_id}]}
    if "手写" in message:
        if any(w in message for w in ("教学", "教我", "手把手")):
            return {
                "reply": "好的，打开手把手教学页，上传手写过程即可。",
                "actions": [{"type": "navigate", "page": "teach", "params": {"mode": "handwriting"}}],
            }
        if any(w in message for w in ("改卷", "判分", "批改")):
            return {
                "reply": "好的，打开 AI 改卷页，上传手写作答即可。",
                "actions": [{"type": "navigate", "page": "grade", "params": {"mode": "handwriting"}}],
            }
    return None


def _fallback_path(message):
    """LLM/工具循环不可用时的规则兜底，保持原有前端动作。"""
    if _is_teach(message):
        question = _extract_question(message)
        if question:
            return {"reply": "好的，去手把手教学页带你做这道题。", "actions": [{"type": "teach", "question": question}]}
        return {"reply": "好的，打开手把手教学。", "actions": [{"type": "navigate", "page": "teach", "params": {}}]}
    if _is_solve(message):
        question = _extract_question(message)
        if question:
            return {"reply": "好的，去单题解答页做这道题。", "actions": [{"type": "solve", "question": question}]}
        return {"reply": "好的，打开单题解答。", "actions": [{"type": "navigate", "page": "solve", "params": {}}]}
    if _is_grade(message):
        qid = _detect_qid(message)
        return {"reply": "好的，打开 AI 改卷。", "actions": [{"type": "grade", "params": {"question_id": qid}}]}
    search = _detect_search(message)
    if search is not None:
        actions = [{
            "type": "search_questions",
            "query": search["query"],
            "filters": search["filters"],
            "limit": search["limit"],
        }]
        if _is_cart(message):
            actions.append({"type": "add_to_cart", "source": "search", "ids": [], "limit": search["limit"]})
            actions.append({"type": "navigate", "page": "exam", "params": {}})
        return {"reply": _search_reply(search), "actions": actions}
    if _is_cart(message):
        return {"reply": "好的，打开组卷页。", "actions": [{"type": "navigate", "page": "exam", "params": {}}]}
    return {
        "reply": "我可以帮你打开页面、拿题、教学、改卷。试试：打开题库、拿3道解析几何大题、我该学什么、打开组卷。",
        "actions": [],
    }


def _agent_flow(message, history=None):
    """统一处理入口：yield progress dicts，最后 yield result dict。"""
    message = (message or "").strip()
    if not message:
        yield {"type": "result", "result": {"reply": "请告诉我你想做什么。", "actions": []}}
        return
    fast = _fast_path(message)
    if fast is not None:
        yield {"type": "progress", "message": "好的，马上安排。"}
        yield {"type": "result", "result": fast}
        return
    result = None
    for item in _run_agent_loop_gen(message, history):
        if isinstance(item, str):
            yield {"type": "progress", "message": item}
        else:
            result = item
    if result is None:
        yield {"type": "result", "result": _fallback_path(message)}
        return
    yield {"type": "result", "result": result}


def _extract_json(text):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    first = text.find("{")
    if first >= 0:
        text = text[first:]
    last = text.rfind("}")
    if last >= 0:
        text = text[:last + 1]
    return text.strip()


def _call_llm_messages(messages, temperature=0.4):
    try:
        api_key = runtime_settings.get_api_key("deepseek")
    except ValueError:
        return None
    if not api_key:
        return None
    api_cfg = runtime_settings.get_api().get("deepseek") or {}
    base_url = (api_cfg.get("base_url") or "https://api.deepseek.com/v1").rstrip("/")
    endpoint = base_url if base_url.endswith("/chat/completions") else base_url + "/chat/completions"
    settings = runtime_settings.get_settings()
    model = settings.get("teachers", {}).get("liangliang", {}).get("solver", {}).get("model", "deepseek-v4-flash")
    max_tokens = min(int(runtime_settings.get_limits().get("api_max_tokens", 32000)), 2000)
    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    try:
        resp = httpx.post(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=20,
        )
        if resp.status_code != 200:
            return None
        return resp.json()["choices"][0]["message"]["content"]
    except Exception:
        return None


def _stats_reply(ctx):
    lines = []
    if ctx.get("due_reviews"):
        lines.append(f"今天有 {ctx['due_reviews']} 个套路到期复习，建议先打开巩固日历完成复习。")
    if ctx.get("wrong_questions"):
        lines.append(f"题库里还有 {ctx['wrong_questions']} 道带错因标记的题，可以优先拿错题重做。")
    if ctx.get("patterns_mastered") is not None and ctx.get("patterns_total"):
        lines.append(f"套路掌握进度：{ctx['patterns_mastered']} / {ctx['patterns_total']}。")
    if ctx.get("total_questions") is not None:
        lines.append(f"个人题库共有 {ctx['total_questions']} 道题，已记录 {ctx.get('practice_records', 0)} 次作答。")
    return "\n".join(lines) if lines else "目前还没有足够的学习数据，先去解题或上传题目吧。"


def _search_reply(search):
    parts = []
    f = search["filters"]
    if f["category"]:
        parts.append(f["category"])
    if f["question_type"]:
        parts.append(f["question_type"])
    if f["difficulty"]:
        parts.append(f["difficulty"])
    if f["error_type"]:
        parts.append("错题" if f["error_type"] == "errors" else f["error_type"])
    desc = "、".join(parts) if parts else "最新"
    if desc == "错题":
        return f"好，帮你找 {search['limit']} 道错题。"
    return f"好，帮你找 {search['limit']} 道{desc}的题。"


def _chunk_reply(text, size=6):
    if not text:
        return
    for i in range(0, len(text), size):
        yield text[i:i + size]


def agent_act(message, history=None, on_progress=None):
    """同步入口：返回最终 result dict。"""
    result = None
    for ev in _agent_flow(message, history):
        if ev["type"] == "progress":
            if on_progress:
                on_progress(ev["message"])
        elif ev["type"] == "result":
            result = ev["result"]
    return result or {"reply": "连接失败，请稍后再试。", "actions": []}


def agent_act_stream(message, history=None):
    """流式入口：yield NDJSON 事件 dict（progress/token/done）。"""
    result = None
    for ev in _agent_flow(message, history):
        if ev["type"] == "progress":
            yield ev
        elif ev["type"] == "result":
            result = ev["result"]
    if result is None:
        result = {"reply": "连接失败，请稍后再试。", "actions": []}
    yield {"type": "progress", "message": "正在组织回复…"}
    reply = result.get("reply") or ""
    for chunk in _chunk_reply(reply):
        yield {"type": "token", "text": chunk}
        time.sleep(0.012)
    yield {"type": "done", "result": result}
