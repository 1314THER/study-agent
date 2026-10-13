#!/usr/bin/env bash
# Import only the owner's original-question pool, review ledger and attachments.
set -Eeuo pipefail
umask 077

APP_DIR=/opt/study-agent
UNIT=study-agent
PORT=8000
SYNC_DIR=/opt/study-agent-sync
REQUIRED_COMMIT=c9a8d378d01ef2599d6a45680956379e805c0055
PACKAGE_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
PACKAGE_TOOL="$PACKAGE_ROOT/question_data_package.py"
MERGE_TOOL="$PACKAGE_ROOT/question_data_merge.py"
PYTHON="$APP_DIR/.venv/bin/python"
DROPIN=/run/systemd/system/study-agent.service.d/91-study-agent-data-import.conf
STAGING=
BACKUP=
DRAINED=0
STOPPED=0
APPLY_STARTED=0
DROPIN_CREATED=0
SUCCESS=0
KEEP_MAINTENANCE=0

[[ $EUID -eq 0 && $# -eq 0 ]] || { echo "用法（root）：bash $0" >&2; exit 2; }
for executable in git curl systemctl runuser flock realpath sha256sum mktemp; do
    command -v "$executable" >/dev/null
done
[[ -d $APP_DIR && ! -L $APP_DIR && $(realpath "$APP_DIR") == "$APP_DIR" && -x $PYTHON ]] || {
    echo '主人应用目录或 Python 环境不可用。' >&2; exit 1;
}
[[ ! -L $SYNC_DIR ]] || { echo '同步目录不能是符号链接。' >&2; exit 1; }
install -d -o root -g root -m 700 "$SYNC_DIR" "$SYNC_DIR/backups"
[[ $(realpath "$SYNC_DIR") == "$SYNC_DIR" && ! -L $SYNC_DIR/sync.lock ]] || {
    echo '同步目录或锁文件路径异常。' >&2; exit 1;
}
exec 9>"$SYNC_DIR/sync.lock"
flock -n 9 || { echo '另一次站点同步、回滚或题池导入正在运行。' >&2; exit 1; }

status_json() {
    curl --noproxy '*' --connect-timeout 2 --max-time 5 -fsS \
        "http://127.0.0.1:$PORT/_internal/deploy-status"
}
set_drain() {
    curl --noproxy '*' --connect-timeout 2 --max-time 5 -fsS -X POST \
        -H 'Content-Type: application/json' --data "{\"draining\":$1}" \
        "http://127.0.0.1:$PORT/_internal/deploy-drain" >/dev/null
}
check_status() {
    "$PYTHON" - "$1" "$2" <<'PY'
import json, sys
state = json.load(open(sys.argv[1], encoding='utf-8'))
if not all(type(state.get(key)) is int and state[key] >= 0 for key in ('active_requests', 'active_jobs')):
    raise SystemExit('内部部署状态格式异常')
if type(state.get('draining')) is not bool:
    raise SystemExit('内部部署维护状态格式异常')
mode = sys.argv[2]
if mode == 'ready' and state['draining']:
    raise SystemExit('主人网站已处于维护状态，请先处理原维护操作')
if mode == 'idle' and not (state['draining'] and state['active_requests'] == 0 and state['active_jobs'] == 0):
    raise SystemExit(1)
if mode == 'maintenance' and not (state['draining'] and state['active_jobs'] == 0):
    raise SystemExit('重新启动的主人服务未保持维护状态')
PY
}
assert_no_dropins() {
    local path
    for path in /run/systemd/system/study-agent.service.d/90-study-agent-sync.conf \
                /run/systemd/system/study-agent-demo.service.d/90-study-agent-sync.conf "$DROPIN"; do
        [[ ! -e $path && ! -L $path ]] || { echo "存在遗留维护配置 $path，请先人工检查。" >&2; return 1; }
    done
}
ensure_maintenance() {
    if [[ ! -e $DROPIN && ! -L $DROPIN ]]; then
        install -d -m 755 "$(dirname "$DROPIN")" || return 1
        (set -o noclobber; printf '[Service]\nEnvironment=STUDY_DEPLOY_DRAIN=1\n' > "$DROPIN") || return 1
        DROPIN_CREATED=1
    elif (( DROPIN_CREATED != 1 )); then
        echo "维护配置已被其他操作创建：$DROPIN" >&2; return 1
    fi
    systemctl daemon-reload || return 1
}
wait_health() {
    local deadline=$((SECONDS + 60))
    while (( SECONDS < deadline )); do
        if curl --noproxy '*' --connect-timeout 2 --max-time 5 -fsS \
            "http://127.0.0.1:$PORT/health" > "$STAGING/health.json"; then
            if "$PYTHON" - "$STAGING/health.json" <<'PY'
import json, sys
state = json.load(open(sys.argv[1], encoding='utf-8'))
if state.get('ok') is not True or state.get('mode') != 'owner':
    raise SystemExit('主人健康检查失败')
PY
            then
                status_json > "$STAGING/status.json" || return 1
                check_status "$STAGING/status.json" maintenance || return 1
                return 0
            fi
        fi
        sleep 2
    done
    echo '主人服务未在 60 秒内通过健康检查。' >&2
    return 1
}
release_maintenance() {
    if (( DROPIN_CREATED == 1 )); then
        rm -f -- "$DROPIN" || return 1
        systemctl daemon-reload || return 1
    fi
    set_drain false || return 1
    DRAINED=0
    STOPPED=0
    return 0
}
recover_owner() {
    ensure_maintenance || return 1
    systemctl stop "$UNIT" || return 1
    if (( APPLY_STARTED == 1 )); then
        "$PYTHON" "$PACKAGE_TOOL" rollback "$APP_DIR" "$BACKUP" || return 1
    fi
    systemctl start "$UNIT" || return 1
    wait_health || return 1
    release_maintenance || return 1
}
finish() {
    local code=$?
    trap - EXIT INT TERM
    if (( SUCCESS == 0 && STOPPED == 1 )); then
        echo "题池导入失败，正在恢复导入前的数据。备份：${BACKUP:-尚未开始安装}" >&2
        if ! recover_owner; then
            KEEP_MAINTENANCE=1
            # A failed reload or undrain can leave the file removed; recreate it.
            ensure_maintenance || true
            set_drain true || true
            echo '自动恢复未完成，主人服务保留维护状态；不要删除下面的目录和维护配置。' >&2
            echo "维护配置：$DROPIN" >&2
            echo "数据备份：${BACKUP:-无数据更改}；候选目录：$STAGING" >&2
            if (( APPLY_STARTED == 1 )); then
                printf '手工数据回滚（先停止主人服务）：systemctl stop %q && %q %q rollback %q %q\n' \
                    "$UNIT" "$PYTHON" "$PACKAGE_TOOL" "$APP_DIR" "$BACKUP" >&2
            fi
            code=1
        fi
    elif (( SUCCESS == 0 && DRAINED == 1 )); then
        if ! set_drain false; then
            KEEP_MAINTENANCE=1
            echo '尚未替换数据，但解除维护失败，请检查主人服务状态。' >&2
        fi
    fi
    if (( KEEP_MAINTENANCE == 0 )); then
        if (( DROPIN_CREATED == 1 )); then
            rm -f -- "$DROPIN"
            systemctl daemon-reload || true
        fi
        if [[ -n $STAGING && -d $STAGING ]]; then rm -rf -- "$STAGING"; fi
    fi
    exit "$code"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

assert_no_dropins
systemctl is-active --quiet "$UNIT"
[[ $(systemctl show "$UNIT" -p WorkingDirectory --value) == "$APP_DIR" ]] || {
    echo '主人服务工作目录与部署要求不符。' >&2; exit 1;
}
[[ $(runuser -u studyagent -- git -C "$APP_DIR" rev-parse HEAD) == "$REQUIRED_COMMIT" ]] || {
    echo "请先完成代码更新到 $REQUIRED_COMMIT，再导入原题数据。" >&2; exit 1;
}
systemctl show "$UNIT" -p ExecStart --value | "$PYTHON" -c '
import re, sys
unit = sys.stdin.read()
workers = re.findall(r"--workers(?:\s+|=)(\d+)", unit)
if "backend.main:app" not in unit or "--host 127.0.0.1" not in unit or "--port 8000" not in unit:
    raise SystemExit("主人服务启动命令与部署要求不符")
if "--reload" in unit or any(value != "1" for value in workers):
    raise SystemExit("主人服务必须是单 worker 且不使用 reload")
'
OWNER_PID=$(systemctl show "$UNIT" -p MainPID --value)
"$PYTHON" - "$OWNER_PID" "$APP_DIR" <<'PY'
from pathlib import Path
import sys
pid, app = sys.argv[1:]
if not pid.isdigit() or int(pid) <= 0:
    raise SystemExit('主人服务没有有效进程')
environment = {}
for entry in Path('/proc/' + pid + '/environ').read_bytes().split(b'\0'):
    if b'=' in entry:
        key, value = entry.split(b'=', 1)
        environment[key.decode()] = value.decode()
if environment.get('STUDY_AGENT_DATA_DIR'):
    raise SystemExit('主人服务设置了 STUDY_AGENT_DATA_DIR，题池路径可能不同；本工具只支持默认目录')
defaults = {'STUDY_OWNER_DATA_DIR':app,
            'STUDY_AGENT_JOB_DIR':app+'/.runtime', 'STUDY_AUTH_ROOT':app+'/.accounts'}
if any(environment.get(key, '') not in ('', expected) for key, expected in defaults.items()):
    raise SystemExit('当前只支持默认主人数据、任务和账号目录；自定义目录须另行迁移')
if environment.get('WEB_CONCURRENCY', '1') != '1' or environment.get('STUDY_DEMO_ROOT'):
    raise SystemExit('主人服务环境与部署要求不符')
# The startup environment can retain STUDY_DEPLOY_DRAIN=1 after a successful
# release. The internal status endpoint below is the live maintenance state.
PY

echo '正在校验原题池数据包；主人网站继续运行。'
(cd -- "$PACKAGE_ROOT" && sha256sum --check --strict --quiet SHA256SUMS)
echo '题池数据包摘要校验通过。'
"$PYTHON" - "$PACKAGE_TOOL" "$MERGE_TOOL" <<'PY'
from pathlib import Path
import sys
for name in sys.argv[1:]:
    compile(Path(name).read_text(encoding='utf-8'), name, 'exec')
PY
"$PYTHON" "$PACKAGE_TOOL" verify "$PACKAGE_ROOT"
QUESTION_COUNT=$("$PYTHON" - "$PACKAGE_ROOT/question-data-manifest.json" <<'PY'
import json, sys
manifest = json.load(open(sys.argv[1], encoding='utf-8'))
print(f"{manifest['counts']['pool_items']:,}")
PY
)
STAGING=$(mktemp -d "$SYNC_DIR/question-data.XXXXXXXX")
"$PYTHON" "$PACKAGE_TOOL" capacity "$PACKAGE_ROOT" "$APP_DIR" "$STAGING"
status_json > "$STAGING/status.json"
check_status "$STAGING/status.json" ready
PREFLIGHT_CANDIDATE=$(mktemp -d "$STAGING/preflight.XXXXXXXX")
echo '正在预检数据库合并与编号冲突；主人网站继续运行。'
"$PYTHON" "$MERGE_TOOL" "$PACKAGE_ROOT" "$APP_DIR" "$PREFLIGHT_CANDIDATE" > "$STAGING/preflight-merge.json"

# Drain the live process before stopping it. Rebuild from the stopped databases
# so edits made during preflight and any final WAL writes are retained.
DRAINED=1
set_drain true
echo '已暂停新写入与 AI 请求，等待当前任务完成（最多 5 分钟）。'
DEADLINE=$((SECONDS + 300))
IDLE=0
while (( SECONDS < DEADLINE )); do
    status_json > "$STAGING/status.json"
    if check_status "$STAGING/status.json" idle; then IDLE=1; break; fi
    sleep 2
done
(( IDLE == 1 )) || { echo '任务未在 5 分钟内结束，本次不导入。' >&2; exit 1; }
assert_no_dropins
[[ $(runuser -u studyagent -- git -C "$APP_DIR" rev-parse HEAD) == "$REQUIRED_COMMIT" ]] || {
    echo '准备期间服务器代码版本发生变化，本次不导入。' >&2; exit 1;
}
"$PYTHON" "$PACKAGE_TOOL" capacity "$PACKAGE_ROOT" "$APP_DIR" "$STAGING"
ensure_maintenance
STOPPED=1
systemctl stop "$UNIT"
FINAL_CANDIDATE=$(mktemp -d "$STAGING/final.XXXXXXXX")
"$PYTHON" "$MERGE_TOOL" "$PACKAGE_ROOT" "$APP_DIR" "$FINAL_CANDIDATE" > "$STAGING/final-merge.json"
BACKUP=$(mktemp -d "$SYNC_DIR/backups/question-data.XXXXXXXX")
APPLY_STARTED=1
"$PYTHON" "$PACKAGE_TOOL" apply "$PACKAGE_ROOT" "$FINAL_CANDIDATE" "$APP_DIR" "$BACKUP"
install -m 600 "$PACKAGE_TOOL" "$BACKUP/question_data_package.py"
cp -- "$STAGING/final-merge.json" "$BACKUP/merge-result.json"
"$PYTHON" "$PACKAGE_TOOL" verify-live "$PACKAGE_ROOT" "$APP_DIR"
systemctl start "$UNIT"
wait_health
release_maintenance
SUCCESS=1
touch "$BACKUP/import-complete"
printf '原题池与审核数据已导入：%s 道原题。\n' "$QUESTION_COUNT"
printf '备份：%s\n' "$BACKUP"
echo '主人：https://150.chat/home.html'
