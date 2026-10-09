#!/bin/bash
# 产品配置管理系统 - 一键启动脚本

# 设置正确的 PATH（包含 Python 3.13 和 Homebrew）
export PATH="/Library/Frameworks/Python.framework/Versions/3.13/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

PYTHON="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
NPM="/opt/homebrew/bin/npm"

PROJECT_DIR="/Users/xiami/Documents/项目/产品配置管理系统"
FRONTEND_PORT=3006
BACKEND_PORT=8086
FRONTEND_URL="http://127.0.0.1:$FRONTEND_PORT"
BACKEND_URL="http://127.0.0.1:$BACKEND_PORT"
BACKEND_LOG="/tmp/product-config-backend.log"
FRONTEND_LOG="/tmp/product-config-frontend.log"
BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
    [ -z "$FRONTEND_PID" ] || kill "$FRONTEND_PID" 2>/dev/null
    [ -z "$BACKEND_PID" ] || kill "$BACKEND_PID" 2>/dev/null
}
trap cleanup EXIT
trap 'exit 0' INT TERM

wait_for_service() {
    local url="$1" pid="$2" log="$3"
    local attempt
    for ((attempt=0; attempt<30; attempt++)); do
        if ! kill -0 "$pid" 2>/dev/null; then
            break
        fi
        if curl --noproxy '*' --fail --silent --max-time 2 "$url" > /dev/null; then
            return 0
        fi
        sleep 1
    done
    echo "服务启动失败：$url"
    echo "启动日志：$log"
    tail -n 40 "$log"
    return 1
}

echo "=========================================="
echo "  产品配置管理系统启动脚本"
echo "=========================================="

cd "$PROJECT_DIR" || exit 1

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
cd "$PROJECT_DIR/backend" || exit 1
$PYTHON -m uvicorn main:app --host 127.0.0.1 --port $BACKEND_PORT --reload > "$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!
if ! wait_for_service "$BACKEND_URL" "$BACKEND_PID" "$BACKEND_LOG"; then
    exit 1
fi
echo "  ✓ 后端启动成功"

# 3. 启动前端
echo ""
echo "[Step 3] 启动前端服务 (端口 $FRONTEND_PORT)..."
cd "$PROJECT_DIR/frontend" || exit 1
$NPM run dev > "$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!
if ! wait_for_service "$FRONTEND_URL" "$FRONTEND_PID" "$FRONTEND_LOG"; then
    exit 1
fi
echo "  ✓ 前端启动成功"

# 4. 打开浏览器
echo ""
echo "[Step 4] 打开浏览器..."
open "$FRONTEND_URL"

echo ""
echo "=========================================="
echo "  启动完成！"
echo "=========================================="
echo "  前端地址: $FRONTEND_URL"
echo "  后端地址: $BACKEND_URL"
echo "  API文档:  $BACKEND_URL/docs"
echo ""
echo "  按 Ctrl+C 停止所有服务"
echo "=========================================="

wait
