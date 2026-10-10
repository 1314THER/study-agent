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

另有游客工作区隔离、临时会话网关、后台任务及上传文件路径/大小保护测试，以及 `tests/e2e/agent_flow.mjs` 前端端到端冒烟。

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

后台任务、原题池与游客引导有七份不需要服务器、浏览器或 API 密钥的 Node 回归测试：

```bash
node tests/frontend_jobs.test.mjs
node tests/frontend_multimodal.test.mjs
node tests/frontend_job_pages.test.mjs
node tests/frontend_teach.test.mjs
node tests/frontend_loop.test.mjs
node tests/frontend_demo_tour.test.mjs
node tests/frontend_question_pool.test.mjs
```

它们使用内存任务账本与 DOM 模拟，检查文件摘要计算和整批上传期间的导航保护、上传失败留页、多文件结果刷新恢复与去重、部分失败、OCR 返回原批改草稿、新教学任务优先于旧浏览器会话恢复，套路批改离页后的进度恢复与去重，以及 demo 首页自动教程、跨页进度、逐步跳过、完成跳转与三道预设真题加载。多模态测试同时核对已有草稿/任务保留、最新任务的进度与结果恢复、部分失败和示例来源标记。不会调用真实 AI。

原题池测试另外覆盖主人访问保护、数据库分页与跨页选择恢复、仅为选中题生成解析、安全文字和公式渲染、未保存编辑保护、原文件回看与导入重试、发布范围设置、答案冲突与未验证答案的逐题确认、角色冲突拦截、入库请求重试去重，以及过期分页响应不覆盖当前结果。

需要后端已启动，且本机可用 Playwright/Chrome：

```bash
BASE_URL=http://127.0.0.1:8000 node tests/e2e/agent_flow.mjs
```

它会真实打开首页、发送“拿3道题练练”、等待流式回复和题目卡片渲染，
并检查页面是否出现 JS 报错。

## 部署脚本与双站验收

本机可先检查 Bash 语法；这一步不连接服务器：

```bash
bash -n deploy/sync-sites.sh deploy/rollback-sites.sh deploy/install-demo.sh
```

同步脚本的 systemd、权限、Git 快进、虚拟环境切换与回滚需要在 Ubuntu 上验收，Bash 语法通过不能证明这些操作已在服务器完成。按 [部署说明](../deploy/ubuntu.md#第四步验收) 检查两个本机端口、公开 HTTPS、主人密码保护和两个游客浏览器的数据隔离；部署日志应记录固定提交 SHA 与备份目录。内部任务状态/暂停接口只接受回环请求，健康检查与内部检查不应计入活跃任务。
