#!/bin/bash
# 产品配置管理系统 - 一键启动脚本

# 设置正确的 PATH（包含 Python 3.13 和 Homebrew）
export PATH="/Library/Frameworks/Python.framework/Versions/3.13/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

PYTHON="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
NPM="/opt/homebrew/bin/npm"

PROJECT_DIR="/Users/xiami/Documents/项目/产品配置管理系统"
FRONTEND_PORT=3006
BACKEND_PORT=8086

echo "=========================================="
echo "  产品配置管理系统启动脚本"
echo "=========================================="

cd "$PROJECT_DIR"

# 1. 停止已有进程
echo ""
echo "[Step 1] 检查并清理端口..."
for port in $BACKEND_PORT $FRONTEND_PORT; do
    pid=$(lsof -t -i:$port 2>/dev/null)
    if [ -n "$pid" ]; then
        echo "  - 停止端口 $port 的进程 (PID: $pid)"
        kill $pid 2>/dev/null
        sleep 1
    fi
done

# 2. 启动后端
echo ""
echo "[Step 2] 启动后端服务 (端口 $BACKEND_PORT)..."
cd "$PROJECT_DIR/backend"
$PYTHON -m uvicorn main:app --host 0.0.0.0 --port $BACKEND_PORT --reload &
BACKEND_PID=$!
sleep 3

if curl -s http://localhost:$BACKEND_PORT/ > /dev/null 2>&1; then
    echo "  ✓ 后端启动成功"
else
    echo "  ✗ 后端启动失败，检查 /tmp/backend.log"
fi

# 3. 启动前端
echo ""
echo "[Step 3] 启动前端服务 (端口 $FRONTEND_PORT)..."
cd "$PROJECT_DIR/frontend"
$NPM run dev &
FRONTEND_PID=$!
sleep 5

if curl -s http://localhost:$FRONTEND_PORT/ > /dev/null 2>&1; then
    echo "  ✓ 前端启动成功"
else
    echo "  ✗ 前端启动失败，检查 /tmp/frontend.log"
fi

# 4. 打开浏览器
echo ""
echo "[Step 4] 打开浏览器..."
open "http://localhost:$FRONTEND_PORT"

echo ""
echo "=========================================="
echo "  启动完成！"
echo "=========================================="
echo "  前端地址: http://localhost:$FRONTEND_PORT"
echo "  后端地址: http://localhost:$BACKEND_PORT"
echo "  API文档:  http://localhost:$BACKEND_PORT/docs"
echo ""
echo "  按 Ctrl+C 停止所有服务"
echo "=========================================="

# 捕获退出信号，停止服务
trap "echo ''; echo '正在停止服务...'; kill $BACKEND_PID 2>/dev/null; kill $FRONTEND_PID 2>/dev/null; echo '服务已停止'; exit 0" INT TERM

wait