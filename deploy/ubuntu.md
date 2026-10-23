# Ubuntu 26.04 / 阿里云 ECS 部署

主人应用使用 FastAPI + SQLite，由一个后端进程提供页面与 API，通过 Caddy 提供 HTTPS 和密码保护，只监听 `127.0.0.1:8000`。公开项目展示使用独立用户和进程，只提供固定介绍与预制样例，只监听 `127.0.0.1:8001`；两站通过同一套发布流程更新。

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

如果命令停在 `git fetch`，先按 `Ctrl+C`，直到重新出现 root 提示符。可以直接从 Mac 上传这两个部署文件，跳过服务器访问 GitHub。在 **Mac 终端**运行：

```bash
scp -i "$HOME/.ssh/study-agent-ecs" -o IdentitiesOnly=yes -o ConnectTimeout=10 \
  /Users/sqz/Desktop/study-agent/deploy/public/index.html \
  /Users/sqz/Desktop/study-agent/deploy/Caddyfile.example \
  studyviewer@47.117.107.156:/home/studyviewer/
```

确认两个文件均上传成功后，在 **Workbench 的 root 终端**运行：

```bash
install -d -m 755 /var/www/study-agent-public
install -m 644 /home/studyviewer/index.html /var/www/study-agent-public/index.html
install -m 644 /home/studyviewer/Caddyfile.example /etc/caddy/Caddyfile
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

## 3. 追加项目展示站

两站都运行在公网 IP **`47.117.107.156`** 的同一台 ECS 上。DNS 的 `@` 与 `demo` 两条 A 记录都指向这个 IP；Caddy 按域名转发，外部只使用 80/443。

| 项目 | 正式站 `150.chat` | 演示站 `demo.150.chat` |
|---|---|---|
| 代码 | `/opt/study-agent` | `/opt/study-agent-demo/current`（指向独立发布目录） |
| systemd 服务 | `study-agent` | `study-agent-demo` |
| Linux 用户 | `studyagent` | `studydemo` |
| 内部地址 | `127.0.0.1:8000` | `127.0.0.1:8001` |
| 运行数据 | `/opt/study-agent` 中的正式数据库与 `.runtime/` | 固定公开展示素材；旧体验数据保留供回滚 |
| AI 配置 | 正式站原配置 | 不读取 AI 配置，不调用模型 |

两个代码目录来自同一个 Git 提交。项目展示站运行独立 `backend.showcase:app`，提供专属页面、固定样例与本地数学/几何资源；不导入主人后端，不创建游客题库，不加载学习教程。同步保留正式站账号、题库和密钥配置。
主人继续使用 `https://150.chat/home.html`：用户名 **`studyadmin`**，密码是部署 Caddy 时自设的网站密码，主数据持续保存。Caddy 保存的是不可逆密码哈希，无法从配置反查明文；忘记时，在 Workbench 运行 `caddy hash-password` 设置新密码，然后在 `/etc/caddy/Caddyfile` 仅替换 `studyadmin` 后的旧哈希，执行 `caddy validate --config /etc/caddy/Caddyfile` 与 `systemctl reload caddy`。不要将密码或哈希提交到 Git。

项目展示入口为 `https://demo.150.chat/home.html`，无需账号密码。已有功能通过分步解析、作答诊断、几何动画和只读套路图谱展示；未来能力用图文规划说明。所有交互在浏览器运行，展示站不开放教学、上传、生成与写入接口。原有体验目录及旧 AI 快照不主动删除，便于版本回滚。

本地预览运行 `.venv/bin/python scripts/run_demo.py --port 8301`，打开 `http://127.0.0.1:8301/home.html`，无需 API 密钥。`Ctrl+C` 停止预览。详细内容和验收见 [展示站说明](../docs/showcase-demo.md)。
### 第一步：添加子域名解析

在阿里云云解析 DNS 新增一条记录：类型 **A**，主机记录 **`demo`**，记录值 **`47.117.107.156`**。保留原来的 `@` 记录。在 Mac 运行 `dig +short A demo.150.chat`，确认解析正确。现有安全组的 TCP 80/443 规则继续使用，8000/8001 无需对公网开放。

### 第二步：从 Mac 提交并推送

在 **Mac 终端**运行。先查看改动，确认本次功能文件已包括；不要添加 `.env`、运行时配置或数据库：

```bash
cd /Users/sqz/Desktop/study-agent
git status --short
git add .gitignore README.md requirements.txt backend/*.py frontend/ deploy/ docs/ scripts/run_demo.py tests/
git diff --cached --stat
git commit -m "Add isolated visitor experience and unified site deployment"
git push origin main
git rev-parse HEAD
```

保存最后输出的完整 **40 位提交 SHA**；后面统一发布必须填写这个值。这样两个网站对应同一个确定版本。若推送因网络超时，而且代理软件的 HTTP 端口仍是 7897，可运行 `git -c http.proxy=http://127.0.0.1:7897 push origin main`；确认成功后再部署。

### 第三步：统一发布主人站与游客站

首次升级旧服务时，先在两站确认没有 AI 解题、教学或仿题任务，然后关闭网站页面。本次首次升级加 `--bootstrap`：旧服务没有任务状态接口，因此这一轮需要由你确认任务已结束；脚本还会保守检查旧进程是否有已建立的网络连接。有连接就停止同步，等任务和连接结束后再试。后续发布无需此选项，脚本会暂停新写入/AI 请求，最多等待 5 分钟让已有请求和后台任务完成；超时会取消更新并恢复访问。

在 **Workbench 的 root 终端**，把下面 `REPLACE_WITH_FULL_COMMIT_SHA` 替换为 Mac 上得到的完整 SHA，再整段粘贴：

```bash
umask 077
cat > /root/study-agent-bootstrap-sites.sh <<'BOOTSTRAP'
#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
sync_commit=${1:-}
[[ $sync_commit =~ ^[0-9a-f]{40}$ ]] || { echo '请输入完整40位提交SHA。' >&2; exit 2; }
shift
timeout 300 runuser -u studyagent -- git -C /opt/study-agent -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=30 fetch --no-tags origin main
sync_script=$(mktemp /root/study-agent-sync-sites.XXXXXXXX.sh)
trap 'rm -f -- "$sync_script"' EXIT
runuser -u studyagent -- git -C /opt/study-agent show "${sync_commit}:deploy/sync-sites.sh" > "$sync_script"
bash -n "$sync_script"
chmod 700 "$sync_script"
/bin/bash "$sync_script" "$sync_commit" "$@"
BOOTSTRAP
chmod 700 /root/study-agent-bootstrap-sites.sh
bash -n /root/study-agent-bootstrap-sites.sh && systemd-run --unit=study-agent-sites-sync --collect /bin/bash /root/study-agent-bootstrap-sites.sh REPLACE_WITH_FULL_COMMIT_SHA --bootstrap
```

先保存脚本再让 systemd 运行文件，可避免它提前展开脚本文本里的 `$` 变量。仓库中也保存了对应的 [启动脚本](bootstrap-sites.sh)。

命令显示已创建 `study-agent-sites-sync.service` 后，拉取和安装会由服务器独立执行，Workbench 断线也会继续。重新登录查看日志：

```bash
journalctl -u study-agent-sites-sync -n 120 --no-pager
```

成功日志会显示「双站已同步到……」与备份目录。`--collect` 会在结束后回收临时任务；之后 `systemctl status study-agent-sites-sync` 可能显示单元不存在，历史结果仍以日志为准。若 GitHub 拉取、依赖安装或任务等待失败，这些步骤尚未更新服务版本；错误后查看日志，处理原因再运行。

旧版本首次同步若提示未跟踪文件，且列出的文件都在 `.cache/pip/`，这是先前安装依赖留下的下载缓存。当前版本已在 `.gitignore` 忽略该目录；旧服务器需要先添加同样的本地忽略规则，才能通过更新前检查。在 Workbench 运行下面命令，再重试发布命令：

```bash
runuser -u studyagent -- /bin/sh -c 'printf "\n/.cache/pip/\n" >> /opt/study-agent/.git/info/exclude'
```

该规则仅匹配仓库根目录的 pip 缓存，缓存继续保留；其他代码改动与未跟踪文件仍会触发检查。如果错误列出了其他路径，应先检查那些文件。

脚本在 `/opt/study-agent-sync/backups/` 创建 root 私有快照：用 SQLite 备份 API 保存并检查两个主人数据库、已有的 `.runtime/jobs.sqlite3` 任务/教学记录、`.runtime/question_pool.db` 原题池和 `.runtime/routine-review.sqlite3` 审核账本；同时保存 `.runtime/question-pool/` 题源原件、`.runtime/question-assets/` 题图、`.runtime/routine-matching/` 新套路目录与图谱布局、默认 `.accounts/` 账号数据，以及套路、看板顺序、设置、`.env`、Caddy、公开首页、systemd 配置、AI 快照与旧 Python 环境。`runtime_snapshot.py` 保存每个文件的大小与 SHA-256，数据库临时日志通过备份 API 归并。发布前检查备份磁盘空间；空间不足时不停止网站。代码更新保留原有运行文件，失败回滚时才从完整快照恢复；旧格式快照仍兼容。两个服务停站后还会复制 `/var/lib/study-agent-demo` 的游客数据库、任务、配置与日志，保留权限及归属，并归并数据库临时日志。复制前后拒绝链接和特殊文件，校验数据库完整性。脚本支持默认数据路径；如果 systemd 设置了自定义 `STUDY_AGENT_DATA_DIR`、`STUDY_AGENT_JOB_DIR`、`STUDY_AUTH_ROOT`、`STUDY_OWNER_DATA_DIR` 或游客 `STUDY_DEMO_ROOT`，会停止并要求另行制定备份路径。遗留同步维护配置会在停站前阻止发布，脚本仅清理本次创建的维护配置。服务器代码必须能从当前 `main` 快进到指定提交；除运行时 `backend/patterns.yaml` 外有代码改动、暂存改动或意外未跟踪文件时会停止，避免覆盖人工改动。它仅临时还原该套路导出文件的 Git 版本以完成 `merge --ff-only`，随后恢复主人原文件，**不使用 `git reset --hard`**。

依赖清单变化时，先在候选虚拟环境安装与检查；通过后才停站。主人服务保留现有 systemd 配置，游客使用独立用户 `studydemo`、独立代码发布目录和 `/var/lib/study-agent-demo`；两个服务分别运行在 `127.0.0.1:8000`、`127.0.0.1:8001`，各一个 worker。游客 Python 环境每次从本次主人环境重新复制，防止两站依赖版本不同。新展示服务不读取主人 AI 配置或原题库，不创建临时数据库；旧 AI 快照和体验数据保留在备份/原目录，以支持回滚。既有网站密码哈希与 API 密钥保持原值，无需重设。备份含私有密钥配置，不要上传到 Git 或发到聊天。

新版本启动时暂处于维护状态，完成两端口健康检查、展示站 HTTPS、主人公开首页与密码保护检查后才解除维护。脚本发生错误会尝试自动恢复旧代码、数据、依赖、入口配置与原服务状态，并保留备份。同步保留原体验数据与已完成任务供回滚；主人数据库持续保存。

### 第四步：验收

在 **Workbench 的 root 终端**运行：

```bash
systemctl status study-agent study-agent-demo --no-pager -l
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8001/health
curl -fsS https://demo.150.chat/health
curl -I https://150.chat/
curl -I https://150.chat/home.html
journalctl -u study-agent -u study-agent-demo -n 80 --no-pager
```

展示站健康检查应包含 `"mode":"demo","demo_mode":"showcase","ai_enabled":false`；主人公开首页返回 `200`，未输入网站密码的 `/home.html` 返回 `401`。Caddy 在 DNS 和 80/443 可达时自动申请 HTTPS，首次证书失败还可查看 `journalctl -u caddy -n 100 --no-pager`。不需要开放 8000/8001。

在浏览器验证：

1. 打开 `https://150.chat/`，应有「项目演示」「主人登录」及备案信息。
2. 主人登录仍用 `studyadmin` 和原网站密码，核对原题库与学习记录。
3. 打开 `https://demo.150.chat/home.html`，应有五部分项目介绍及四组可点击样例；无需登录、倒计时或 AI 等待。核对公式、几何旋转与参数、图谱筛选缩放，并确认未来功能和目标数值的状态标注。
4. 用手机或无痕窗口打开展示站；旧 `/teach.html`、`/routine-graph.html` 等链接应跳到展示章节。主人和账号版游客继续在原入口核对题库、学习记录及账号隔离。

展示站只提供公开静态资源及本机维护接口；教学、上传、生成、账号与写入 API 返回 404，不设置体验 Cookie、不创建访客工作区。浏览器交互只加载同源静态资源，不调用模型或主人题库。原账号版游客功能继续由主人应用提供。

### 日后同步与回滚

以后仍然在 Mac 提交并推送，复制新的完整 SHA，再运行上面的后台命令，**删掉最后的 `--bootstrap`**；GitHub 网络不通时按 [离线同步说明](../docs/offline-server-sync.md)制作源码包。脚本会检查并等待当前任务，更新两站到同一提交，验收展示模式和主人访问保护。展示站无需 AI 快照。不要再只更新一站，也不要直接 `git pull` 覆盖运行时套路文件。

需要恢复某次快照时，先确定要恢复的备份路径；日志中有完整路径，`/opt/study-agent-sync/latest-backup` 保存最近一次路径。**手动回滚会恢复快照时的主人及游客数据，发布后新产生的编辑不会保留在运行站点**。回滚前的游客目录会另存至 `/opt/study-agent-sync/failed-demo-data.XXXXXXXX`，供人工检查。在 Workbench 运行：

```bash
sync_backup=$(cat /opt/study-agent-sync/latest-backup)
systemd-run --unit=study-agent-sites-rollback --collect /bin/bash "$sync_backup/rollback-sites.sh" "$sync_backup"
journalctl -u study-agent-sites-rollback -n 120 --no-pager
```

回滚脚本先暂停新任务并等待现有任务完成，再恢复快照。如果仓库已有另一个提交或新代码修改，它会停止并要求人工检查。代码恢复采用 `git reset --keep`，遇到冲突会失败，不丢弃额外改动。确认成功后重复上面的健康与 HTTPS 检查。回滚时若旧游客服务原本未安装，则恢复为仅主人服务运行。

原有 SSH 邀请脚本仍然直接连接**主服务**，被授权的人可以改主库。公开展示请分享游客网址。

## 4. 更新与备份

### 从 Mac 迁移当前数据

GitHub 只同步源码，不包含原题池、审核结果、题图、新套路和图谱布局。本轮 23,255 道原题已有独立数据包，按 [题池数据导入说明](../docs/question-data-server-import.md)手动上传后执行。新工具校验所有附件和两库引用，在候选副本中合并并拒绝冲突；停站后从最新服务器数据重建候选，备份后安装，失败自动回滚。不更改账号、密码、API 配置或学习数据库。

下面的旧版五文件导入脚本仅适用于旧题库，不能用于迁移本轮审核数据；`runtime_snapshot.py restore` 是同一台服务器的回滚工具，不应直接拿本机快照覆盖服务器账号。图谱和题图读取已支持 `.runtime/question-pool/` 根路径跨电脑变化，保留原始出处记录。

在 Mac 上用 SQLite 备份 API 制作两个数据库快照，再将它们与 `patterns.yaml`、`settings.json`、`.env` 打包为恰好五个文件。通过 SSH 将压缩包上传至服务器。验证压缩包 SHA-256 后，在服务器上运行 `deploy/import-local-data.sh 压缩包路径`。该脚本先验证数据库及配置，然后停止服务、备份服务器原有数据、导入、重启并检查接口；失败时尝试恢复原数据。若 Workbench 容易断线，可通过 `systemd-run --unit=study-agent-import /bin/bash /opt/study-agent/deploy/import-local-data.sh 压缩包路径` 独立运行，并用 `journalctl -u study-agent-import -n 80 --no-pager` 查看结果。成功后删除 `studyviewer` 家目录里的上传压缩包，因为它包含 API 密钥。

### 日常更新

主人站和游客站使用上面的统一同步流程，固定完整提交 SHA、先检查任务再备份与更新。查看应用日志：

```bash
journalctl -u study-agent -u study-agent-demo -n 100 --no-pager
journalctl -u caddy -n 100 --no-pager
```
