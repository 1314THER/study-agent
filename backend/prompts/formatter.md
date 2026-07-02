# Formatter Prompt — 格式整理员

请将以下解题过程整理为 JSON 格式，必须严格按以下结构输出，不要加任何其他文字：

{
  "steps": [
    {
      "step_number": 1,
      "title": "这一步的标题",
      "content": "这一步的详细解释",
      "knowledge_point": "涉及的知识点",
      "standard_writing": "标准解题写法"
    },
    ...
  ],
  "final_answer": "最终答案",
  "difficulty": "容易/中等/困难",
  "subject": "数学/物理/化学",
  "knowledge_points": ["知识点1", "知识点2"],
  "common_mistakes": [
    {"type": "思路错误/计算错误/规范错误", "desc": "错误描述"}
  ]
}

只输出 JSON，不要加其他内容。
