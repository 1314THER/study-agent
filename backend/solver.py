"""
做题系统：三段式AI处理

流程：
  1. Solver  — AI 先完整做题，生成解题思路、步骤和答案
  2. Verifier — AI 二次检查答案、步骤、逻辑和常见错误
  3. Formatter — 整理为前端可用的结构化 JSON
"""

import os
import json
import httpx
from typing import Dict, Any

# ---------- 读取 API Key ----------

def get_api_key() -> str:
    """从 .env 文件读取 DeepSeek API Key"""
    # 先去环境变量找
    key = os.environ.get("DEEPSEEK_API_KEY")
    if key:
        return key
    # 再试 .env 文件
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
    """调用 DeepSeek API，返回 AI 回复文本"""
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
            "temperature": 0.3,       # 低温度，让输出更稳定
            "max_tokens": 4096
        },
        timeout=60
    )

    if response.status_code != 200:
        raise Exception(f"API 请求失败: {response.status_code} {response.text}")

    result = response.json()
    return result["choices"][0]["message"]["content"]

# ---------- 三段式 Prompt ----------

SOLVER_PROMPT = """你是一个高中数理化解题老师。请仔细解答以下题目。

要求：
1. 先审题，分析题目考什么知识点
2. 分步骤写出完整解题过程
3. 步骤要清晰，每一步都要写标准写法
4. 最后给出最终答案

用中文回复。"""

VERIFIER_PROMPT = """你是一个严格的高中数理化阅卷老师。请检查以下解题过程：

检查要点：
1. 答案是否正确
2. 每一步的逻辑是否严密
3. 有没有步骤跳跃
4. 有没有常见错误（思路错误、计算错误、规范错误）

如果有问题，请修正。如果正确，请保持原样。
最后输出修正后的完整解题过程。"""

FORMATTER_PROMPT = """请将以下解题过程整理为 JSON 格式，必须严格按以下结构输出，不要加任何其他文字：

{{
  "steps": [
    {{
      "step_number": 1,
      "title": "这一步的标题",
      "content": "这一步的详细解释",
      "knowledge_point": "涉及的知识点",
      "standard_writing": "标准解题写法"
    }},
    ...
  ],
  "final_answer": "最终答案",
  "difficulty": "容易/中等/困难",
  "subject": "数学/物理/化学",
  "knowledge_points": ["知识点1", "知识点2"],
  "common_mistakes": [
    {{"type": "思路错误/计算错误/规范错误", "desc": "错误描述"}}
  ]
}}

只输出 JSON，不要加其他内容。"""

# ---------- 三段式解题 ----------

def solve(question: str) -> Dict[str, Any]:
    """
    三段式解题流程：
    1. Solver — AI 完整做题
    2. Verifier — AI 校验修正
    3. Formatter — 整理为结构化 JSON
    """
    print(f"[Solver] 正在解题：{question[:50]}...")

    # 第1步：Solver — 解题
    solver_result = call_deepseek(SOLVER_PROMPT, question)
    print(f"[Solver] 完成，长度：{len(solver_result)} 字")

    # 第2步：Verifier — 校验
    verified = call_deepseek(VERIFIER_PROMPT, solver_result)
    print(f"[Verifier] 校验完成")

    # 第3步：Formatter — 格式化为 JSON
    formatted = call_deepseek(FORMATTER_PROMPT, verified)
    print(f"[Formatter] 格式化完成")

    # 清理 JSON（防止 AI 输出多余的 ```json ``` 包围）
    formatted = formatted.strip()
    if formatted.startswith("```"):
        formatted = formatted.split("\n", 1)[1]
    if formatted.endswith("```"):
        formatted = formatted.rsplit("```", 1)[0]
    formatted = formatted.strip()

    try:
        result = json.loads(formatted)
        return result
    except json.JSONDecodeError as e:
        print(f"[Error] JSON 解析失败：{e}")
        print(f"[Error] 原始输出：{formatted[:200]}")
        # 兜底返回
        return {
            "steps": [
                {"step_number": 1, "title": "解答", "content": solver_result}
            ],
            "final_answer": "解析失败，请重试",
            "difficulty": "未知",
            "subject": "未知",
            "knowledge_points": [],
            "common_mistakes": []
        }

# ---------- 直接测试 ----------

if __name__ == "__main__":
    result = solve("已知函数f(x)=x²+ax+1在[1,3]上单调递增，求a的取值范围")
    print(json.dumps(result, ensure_ascii=False, indent=2))
