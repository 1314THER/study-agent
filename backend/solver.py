"""
做题系统：三段式AI处理
提示词从 prompts/ 目录下的 .md 文件读取，方便自定义。
"""

import os
import json
import httpx
from typing import Dict, Any
from backend.database import find_question, save_question

# ---------- 读取 .md 提示词文件 ----------

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")

def _read_prompt(name: str) -> str:
    """从 prompts/ 目录读取对应的 .md 文件"""
    path = os.path.join(PROMPTS_DIR, f"{name}.md")
    with open(path, encoding="utf-8") as f:
        return f.read().strip()

SOLVER_PROMPT = _read_prompt("solver")
VERIFIER_PROMPT = _read_prompt("verifier")
FORMATTER_PROMPT = _read_prompt("formatter")
print(f"[Skills] Solver: {len(SOLVER_PROMPT)}字 | Verifier: {len(VERIFIER_PROMPT)}字 | Formatter: {len(FORMATTER_PROMPT)}字")

# ---------- 读取 API Key ----------

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
    raise ValueError("未找到 DEEPSEEK_API_KEY，请在 .env 文件中设置")

# ---------- 调用 DeepSeek API ----------

def call_deepseek(system_prompt: str, user_prompt: str) -> str:
    api_key = get_api_key()
    response = httpx.post(
        "https://api.deepseek.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        json={
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 4096
        },
        timeout=60
    )
    if response.status_code != 200:
        raise Exception(f"API 请求失败: {response.status_code} {response.text}")
    return response.json()["choices"][0]["message"]["content"]

# ---------- 三段式解题 ----------

def solve(question: str) -> Dict[str, Any]:
    cached = find_question(question)
    if cached:
        return cached

    print(f"[Solver] 新题目：{question[:50]}...")

    solver_result = call_deepseek(SOLVER_PROMPT, question)
    print(f"[Solver] 完成，{len(solver_result)} 字")

    verified = call_deepseek(VERIFIER_PROMPT, solver_result)
    print(f"[Verifier] 校验完成")

    formatted = call_deepseek(FORMATTER_PROMPT, verified)
    print(f"[Formatter] 格式化完成")

    formatted = formatted.strip()
    if formatted.startswith("```"):
        formatted = formatted.split("\n", 1)[1]
    if formatted.endswith("```"):
        formatted = formatted.rsplit("```", 1)[0]
    formatted = formatted.strip()

    try:
        result = json.loads(formatted)
        save_question(question, result)
        return result
    except json.JSONDecodeError as e:
        print(f"[Error] JSON 解析失败：{e}")
        return {
            "steps": [{"step_number": 1, "title": "解答", "content": solver_result}],
            "final_answer": "解析失败，请重试",
            "difficulty": "未知",
            "subject": "未知",
            "knowledge_points": [],
            "common_mistakes": []
        }


if __name__ == "__main__":
    from backend.database import init_db
    init_db()
    result = solve("已知函数f(x)=x²+ax+1在[1,3]上单调递增，求a的取值范围")
    print(json.dumps(result, ensure_ascii=False, indent=2))
