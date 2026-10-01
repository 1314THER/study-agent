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

若服务器下载官方 PyPI 超时，可以仅对本次准备命令使用清华镜像：

```bash
runuser -u studyagent -- env PIP_INDEX_URL=https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=10 python3 scripts/run.py --prepare-only
```

安装自启动服务：

```bash
cp deploy/study-agent.service /etc/systemd/system/study-agent.service
systemctl daemon-reload
systemctl enable --now study-agent
systemctl status study-agent --no-pager
curl -I http://127.0.0.1:8000/home.html
```

`curl` 应返回 `HTTP/1.1 200 OK`。失败时查看 `journalctl -u study-agent -n 100 --no-pager`。

### 通过 SSH 邀请朋友预览

桌面上的 `学习助手·服务器.command` 供主人从 Mac 建立 SSH 转发。朋友可以使用 `deploy/share-preview/` 中相应系统的连接文件；每台电脑首次运行会生成独立公钥，主人需要在服务器上逐一授权。连接后的 `127.0.0.1:18000` 是**朋友各自电脑**上的本地地址，所有人访问同一台服务器和同一份题库。共享题库允许朋友查看与修改内容，请只授权信任的人。

服务器上以 root 身份运行 `bash /opt/study-agent/deploy/authorize-preview-key.sh`，按提示粘贴朋友发来的单行 `ssh-ed25519` 公钥。此脚本将该公钥限定为只可通过 SSH 转发到应用的 `127.0.0.1:8000`，不允许普通 shell 命令。不要收取、复制或共享朋友的私钥。若要撤销一位朋友的权限，从 `/home/studyviewer/.ssh/authorized_keys` 删除包含其公钥的那一整行；已经建立的连接需要断开后才会受影响。

## 2. 备案成功后接入 `150.chat`

备案号为 `渝ICP备2026024246号-1`。域名 DNS 尚需设置：在阿里云云解析 DNS 给根域名添加 **A 记录**，主机记录填 `@`，记录值填 ECS **公网** IP `47.117.107.156`。截图中的 `172.22.145.103` 是私网 IP，不能用于公网解析。没有 IPv6 服务器时不要配置 AAAA 记录。在 Mac 或服务器运行 `dig +short A 150.chat`，确认结果为 `47.117.107.156` 后继续。

完成 Caddy 配置后，在阿里云 ECS 安全组入方向允许公网 TCP **80、443**。不要开放应用的 8000 端口；22 端口仅供 SSH。若已启用 UFW，另运行 `ufw allow 80/tcp` 和 `ufw allow 443/tcp`，不要为此临时启用 UFW。

仓库中的 [公开入口页](public/index.html)在 `/` 展示备案号及工信部查询链接；点击「进入学习助手」后，应用页面及 API 才要求整站密码。先从 Mac 推送包含这两个部署文件的提交。然后在 Workbench 的 root 终端运行以下命令；`git fetch` 不会覆盖服务器上已迁移的题库和配置：

```bash
systemctl is-active study-agent
curl -I http://127.0.0.1:8000/home.html
apt update
apt install -y caddy
runuser -u studyagent -- git -C /opt/study-agent fetch origin main
install -d -m 755 /var/www/study-agent-public
runuser -u studyagent -- git -C /opt/study-agent show origin/main:deploy/public/index.html > /var/www/study-agent-public/index.html
runuser -u studyagent -- git -C /opt/study-agent show origin/main:deploy/Caddyfile.example > /etc/caddy/Caddyfile
chmod 644 /var/www/study-agent-public/index.html /etc/caddy/Caddyfile
caddy hash-password
```

`caddy hash-password` 会提示输入你自选的访问密码，并输出哈希。运行 `nano /etc/caddy/Caddyfile`，将 `REPLACE_WITH_CADDY_HASH_PASSWORD_OUTPUT` 替换为整段哈希，保存退出。密码不要发到聊天或提交到 Git。先在阿里云安全组放行 80/443，再运行：

```bash
caddy validate --config /etc/caddy/Caddyfile
systemctl enable caddy
systemctl restart caddy
systemctl status caddy --no-pager -l
```

最后在 **Mac 终端**（从公网）运行：

```bash
curl -I https://150.chat/
curl -I https://150.chat/home.html
```

根路径应返回 `200`，并在页面底部显示备案号；`/home.html` 未输入密码时应返回 `401`。浏览器打开 `https://150.chat/`，点击「进入学习助手」，输入用户名 `studyadmin` 和刚才设置的密码。Caddy 会在域名解析正确、80/443 可达时自动申请并续期 HTTPS 证书。若证书申请或访问失败，查看 `journalctl -u caddy -n 100 --no-pager`，先核对 DNS、安全组和端口占用。

网站开通后还需按所在地要求办理公安联网备案，并在取得公安备案号后展示。不要将 `.env`、`backend/settings.json` 或数据库提交到 Git。

## 3. 更新与备份

### 从 Mac 迁移当前数据

在 Mac 上用 SQLite 备份 API 制作两个数据库快照，再将它们与 `patterns.yaml`、`settings.json`、`.env` 打包为恰好五个文件。通过 SSH 将压缩包上传至服务器。验证压缩包 SHA-256 后，在服务器上运行 `deploy/import-local-data.sh 压缩包路径`。该脚本先验证数据库及配置，然后停止服务、备份服务器原有数据、导入、重启并检查接口；失败时尝试恢复原数据。若 Workbench 容易断线，可通过 `systemd-run --unit=study-agent-import /bin/bash /opt/study-agent/deploy/import-local-data.sh 压缩包路径` 独立运行，并用 `journalctl -u study-agent-import -n 80 --no-pager` 查看结果。成功后删除 `studyviewer` 家目录里的上传压缩包，因为它包含 API 密钥。

### 日常更新

更新前备份 `study_agent.db`、`mastery.db`、`backend/patterns.yaml`、`backend/settings.json` 和 `.env`。其中 `backend/patterns.yaml` 既是 Git 跟踪文件又会在运行时修改，所以更新时可能与上游冲突；不要用 `git reset --hard` 覆盖它。代码拉取后执行 `runuser -u studyagent -- python3 scripts/run.py --prepare-only`，再 `systemctl restart study-agent`。

常用排查：

```bash
journalctl -u study-agent -n 100 --no-pager
journalctl -u caddy -n 100 --no-pager
curl -I http://127.0.0.1:8000/home.html
```
