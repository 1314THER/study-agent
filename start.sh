#!/bin/bash
# AI学习伴侣 - 启动后端服务器

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 检查端口是否被占用
if lsof -i:8000 > /dev/null 2>&1; then
    echo "端口 8000 已被占用，请先运行 ./stop.sh"
    exit 1
fi

echo "启动后端服务器..."
python3 -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
