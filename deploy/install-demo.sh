#!/usr/bin/env bash
# Install a read-only project showcase, preserving old demo data for rollback.
set -Eeuo pipefail

APP_DIR=/opt/study-agent
DEMO_DIR=/opt/study-agent-demo
REF=${1:-origin/main}
RELEASE=
BACKUP=
OLD_CURRENT=
SERVICE_CHANGED=0
VENV_CHANGED=0
STAGED_VENV=
CADDY_CHANGED=0
SUCCESS=0

if [[ $EUID -ne 0 ]]; then
    echo '请在 Workbench 的 root 终端运行此脚本。' >&2
    exit 2
fi
if [[ ! -x $APP_DIR/.venv/bin/python || ! -f /etc/caddy/Caddyfile ]]; then
    echo '请先完成主应用和 Caddy 部署。' >&2
    exit 2
fi
command -v caddy >/dev/null
runuser -u studyagent -- git -C "$APP_DIR" rev-parse --verify "$REF^{commit}" >/dev/null
if ! id studydemo >/dev/null 2>&1; then
    useradd --system --home /var/lib/study-agent-demo --shell /usr/sbin/nologin studydemo
fi
install -d -m 755 "$DEMO_DIR" "$DEMO_DIR/releases"
install -d -o studydemo -g studydemo -m 700 /var/lib/study-agent-demo
install -d -o root -g studydemo -m 750 /etc/study-agent-demo
RELEASE=$(mktemp -d "$DEMO_DIR/releases/release.XXXXXXXX")
chmod 755 "$RELEASE"
BACKUP=$(mktemp -d /root/study-agent-demo-backup.XXXXXXXX)
cp -a /etc/caddy/Caddyfile "$BACKUP/Caddyfile"
for path in /etc/caddy/study-agent-demo.caddy /etc/systemd/system/study-agent-demo.service /var/www/study-agent-public/index.html; do
    if [[ -f $path ]]; then
        cp -a "$path" "$BACKUP/$(basename "$path")"
    fi
done
if [[ -f /etc/study-agent-demo/ai.json ]]; then
    cp -a /etc/study-agent-demo/ai.json "$BACKUP/ai.json"
fi
if [[ -L $DEMO_DIR/current ]]; then
    OLD_CURRENT=$(readlink "$DEMO_DIR/current")
fi

finish() {
    local code=$?
    trap - EXIT
    if (( SUCCESS == 0 )); then
        echo "安装失败，恢复已有入口配置。备份：$BACKUP" >&2
        if (( CADDY_CHANGED == 1 )); then
            cp -a "$BACKUP/Caddyfile" /etc/caddy/Caddyfile
            if [[ -f $BACKUP/study-agent-demo.caddy ]]; then
                cp -a "$BACKUP/study-agent-demo.caddy" /etc/caddy/study-agent-demo.caddy
            else
                rm -f /etc/caddy/study-agent-demo.caddy
            fi
            systemctl reload caddy || true
        fi
        if [[ -f $BACKUP/index.html ]]; then
            cp -a "$BACKUP/index.html" /var/www/study-agent-public/index.html
        fi
        if (( SERVICE_CHANGED == 1 )); then
            systemctl stop study-agent-demo || true
            if (( VENV_CHANGED == 1 )); then
                rm -rf -- "$DEMO_DIR/.venv"
                if [[ -d $BACKUP/.venv ]]; then
                    mv -- "$BACKUP/.venv" "$DEMO_DIR/.venv"
                fi
            fi
            if [[ -f $BACKUP/ai.json ]]; then
                cp -a "$BACKUP/ai.json" /etc/study-agent-demo/ai.json
            fi
            if [[ -n $OLD_CURRENT ]]; then
                ln -sfn "$OLD_CURRENT" "$DEMO_DIR/current"
            fi
            if [[ -f $BACKUP/study-agent-demo.service ]]; then
                cp -a "$BACKUP/study-agent-demo.service" /etc/systemd/system/study-agent-demo.service
                systemctl daemon-reload
                systemctl start study-agent-demo || true
            else
                systemctl disable study-agent-demo || true
                rm -f /etc/systemd/system/study-agent-demo.service
                systemctl daemon-reload
            fi
        fi
    fi
    if [[ -n $STAGED_VENV && -d $STAGED_VENV ]]; then
        rm -rf -- "$STAGED_VENV"
    fi
    exit "$code"
}
trap finish EXIT

# A git archive contains versioned example data, never .env or runtime settings.
runuser -u studyagent -- git -C "$APP_DIR" archive "$REF" | tar -x -C "$RELEASE"
for relative in backend/showcase.py deploy/study-agent-demo.service deploy/study-agent-demo.caddy deploy/public/index.html frontend/showcase/index.html frontend/showcase/style.css frontend/showcase/app.js frontend/showcase/data.json frontend/geometry.js frontend/geometry.css frontend/vendor/katex/katex.min.js frontend/vendor/katex/katex.min.css frontend/vendor/three-0.180.0/build/three.module.min.js frontend/vendor/three-0.180.0/build/three.core.min.js frontend/vendor/three-0.180.0/examples/jsm/controls/OrbitControls.js frontend/vendor/jsxgraph-1.11.1/distrib/jsxgraphcore.js frontend/vendor/jsxgraph-1.11.1/distrib/jsxgraph.css; do
    if [[ ! -f $RELEASE/$relative ]]; then
        echo "提交缺少 ${relative}，请先从 Mac 提交并推送全部项目展示文件。" >&2
        exit 1
    fi
done
# Refresh the independent copy on every install, including dependency updates.
STAGED_VENV=$(mktemp -d "$DEMO_DIR/venv.new.XXXXXXXX")
cp -a "$APP_DIR/.venv/." "$STAGED_VENV/"
chown -R root:root "$STAGED_VENV"
chmod -R a+rX "$STAGED_VENV"
chown -R root:root "$RELEASE"
chmod -R a+rX "$RELEASE"
(cd "$RELEASE" && "$STAGED_VENV/bin/python" - <<'PY'
import fastapi, uvicorn
from backend.showcase import ASSET_PATHS, FRONTEND
missing = [path for path in ASSET_PATHS | {"/showcase/index.html"} if not (FRONTEND / path.lstrip("/")).is_file()]
if missing:
    raise SystemExit("展示资源缺失：" + ", ".join(sorted(missing)))
PY
)
SERVICE_CHANGED=1
systemctl stop study-agent-demo || true
if [[ -d $DEMO_DIR/.venv ]]; then
    mv -- "$DEMO_DIR/.venv" "$BACKUP/.venv"
fi
VENV_CHANGED=1
mv -- "$STAGED_VENV" "$DEMO_DIR/.venv"
STAGED_VENV=
ln -sfn "$RELEASE" "$DEMO_DIR/current"
install -m 644 "$RELEASE/deploy/study-agent-demo.service" /etc/systemd/system/study-agent-demo.service
systemctl daemon-reload
systemctl enable --now study-agent-demo
ready=0
for _ in $(seq 1 30); do
    if curl --noproxy '*' --connect-timeout 2 --max-time 5 -fsS http://127.0.0.1:8001/health | "$DEMO_DIR/.venv/bin/python" -c '
import json, sys
state = json.load(sys.stdin)
raise SystemExit(0 if state.get("ok") is True and state.get("mode") == "demo" and state.get("demo_mode") == "showcase" and state.get("ai_enabled") is False else 1)
'; then
        ready=1
        break
    fi
    sleep 1
done
if (( ready != 1 )); then
    journalctl -u study-agent-demo -n 30 --no-pager
    exit 1
fi
CADDY_CHANGED=1
install -m 644 "$RELEASE/deploy/study-agent-demo.caddy" /etc/caddy/study-agent-demo.caddy
if ! grep -q '^import /etc/caddy/study-agent-demo\.caddy[[:space:]]*$' /etc/caddy/Caddyfile; then
    printf '\nimport /etc/caddy/study-agent-demo.caddy\n' >> /etc/caddy/Caddyfile
fi
caddy validate --config /etc/caddy/Caddyfile
install -d -m 755 /var/www/study-agent-public
install -m 644 "$RELEASE/deploy/public/index.html" /var/www/study-agent-public/index.html
systemctl reload caddy
SUCCESS=1
echo "项目展示服务已启动，主账号及主数据保持原配置。备份：$BACKUP"
echo '项目演示：https://demo.150.chat/home.html（无需账号密码，无 AI 调用）'
echo '主人入口：https://150.chat/home.html（studyadmin / 原网站密码）'
echo '请确认 DNS 已添加 demo 的 A 记录 -> 47.117.107.156。'
echo '日志：journalctl -u study-agent-demo -n 60 --no-pager'
