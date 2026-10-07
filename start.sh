#!/bin/bash
echo "========================================"
echo "  Knowledge Base Agent System - Start"
echo "========================================"
echo

cd "$(dirname "$0")"

if [ -d ".venv" ]; then
    PYTHON=".venv/bin/python"
    UVICORN=".venv/bin/uvicorn"
elif [ -d "../.venv" ]; then
    echo "[INFO] Using existing virtual environment at ../.venv"
    PYTHON="../.venv/bin/python"
    UVICORN="../.venv/bin/uvicorn"
else
    echo "[INFO] Virtual environment not found, creating..."
    python3 -m venv .venv
    echo "[INFO] Installing dependencies..."
    .venv/bin/pip install -r requirements.txt
    PYTHON=".venv/bin/python"
    UVICORN=".venv/bin/uvicorn"
fi

echo "Starting Web server (port 8000)..."
echo
echo "========================================"
echo "  Frontend:   http://127.0.0.1:8000/"
echo "  API Docs:   http://127.0.0.1:8000/docs"
echo "========================================"
echo
"$UVICORN" webapis.app:app --host 127.0.0.1 --port 8000
