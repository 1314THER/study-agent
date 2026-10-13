#!/bin/bash
# 双击打开学习系统；保留本地题库和原有匹配进度。
set -euo pipefail
cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

launch() {
    if [ ! -x ".venv/bin/python" ]; then
        python3 scripts/run.py --prepare-only || return $?
    fi
    .venv/bin/python scripts/desktop_launcher.py "$@"
}

if ! launch "$@"; then
    echo "启动未完成，错误信息见上方。"
    if [ -t 0 ]; then
        read -r -p "按回车关闭此窗口…" _reply
    fi
    exit 1
fi
