#!/bin/bash
# AI学习伴侣 - 停止后端服务器

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PIDS=$(lsof -ti:8000 2>/dev/null)
if [ -z "$PIDS" ]; then
    echo "没有运行的服务器 (端口 8000 无进程)"
    exit 0
fi

echo "🛑 停止服务器 (PID: $PIDS)..."
kill $PIDS 2>/dev/null
sleep 1

# 确认已停止
if lsof -ti:8000 > /dev/null 2>&1; then
    echo "⚠️  强制停止..."
    kill -9 $PIDS 2>/dev/null
fi

echo "✅ 服务器已停止"
