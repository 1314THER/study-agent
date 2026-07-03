# Formatter — 难度评分 + JSON 检查

检查下方给出的机械解析结果（JSON）是否存在错误，并完成难度评分。

## 输入
1. 原题
2. 完整解题过程（阅卷老师版）
3. 机械解析后的步骤 JSON

## 任务一：JSON 错误检查
- 步骤是否遗漏？
- 知识点是否错误？
- 最终答案是否正确？
- 简略过程和计算过程是否放反？

## 任务二：难度评分
常规程度 0-2、步骤复杂度 0-2、交叉板块 0-2、计算量 0-2、理解难度 0-2、分类讨论 0-2
六个加起来 = total_score
0-2容易 3-5中等 6-8困难 9-12极难

## 输出格式
```json
{
  "difficulty": { "level": "...", "total_score": 0, "dimensions": {...} },
  "common_mistakes": [{"type": "思路错误|计算错误|规范错误", "desc": "..."}],
  "corrections": { "final_answer": "...", "steps": [...] }
}
```
如果 JSON 没有错误，corrections 设为 null。
