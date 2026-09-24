# 参与开发

欢迎一起完善高中数学学习助手。先按 [README.md](README.md) 的快速开始步骤运行项目，浏览已有题库、闯关和学习记录，再选择一个明确的问题或功能改进。

## 本地开发

1. 从 `main` 创建自己的分支，在分支上修改代码和文档。
2. macOS 运行 `./start.sh`，Windows 运行 `start.bat`。首次启动会在本地复制演示数据；本地数据库不会提交。
3. API 密钥填在网页设置页或自己的 `.env` 中。请勿提交 `.env`、`backend/settings.json`、日志或个人数据库。
4. 提交前运行 `python -m unittest discover -s tests -q`（使用 `.venv` 内的 Python），并检查 `git diff --check`。
5. 提交 Pull Request，说明改动目的、手动验证步骤，以及界面改动的截图。

## 项目位置

- `backend/`：FastAPI 接口、解题和学习流程、SQLite 数据层。
- `frontend/`：静态 HTML、CSS、JavaScript 页面。
- `demo-data/`：供新成员首次启动使用的完整快照。不要直接修改这里的数据库；如需更新演示数据，先核对内容与密钥，再用 SQLite 备份生成一致的快照。
- `tests/`：后端测试和可选的浏览器冒烟脚本。

题目内容、答案和学习记录目前随演示快照一起共享。新增数据前请确认有权公开，并避免把真实 API 密钥写入题目或日志。
