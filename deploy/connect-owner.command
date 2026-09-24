#!/bin/bash
# Double-click on macOS to open the private server preview.
set -u

KEY="$HOME/.ssh/study-agent-ecs"
URL="http://127.0.0.1:18000/home.html"
HEALTH="http://127.0.0.1:18000/openapi.json"

ready() {
    /usr/bin/curl --noproxy '*' -fs --max-time 2 "$HEALTH" 2>/dev/null |
        /usr/bin/grep -Fq '"/agent/context"'
}

if [[ ! -f "$KEY" ]]; then
    echo "找不到 SSH 密钥：$KEY"
    read -r -p "按回车关闭窗口… " _
    exit 1
fi

if ready; then
    /usr/bin/open "$URL"
    exit 0
fi

echo "正在连接学习助手服务器。若提示密钥口令，请在这里输入。"
echo "连接成功后会自动打开网页。保持此窗口打开；关闭窗口即断开预览。"

(
    for ((i=0; i<120; i++)); do
        if ready; then
            /usr/bin/open "$URL"
            exit 0
        fi
        /bin/sleep 1
    done
) &
opener_pid=$!

/usr/bin/ssh -i "$KEY" -o IdentitiesOnly=yes -o ExitOnForwardFailure=yes \
    -N -L 127.0.0.1:18000:127.0.0.1:8000 studyviewer@47.117.107.156
result=$?
kill "$opener_pid" 2>/dev/null || true

if (( result != 0 )); then
    echo "SSH 连接失败，退出码：$result"
else
    echo "预览连接已断开。"
fi
read -r -p "按回车关闭窗口… " _
exit "$result"
