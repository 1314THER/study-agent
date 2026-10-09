#!/usr/bin/env bash
# Synchronize owner and demo to one explicit commit, preserving private data.
set -Eeuo pipefail
umask 077

APP_DIR=/opt/study-agent
DEMO_DIR=/opt/study-agent-demo
DEMO_DATA_DIR=/var/lib/study-agent-demo
SYNC_DIR=/opt/study-agent-sync
TARGET=${1:-}
BOOTSTRAP=${2:-}
BACKUP=
STAGING=
STOPPED=0
SUCCESS=0
DRAINED_PORTS=()
CREATED_DROPINS=()
RUNTIME=(study_agent.db mastery.db .runtime/jobs.sqlite3 backend/patterns.yaml backend/board_order.yaml backend/settings.json .env)

dropin() { printf '/run/systemd/system/%s.service.d/90-study-agent-sync.conf' "$1"; }
assert_no_dropins() {
    local unit path
    for unit in study-agent study-agent-demo; do
        path=$(dropin "$unit")
        [[ ! -e $path && ! -L $path ]] || { echo "存在遗留维护配置 $path，停止同步；请先人工检查。" >&2; return 1; }
    done
}
verify_demo_tree() {
    # Directory copies avoid archive path traversal. Reject links and special
    # files before copying, then normalize and validate copied SQLite files.
    python3 - "$1" "${2:-check}" <<'PY'
from pathlib import Path
import os, sqlite3, stat, sys, tempfile
root = Path(sys.argv[1])
mode = sys.argv[2]
if root.is_symlink() or not root.is_dir() or root.resolve() != root:
    raise SystemExit("游客快照路径不是独立的真实目录")
databases = []
for base, dirs, files in os.walk(root, followlinks=False):
    for name in dirs + files:
        path = Path(base) / name
        state = path.lstat()
        if not (stat.S_ISDIR(state.st_mode) or stat.S_ISREG(state.st_mode)):
            raise SystemExit("游客运行目录包含链接或特殊文件，停止操作")
        if stat.S_ISREG(state.st_mode) and state.st_nlink != 1:
            raise SystemExit("游客运行目录包含硬链接，停止操作")
        if stat.S_ISREG(state.st_mode) and path.suffix in (".db", ".sqlite3"):
            databases.append((path, state))
if mode == "normalize":
    for path, state in databases:
        handle, name = tempfile.mkstemp(prefix=".sqlite-snapshot.", dir=path.parent)
        os.close(handle)
        temp = Path(name)
        original = saved = None
        try:
            original = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
            saved = sqlite3.connect(temp)
            original.backup(saved)
            saved.execute("PRAGMA journal_mode=DELETE")
            if saved.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise SystemExit("游客数据库快照完整性校验失败")
            saved.close()
            saved = None
            original.close()
            original = None
            os.chown(temp, state.st_uid, state.st_gid)
            os.chmod(temp, stat.S_IMODE(state.st_mode))
            os.utime(temp, ns=(state.st_atime_ns, state.st_mtime_ns))
            os.replace(temp, path)
            for suffix in ("-wal", "-shm", "-journal"):
                Path(str(path) + suffix).unlink(missing_ok=True)
        finally:
            if saved is not None:
                saved.close()
            if original is not None:
                original.close()
            temp.unlink(missing_ok=True)
elif mode != "check":
    raise SystemExit("未知游客快照检查方式")
PY
}

if [[ $EUID -ne 0 || ! $TARGET =~ ^[0-9a-fA-F]{40}$ || ( -n $BOOTSTRAP && $BOOTSTRAP != --bootstrap ) ]]; then
    echo "用法（root）：bash $0 <完整的 40 位提交 SHA> [--bootstrap]" >&2
    exit 2
fi
for executable in git curl caddy systemctl runuser flock timeout ss python3 realpath; do
    command -v "$executable" >/dev/null
done
install -d -o root -g root -m 700 "$SYNC_DIR" "$SYNC_DIR/backups"
exec 9>"$SYNC_DIR/sync.lock"
flock -n 9 || { echo '另一次双站同步或回滚正在运行。' >&2; exit 1; }
preflight_cleanup() {
    local code=$?
    trap - EXIT
    if [[ -n $STAGING && -d $STAGING ]]; then rm -rf -- "$STAGING"; fi
    chmod 700 "$SYNC_DIR" || true
    exit "$code"
}
trap preflight_cleanup EXIT
assert_no_dropins
[[ -x $APP_DIR/.venv/bin/python && -f /etc/caddy/Caddyfile ]]
systemctl is-active --quiet study-agent
systemctl show study-agent -p ExecStart -p Environment --value | python3 -c '
import re, sys
unit = sys.stdin.read()
workers = re.findall(r"--workers(?:\s+|=)(\d+)", unit)
env_workers = re.findall(r"WEB_CONCURRENCY=(\d+)", unit)
if "backend.main:app" not in unit or "--host 127.0.0.1" not in unit or "--port 8000" not in unit:
    raise SystemExit("主人启动命令与当前部署不符；请先检查 systemd 配置")
if "--reload" in unit or any(n != "1" for n in workers + env_workers):
    raise SystemExit("主人服务必须是单 worker 且不使用 reload")
if re.search(r"STUDY_AGENT_(?:DATA|JOB)_DIR=", unit):
    raise SystemExit("自定义数据或任务目录需要单独制定备份路径，当前脚本只支持默认目录")
'
if systemctl cat study-agent-demo >/dev/null 2>&1; then
    systemctl show study-agent-demo -p Environment --value | python3 -c '
import re, sys
unit = sys.stdin.read()
roots = re.findall(r"(?:^|\s)STUDY_DEMO_ROOT=(\S+)", unit)
if roots != ["/var/lib/study-agent-demo"]:
    raise SystemExit("游客服务必须使用默认 STUDY_DEMO_ROOT=/var/lib/study-agent-demo；自定义路径需要单独备份方案")
'
fi
[[ ! -L $DEMO_DATA_DIR ]] || { echo '游客运行目录是符号链接，停止同步。' >&2; exit 1; }
if [[ -e $DEMO_DATA_DIR ]]; then
    [[ -d $DEMO_DATA_DIR && $(realpath "$DEMO_DATA_DIR") == "$DEMO_DATA_DIR" ]] || { echo '游客运行目录路径异常，停止同步。' >&2; exit 1; }
fi
OWNER_BRANCH=$(runuser -u studyagent -- git -C "$APP_DIR" symbolic-ref --short HEAD)
[[ $OWNER_BRANCH == main ]] || { echo '主人仓库必须在 main 分支；请先检查当前分支。' >&2; exit 1; }
OLD_COMMIT=$(runuser -u studyagent -- git -C "$APP_DIR" rev-parse HEAD)

git_owner() { runuser -u studyagent -- git -C "$APP_DIR" "$@"; }
assert_clean_code() {
    # patterns.yaml is the sole tracked runtime file. All other edits need review.
    [[ -z $(git_owner diff --cached --name-only) ]] || { echo '仓库有暂存改动，先人工检查。' >&2; return 1; }
    git_owner diff --name-only -z | python3 -c '
import sys
paths = [p for p in sys.stdin.buffer.read().split(b"\0") if p]
bad = [p for p in paths if p != b"backend/patterns.yaml"]
if bad:
    print("服务器有代码改动，停止同步：" + ", ".join(p.decode(errors="replace") for p in bad), file=sys.stderr)
    raise SystemExit(1)
'
    git_owner ls-files --others --exclude-standard -z | python3 -c '
import sys
paths = [p for p in sys.stdin.buffer.read().split(b"\0") if p]
bad = [p for p in paths if p != b"backend/board_order.yaml"]
if bad:
    print("服务器有未跟踪文件，停止同步：" + ", ".join(p.decode(errors="replace") for p in bad), file=sys.stderr)
    raise SystemExit(1)
'
}
assert_clean_code
echo '正在拉取 GitHub；尚未停止网站。'
timeout 300 runuser -u studyagent -- git -C "$APP_DIR" -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=30 fetch --no-tags origin main
TARGET=$(git_owner rev-parse --verify "$TARGET^{commit}")
git_owner merge-base --is-ancestor "$TARGET" origin/main || { echo '指定提交不在已获取的 origin/main 历史中。' >&2; exit 1; }
git_owner merge-base --is-ancestor "$OLD_COMMIT" "$TARGET" || { echo '指定提交无法从服务器当前提交快进，停止同步。' >&2; exit 1; }
STAGING=$(mktemp -d "$SYNC_DIR/staging.XXXXXXXX")
install -d -m 755 "$STAGING/code"
git_owner archive "$TARGET" | tar -x -C "$STAGING/code"
for relative in requirements.txt deploy/install-demo.sh deploy/rollback-sites.sh backend/jobs.py backend/demo.py frontend/demo-home.html; do
    [[ -f $STAGING/code/$relative ]] || { echo "指定提交缺少 $relative。" >&2; exit 1; }
done
cp -a "$APP_DIR/.venv" "$STAGING/.venv"
chmod 755 "$SYNC_DIR" "$STAGING"
chown -R studyagent:studyagent "$STAGING/.venv"
git_owner show "$OLD_COMMIT:requirements.txt" > "$STAGING/requirements.old"
if ! cmp -s "$STAGING/requirements.old" "$STAGING/code/requirements.txt"; then
    echo '依赖清单已变化，先在候选环境安装；网站继续运行。'
    runuser -u studyagent -- env PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=10 \
        "$STAGING/.venv/bin/python" -m pip install -r "$STAGING/code/requirements.txt"
fi
"$STAGING/.venv/bin/python" -c 'import fastapi, uvicorn, multipart, httpx, yaml, fitz, docx'
"$STAGING/.venv/bin/python" -m pip check
# _gen.py is an unused, versioned debug placeholder from an older checkout.
# Keep the user's file, but do not let that placeholder block a release.
"$STAGING/.venv/bin/python" -m compileall -q -x '(^|/)_gen\.py$' "$STAGING/code/backend"
chmod 700 "$SYNC_DIR"

status_json() { curl --noproxy '*' --connect-timeout 2 --max-time 5 -fsS "http://127.0.0.1:$1/_internal/deploy-status"; }
set_drain() {
    curl --noproxy '*' --connect-timeout 2 --max-time 5 -fsS -X POST \
        -H 'Content-Type: application/json' --data "{\"draining\":$2}" \
        "http://127.0.0.1:$1/_internal/deploy-drain" >/dev/null
}
finish() {
    local code=$?
    trap - EXIT
    if (( SUCCESS == 0 && STOPPED == 1 )) && [[ -n $BACKUP ]]; then
        echo "同步失败，正在自动回滚：$BACKUP" >&2
        # Remove our startup maintenance flags before restored units restart.
        # Existing processes stay drained until rollback stops them.
        for path in "${CREATED_DROPINS[@]}"; do rm -f -- "$path"; done
        CREATED_DROPINS=()
        systemctl daemon-reload
        SYNC_LOCK_HELD=1 bash "$BACKUP/rollback-sites.sh" "$BACKUP" || {
            echo "自动回滚未完成。请运行：bash $BACKUP/rollback-sites.sh $BACKUP" >&2
            code=1
        }
    elif (( SUCCESS == 0 )); then
        for port in "${DRAINED_PORTS[@]}"; do set_drain "$port" false || true; done
    fi
    for path in "${CREATED_DROPINS[@]}"; do rm -f -- "$path"; done
    systemctl daemon-reload || true
    if [[ -n $STAGING && -d $STAGING ]]; then rm -rf -- "$STAGING"; fi
    chmod 700 "$SYNC_DIR" || true
    exit "$code"
}
trap finish EXIT

PORTS=(8000)
if systemctl is-active --quiet study-agent-demo; then PORTS+=(8001); fi
LEGACY=()
for port in "${PORTS[@]}"; do
    if status_json "$port" > "$STAGING/status.$port.json"; then
        python3 - "$STAGING/status.$port.json" <<'PY'
import json, sys
state = json.load(open(sys.argv[1], encoding="utf-8"))
if not all(isinstance(state.get(k), int) and state[k] >= 0 for k in ("active_requests", "active_jobs")):
    raise SystemExit("内部部署状态格式异常，停止同步")
PY
        set_drain "$port" true
        DRAINED_PORTS+=("$port")
    elif [[ $BOOTSTRAP == --bootstrap ]]; then
        LEGACY+=("$port")
    else
        echo '运行版本还没有任务状态接口。首次升级确认两站没有 AI/仿题任务后，才使用 --bootstrap。' >&2
        exit 1
    fi
done
if (( ${#LEGACY[@]} > 0 )); then
    echo '首次升级模式：你已确认旧站没有 AI/仿题任务。继续检查旧进程网络连接。'
    for port in "${LEGACY[@]}"; do
        unit=study-agent
        [[ $port == 8001 ]] && unit=study-agent-demo
        pid=$(systemctl show "$unit" -p MainPID --value)
        ss -Hntp state established | python3 -c '
import sys
pid = sys.argv[1]
if pid == "0" or any(("pid=" + pid + ",") in row for row in sys.stdin):
    raise SystemExit("旧站仍有已建立的网络连接，停止同步；请关闭页面并等待 AI 任务结束")
' "$pid"
    done
fi
echo '已暂停新写入与 AI 请求，等待当前任务完成（最多 5 分钟）。'
idle=0
for _ in $(seq 1 150); do
    idle=1
    for port in "${DRAINED_PORTS[@]}"; do
        status_json "$port" > "$STAGING/status.$port.json"
        if ! python3 - "$STAGING/status.$port.json" <<'PY'
import json, sys
s = json.load(open(sys.argv[1], encoding="utf-8"))
raise SystemExit(0 if s.get("draining") is True and s.get("active_requests") == 0 and s.get("active_jobs") == 0 else 1)
PY
        then idle=0; fi
    done
    (( idle == 1 )) && break
    sleep 2
done
(( idle == 1 )) || { echo '任务未在 5 分钟内结束，本次不更新。' >&2; exit 1; }
assert_clean_code
assert_no_dropins
[[ $(git_owner rev-parse HEAD) == "$OLD_COMMIT" ]] || { echo '准备期间服务器提交发生变化，停止同步。' >&2; exit 1; }

BACKUP=$(mktemp -d "$SYNC_DIR/backups/sites.XXXXXXXX")
cp "$STAGING/code/deploy/rollback-sites.sh" "$BACKUP/rollback-sites.sh"
chmod 700 "$BACKUP/rollback-sites.sh"
printf '%s\n' "$OLD_COMMIT" > "$BACKUP/owner.old-commit"
printf '%s\n' "$TARGET" > "$BACKUP/owner.target-commit"
for unit in study-agent study-agent-demo; do
    systemctl is-active --quiet "$unit" && touch "$BACKUP/$unit.was-active"
    systemctl is-enabled --quiet "$unit" && touch "$BACKUP/$unit.was-enabled"
done
if [[ -L $DEMO_DIR/current ]]; then readlink "$DEMO_DIR/current" > "$BACKUP/demo.current"; fi
if [[ -d $DEMO_DIR/.venv ]]; then cp -a "$DEMO_DIR/.venv" "$BACKUP/demo.venv"; fi
SYSTEM_FILES=(/etc/caddy/Caddyfile /etc/caddy/study-agent-demo.caddy /etc/systemd/system/study-agent.service /etc/systemd/system/study-agent-demo.service /etc/study-agent-demo/ai.json /var/www/study-agent-public/index.html)
for file in "${SYSTEM_FILES[@]}"; do
    if [[ -f $file ]]; then install -d "$BACKUP/system$(dirname "$file")"; cp -a "$file" "$BACKUP/system$file"; fi
done
touch "$BACKUP/system-snapshot-complete"
STOPPED=1
systemctl stop study-agent-demo 2>/dev/null || true
systemctl stop study-agent
python3 - "$APP_DIR" "$BACKUP/owner-data" <<'PY'
from pathlib import Path
import os, shutil, sqlite3, sys
source, backup = map(Path, sys.argv[1:])
backup.mkdir(mode=0o700)
for name in ("study_agent.db", "mastery.db", ".runtime/jobs.sqlite3"):
    src = source / name
    if not src.is_file():
        if name == ".runtime/jobs.sqlite3":
            continue
        raise SystemExit("主人数据库不存在：" + name)
    dest = backup / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(src.as_uri() + "?mode=ro", uri=True) as original, sqlite3.connect(dest) as saved:
        original.backup(saved)
        if saved.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise SystemExit("数据库备份校验失败：" + name)
    os.chmod(backup / name, 0o600)
for name in ("backend/patterns.yaml", "backend/board_order.yaml", "backend/settings.json", ".env"):
    src = source / name
    if src.is_file():
        dest = backup / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        os.chmod(dest, 0o600)
print("主人数据库与私有配置快照已校验。", flush=True)
PY
if [[ -e $DEMO_DATA_DIR ]]; then
    verify_demo_tree "$DEMO_DATA_DIR"
    cp -a -- "$DEMO_DATA_DIR" "$BACKUP/demo-data"
    # Normalize copied SQLite files through their backup API so a WAL is not
    # needed on restore and read-only checks cannot create root-owned sidecars.
    verify_demo_tree "$BACKUP/demo-data" normalize
    verify_demo_tree "$BACKUP/demo-data"
    touch "$BACKUP/demo-data.was-present"
fi
touch "$BACKUP/demo-data-snapshot-complete"
touch "$BACKUP/data-snapshot-complete"
printf '%s\n' "$BACKUP" > "$SYNC_DIR/latest-backup"

# Temporarily restore only the versioned runtime export so FF cannot overwrite it.
if git_owner ls-files --error-unmatch backend/patterns.yaml >/dev/null 2>&1; then
    git_owner restore --source=HEAD --worktree -- backend/patterns.yaml
fi
git_owner merge --ff-only "$TARGET"
for relative in "${RUNTIME[@]}"; do
    if [[ -f $BACKUP/owner-data/$relative ]]; then
        install -D -o studyagent -g studyagent -m 600 "$BACKUP/owner-data/$relative" "$APP_DIR/$relative"
    fi
done
rm -f -- "$APP_DIR/study_agent.db-wal" "$APP_DIR/study_agent.db-shm" "$APP_DIR/mastery.db-wal" "$APP_DIR/mastery.db-shm" \
    "$APP_DIR/.runtime/jobs.sqlite3-wal" "$APP_DIR/.runtime/jobs.sqlite3-shm"
install -d -o studyagent -g studyagent -m 700 "$APP_DIR/.runtime"
mv "$APP_DIR/.venv" "$BACKUP/owner.venv"
mv "$STAGING/.venv" "$APP_DIR/.venv"
chown -R studyagent:studyagent "$APP_DIR/.venv"
for unit in study-agent study-agent-demo; do
    path=$(dropin "$unit")
    install -d -m 755 "/run/systemd/system/$unit.service.d"
    (set -o noclobber; printf '[Service]\nEnvironment=STUDY_DEPLOY_DRAIN=1\n' > "$path")
    CREATED_DROPINS+=("$path")
done
systemctl daemon-reload
systemctl start study-agent
bash "$STAGING/code/deploy/install-demo.sh" "$TARGET"

wait_health() {
    for _ in $(seq 1 30); do
        if curl --noproxy '*' --connect-timeout 2 --max-time 5 -fsS "$1" > "$STAGING/health.json"; then return 0; fi
        sleep 2
    done
    return 1
}
wait_health http://127.0.0.1:8000/health
wait_health http://127.0.0.1:8001/health
python3 - "$STAGING/health.json" <<'PY'
import json, sys
state = json.load(open(sys.argv[1], encoding="utf-8"))
if state.get("mode") != "demo" or state.get("ai_enabled") is not True:
    raise SystemExit("游客健康检查未确认 AI 已开启")
PY
for port in 8000 8001; do
    status_json "$port" > "$STAGING/status.$port.json"
    python3 - "$STAGING/status.$port.json" <<'PY'
import json, sys
state = json.load(open(sys.argv[1], encoding="utf-8"))
if state.get("draining") is not True or state.get("active_jobs") != 0:
    raise SystemExit("新服务没有进入部署维护状态")
PY
done
wait_health https://demo.150.chat/health
OWNER_ROOT=$(curl --noproxy '*' --connect-timeout 5 --max-time 15 -sS -o /dev/null -w '%{http_code}' https://150.chat/)
OWNER_PRIVATE=$(curl --noproxy '*' --connect-timeout 5 --max-time 15 -sS -o /dev/null -w '%{http_code}' https://150.chat/home.html)
[[ $OWNER_ROOT == 200 && $OWNER_PRIVATE == 401 ]] || { echo '主人公网入口或密码保护检查失败。' >&2; exit 1; }
DEMO_PAGE=$(curl --noproxy '*' --connect-timeout 5 --max-time 15 -sS -o /dev/null -w '%{http_code}' https://demo.150.chat/home.html)
[[ $DEMO_PAGE == 200 ]] || { echo '游客 HTTPS 页面检查失败。' >&2; exit 1; }
for port in 8000 8001; do set_drain "$port" false; done
for path in "${CREATED_DROPINS[@]}"; do rm -f -- "$path"; done
CREATED_DROPINS=()
systemctl daemon-reload
SUCCESS=1
touch "$BACKUP/sync-complete"
echo "双站已同步到 $TARGET。主人题库、网站密码和 API 配置已保留。"
echo "备份：$BACKUP"
echo "回滚：bash $BACKUP/rollback-sites.sh $BACKUP"
echo '主人：https://150.chat/home.html；游客：https://demo.150.chat/home.html'
