@echo off
chcp 65001 >nul
set "PROJECT_DIR=%~dp0"
set "PYTHON=python"
if exist "%PROJECT_DIR%backend\.venv\Scripts\python.exe" set "PYTHON=%PROJECT_DIR%backend\.venv\Scripts\python.exe"
"%PYTHON%" "%PROJECT_DIR%tools\service_manager.py" start %*
if errorlevel 1 pause
