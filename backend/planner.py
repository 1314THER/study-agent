"""一键规划：按板块顺序 + 关内顺序，把未掌握套路排进巩固日历。"""

import os
from datetime import date, datetime, timedelta

import yaml

from backend.categories import CATEGORIES
from backend.patterns import get_boards, get_patterns, set_pattern_schedule


CONFIG_PATH = os.path.join(os.path.dirname(__file__), "board_order.yaml")

TEMPLATES = {
    "daily1": {"name": "稳妥模式", "per_day": 1},
    "daily2": {"name": "加速模式", "per_day": 2},
    "daily3": {"name": "冲刺模式", "per_day": 3},
}


def _load_config():
    if not os.path.exists(CONFIG_PATH):
        return {"board_order": []}
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {"board_order": []}


def _save_config(data):
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(
            "# 板块顺序配置\n"
            "# board_order: 一级板块的先后顺序，nodes 是该板块内可精确指定的关卡顺序（question_id 列表）。\n"
            "# nodes 留空时，规划器按闯关地图的连线做拓扑排序兜底。\n"
        )
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    os.replace(tmp, CONFIG_PATH)


def get_board_order_config():
    """返回完整板块顺序配置，未配置的板块自动补在末尾。"""
    data = _load_config()
    order = data.get("board_order") or []
    result = []
    seen = set()
    for item in order:
        if not isinstance(item, dict):
            continue
        cat = str(item.get("category") or "").strip()
        if cat not in CATEGORIES or cat in seen:
            continue
        nodes = []
        for q in (item.get("nodes") or []):
            try:
                nodes.append(int(q))
            except (TypeError, ValueError):
                continue
        result.append({"category": cat, "nodes": nodes})
        seen.add(cat)
    for cat in CATEGORIES:
        if cat not in seen:
            result.append({"category": cat, "nodes": []})
    return {"board_order": result}


def save_board_order_config(board_order):
    """保存板块顺序配置，供母题看板后续编辑使用。"""
    cleaned = []
    seen = set()
    for item in board_order or []:
        if not isinstance(item, dict):
            continue
        cat = str(item.get("category") or "").strip()
        if cat not in CATEGORIES or cat in seen:
            continue
        nodes = []
        for q in (item.get("nodes") or []):
            try:
                nodes.append(int(q))
            except (TypeError, ValueError):
                continue
        cleaned.append({"category": cat, "nodes": nodes})
        seen.add(cat)
    for cat in CATEGORIES:
        if cat not in seen:
            cleaned.append({"category": cat, "nodes": []})
    _save_config({"board_order": cleaned})
    return get_board_order_config()


def _topo_order(board):
    """按闯关地图连线对板内套路做稳定拓扑排序。"""
    nodes = [n for n in board.get("nodes", []) if n.get("pattern_id")]
    if not nodes:
        return []
    q_to_p = {n["question_id"]: n["pattern_id"] for n in nodes}
    node_pos = {n["pattern_id"]: i for i, n in enumerate(nodes)}
    adj = {}
    indeg = {}
    for n in nodes:
        adj.setdefault(n["pattern_id"], [])
        indeg.setdefault(n["pattern_id"], 0)
    for e in board.get("edges", []):
        f = q_to_p.get(e.get("from_question_id"))
        t = q_to_p.get(e.get("to_question_id"))
        if f and t and f != t and t not in adj[f]:
            adj[f].append(t)
            indeg[t] = indeg.get(t, 0) + 1
    queue = [p for p, d in indeg.items() if d == 0]
    queue.sort(key=lambda p: node_pos.get(p, 0))
    result = []
    while queue:
        p = queue.pop(0)
        result.append(p)
        for nb in adj.get(p, []):
            indeg[nb] -= 1
            if indeg[nb] == 0:
                queue.append(nb)
                queue.sort(key=lambda x: node_pos.get(x, 0))
    if len(result) != len(indeg):
        for n in nodes:
            if n["pattern_id"] not in result:
                result.append(n["pattern_id"])
    return result


def _ordered_patterns(patterns, boards, config):
    """返回按板块顺序 + 关内顺序排好的套路列表。"""
    explicit = {}
    for item in config.get("board_order", []):
        explicit[item["category"]] = item.get("nodes") or []
    by_cat = {}
    for p in patterns:
        by_cat.setdefault(p.get("category"), []).append(p)
    board_by_cat = {b.get("category"): b for b in boards}
    ordered = []
    for cat in CATEGORIES:
        plist = by_cat.get(cat, [])
        if not plist:
            continue
        p_by_id = {p["id"]: p for p in plist}
        used = set()
        q_to_p = {}
        for p in plist:
            if p.get("mother_id"):
                q_to_p[int(p["mother_id"])] = p
        result = []
        exp = explicit.get(cat) or []
        if exp:
            for qid in exp:
                p = q_to_p.get(qid)
                if p and p["id"] not in used:
                    result.append(p)
                    used.add(p["id"])
            for p in plist:
                if p["id"] not in used:
                    result.append(p)
                    used.add(p["id"])
        else:
            board = board_by_cat.get(cat)
            topo = _topo_order(board) if board else []
            for pid in topo:
                p = p_by_id.get(pid)
                if p and pid not in used:
                    result.append(p)
                    used.add(pid)
            for p in plist:
                if p["id"] not in used:
                    result.append(p)
                    used.add(p["id"])
        ordered.extend(result)
    return ordered


def _parse_date(value):
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return date.today() + timedelta(days=1)


def build_plan(template=None, per_day=None, start_date=None, categories=None):
    """生成规划预览，不写库。"""
    if template in TEMPLATES:
        per_day = TEMPLATES[template]["per_day"]
    try:
        per_day = max(1, min(int(per_day or 1), 10))
    except (TypeError, ValueError):
        per_day = 1
    start = _parse_date(start_date)
    cats = [c.strip() for c in (categories or []) if c and str(c).strip()] or None
    patterns = get_patterns()
    unmastered = []
    for p in patterns:
        mastery = p.get("mastery") or {}
        if mastery.get("state") == "third_pass":
            continue
        if cats and p.get("category") not in cats:
            continue
        unmastered.append(p)
    config = get_board_order_config()
    boards = get_boards()
    ordered = _ordered_patterns(unmastered, boards, config)
    plan = []
    for i in range(0, len(ordered), per_day):
        day = start + timedelta(days=len(plan))
        chunk = ordered[i:i + per_day]
        plan.append({
            "date": day.isoformat(),
            "patterns": [
                {
                    "pattern_id": p["id"],
                    "name": p.get("name") or "",
                    "category": p.get("category") or "",
                    "state": (p.get("mastery") or {}).get("state", "never"),
                    "mother_id": p.get("mother_id"),
                }
                for p in chunk
            ],
        })
    return {
        "template": template,
        "per_day": per_day,
        "start_date": start.isoformat(),
        "total_patterns": len(ordered),
        "days": len(plan),
        "plan": plan,
    }


def apply_plan(plan):
    """把规划写入 pattern_mastery，返回已写入数量。"""
    count = 0
    for day in plan.get("plan", []):
        next_check_at = day.get("date", "") + " 08:00:00"
        for p in day.get("patterns", []):
            try:
                pid = int(p["pattern_id"])
            except (TypeError, ValueError, KeyError):
                continue
            set_pattern_schedule(pid, next_check_at, need_check=1)
            count += 1
    return {"applied": count}
