"""全局智能体：把自然语言指令转成前端可执行的标准化动作。"""

import json
import re

import httpx

from backend.categories import CATEGORIES
from backend.database import MISTAKE_TYPES, get_connection, search_questions
from backend.patterns import get_pattern_calendar, get_patterns
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
_SEARCH_VERBS = ("拿", "找", "搜", "出", "查", "列", "选", "组")
_ACTION_TYPES = ("navigate", "search_questions", "open_question", "teach", "solve", "grade", "add_to_cart", "context")


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
    has_subject = "题" in message or "卷" in message
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
    residual = re.sub(r"卷子|试卷|道|题|卷|套|张|份|个|组|的", " ", residual)
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
    return None


def _llm_plan(message):
    system = (
        "你是数学学习系统的全局教练。请把用户指令转成 JSON 动作数组，动作类型只能是："
        "navigate / search_questions / open_question / teach / solve / grade / add_to_cart / context。\n"
        "navigate 的 page 只能是：home/solve/multimodal/teach/history/exam/grade/settings/mother/loop/calendar/board。\n"
        "search_questions 返回 {\"type\":\"search_questions\",\"query\":\"关键词\",\"filters\":{\"category\":\"\",\"question_type\":\"\",\"difficulty\":\"\",\"error_type\":\"\",\"source_type\":\"\"},\"limit\":5}。\n"
        "add_to_cart 用于把刚才搜到的题加入组卷：{\"type\":\"add_to_cart\",\"source\":\"search\",\"ids\":[],\"limit\":5}。\n"
        "只返回 JSON，不要输出任何其他文字。"
    )
    try:
        content = _call_agent_llm(system, f"用户指令：{message}\n\n题库板块：{'、'.join(CATEGORIES)}")
        if not content:
            return None
        data = json.loads(_extract_json(content))
        actions = data.get("actions") if isinstance(data, dict) else data
        if not isinstance(actions, list):
            actions = [data]
        valid = [_validate_action(a) for a in actions]
        valid = [a for a in valid if a]
        return valid or None
    except Exception:
        return None


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


def _call_agent_llm(system_prompt, user_prompt):
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
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
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


def agent_act(message):
    message = (message or "").strip()
    if not message:
        return {"reply": "请告诉我你想做什么。", "actions": []}

    if _is_stats(message):
        ctx = agent_context()
        return {"reply": _stats_reply(ctx), "actions": [{"type": "context"}], "context": ctx}

    nav = _detect_navigation(message)
    if nav:
        return {"reply": f"好的，带你打开{PAGES[nav]['name']}。", "actions": [{"type": "navigate", "page": nav, "params": {}}]}

    open_id = _detect_open_question(message)
    if open_id:
        return {"reply": f"好的，打开题目 #{open_id} 的详情。", "actions": [{"type": "open_question", "id": open_id}]}

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

    actions = _llm_plan(message)
    if actions:
        return {"reply": "好的，我来安排。", "actions": actions}

    return {
        "reply": "我可以帮你打开页面、拿题、教学、改卷。试试：打开题库、拿3道解析几何大题、我该学什么、打开组卷。",
        "actions": [],
    }
