@echo off
chcp 65001 >nul
title 产品配置管理系统

set PROJECT_DIR=%~dp0
set BACKEND_DIR=%PROJECT_DIR%backend
set FRONTEND_DIR=%PROJECT_DIR%frontend

echo === 产品配置管理系统 ===
echo.

:: 停止已有进程
taskkill /F /FI "WINDOWTITLE eq 产品配置管理系统-后端" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq 产品配置管理系统-前端" >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8086 " ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":3006 " ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1
timeout /t 2 /nobreak >nul

:: 启动后端
echo 正在启动后端...
cd /d "%BACKEND_DIR%"
start "产品配置管理系统-后端" /min cmd /c "python -m uvicorn main:app --host 127.0.0.1 --port 8086"
cd /d "%PROJECT_DIR%"

timeout /t 2 /nobreak >nul

:: 启动前端
echo 正在启动前端...
cd /d "%FRONTEND_DIR%"
start "产品配置管理系统-前端" /min cmd /c "npx vite --port 3006 --strictPort"
cd /d "%PROJECT_DIR%"

timeout /t 4 /nobreak >nul

:: 状态检查
echo.
curl -s http://127.0.0.1:8086/ >nul 2>&1 && (echo [OK] 后端: http://localhost:8086) || (echo [FAIL] 后端启动失败，请检查 Python 环境)
curl -s http://127.0.0.1:3006/ >nul 2>&1 && (echo [OK] 前端: http://localhost:3006) || (echo [FAIL] 前端启动失败，请检查 Node.js 环境)

echo.
echo 服务已在后台运行，关闭此窗口不影响服务。
echo 如需停止服务，请双击 stop.bat
echo.

timeout /t 1 /nobreak >nul
start http://localhost:3006
