#!/bin/bash
# 产品配置管理系统 - 一键启动

PROJECT_DIR="/Users/xiami/Documents/项目/产品配置管理系统"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"

echo "=== 产品配置管理系统 ==="
echo ""

# 强制停止所有相关进程
pkill -9 -f "uvicorn.*8086" 2>/dev/null
pkill -9 -f "vite.*3006" 2>/dev/null
sleep 2

# 再次确认端口已释放
lsof -ti:3006 2>/dev/null | xargs kill -9 2>/dev/null
lsof -ti:8086 2>/dev/null | xargs kill -9 2>/dev/null
sleep 1

# 启动后端（使用 nohup 独立运行）
cd "$BACKEND_DIR"
nohup python3 -m uvicorn main:app --host 127.0.0.1 --port 8086 > /tmp/backend.log 2>&1 &
BACKEND_PID=$!
cd "$PROJECT_DIR"

sleep 2

# 启动前端（使用 nohup 独立运行）
cd "$FRONTEND_DIR"
nohup npm run dev -- --port 3006 --strictPort > /tmp/frontend.log 2>&1 &
FRONTEND_PID=$!
cd "$PROJECT_DIR"

sleep 4

# 状态检查
BACKEND_OK=$(curl -s http://127.0.0.1:8086/ > /dev/null && echo "✓" || echo "✗")
FRONTEND_OK=$(curl -s http://127.0.0.1:3006/ > /dev/null && echo "✓" || echo "✗")

echo "$BACKEND_OK 后端: http://localhost:8086 (PID: $BACKEND_PID)"
echo "$FRONTEND_OK 前端: http://localhost:3006 (PID: $FRONTEND_PID)"

echo ""
echo "服务已在后台独立运行，关闭此窗口不影响服务。"
echo "如需停止服务，请双击桌面上的「停止配置管理.app」"
echo ""

sleep 1
open http://localhost:3006