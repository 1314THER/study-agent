# 测试

项目测试覆盖：

- 全部 FastAPI API 路由（解题、题目、题单、教学、批改、agent、套路、
  闯关地图、规划、设置、仿题、语义搜索、多模态/OCR 等）。
- `backend/agent.py`、`backend/agent_tools.py` 的全部函数。
- `backend/database.py` 的全部函数（临时 SQLite 隔离）。
- `backend/solver.py`、`backend/grade.py`、`backend/teach.py`、
  `backend/planner.py`、`backend/settings.py`、`backend/patterns.py`、
  `backend/categories.py`、`backend/difficulty.py`、`backend/steps.py`、
  `backend/multimodal.py`、`backend/generate.py`、`backend/repair_questions.py`、
  `backend/rescore_questions.py` 的纯函数与关键流程，包括套路状态机、
  错题匹配、巩固日历、AI 仿题异步任务、PDF/图片/Word/文本切题和手写 OCR。

测试会 mock 掉 DeepSeek 调用；涉及数据库的用例使用临时 SQLite，
不会污染 `study_agent.db`、`mastery.db`、`settings.json` 或 `patterns.yaml`。

## 运行

无需安装额外依赖，直接使用 Python 标准库 unittest：

```bash
python3 -m unittest discover -s tests -v
```

如果安装了 pytest，也可以用：

```bash
python3 -m pytest tests -v
```

## 前端端到端冒烟（可选）

需要后端已启动，且本机可用 Playwright/Chrome：

```bash
BASE_URL=http://127.0.0.1:8000 node tests/e2e/agent_flow.mjs
```

它会真实打开首页、发送“拿3道题练练”、等待流式回复和题目卡片渲染，
并检查页面是否出现 JS 报错。
