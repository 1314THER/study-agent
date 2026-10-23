#!/usr/bin/env bash
# 停止当前项目启动的本地后端。
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$PROJECT_DIR/scripts/stop_local_server.py" "$@"
