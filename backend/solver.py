"""
做题系统：三阶流程
Solver（切块+解答） -> 解析块 -> 逐块 Verifier + Formatter -> 聚合
"""

import os
import json
import re
import httpx
from typing import Dict, Any, List, Optional, Tuple

from backend.categories import CATEGORIES, get_knowledge_points, validate_knowledge_points

# ---------- 目录 ----------
PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")

# ---------- 正则 ----------
TYPE_PATTERN = re.compile(r'^\[题型：(.+?)\]')
CATEGORY_PATTERN = re.compile(r'^\[板块：(.+?)\]')
STATUS_PATTERN = re.compile(r'^\[(?:确认|修正)：(.+?)\]')
STEP_HEADER_PATTERN = re.compile(r'^步骤(\d+)\s*[：:]\s*(.+)$')
FINAL_ANSWER_PATTERN = re.compile(r'^最终答案[：:]\s*(.+)$')
KNOWLEDGE_POINT_PATTERN = re.compile(r'^知识点[：:]\s*(.+)$')
BRIEF_PATTERN = re.compile(r'^简略过程[：:]\s*(.+)$')
DETAIL_PATTERN = re.compile(r'^计算过程[：:]\s*(.+)$')
CHUNK_PATTERN = re.compile(r'###\s*块(\d+)\s*')

# ---------- 读取 prompt ----------
def _read_prompt(name: str) -> str:
    with open(os.path.join(PROMPTS_DIR, f"{name}.md"), encoding="utf-8") as f:
        return f.read().strip()

SOLVER_PROMPT = _read_prompt("solver")
FORMATTER_PROMPT = _read_prompt("formatter")

# ---------- API Key ----------
def get_api_key() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY")
    if key:
        return key
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("DEEPSEEK_API_KEY="):
                    return line.split("=", 1)[1]
    raise ValueError("未找到 DEEPSEEK_API_KEY")

# ---------- 调用 DeepSeek ----------
def call_deepseek(system_prompt: str, user_prompt: str, temperature: float = 0.3):
    api_key = get_api_key()
    resp = httpx.post(
        "https://api.deepseek.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": 32000,
        },
        timeout=180,
    )
    if resp.status_code != 200:
        raise Exception(f"API 请求失败: {resp.status_code} {resp.text}")
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    return content, usage

# ---------- 提取器 ----------
def _extract_status(text: str) -> str:
    first_line = text.strip().split("\n")[0].strip()
    m = STATUS_PATTERN.match(first_line)
    if m:
        status = m.group(1).strip()
        if status in ("可解", "不会做", "错题"):
            return status
    return "可解"

def _extract_json(text: str) -> str:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    first = text.find("{")
    if first >= 0:
        text = text[first:]
    last = text.rfind("}")
    if last >= 0:
        text = text[: last + 1]
    return text.strip()

def _parse_final_answer(text: str) -> str:
    for line in text.split("\n"):
        m = FINAL_ANSWER_PATTERN.match(line.strip())
        if m:
            return m.group(1).strip()
    return ""

def _parse_steps(text: str) -> list:
    steps = []
    current_step = None
    in_step = False
    lines = text.split("\n")
    for line in lines:
        stripped = line.strip()
        m = STEP_HEADER_PATTERN.match(stripped)
        if m:
            if current_step is not None:
                steps.append(current_step)
            current_step = {
                "step_number": int(m.group(1)),
                "title": m.group(2).strip(),
                "standard_writing": "",
                "detail": "",
                "knowledge_point": "",
            }
            in_step = True
            continue
        if not in_step or current_step is None:
            continue
        m = KNOWLEDGE_POINT_PATTERN.match(stripped)
        if m:
            current_step["knowledge_point"] = m.group(1).strip()
            continue
        m = BRIEF_PATTERN.match(stripped)
        if m:
            current_step["standard_writing"] = m.group(1).strip()
            continue
        m = DETAIL_PATTERN.match(stripped)
        if m:
            current_step["detail"] = m.group(1).strip()
            continue
        if not stripped.startswith("最终答案") and not stripped.startswith("[确认"):
            if current_step["detail"]:
                current_step["detail"] += "\n" + line
            else:
                current_step["detail"] = line
    
    if current_step is not None:
        steps.append(current_step)

    # 兜底：如果没解析出任何步骤但文本有内容，回退为整段
    if not steps:
        content = text.strip()
        # 去掉状态行和最终答案行
        for marker in ("[确认", "最终答案", "题型", "板块"):
            content = "\n".join(l for l in content.split("\n") if not l.strip().startswith(marker))
        content = content.strip()
        if content:
            steps.append({
                "step_number": 1,
                "title": "解答",
                "standard_writing": "",
                "detail": content,
                "knowledge_point": "",
            })
    return steps

def _parse_sub_answers(text: str) -> list:
    parts = re.split(r'(?:^|\s+)\((\d+)\)\s*', text.strip())
    if len(parts) < 2:
        return []
    results = []
    for i in range(1, len(parts), 2):
        if i + 1 < len(parts):
            results.append(f"({parts[i]}) {parts[i+1].strip()}")
    return results

# ---------- 块解析 ----------
def _parse_chunks(text: str) -> list:
    parts = CHUNK_PATTERN.split(text)
    if len(parts) < 3:
        return [{"id": 1, "type": "整体", "content": text}]
    chunks = []
    for i in range(1, len(parts) - 1, 2):
        chunk_id = int(parts[i])
        content = parts[i + 1].strip()
        lines = content.split("\n")
        qtype = "整体"
        category = None
        for line in lines:
            if line.startswith("题型") and ("：" in line or ":" in line):
                sep = "：" if "：" in line else ":"
                val = line.split(sep, 1)[1].strip()
                if val and not val.startswith("["):
                    qtype = val
            if line.startswith("板块") and ("：" in line or ":" in line):
                sep = "：" if "：" in line else ":"
                val = line.split(sep, 1)[1].strip()
                # 取第一个连续中文词作为板块名（去掉后面的注释）
                import re as _re
                m = _re.match(r'([一-鿿]+)', val)
                if m:
                    candidate = m.group(1)
                    # 只取存在于CATEGORIES中的板块
                    if candidate in CATEGORIES:
                        category = candidate
        chunks.append({"id": chunk_id, "type": qtype or "整体", "category": category, "content": content.strip()})
    return chunks

# ---------- Verifier 路由 ----------
def _load_verifier_prompt(category: str, is_cross: bool, involved: list) -> str:
    if is_cross:
        path = os.path.join(PROMPTS_DIR, "verifiers", "交叉压轴题.md")
        with open(path, encoding="utf-8") as f:
            prompt = f.read().strip()
        if len(involved) >= 2:
            prompt = prompt.replace("{板块A}", involved[0]).replace("{板块B}", involved[1])
        all_kps = set()
        for cat in involved:
            all_kps.update(get_knowledge_points(cat))
        kp_str = "、".join(sorted(all_kps))
        prompt = prompt.replace("可选知识点：多板块综合", f"可选知识点：{kp_str}")
        return prompt
    path = os.path.join(PROMPTS_DIR, "verifiers", f"{category}.md")
    if not os.path.exists(path):
        raise FileNotFoundError(f"找不到板块对应的 verifier: {category}（路径: {path}）")
    with open(path, encoding="utf-8") as f:
        return f.read().strip()

# ---------- 块上下文 ----------
def _build_context(chunk: dict, solved: list) -> str:
    parts = []
    for dep_id in chunk.get("depends_on", []):
        prev = next((s for s in solved if s.get("chunk_id") == dep_id), None)
        if prev:
            answer = prev.get("final_answer", "")
            parts.append(f"第({dep_id})问答案：{answer}")
    return "\n".join(parts) if parts else ""

# ---------- 聚合 ----------
def aggregate_chunks(chunks: list, results: list) -> dict:
    steps_all = []
    sub_answers = []
    kps = set()
    for r in results:
        for step in r.get("steps", []):
            steps_all.append(dict(step))
        sa = r.get("sub_answers") or []
        sub_answers.extend(sa)
        for kp in r.get("knowledge_points", []):
            kps.add(kp)
    final_answers = [r.get("final_answer", "") for r in results if r.get("final_answer")]
    return {
        "steps": steps_all,
        "final_answer": " | ".join(final_answers) if len(final_answers) > 1 else (final_answers[0] if final_answers else ""),
        "sub_answers": sub_answers if sub_answers else None,
        "knowledge_points": list(kps),
        "chunk_results": results,
        "chunks": chunks,
    }

# ---------- Solver 步 ----------
def step_solver_only(question: str, question_type: str = None) -> dict:
    """仅做 solver（切块+解答），返回解析后的 chunks"""
    prompt = SOLVER_PROMPT
    if question_type:
        prompt += f"\n\n注意：已知本题为{question_type}，请按该题型切块和解答。"
    content, usage = call_deepseek(prompt, question)
    chunks = _parse_chunks(content)
    if not chunks:
        chunks = [{"id": 1, "type": question_type or "整体", "content": content}]
    return {"content": content, "chunks": chunks, "token_usage": usage}

# ---------- Verifier + Formatter 步（一个块）----------
def step_verify_format_chunk(chunk: dict, question: str, solved: list) -> dict:
    cid = chunk["id"]
    ctype = chunk.get("type", "整体")
    ccontent = chunk["content"]
    cat = chunk.get("category")
    # 如果 solver 没输出板块，从内容中自动匹配
    if not cat and ctype in ("子问", "整体", "大题"):
        for known_cat in CATEGORIES:
            if known_cat in ccontent:
                cat = known_cat
                break

    ctx_parts = [f"原题：{question}"]
    dep_ctx = _build_context(chunk, solved)
    if dep_ctx:
        ctx_parts.append(dep_ctx)
    context = "\n".join(ctx_parts)

    # Verifier
    is_cross = cat == "交叉压轴题"
    verifier_prompt = _load_verifier_prompt(cat or ctype, is_cross, [cat] if cat else [])
    verified_out, v_usage = call_deepseek(verifier_prompt, f"{context}\n\n解答内容：\n{ccontent}")
    status = _extract_status(verified_out)

    # Formatter
    v_output = {
        "content": verified_out,
        "status": status,
        "question_type": ctype,
        "category": cat,
        "involved": [cat] if cat else [],
    }
    f_result = _step_formatter(v_output, ccontent)

    token_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for u in (v_usage, f_result["token_usage"]):
        for k in token_total:
            token_total[k] += u.get(k, 0)

    result = f_result["result"]
    result["chunk_id"] = cid
    return {"result": result, "token_usage": token_total}

# ---------- Formatter（纯机械 + AI 纠错）----------
def _step_formatter(verifier_output: dict, original_question: str = None) -> dict:
    content = verifier_output["content"]
    _content_for_ai = content[:6000]
    qtype = verifier_output.get("question_type", "大题")
    category = verifier_output.get("category", "未知")
    involved = verifier_output.get("involved", [])
    status = verifier_output.get("status", "可解")

    if status in ("不会做", "错题"):
        lines = content.strip().split("\n", 1)
        reason = lines[1].strip() if len(lines) > 1 else ""
        if reason.startswith("["):
            reason = ""
        result = {
            "status": status, "reason": reason,
            "steps": [], "final_answer": "无法解答" if status == "不会做" else "错题",
            "difficulty": {"level": "未知", "total_score": 0, "dimensions": {}},
            "category": {"level1": category if category else qtype, "level2": None},
            "knowledge_points": [], "common_mistakes": [],
        }
        return {"result": result, "token_usage": {}}

    steps = _parse_steps(content)
    _parsed_final_answer = _parse_final_answer(content)
    _sub_answers = _parse_sub_answers(_parsed_final_answer)

    # 知识点
    raw_kps = []
    for s in steps:
        kp = s.get("knowledge_point", "")
        if kp:
            for item in kp.split("、"):
                item = item.strip()
                if item:
                    raw_kps.append(item)

    if qtype in ("选择题", "填空题"):
        valid_kps = [kp for kp in raw_kps if kp]
    elif involved:
        valid_kps = []
        for kp in raw_kps:
            found = False
            for cat in involved:
                if kp in CATEGORIES.get(cat, []):
                    found = True
                    break
            if found:
                valid_kps.append(kp)
    else:
        valid_kps = validate_knowledge_points(category, raw_kps)

    seen = set()
    unique_kps = []
    for kp in valid_kps:
        if kp not in seen:
            seen.add(kp)
            unique_kps.append(kp)

    # AI 难度评分 + JSON 纠错
    steps_json_str = json.dumps(steps, ensure_ascii=False, indent=2)
    diff_input = (
        f"【原题】\n{original_question or '(未提供)'}\n\n"
        f"【完整解题过程】\n{_content_for_ai}\n\n"
        f"【机械解析步骤 JSON】\n{steps_json_str}\n\n"
        f"【最终答案】\n{_parsed_final_answer}"
    )
    formatted, usage = call_deepseek(FORMATTER_PROMPT, diff_input, temperature=0.2)

    difficulty = {"level": "中等", "total_score": 4, "dimensions": {}}
    common_mistakes = []
    corrections = None
    try:
        diff_json = json.loads(_extract_json(formatted))
        if "difficulty" in diff_json:
            difficulty = diff_json["difficulty"]
        if "common_mistakes" in diff_json:
            common_mistakes = diff_json["common_mistakes"]
        if "corrections" in diff_json and diff_json["corrections"] is not None:
            corrections = diff_json["corrections"]
    except (json.JSONDecodeError, ValueError):
        pass

    if corrections:
        if "final_answer" in corrections and corrections["final_answer"]:
            _parsed_final_answer = corrections["final_answer"]
        if "knowledge_points" in corrections and corrections["knowledge_points"]:
            unique_kps = []
            seen = set()
            for kp in corrections["knowledge_points"]:
                if kp not in seen:
                    seen.add(kp)
                    unique_kps.append(kp)
        if "steps" in corrections and corrections["steps"]:
            for cor_step in corrections["steps"]:
                sn = cor_step.get("step_number")
                for existing in steps:
                    if existing["step_number"] == sn:
                        for field in ("title", "standard_writing", "detail", "knowledge_point"):
                            if field in cor_step and cor_step[field]:
                                existing[field] = cor_step[field]

    result = {
        "status": status, "question_type": qtype,
        "steps": steps, "final_answer": _parsed_final_answer,
        "sub_answers": _sub_answers if _sub_answers else None,
        "category": {"level1": category if category else qtype, "level2": unique_kps[0] if unique_kps else None},
        "knowledge_points": unique_kps,
        "difficulty": difficulty, "common_mistakes": common_mistakes,
    }
    if original_question:
        from backend.database import save_question
        save_question(original_question, result)
    return {"result": result, "token_usage": usage}

# ---------- 完整流程 ----------
def solve_multi(question: str, question_type: str = None) -> dict:
    from backend.database import find_question
    cached = find_question(question)
    if cached:
        return cached

    token_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    def _add(u):
        for k in token_total:
            token_total[k] += u.get(k, 0)

    r1 = step_solver_only(question, question_type)
    _add(r1["token_usage"])
    chunks = r1["chunks"]

    solved = []
    chunk_results = []
    for chunk in chunks:
        r2 = step_verify_format_chunk(chunk, question, solved)
        _add(r2["token_usage"])
        chunk_results.append(r2["result"])
        solved.append(r2["result"])

    final = aggregate_chunks(chunks, chunk_results)
    final["token_usage"] = token_total
    return final

def solve(question: str, question_type: str = None) -> dict:
    return solve_multi(question, question_type)
