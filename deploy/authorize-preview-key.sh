#!/usr/bin/env bash
# Run as root on the ECS. Paste one guest SSH public key when prompted.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo '请在服务器上以 root 身份运行。' >&2
    exit 1
fi
if ! id studyviewer >/dev/null 2>&1; then
    echo 'studyviewer 用户不存在。' >&2
    exit 1
fi

echo '请粘贴朋友发来的单行公钥（以 ssh-ed25519 开头），然后按回车：'
IFS= read -r public_key
if [[ ! $public_key =~ ^ssh-ed25519\ [A-Za-z0-9+/]+=*(\ [^[:cntrl:]]*)?$ ]]; then
    echo '公钥格式不正确。' >&2
    exit 1
fi

temp_key=$(mktemp)
trap 'rm -f "$temp_key"' EXIT
printf '%s\n' "$public_key" > "$temp_key"
ssh-keygen -lf "$temp_key" >/dev/null

ssh_dir=/home/studyviewer/.ssh
authorized_keys=$ssh_dir/authorized_keys
install -d -o studyviewer -g studyviewer -m 700 "$ssh_dir"
touch "$authorized_keys"
chown studyviewer:studyviewer "$authorized_keys"
chmod 600 "$authorized_keys"

key_blob=${public_key#ssh-ed25519 }
key_blob=${key_blob%% *}
if grep -Fq "$key_blob" "$authorized_keys"; then
    echo '这把公钥已经授权。'
    exit 0
fi

printf 'restrict,port-forwarding,permitopen="127.0.0.1:8000",command="/bin/false" %s\n' \
    "$public_key" >> "$authorized_keys"
echo '已授权：此密钥只能建立到服务器 127.0.0.1:8000 的 SSH 转发。'
