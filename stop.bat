@echo off
chcp 65001 >nul

echo 正在停止产品配置管理系统...

taskkill /F /FI "WINDOWTITLE eq 产品配置管理系统-后端" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq 产品配置管理系统-前端" >nul 2>&1

for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8086 " ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":3006 " ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1

echo 已停止。
timeout /t 2 /nobreak >nul
