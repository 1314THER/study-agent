#!/bin/bash
# macOS: double-click. Each person uses their own SSH key.
set -u

KEY="$HOME/.ssh/study-agent-viewer"
PUB="$KEY.pub"
URL="http://127.0.0.1:18000/home.html"
HEALTH="http://127.0.0.1:18000/openapi.json"

ready() {
    /usr/bin/curl --noproxy '*' -fs --max-time 2 "$HEALTH" 2>/dev/null |
        /usr/bin/grep -Fq '"/agent/context"'
}

if [[ ! -f "$KEY" ]]; then
    /bin/mkdir -p "$HOME/.ssh"
    /bin/chmod 700 "$HOME/.ssh"
    echo "首次使用：为这台 Mac 创建专用 SSH 密钥。"
    echo "可设置密钥口令；如果留空，以后双击即可直接连接。"
    /usr/bin/ssh-keygen -t ed25519 -f "$KEY" -C "study-agent-viewer" || exit 1
    /bin/chmod 600 "$KEY"
    /usr/bin/pbcopy < "$PUB"
    echo
    echo "公钥已经复制到剪贴板，请发给学习助手的主人授权。"
    echo "只发送以 ssh-ed25519 开头的公钥；私钥 $KEY 绝不能发送。"
    echo "授权完成后再次双击本文件。"
    read -r -p "按回车关闭窗口… " _
    exit 0
fi

if ready; then
    /usr/bin/open "$URL"
    exit 0
fi

echo "正在连接。首次连接时请核对服务器 ED25519 指纹："
echo "SHA256:/jN3UQmpWPnPXFvFDTi2FVEQwZ/JrtRBDiB0IJliwi4"
echo "连接成功后自动打开网页；保持此窗口打开。"
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
echo "连接已断开或未获授权（SSH 退出码：$result）。"
read -r -p "按回车关闭窗口… " _
exit "$result"
