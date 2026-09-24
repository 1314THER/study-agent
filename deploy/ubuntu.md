# Ubuntu 26.04 / 阿里云 ECS 部署

当前项目是单用户 FastAPI + SQLite 应用。服务器使用一个进程运行后端；前端由后端直接提供。对外通过 Caddy 提供 HTTPS 和整站密码保护。后端只监听 `127.0.0.1:8000`。

## 1. 先完成服务器本机部署

在 Workbench 的 root 终端逐行运行：

```bash
apt update
apt install -y git python3 python3-venv python3-pip curl
useradd --system --home /opt/study-agent --shell /usr/sbin/nologin studyagent
git clone https://github.com/1314THER/study-agent.git /opt/study-agent
chown -R studyagent:studyagent /opt/study-agent
cd /opt/study-agent
runuser -u studyagent -- python3 scripts/run.py --prepare-only
runuser -u studyagent -- python3 scripts/run.py --smoke
```

`--prepare-only` 会安装 Python 依赖，并从 `demo-data/` 复制两个演示数据库到项目根目录；之后不会覆盖数据库。`--smoke` 会启动服务、检查接口，然后退出。首次运行依赖于服务器访问 GitHub 和 PyPI。Ubuntu 26.04 默认 Python 3.14，本项目的 CI 目前只验证了 Python 3.11。如果依赖安装或冒烟检查失败，先记录完整报错，不要反复安装到系统 Python。

安装自启动服务：

```bash
cp deploy/study-agent.service /etc/systemd/system/study-agent.service
systemctl daemon-reload
systemctl enable --now study-agent
systemctl status study-agent --no-pager
curl -I http://127.0.0.1:8000/home.html
```

`curl` 应返回 `HTTP/1.1 200 OK`。失败时查看 `journalctl -u study-agent -n 100 --no-pager`。

## 2. 等备案完成后接入域名

这台 ECS 位于上海。需要确认你说的“审核”是哪一种：域名实名认证和 ICP 备案是两件事。中国内地 ECS 对外提供网站服务，需要 ICP 备案通过；在此之前先不要开放网站。备案通过后，将根域名 `@` 的 A 记录指向 ECS **公网** IP `47.117.107.156`；截图中的 `172.22.145.103` 是私网 IP。

在阿里云 ECS 安全组入方向允许 TCP 80、443。不要开放 8000；22 端口尽量限制为自己的 IP。若启用了 UFW，也需放行 80、443。

安装 Ubuntu 自带的 Caddy 2.6：

```bash
apt install -y caddy
caddy hash-password
```

第二条命令会在终端中隐藏输入密码，并打印哈希。将 `deploy/Caddyfile.example` 复制到 `/etc/caddy/Caddyfile`，把占位符替换为生成的哈希：

```bash
cp /opt/study-agent/deploy/Caddyfile.example /etc/caddy/Caddyfile
nano /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile
systemctl reload caddy
```

现在打开 `https://150.chat/home.html`，浏览器应先要求输入 `studyadmin` 和你刚才设置的密码。Caddy 在域名正确解析、80/443 可达时自动申请并续期 HTTPS 证书。确认后再在网站设置页填写自己的 API 密钥；不要将 `.env` 或 `backend/settings.json` 提交到 Git。

## 3. 更新与备份

更新前备份 `study_agent.db`、`mastery.db`、`backend/patterns.yaml`、`backend/settings.json` 和 `.env`。其中 `backend/patterns.yaml` 既是 Git 跟踪文件又会在运行时修改，所以更新时可能与上游冲突；不要用 `git reset --hard` 覆盖它。代码拉取后执行 `runuser -u studyagent -- python3 scripts/run.py --prepare-only`，再 `systemctl restart study-agent`。

常用排查：

```bash
journalctl -u study-agent -n 100 --no-pager
journalctl -u caddy -n 100 --no-pager
curl -I http://127.0.0.1:8000/home.html
```
