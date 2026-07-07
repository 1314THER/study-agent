"""
做题系统：三阶流程（最终版）
Solver（1 次调用）：解答并输出板块
  └─ 雪碧了检测
Verifier（1 次调用）：切大块/小块 + 归类知识点 + 打分
Formatter（1 次调用）：全局校验 + 聚合入库
"""

import os
import json
import re
import httpx
from typing import Dict, Any, List, Optional

from backend.categories import CATEGORIES

# ---------- 目录 ----------
PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")

# ---------- 正则 ----------
SOLVER_STATUS_PATTERN = re.compile(r'^\[(?:状态|确认|修正)：(.+?)\]')
BRIEF_PATTERN = re.compile(r'^简略过程[：:]\s*(.+)$')
STANDARD_PATTERN = re.compile(r'^标准过程[：:]\s*(.+)$')
DETAIL_PATTERN = re.compile(r'^详细过程[：:]\s*(.+)$')
KNOWLEDGE_POINT_PATTERN = re.compile(r'^知识点[：:]\s*(.+)$')
STEP_HEADER_PATTERN = re.compile(r'^步骤(\d+)\s*(?:[（(]?小块[）)]?)?[：:]\s*(.*)$')
CHUNK_PATTERN = re.compile(r'###\s*块(\d+)\s*')

# Verifier 输出中的块级字段
BLOCK_TYPE_PATTERN = re.compile(r'^块类型[：:]\s*(.+)$')
BLOCK_CATEGORY_PATTERN = re.compile(r'^板块[：:]\s*(.+)$')
# Solver 结构化状态字段
IS_MATH_PATTERN = re.compile(r'^是否数学题[：:]\s*(.+)$')
IS_MISTAKE_PATTERN = re.compile(r'^是否错题[：:]\s*(.+)$')
CAN_SOLVE_PATTERN = re.compile(r'^是否能做出来[：:]\s*(.+)$')
STATUS_PLAIN_PATTERN = re.compile(r'^状态[：:]\s*(.+)$')
BLOCK_DIFFICULTY_PATTERN = re.compile(r'^块难度[：:]\s*(.+)$')
BLOCK_FINAL_ANSWER_PATTERN = re.compile(r'^块最终答案[：:]\s*(.+)$')
BLOCK_KP_PATTERN = re.compile(r'^块知识点[：:]\s*(.+)$')
STEP_DIFFICULTY_PATTERN = re.compile(r'^步骤难度[：:]\s*(.+)$')


# ---------- 读取 prompt ----------
def _read_prompt(name: str) -> str:
    with open(os.path.join(PROMPTS_DIR, f"{name}.md"), encoding="utf-8") as f:
        return f.read().strip()


TEACHER_CONFIG = {
    "liangliang": {
        "solver": {"model": "deepseek-v4-flash", "reasoning_effort": None},
        "verifier": {"model": "deepseek-v4-flash"},
        "formatter": {"model": "deepseek-v4-flash"},
    },
    "taotao": {
        "solver": {"model": "deepseek-v4-pro", "reasoning_effort": "low"},
        "verifier": {"model": "deepseek-v4-flash"},
        "formatter": {"model": "deepseek-v4-flash"},
    },
    "xuefeng": {
        "solver": {"model": "deepseek-v4-pro", "reasoning_effort": "high"},
        "verifier": {"model": "deepseek-v4-flash"},
        "formatter": {"model": "deepseek-v4-flash"},
    },
    "ji": {
        "solver": {"model": "deepseek-v4-pro", "reasoning_effort": "high"},
        "verifier": {"model": "deepseek-v4-pro", "reasoning_effort": "high"},
        "formatter": {"model": "deepseek-v4-pro", "reasoning_effort": "high"},
    },
}

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
def call_deepseek(system_prompt: str, user_prompt: str, temperature: float = 0.3, model: str = "deepseek-chat", reasoning_effort: str = None):
    api_key = get_api_key()
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": 32000,
    }
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort
        body["thinking"] = {"type": "enabled"}
    try:
        resp = httpx.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=300,
        )
        if resp.status_code != 200:
            raise Exception(f"状态码 {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
    except httpx.TimeoutException:
        raise Exception("API 请求超时（300s）")
    except httpx.ConnectError:
        raise Exception("无法连接到 API 服务器")
    except (httpx.HTTPError, KeyError, json.JSONDecodeError) as e:
        raise Exception(f"API 请求异常: {str(e)[:200]}")
    usage = data.get("usage", {})
    return content, usage


# ---------- 提取器 ----------
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


def _compute_overall_difficulty(chunk_results: list) -> dict:
    """从各块难度计算整体题目难度：每维取最大值，再求和（5维 0-3，总分 0-15）"""
    dim_keys = ["非常规程度", "计算量", "理解难度", "分类讨论", "知识点密度"]
    max_dims = {k: 0 for k in dim_keys}
    for cr in chunk_results:
        dims = cr.get("difficulty", {}).get("dimensions", {})
        if not isinstance(dims, dict):
            continue
        for k in dim_keys:
            val = dims.get(k, 0)
            if isinstance(val, (int, float)) and val > max_dims[k]:
                max_dims[k] = val
    total = sum(max_dims.values())
    if total <= 2:
        level = "容易"
    elif total <= 4:
        level = "中等"
    elif total <= 6:
        level = "困难"
    else:
        level = "极难"
    return {"level": level, "total_score": total, "dimensions": max_dims}


def _extract_solver_status(text: str) -> Optional[str]:
    """检查 Solver 输出中是否有不会做/错题的标记"""
    for line in text.split("\n"):
        stripped = line.strip()
        m = SOLVER_STATUS_PATTERN.match(stripped)
        if m:
            status = m.group(1).strip()
            if status in ("不会做", "错题"):
                return status
    return None


def _check_solver_viable(content: str) -> Optional[str]:
    """检查 Solver 输出是否可解。返回 None 表示可解，str 表示雪碧了的原因。"""
    def _strip_brackets(s: str) -> str:
        return s.strip().strip('[]')
    for line in content.split("\n"):
        stripped = line.strip()
        m = IS_MATH_PATTERN.match(stripped)
        if m and _strip_brackets(m.group(1)) == "否":
            return "不是数学题"
        m = IS_MISTAKE_PATTERN.match(stripped)
        if m and _strip_brackets(m.group(1)) == "是":
            return "题目本身有错"
        m = CAN_SOLVE_PATTERN.match(stripped)
        if m and _strip_brackets(m.group(1)) == "否":
            return "Solver 判定：不会做"
        m = STATUS_PLAIN_PATTERN.match(stripped)
        if m:
            s = _strip_brackets(m.group(1))
            if s == "不会做":
                return "Solver 判定：不会做"
            if s == "错题":
                return "Solver 判定：错题"
            if s == "非数学题":
                return "不是数学题"
        m = SOLVER_STATUS_PATTERN.match(stripped)
        if m:
            s = m.group(1).strip()
            if s in ("不会做", "错题"):
                return f"Solver 判定：{s}"
    return None


def _extract_category(text: str) -> Optional[str]:
    """从 Solver 输出中提取板块（精确匹配 Solver 写死的板块名）"""
    for line in text.split("\n"):
        stripped = line.strip()
        m = BLOCK_CATEGORY_PATTERN.match(stripped)
        if m:
            val = m.group(1).strip()
            # Solver 输出可能带括号如 [解析几何]，去掉外层括号
            val = val.strip('[]')
            if val in CATEGORIES:
                return val
    return None


def _parse_chunk_meta(text: str) -> dict:
    """从 Verifier 输出的块内容中提取块级元数据"""
    meta = {"chunk_type": None, "category": None,
            "difficulty": None, "final_answer": "", "knowledge_points": []}
    for line in text.split("\n"):
        stripped = line.strip()
        m = BLOCK_TYPE_PATTERN.match(stripped)
        if m:
            meta["chunk_type"] = m.group(1).strip()
            continue
        m = BLOCK_CATEGORY_PATTERN.match(stripped)
        if m:
            meta["category"] = m.group(1).strip()
            continue
        m = BLOCK_DIFFICULTY_PATTERN.match(stripped)
        if m:
            try:
                meta["difficulty"] = json.loads(m.group(1).strip())
            except (json.JSONDecodeError, ValueError):
                pass
            continue
        m = BLOCK_FINAL_ANSWER_PATTERN.match(stripped)
        if m:
            meta["final_answer"] = m.group(1).strip()
            continue
        m = BLOCK_KP_PATTERN.match(stripped)
        if m:
            kps = [kp.strip().strip("[]") for kp in m.group(1).split("、") if kp.strip()]
            meta["knowledge_points"] = kps
            continue
    return meta


def _parse_steps(text: str) -> list:
    """从 Verifier 输出中解析步骤（小块）"""
    steps = []
    current_step = None
    in_step = False
    for line in text.split("\n"):
        stripped = line.strip()
        m = STEP_HEADER_PATTERN.match(stripped)
        if m:
            if current_step is not None:
                steps.append(current_step)
            current_step = {
                "step_number": int(m.group(1)),
                "title": (m.group(2) or "").strip(),
                "standard_writing": "",
                "detailed_writing": "",
                "knowledge_point": "",
                "step_difficulty": None,
            }
            in_step = True
            continue
        if not in_step or current_step is None:
            continue
        km = KNOWLEDGE_POINT_PATTERN.match(stripped)
        if km:
            kp_raw = km.group(1).strip()
            # 去掉可能的外层方括号
            kp_raw = re.sub(r'^\[(.+)\]$', r'\1', kp_raw)
            current_step["knowledge_point"] = kp_raw
            continue
        bm = BRIEF_PATTERN.match(stripped)
        if bm:
            current_step["standard_writing"] = bm.group(1).strip()
            continue
        sm = STANDARD_PATTERN.match(stripped)
        if sm:
            current_step["standard_writing"] = sm.group(1).strip()
            continue
        dm2 = DETAIL_PATTERN.match(stripped)
        if dm2:
            current_step["detailed_writing"] = dm2.group(1).strip()
            continue
        dm = STEP_DIFFICULTY_PATTERN.match(stripped)
        if dm:
            try:
                current_step["step_difficulty"] = json.loads(dm.group(1).strip())
            except (json.JSONDecodeError, ValueError):
                current_step["step_difficulty"] = {"level": "未知", "score": 0}
            continue
        if current_step and current_step["detailed_writing"] and stripped:
            current_step["detailed_writing"] += "\n" + stripped
            continue
    if current_step is not None:
        steps.append(current_step)
    return steps


# ---------- 按 ### 块N 拆分 ----------
def _split_chunks(text: str) -> tuple:
    """按 ### 块N 分割文本，返回 (header, chunks)"""
    parts = CHUNK_PATTERN.split(text)
    if len(parts) < 3:
        return text.strip(), [{"id": 1, "content": text}]
    header = parts[0].strip()
    chunks = []
    for i in range(1, len(parts) - 1, 2):
        chunk_id = int(parts[i])
        content = parts[i + 1].strip()
        chunks.append({"id": chunk_id, "content": content})
    return header, chunks


# ---------- Verifier 路由 ----------
def _load_verifier_prompt(category: str) -> str:
    """加载对应板块的 Verifier prompt"""
    path = os.path.join(PROMPTS_DIR, "verifiers", f"{category}.md")
    if not os.path.exists(path):
        # 尝试从内容自动匹配第一个存在的板块
        for known in CATEGORIES:
            test_path = os.path.join(PROMPTS_DIR, "verifiers", f"{known}.md")
            if os.path.exists(test_path):
                with open(test_path, encoding="utf-8") as f:
                    return f.read().strip()
        raise FileNotFoundError(f"找不到板块对应的 verifier: {category}")
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


# ---------- 雪碧了 ----------
def _recalc_difficulty(diff: dict) -> dict:
    """确保 total_score 等于维度之和（5维 0-3，总分 0-15）"""
    if not diff or not isinstance(diff, dict):
        return {"level": "未知", "total_score": 0, "dimensions": {}}
    dims = diff.get("dimensions", {})
    if isinstance(dims, dict):
        total = sum(v for v in dims.values() if isinstance(v, (int, float)))
        diff["total_score"] = total
        if total <= 2:
            diff["level"] = "容易"
        elif total <= 4:
            diff["level"] = "中等"
        elif total <= 6:
            diff["level"] = "困难"
        else:
            diff["level"] = "极难"
    return diff


def _extract_verifier_status(text: str) -> Optional[str]:
    """提取 Verifier 输出第一行的状态标记"""
    first_line = text.strip().split("\n")[0].strip()
    m = SOLVER_STATUS_PATTERN.match(first_line)
    if m:
        return m.group(1).strip()
    return None


def _xuebile(status: str, detail: str = "") -> dict:
    return {
        "error": "雪碧了",
        "status": status,
        "detail": detail or f"Solver 标记为：{status}",
        "steps": [],
        "final_answer": f"无法解答（{status}）",
        "chunk_results": [],
    }


# ---------- Solver 步 ----------
def step_solver_only(question: str, question_type: str = None, teacher: str = None) -> dict:
    """Solver：解答 + 输出板块"""
    config = TEACHER_CONFIG.get(teacher or "liangliang", TEACHER_CONFIG["liangliang"])
    prompt = SOLVER_PROMPT
    if question_type:
        prompt += f"\n\n注意：已知本题为{question_type}。"
    solver_cfg = config["solver"]
    content, usage = call_deepseek(prompt, question, model=solver_cfg["model"], reasoning_effort=solver_cfg.get("reasoning_effort"))
    viable_reason = _check_solver_viable(content)
    if viable_reason:
        return _xuebile("不可解", viable_reason)
    cat = _extract_category(content)
    return {
        "content": content,
        "category": cat or question_type,
        # 向后兼容：前端 Step1 期望 chunks
        "chunks": [{"id": 1, "type": question_type or "整体", "content": content, "category": cat}],
        "token_usage": usage,
    }


# ---------- Verifier 步（一次调用，切全部）----------
def step_verify_all(content: str, question: str, category: str = None, question_type: str = None, teacher: str = None) -> dict:
    """一次 Verifier：将完整解答切成大块/小块 + 归类知识点 + 打分"""
    config = TEACHER_CONFIG.get(teacher or "liangliang", TEACHER_CONFIG["liangliang"])
    if question_type in ("选择题", "填空题"):
        verifier_cat = question_type
    else:
        verifier_cat = category
        if not verifier_cat:
            verifier_cat = _extract_category(content)
        if not verifier_cat:
            verifier_cat = "函数与导数"  # 最后兜底

    verifier_prompt = _load_verifier_prompt(verifier_cat)
    user_prompt = f"原题：{question}\n\n解答内容：\n{content}"
    v_model = config["verifier"]["model"]
    verified_out, v_usage = call_deepseek(verifier_prompt, user_prompt, temperature=0.3, model=v_model)

    # 解析 Verifier 输出（可能含多个 ### 块N）
    header, raw_chunks = _split_chunks(verified_out)

    # 非常规压轴题使用标准管线

    chunk_results = []
    for pc in raw_chunks:
        meta = _parse_chunk_meta(pc["content"])
        steps = _parse_steps(pc["content"])

        seen = set()
        unique_kps = []
        for kp in meta.get("knowledge_points", []):
            if kp not in seen:
                seen.add(kp)
                unique_kps.append(kp)

        chunk_results.append({
            "chunk_id": pc["id"],
            "chunk_type": meta.get("chunk_type") or category or "整体",
            "category": {"level1": meta.get("category") or category or "整体", "level2": None},
            "difficulty": _recalc_difficulty(meta.get("difficulty")),
            "steps": steps,
            "final_answer": meta.get("final_answer", ""),
            "knowledge_points": unique_kps,
        })
    overall_diff = _compute_overall_difficulty(chunk_results)
    return {"chunk_results": chunk_results, "token_usage": v_usage, "overall_difficulty": overall_diff}


# ---------- 向后兼容：Step2 API ----------
def step_verify_chunk(chunk: dict, question: str, solved: list) -> dict:
    """保留给前端 Step2 API 调用，走新的单次 Verifier"""
    cat = chunk.get("category")
    result = step_verify_all(chunk["content"], question, cat)
    cr = result["chunk_results"]
    return {"result": cr[0] if cr else {}, "token_usage": result["token_usage"]}


# ---------- Formatter：全局校验 ----------
def _aggregate_from_chunks(question: str, chunk_results: list, token_total: dict) -> dict:
    """聚合 Verifier 输出为最终 JSON（当 Formatter 失败时的兜底）"""
    kps = set()
    answers = []
    step_sum = 0
    for cr in chunk_results:
        for kp in cr.get("knowledge_points", []):
            kps.add(kp)
        if cr.get("final_answer"):
            answers.append(cr["final_answer"])
        for step in cr.get("steps", []):
            sd = step.get("step_difficulty", {})
            step_sum += sd.get("score", 0) if isinstance(sd, dict) else 0
    overall = _compute_overall_difficulty(chunk_results)
    return {
        "status": "可解",
        "chunk_results": chunk_results,
        "final_answer": " | ".join(answers) if len(answers) > 1 else (answers[0] if answers else ""),
        "knowledge_points": list(kps),
        "step_difficulty_sum": step_sum,
        "overall_difficulty": overall,
        "token_usage": {k: token_total.get(k, 0) for k in token_total},
    }


def step_final_check(question: str, chunk_results: list, chunks_raw: list, token_total: dict, teacher: str = None) -> dict:
    """全局校验 + 聚合（如果 Formatter 输出雪碧了，兜底用 Verifier 的结果）"""
    config = TEACHER_CONFIG.get(teacher or "liangliang", TEACHER_CONFIG["liangliang"])
    f_cfg = config["formatter"]
    input_data = {
        "question": question,
        "chunk_results": chunk_results,
    }
    formatted, usage = call_deepseek(
        FORMATTER_PROMPT,
        json.dumps(input_data, ensure_ascii=False, indent=2),
        temperature=0.2, model=f_cfg["model"], reasoning_effort=f_cfg.get("reasoning_effort")
    )
    for k in token_total:
        token_total[k] += usage.get(k, 0)
    try:
        result = json.loads(_extract_json(formatted))
        if "error" in result:
            return _aggregate_from_chunks(question, chunk_results, token_total)
        # 计算武亮难度系数（步骤难度之和）
        step_sum = 0
        for cr in chunk_results:
            for step in cr.get("steps", []):
                sd = step.get("step_difficulty", {})
                step_sum += sd.get("score", 0) if isinstance(sd, dict) else 0
        result["step_difficulty_sum"] = step_sum
        result["overall_difficulty"] = _compute_overall_difficulty(chunk_results)
        result["token_usage"] = {k: token_total.get(k, 0) for k in token_total}
        return result
    except (json.JSONDecodeError, ValueError):
        return _aggregate_from_chunks(question, chunk_results, token_total)