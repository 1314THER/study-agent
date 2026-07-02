"""
做题系统：三段式AI处理
提示词从 prompts/ 目录读取。
"""

import os
import json
import httpx
import re
from typing import Dict, Any
from backend.database import find_question, save_question

# ---------- 状态检测 ----------
STATUS_PATTERN = re.compile(r'^\[(?:状态|确认|修正)：(.+?)\]')

def _extract_status(text: str) -> str:
    """从 LLM 输出的第一行检测状态：可解 / 不会做 / 错题"""
    first_line = text.strip().split('\n')[0].strip()
    m = STATUS_PATTERN.match(first_line)
    if m:
        status = m.group(1).strip()
        if status in ("可解", "不会做", "错题"):
            return status
    return "可解"

# ---------- 读取提示词 ----------
PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")
def _read_prompt(name: str) -> str:
    with open(os.path.join(PROMPTS_DIR, f"{name}.md"), encoding="utf-8") as f:
        return f.read().strip()

SOLVER_PROMPT = _read_prompt("solver")
VERIFIER_PROMPT = _read_prompt("verifier")
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
def call_deepseek(system_prompt: str, user_prompt: str):
    """返回 (content, token_usage)"""
    api_key = get_api_key()
    resp = httpx.post(
        "https://api.deepseek.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 32000
        },
        timeout=180
    )
    if resp.status_code != 200:
        raise Exception(f"API 请求失败: {resp.status_code} {resp.text}")
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    return content, usage

# ---------- 三步独立函数 ----------

def step_solver(question: str) -> dict:
    """第1步：Solver 解题，返回 text + tokens"""
    content, usage = call_deepseek(SOLVER_PROMPT, question)
    status = _extract_status(content)
    return {"content": content, "token_usage": usage, "status": status}

def step_verifier(content: str) -> dict:
    """第2步：Verifier 校验，返回 text + tokens"""
    verified, usage = call_deepseek(VERIFIER_PROMPT, content)
    status = _extract_status(verified)
    return {"content": verified, "token_usage": usage, "status": status}


def _extract_json(text: str) -> str:
    """从 LLM 输出中提取 JSON 字符串（去掉 markdown 代码块标记和其他杂音）"""
    text = text.strip()

    # 如果被 ```json ... ``` 包裹，提取中间内容
    m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if m:
        text = m.group(1).strip()

    # 去掉开头的非 JSON 前缀（直到第一个 { 或 [）
    first_brace = text.find('{')
    first_bracket = text.find('[')
    if first_brace >= 0:
        if first_bracket >= 0 and first_bracket < first_brace:
            text = text[first_bracket:]
        else:
            text = text[first_brace:]
    elif first_bracket >= 0:
        text = text[first_bracket:]

    # 去掉末尾的非 JSON 后缀（从最后一个 } 或 ] 之后截断）
    last_brace = text.rfind('}')
    last_bracket = text.rfind(']')
    if last_brace >= 0:
        if last_bracket >= 0 and last_bracket > last_brace:
            text = text[:last_bracket + 1]
        else:
            text = text[:last_brace + 1]
    elif last_bracket >= 0:
        text = text[:last_bracket + 1]

    return text.strip()


def _build_fallback(verifier_content: str) -> dict:
    """解析验证器输出，构造一个兜底的 result dict"""
    steps = []
    lines = verifier_content.split('\n')
    current_step = None
    current_title = ""
    current_writing = ""
    current_detail = ""
    current_kp = ""

    def flush_step():
        nonlocal current_step, current_title, current_writing, current_detail, current_kp
        if current_step is not None:
            steps.append({
                "step_number": current_step,
                "title": current_title.strip(),
                "standard_writing": current_writing.strip(),
                "detail": current_detail.strip(),
                "knowledge_point": current_kp.strip()
            })

    step_pattern = re.compile(r'步骤(\d+)\s*[：:]\s*(.*)')

    for line in lines:
        # 检测步骤标题行
        m = step_pattern.match(line.strip())
        if m:
            flush_step()
            current_step = int(m.group(1))
            current_title = m.group(2)
            current_writing = ""
            current_detail = ""
            current_kp = ""
            continue

        stripped = line.strip()
        # 检测得分点 / 计算过程 / 知识点
        if stripped.startswith('得分点') and (':' in stripped or '：' in stripped):
            current_writing += stripped.split('：', 1)[-1].split(':', 1)[-1] + '\n'
        elif stripped.startswith('计算过程') and (':' in stripped or '：' in stripped):
            current_detail += stripped.split('：', 1)[-1].split(':', 1)[-1] + '\n'
        elif stripped.startswith('知识点') and (':' in stripped or '：' in stripped):
            current_kp += stripped.split('：', 1)[-1].split(':', 1)[-1] + '\n'
        elif stripped.startswith('最终答案') and (':' in stripped or '：' in stripped):
            final_answer = stripped.split('：', 1)[-1].split(':', 1)[-1].strip()
        elif current_step is not None:
            # 当前步骤的非标记行——归入计算过程
            current_detail += line + '\n'

    flush_step()

    return {
        "steps": steps if steps else [
            {"step_number": 1, "title": "解答", "standard_writing": verifier_content[:500], "detail": "", "knowledge_point": ""}
        ],
        "final_answer": final_answer if 'final_answer' in dir() else "",
        "difficulty": {"level": "未知", "total_score": 0, "dimensions": {}},
        "category": {"level1": None, "level2": None},
        "knowledge_points": [],
        "common_mistakes": []
    }


def step_formatter(content: str, original_question: str = None) -> dict:
    """第3步：Formatter 格式化 + 存库，返回 result + tokens"""
    # 检查 verifier 是否确认了 不会做/错题
    status = _extract_status(content)
    if status in ("不会做", "错题"):
        lines = content.strip().split('\n', 1)
        reason = lines[1].strip() if len(lines) > 1 else ""
        # 去掉可能的第一行标记（如 [确认：不会做]）
        if reason.startswith('['):
            reason = ''
        result = {
            "status": status,
            "reason": reason,
            "steps": [],
            "final_answer": "无法解答" if status == "不会做" else "错题",
            "difficulty": {"level": "未知", "total_score": 0, "dimensions": {}},
            "category": {"level1": None, "level2": None},
            "knowledge_points": [],
            "common_mistakes": []
        }
        return {"result": result, "token_usage": {}}

    # 把原题传给 formatter，帮助它理解上下文
    user_msg = content
    if original_question:
        user_msg = f"原题：{original_question}\n\n解题过程：\n{content}"

    formatted, usage = call_deepseek(FORMATTER_PROMPT, user_msg)

    # 提取 JSON
    cleaned = _extract_json(formatted)

    try:
        result = json.loads(cleaned)
        # 验证关键字段
        if 'steps' not in result or not isinstance(result['steps'], list) or len(result['steps']) == 0:
            raise ValueError("JSON 缺少有效 steps")
    except (json.JSONDecodeError, ValueError) as e:
        print(f"[Error] 首次 JSON 解析失败：{e}")
        print(f"[Debug] 原始输出：{formatted[:300]}")

        # 自动重试一次，带更明确的指令
        retry_prompt = (
            f"原题：{original_question}\n\n"
            f"解题过程：\n{content}\n\n"
            "注意：请只输出一个合法的 JSON 对象，不要包含任何其他文字、注释、或 markdown 标记。"
            "JSON 必须包含 steps 数组（每个 step 包含 step_number, title, standard_writing, detail, knowledge_point）、"
            "final_answer、category、knowledge_points、difficulty、common_mistakes 字段。"
        )
        formatted2, _ = call_deepseek(FORMATTER_PROMPT, retry_prompt)
        cleaned2 = _extract_json(formatted2)
        try:
            result = json.loads(cleaned2)
            if 'steps' not in result or not isinstance(result['steps'], list) or len(result['steps']) == 0:
                raise ValueError("重试后 JSON 仍缺少有效 steps")
            print("[Recovery] 重试成功")
        except (json.JSONDecodeError, ValueError) as e2:
            print(f"[Error] 重试仍失败：{e2}")
            result = _build_fallback(content)

    # 存库
    if original_question:
        result["token_usage"] = usage
        save_question(original_question, result)

    return {"result": result, "token_usage": usage}

# ---------- 聚合函数（兼容旧接口）----------

def solve(question: str) -> Dict[str, Any]:
    """完整三步解题，返回最终 result 带累计 token"""
    cached = find_question(question)
    if cached:
        return cached

    token_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    def _add(u):
        for k in token_total:
            token_total[k] += u.get(k, 0)

    r1 = step_solver(question)
    _add(r1["token_usage"])

    r2 = step_verifier(r1["content"])
    _add(r2["token_usage"])

    r3 = step_formatter(r2["content"], question)
    _add(r3["token_usage"])

    result = r3["result"]
    result["token_usage"] = token_total
    return result


if __name__ == "__main__":
    from backend.database import init_db
    init_db()
    r = solve("已知椭圆x²/4+y²/3=1，求右焦点坐标")
    print(json.dumps(r, ensure_ascii=False, indent=2)[:500])
