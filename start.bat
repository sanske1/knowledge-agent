@echo off
title Knowledge Base Agent System

echo ========================================
echo   Knowledge Base Agent System - Start
echo ========================================
echo.

cd /d "%~dp0"

REM Resolve python: prefer local .venv, then parent .venv, else create new
set "PYTHON="
if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
    set "UVICORN=.venv\Scripts\uvicorn.exe"
) else if exist "..\.venv\Scripts\python.exe" (
    echo [INFO] Using existing virtual environment at ..\.venv
    set "PYTHON=..\.venv\Scripts\python.exe"
    set "UVICORN=..\.venv\Scripts\uvicorn.exe"
) else (
    echo [INFO] Virtual environment not found, creating...
    python -m venv .venv
    echo [INFO] Installing dependencies...
    .venv\Scripts\pip.exe install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    set "PYTHON=.venv\Scripts\python.exe"
    set "UVICORN=.venv\Scripts\uvicorn.exe"
)

echo Starting Web server (port 8000)...
echo.
echo ========================================
echo   Frontend:   http://127.0.0.1:8000/
echo   API Docs:   http://127.0.0.1:8000/docs
echo docker 
echo ollama 
echo mcpserver
echo ========================================
echo.
"%UVICORN%" webapis.app:app --host 0.0.0.0 --port 8000



pause
