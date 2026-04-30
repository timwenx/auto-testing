#!/bin/bash
# MyTest - Development Startup Script for Mac/Linux
# Usage: bash start_dev.sh
# Starts Django backend on :8000 and Vue frontend on :3000

set -e

echo "========================================"
echo "  MyTest - AI Test Platform (Dev Mode)"
echo "========================================"
echo

# Detect OS
OS_TYPE=$(uname -s)
if [[ "$OS_TYPE" == "Darwin" ]]; then
    echo "Detected: macOS"
elif [[ "$OS_TYPE" == "Linux" ]]; then
    echo "Detected: Linux"
else
    echo "Warning: Unknown OS - $OS_TYPE (script may not work correctly)"
fi
echo

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python3 not found. Please install Python 3.11+."
    exit 1
fi

# Check Node
if ! command -v node &> /dev/null; then
    echo "[ERROR] Node.js not found. Please install Node.js 18+."
    exit 1
fi

# Install Python dependencies
echo "[1/4] Installing Python dependencies..."
pip install -r requirements.txt -q 2>/dev/null || pip install -r requirements.txt

# Run migrations
echo "[2/4] Running database migrations..."
python3 manage.py migrate --run-syncdb 2>/dev/null || python3 manage.py migrate

# Install frontend dependencies
echo "[3/4] Installing frontend dependencies..."
cd frontend
if [ ! -d "node_modules" ]; then
    npm install --legacy-peer-deps 2>/dev/null || npm install
fi
cd ..

# Start servers
echo "[4/4] Starting servers..."
echo
echo "  Backend:  http://localhost:8000"
echo "  Frontend: http://localhost:3000"
echo "  Admin:    http://localhost:8000/admin/"
echo
echo "  Press Ctrl+C to stop all servers."
echo "========================================"
echo

# 清理函数: Ctrl+C 时同时杀掉两个进程
cleanup() {
    echo
    echo "Stopping servers..."
    kill $BACKEND_PID $FRONTEND_PID 2>/dev/null
    wait $BACKEND_PID $FRONTEND_PID 2>/dev/null
    echo "Stopped."
    exit 0
}
trap cleanup INT TERM

# 启动 Django 后端 (前台)
python3 manage.py runserver 0.0.0.0:8000 --noreload &
BACKEND_PID=$!

# 启动 Vue 前端 (前台)
cd frontend
npm run dev &
FRONTEND_PID=$!
cd ..

# 等待任一进程退出
wait -n $BACKEND_PID $FRONTEND_PID 2>/dev/null || wait $BACKEND_PID $FRONTEND_PID

echo "A server process exited. Stopping all..."
cleanup
