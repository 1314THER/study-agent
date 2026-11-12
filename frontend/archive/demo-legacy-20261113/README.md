# 旧版 demo 快照

此目录保存 2026-11-13 时 `demo.150.chat` 的只读站点文件和其最小 FastAPI 静态服务代码。快照依据 `backend/showcase.py` 的明确公开资源白名单制作，包含页面、原有公开 JSON、字体、图形库和题库白名单文件；不包含正式站数据库、账号、环境变量或密钥。

- 原公开入口：`https://demo.150.chat/home.html`
- 源提交：见 `snapshot-manifest.json`
- 文件摘要：见 `snapshot-manifest.json`
- 预期用途：作为可独立搬迁/回滚的旧站源码快照；确认目标子域名后可配独立服务。

`backend/showcase.py` 以同目录下的 `frontend/` 为站点根目录。该快照不改变现有 `demo.150.chat` 或 `math.150.chat`。
