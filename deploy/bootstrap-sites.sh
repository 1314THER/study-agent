#!/usr/bin/env bash
# Run this saved file via systemd-run, rather than passing a script to bash -c.
set -Eeuo pipefail
umask 077

if [[ $EUID -ne 0 ]]; then
    echo '请在 Workbench 的 root 终端启动同步。' >&2
    exit 2
fi
sync_commit=${1:-}
if [[ ! $sync_commit =~ ^[0-9a-f]{40}$ ]]; then
    echo '请填写完整的 40 位 Git 提交 SHA。' >&2
    exit 2
fi
shift
timeout 300 runuser -u studyagent -- git -C /opt/study-agent \
    -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=30 fetch --no-tags origin main
sync_script=$(mktemp /root/study-agent-sync-sites.XXXXXXXX.sh)
trap 'rm -f -- "$sync_script"' EXIT
runuser -u studyagent -- git -C /opt/study-agent show "${sync_commit}:deploy/sync-sites.sh" > "$sync_script"
bash -n "$sync_script"
chmod 700 "$sync_script"
/bin/bash "$sync_script" "$sync_commit" "$@"
