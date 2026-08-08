"""一次性修复：清洗已入库题目 answer_json 里的解析残留。

用途：把历史生成/保存的题目按当前 Verifier 标准重新整理，包括：
  - 去掉混进步骤正文的“步骤难度/知识点/---/难度评分表”等元数据
  - 从残留文本里补回步骤难度、知识点和块难度
  - 统一难度维度名并重算总分/等级
  - 规范化最终答案和顶层字段
"""

import json
import re

from backend import difficulty as diff
from backend.database import (
    _build_steps_structure,
    _collect_step_knowledge_points,
    _ensure_multi_choice_marker,
    _sanitize_category,
    _sanitize_difficulty,
    _sanitize_knowledge_points,
    get_connection,
    looks_like_choice_question,
)


DIM_MAP = {
    "常规程度": "非常规程度",
    "理解难度": "条件转化难度",
    "涉及到的知识点数量": "知识广度",
    "知识点数量": "知识广度",
    "知识点密度": "知识广度",
}


def _norm_dims(dims: dict) -> dict:
    return {DIM_MAP.get(k, k): v for k, v in (dims or {}).items()}


def _strip_meta(text: str) -> str:
    out = []
    skip_table = False
    kp_collect = False
    for raw in text.split("\n"):
        s = raw.strip()
        if not s:
            continue
        body = re.sub(r"^\s*[-*•]\s*", "", s)
        if re.match(r"^#{1,6}\s*难度评分", body):
            skip_table = True
            continue
        if skip_table:
            continue
        if re.match(r"^-{2,}\s*$", s) or re.match(r"^\*{2,}\s*$", s):
            kp_collect = False
            continue
        if re.match(r"^(步骤难度|块类型|板块|块难度|块最终答案|块知识点)\s*[：:]\s*", body):
            kp_collect = False
            continue
        if re.match(r"^(level|score)\s*[：:]\s*", body):
            continue
        km = re.match(r"^知识点\s*[：:]\s*(.*)$", body)
        if km:
            kp_collect = not km.group(1).strip()
            continue
        if kp_collect:
            continue
        out.append(raw.rstrip())
    return "\n".join(out).strip()


def _extract_sd(text: str):
    m = re.search(r"步骤难度\s*[：:]\s*(\{.*?\})", text, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError):
            pass
    m = re.search(
        r"步骤难度\s*[：:]\s*\n?\s*[-*•]?\s*level\s*[：:]\s*([^\n]+?)\s*\n\s*[-*•]?\s*score\s*[：:]\s*(\d+)",
        text,
    )
    if m:
        return {"level": m.group(1).strip(), "score": int(m.group(2))}
    return None


def _extract_kp(text: str) -> str:
    m = re.search(r"(?:^|\n)\s*[-*•]?\s*知识点\s*[：:][^\S\n]*([^\n]+)", text)
    if m:
        raw = m.group(1).strip()
        if raw:
            return raw
    lines = text.split("\n")
    collecting = False
    kps = []
    for line in lines:
        body = re.sub(r"^\s*[-*•]\s*", "", line.strip())
        if re.match(r"^知识点\s*[：:]\s*$", body):
            collecting = True
            continue
        if collecting:
            if re.match(r"^(步骤难度|level|score)\s*[：:]", body) or re.match(r"^-{2,}\s*$", body):
                break
            if body and not re.match(r"^[|#]", body):
                kps.append(body)
    return "、".join(kps) if kps else ""


def _extract_chunk_dims(text: str) -> dict:
    rows = {}
    in_table = False
    for line in text.split("\n"):
        body = re.sub(r"^\s*[-*•]\s*", "", line.strip())
        if re.match(r"^#{1,6}\s*难度评分", body):
            in_table = True
            continue
        if in_table:
            m = re.match(r"^\|\s*([^|]+?)\s*\|\s*(\d+)\s*\|", body)
            if m:
                key = DIM_MAP.get(m.group(1).strip(), m.group(1).strip())
                rows[key] = int(m.group(2))
    return rows


def _extract_final_from_steps(steps: list) -> str:
    for step in reversed(steps or []):
        if not isinstance(step, dict):
            continue
        text = "\n".join([
            str(step.get("standard_writing") or ""),
            str(step.get("detailed_writing") or ""),
        ])
        m = re.search(r"最终答案\s*[：:]\s*(.+)$", text, re.M)
        if m:
            return m.group(1).strip()
        m = re.search(
            r"(?:故选|所以选|答案为|正确答案为|最终答案为|答案是|答案\s*[：:])\s*选?\s*[A-H](?:\s*[、,，/]\s*[A-H])*",
            text,
        )
        if m:
            label = m.group(0).strip()
            label = re.sub(
                r"^(?:故选|所以选|答案为|正确答案为|最终答案为|答案是|答案)\s*[：:]?",
                "",
                label,
            ).strip()
            if re.match(r"^[A-H]", label):
                label = "选 " + label
            return label
    return ""


def clean_answer_json(aj: dict) -> tuple:
    changed = False
    crs = aj.get("chunk_results")
    if not isinstance(crs, list):
        return aj, changed

    for cr in crs:
        if not isinstance(cr, dict):
            continue
        cat = cr.get("category")
        if isinstance(cat, str):
            cr["category"] = {"level1": cat, "level2": None}
            changed = True

        block_diff = cr.get("difficulty")
        if isinstance(block_diff, dict) and isinstance(block_diff.get("dimensions"), dict):
            nd = _norm_dims(block_diff["dimensions"])
            if nd != block_diff["dimensions"]:
                block_diff["dimensions"] = nd
                changed = True

        raw_text = "\n".join(
            str(s.get("standard_writing") or "") for s in cr.get("steps") or [] if isinstance(s, dict)
        ) + "\n" + json.dumps(cr, ensure_ascii=False)
        dims = _extract_chunk_dims(raw_text)
        if dims:
            if not isinstance(block_diff, dict) or not block_diff.get("dimensions"):
                cr["difficulty"] = {"level": "未知", "total_score": 0, "dimensions": dims}
                changed = True
            else:
                merged = dict(block_diff["dimensions"])
                merged.update(dims)
                if merged != block_diff["dimensions"]:
                    block_diff["dimensions"] = merged
                    changed = True
        for s in cr.get("steps") or []:
            if not isinstance(s, dict):
                continue
            raw_std = str(s.get("standard_writing") or "")
            raw_det = str(s.get("detailed_writing") or "")
            combo_raw = raw_std + "\n" + raw_det
            if not s.get("step_difficulty"):
                sd = _extract_sd(combo_raw)
                if sd:
                    s["step_difficulty"] = sd
                    changed = True
            sd = s.get("step_difficulty")
            if isinstance(sd, dict) and not diff.normalize_dims(sd.get("dimensions")):
                s["step_difficulty"] = None
                changed = True
            if not str(s.get("knowledge_point") or "").strip():
                kp = _extract_kp(combo_raw)
                if kp:
                    s["knowledge_point"] = kp
                    changed = True
            for key in ("standard_writing", "detailed_writing"):
                old_text = raw_std if key == "standard_writing" else raw_det
                if old_text:
                    clean = _strip_meta(old_text)
                    if clean != old_text:
                        s[key] = clean
                        changed = True
            if not str(s.get("detailed_writing") or "").strip() and str(s.get("standard_writing") or "").strip():
                s["detailed_writing"] = s["standard_writing"]
                changed = True

    for cr in crs:
        if isinstance(cr, dict) and not str(cr.get("final_answer") or "").strip():
            fa = _extract_final_from_steps(cr.get("steps") or [])
            if fa:
                cr["final_answer"] = fa
                changed = True

    fas = [
        str(c.get("final_answer") or "").strip()
        for c in crs
        if isinstance(c, dict) and str(c.get("final_answer") or "").strip()
    ]
    if fas:
        joined = " | ".join(fas)
        if joined != (aj.get("final_answer") or ""):
            aj["final_answer"] = joined
            changed = True
        for c in crs:
            if isinstance(c, dict) and not str(c.get("final_answer") or "").strip():
                c["final_answer"] = fas[0]
                changed = True

    if crs:
        if diff.has_step_dimensions(crs):
            _, od = diff.aggregate_chunk_results(crs)
        else:
            old_od = aj.get("overall_difficulty") or {}
            if old_od and old_od != diff.UNKNOWN_DIFFICULTY:
                aj["legacy_difficulty"] = old_od
                changed = True
            od = dict(diff.UNKNOWN_DIFFICULTY)
            for c in crs:
                c["difficulty"] = dict(diff.UNKNOWN_DIFFICULTY)
        if od != (aj.get("overall_difficulty") or {}):
            aj["overall_difficulty"] = od
            changed = True

    kps = _collect_step_knowledge_points(crs)
    if kps and kps != (aj.get("knowledge_points") or []):
        aj["knowledge_points"] = kps
        changed = True

    qt = aj.get("question_type")
    if not qt and crs:
        qt = crs[0].get("chunk_type")
    if qt in ("选择题", "填空题", "多选题", "大题"):
        aj["question_type"] = qt
    return aj, changed


def repair_all() -> list:
    conn = get_connection()
    rows = conn.execute(
        """SELECT id, content, answer_json, source_type, source_meta,
                  category_level1, category_level2, question_type
           FROM questions ORDER BY id"""
    ).fetchall()
    changed_ids = []
    for r in rows:
        try:
            aj = json.loads(r["answer_json"]) if r["answer_json"] else {}
        except (json.JSONDecodeError, TypeError):
            aj = {}
        if not isinstance(aj, dict):
            aj = {}
        aj, changed = clean_answer_json(aj)
        if not changed:
            continue

        aj.setdefault("source_type", r["source_type"])
        if not aj.get("source_meta") and r["source_meta"]:
            try:
                aj["source_meta"] = json.loads(r["source_meta"])
            except (json.JSONDecodeError, TypeError):
                aj["source_meta"] = None

        category_level1, category_level2 = _sanitize_category(aj.get("category") or {})
        if not category_level1:
            category_level1 = r["category_level1"]
            category_level2 = r["category_level2"]

        difficulty = aj.get("overall_difficulty") or aj.get("difficulty") or {}
        diff_level, diff_score, diff_dims = _sanitize_difficulty(difficulty)

        qtype = aj.get("question_type")
        if qtype not in ("选择题", "填空题", "多选题", "大题"):
            qtype = r["question_type"] or "大题"
        content = r["content"]
        if qtype == "多选题":
            content = _ensure_multi_choice_marker(content)
        elif qtype == "大题" and looks_like_choice_question(content):
            qtype = "选择题"
            aj["question_type"] = "选择题"

        clean_kps = _sanitize_knowledge_points(category_level1, aj.get("knowledge_points") or [])
        steps_structure = _build_steps_structure(aj.get("chunk_results") or [])
        conn.execute(
            """UPDATE questions SET
                 content = ?, answer_json = ?,
                 category_level1 = ?, category_level2 = ?,
                 difficulty_level = ?, difficulty_score = ?, difficulty_dimensions = ?,
                 knowledge_points = ?, question_type = ?, steps_structure = ?
               WHERE id = ?""",
            (
                content,
                json.dumps(aj, ensure_ascii=False),
                category_level1,
                category_level2,
                diff_level,
                diff_score,
                diff_dims,
                json.dumps(clean_kps, ensure_ascii=False),
                qtype,
                steps_structure,
                r["id"],
            ),
        )
        changed_ids.append(r["id"])
    conn.commit()
    conn.close()
    return changed_ids


if __name__ == "__main__":
    ids = repair_all()
    print(f"已修复 {len(ids)} 道题: {ids}")
