#!/usr/bin/env bash
# Restore one root-owned sync snapshot, without a hard reset or lost secrets.
set -Eeuo pipefail
umask 077
APP_DIR=/opt/study-agent
DEMO_DIR=/opt/study-agent-demo
DEMO_DATA_DIR=/var/lib/study-agent-demo
SYNC_DIR=/opt/study-agent-sync
BACKUP=${1:-}
STOPPED=0
DRAINED_PORTS=()
verify_demo_tree() {
    python3 - "$1" <<'PY'
from pathlib import Path
import os, sqlite3, stat, sys
root = Path(sys.argv[1])
if root.is_symlink() or not root.is_dir() or root.resolve() != root:
    raise SystemExit("游客快照路径不是独立的真实目录")
for base, dirs, files in os.walk(root, followlinks=False):
    for name in dirs + files:
        path = Path(base) / name
        state = path.lstat()
        if not (stat.S_ISDIR(state.st_mode) or stat.S_ISREG(state.st_mode)):
            raise SystemExit("游客快照包含链接或特殊文件，拒绝恢复")
        if stat.S_ISREG(state.st_mode) and state.st_nlink != 1:
            raise SystemExit("游客快照包含硬链接，拒绝恢复")
        if stat.S_ISREG(state.st_mode) and path.suffix in (".db", ".sqlite3"):
            if any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
                raise SystemExit("游客数据库快照包含未归并的临时日志，拒绝恢复")
            db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
            try:
                if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise SystemExit("游客数据库快照完整性校验失败")
            finally:
                db.close()
PY
}
if [[ $EUID -ne 0 || -z $BACKUP || ! -f $BACKUP/owner.old-commit || ! -f $BACKUP/owner.target-commit ]]; then
    echo "用法（root）：bash $0 /opt/study-agent-sync/backups/sites.XXXXXXXX" >&2
    exit 2
fi
[[ ! -L $BACKUP && -d $BACKUP ]] || { echo '备份路径必须是独立的真实目录。' >&2; exit 1; }
BACKUP=$(realpath "$BACKUP")
[[ $(dirname "$BACKUP") == "$SYNC_DIR/backups" && $(basename "$BACKUP") =~ ^sites\.[a-zA-Z0-9]{8}$ && $(stat -c '%u' "$BACKUP") == 0 && -f $BACKUP/system-snapshot-complete ]] || { echo '备份路径必须是 root 所有且系统配置已完整保存的同步快照。' >&2; exit 1; }
if [[ ${SYNC_LOCK_HELD:-0} != 1 ]]; then
    [[ -f $BACKUP/data-snapshot-complete ]] || { echo '该快照数据备份未完成，拒绝手动恢复。' >&2; exit 1; }
    exec 9>"$SYNC_DIR/sync.lock"
    flock -n 9 || { echo '另一次同步或回滚正在运行。' >&2; exit 1; }
    for unit in study-agent study-agent-demo; do
        path="/run/systemd/system/$unit.service.d/90-study-agent-sync.conf"
        [[ ! -e $path && ! -L $path ]] || { echo "存在遗留维护配置 $path，停止回滚；请先人工检查。" >&2; exit 1; }
    done
fi
[[ ! -L $DEMO_DATA_DIR ]] || { echo '游客运行目录是符号链接，拒绝回滚。' >&2; exit 1; }
if [[ -e $DEMO_DATA_DIR ]]; then
    [[ -d $DEMO_DATA_DIR && $(realpath "$DEMO_DATA_DIR") == "$DEMO_DATA_DIR" ]] || { echo '游客运行目录路径异常，拒绝回滚。' >&2; exit 1; }
fi
if [[ -f $BACKUP/data-snapshot-complete ]]; then
    [[ -f $BACKUP/demo-data-snapshot-complete ]] || { echo '游客运行数据快照未完成，拒绝恢复。' >&2; exit 1; }
    if [[ -f $BACKUP/demo-data.was-present ]]; then
        verify_demo_tree "$BACKUP/demo-data"
    else
        [[ ! -e $BACKUP/demo-data && ! -L $BACKUP/demo-data ]] || { echo '游客快照的缺失标记与目录不一致，拒绝恢复。' >&2; exit 1; }
    fi
fi
cleanup() {
    local code=$?
    trap - EXIT
    if (( code != 0 && STOPPED == 0 )); then
        for port in "${DRAINED_PORTS[@]}"; do
            curl --noproxy '*' --max-time 5 -fsS -X POST -H 'Content-Type: application/json' --data '{"draining":false}' \
                "http://127.0.0.1:$port/_internal/deploy-drain" >/dev/null 2>&1 || true
        done
    fi
    exit "$code"
}
trap cleanup EXIT
git_owner() { runuser -u studyagent -- git -C "$APP_DIR" "$@"; }
OLD=$(cat "$BACKUP/owner.old-commit")
TARGET=$(cat "$BACKUP/owner.target-commit")
CURRENT=$(git_owner rev-parse HEAD)
[[ $CURRENT == "$OLD" || $CURRENT == "$TARGET" ]] || { echo '主人仓库已出现其他提交，拒绝自动回滚。' >&2; exit 1; }
[[ -z $(git_owner diff --cached --name-only) ]] || { echo '主人仓库有暂存改动，拒绝回滚。' >&2; exit 1; }
git_owner diff --name-only -z | python3 -c '
import sys
bad = [p for p in sys.stdin.buffer.read().split(b"\0") if p and p != b"backend/patterns.yaml"]
if bad:
    raise SystemExit("主人代码已有人修改，拒绝覆盖；先检查备份与当前改动")
'
if [[ ${SYNC_LOCK_HELD:-0} != 1 ]]; then
    # Manual rollback is a maintenance action: drain and finish new AI jobs first.
    for port in 8000 8001; do
        unit=study-agent
        [[ $port == 8001 ]] && unit=study-agent-demo
        systemctl is-active --quiet "$unit" || continue
        curl --noproxy '*' --connect-timeout 2 --max-time 5 -fsS -X POST -H 'Content-Type: application/json' \
            --data '{"draining":true}' "http://127.0.0.1:$port/_internal/deploy-drain" >/dev/null
        DRAINED_PORTS+=("$port")
    done
    idle=0
    for _ in $(seq 1 150); do
        idle=1
        for port in 8000 8001; do
            unit=study-agent
            [[ $port == 8001 ]] && unit=study-agent-demo
            systemctl is-active --quiet "$unit" || continue
            if ! curl --noproxy '*' --connect-timeout 2 --max-time 5 -fsS "http://127.0.0.1:$port/_internal/deploy-status" | python3 -c '
import json, sys
s = json.load(sys.stdin)
raise SystemExit(0 if s.get("draining") is True and s.get("active_requests") == 0 and s.get("active_jobs") == 0 else 1)
'; then idle=0; fi
        done
        (( idle == 1 )) && break
        sleep 2
    done
    if (( idle != 1 )); then
        for port in 8000 8001; do
            curl --noproxy '*' --max-time 5 -fsS -X POST -H 'Content-Type: application/json' --data '{"draining":false}' \
                "http://127.0.0.1:$port/_internal/deploy-drain" >/dev/null 2>&1 || true
        done
        echo '任务仍在运行，取消回滚。' >&2
        exit 1
    fi
    echo '手动回滚将恢复该快照时的主人与游客数据；升级之后的新编辑不会保留。'
fi
STOPPED=1
systemctl stop study-agent-demo 2>/dev/null || true
systemctl stop study-agent
if [[ $CURRENT != "$OLD" ]]; then
    git_owner restore --source=HEAD --worktree -- backend/patterns.yaml
    # --keep fails on unexpected conflicting edits instead of discarding them.
    git_owner reset --keep "$OLD"
fi
if [[ -f $BACKUP/data-snapshot-complete ]]; then
    install -d -o studyagent -g studyagent -m 700 "$APP_DIR/.runtime"
    for relative in study_agent.db mastery.db .runtime/jobs.sqlite3 backend/patterns.yaml backend/board_order.yaml backend/settings.json .env; do
        if [[ -f $BACKUP/owner-data/$relative ]]; then
            install -D -o studyagent -g studyagent -m 600 "$BACKUP/owner-data/$relative" "$APP_DIR/$relative"
        else
            rm -f -- "$APP_DIR/$relative"
        fi
    done
    rm -f -- "$APP_DIR/study_agent.db-wal" "$APP_DIR/study_agent.db-shm" "$APP_DIR/mastery.db-wal" "$APP_DIR/mastery.db-shm" \
        "$APP_DIR/.runtime/jobs.sqlite3-wal" "$APP_DIR/.runtime/jobs.sqlite3-shm"
    if [[ -e $DEMO_DATA_DIR ]]; then
        FAILED_DEMO_DATA=$(mktemp -d "$SYNC_DIR/failed-demo-data.XXXXXXXX")
        rmdir "$FAILED_DEMO_DATA"
        mv -- "$DEMO_DATA_DIR" "$FAILED_DEMO_DATA"
        echo "回滚前的游客运行数据另存于：$FAILED_DEMO_DATA"
    fi
    if [[ -f $BACKUP/demo-data.was-present ]]; then
        cp -a -- "$BACKUP/demo-data" "$DEMO_DATA_DIR"
        verify_demo_tree "$DEMO_DATA_DIR"
    fi
fi
if [[ -d $BACKUP/owner.venv ]]; then
    FAILED_VENV=$(mktemp -d "$SYNC_DIR/failed-owner-venv.XXXXXXXX")
    rmdir "$FAILED_VENV"
    [[ ! -d $APP_DIR/.venv ]] || mv "$APP_DIR/.venv" "$FAILED_VENV"
    cp -a "$BACKUP/owner.venv" "$APP_DIR/.venv"
fi
if [[ -d $BACKUP/demo.venv ]]; then
    FAILED_DEMO_VENV=$(mktemp -d "$SYNC_DIR/failed-demo-venv.XXXXXXXX")
    rmdir "$FAILED_DEMO_VENV"
    [[ ! -d $DEMO_DIR/.venv ]] || mv "$DEMO_DIR/.venv" "$FAILED_DEMO_VENV"
    cp -a "$BACKUP/demo.venv" "$DEMO_DIR/.venv"
fi
if [[ -f $BACKUP/demo.current ]]; then
    ln -sfn "$(cat "$BACKUP/demo.current")" "$DEMO_DIR/current"
else
    rm -f -- "$DEMO_DIR/current"
fi
for file in /etc/caddy/Caddyfile /etc/caddy/study-agent-demo.caddy /etc/systemd/system/study-agent.service /etc/systemd/system/study-agent-demo.service /etc/study-agent-demo/ai.json /var/www/study-agent-public/index.html; do
    if [[ -f $BACKUP/system$file ]]; then
        install -d "$(dirname "$file")"
        cp -a "$BACKUP/system$file" "$file"
    else
        rm -f -- "$file"
    fi
done
# During automatic recovery, the synchronizer removes only its own drop-ins.
# A manual rollback never removes a maintenance file created by another run.
systemctl daemon-reload
caddy validate --config /etc/caddy/Caddyfile
systemctl reload caddy
for unit in study-agent study-agent-demo; do
    if [[ -f $BACKUP/$unit.was-enabled ]]; then systemctl enable "$unit"; else systemctl disable "$unit" 2>/dev/null || true; fi
    if [[ -f $BACKUP/$unit.was-active ]]; then systemctl start "$unit"; fi
done
for port in 8000 8001; do
    curl --noproxy '*' --max-time 5 -fsS -X POST -H 'Content-Type: application/json' --data '{"draining":false}' \
        "http://127.0.0.1:$port/_internal/deploy-drain" >/dev/null 2>&1 || true
done
for _ in $(seq 1 30); do
    ready=1
    curl --noproxy '*' --max-time 5 -fsS http://127.0.0.1:8000/openapi.json >/dev/null 2>&1 || ready=0
    if [[ -f $BACKUP/study-agent-demo.was-active ]]; then
        curl --noproxy '*' --max-time 5 -fsS http://127.0.0.1:8001/health >/dev/null 2>&1 || ready=0
    fi
    if (( ready == 1 )); then
        echo "已恢复主人代码 $OLD 和快照配置。备份仍在：$BACKUP"
        touch "$BACKUP/rollback-complete"
        exit 0
    fi
    sleep 1
done
echo '回滚后的服务未就绪，请查看 journalctl -u study-agent -u study-agent-demo -n 100 --no-pager。' >&2
exit 1
