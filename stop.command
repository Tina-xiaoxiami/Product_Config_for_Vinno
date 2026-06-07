#!/bin/bash
# 产品配置管理系统停止脚本

# 加载用户环境变量
source ~/.zshrc 2>/dev/null || source ~/.bashrc 2>/dev/null
export PATH="/usr/local/bin:/opt/homebrew/bin:$HOME/.local/bin:$PATH"

BACKEND_PORT=8086
FRONTEND_PORT=3006

echo "=========================================="
echo "  产品配置管理系统停止脚本"
echo "=========================================="

# 停止后端
pid=$(lsof -t -i:$BACKEND_PORT 2>/dev/null)
if [ -n "$pid" ]; then
    echo "停止后端服务 (端口 $BACKEND_PORT, PID: $pid)..."
    kill $pid 2>/dev/null
else
    echo "后端服务未运行"
fi

# 停止前端
pid=$(lsof -t -i:$FRONTEND_PORT 2>/dev/null)
if [ -n "$pid" ]; then
    echo "停止前端服务 (端口 $FRONTEND_PORT, PID: $pid)..."
    kill $pid 2>/dev/null
else
    echo "前端服务未运行"
fi

echo ""
echo "所有服务已停止"