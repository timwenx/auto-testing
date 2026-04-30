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
echo "  Press Ctrl+C to stop."
echo "========================================"
echo

# Start both servers in background
python3 manage.py runserver 0.0.0.0:8000 &
BACKEND_PID=$!

sleep 2

cd frontend
npm run dev
cd ..

# Kill backend when frontend stops
wait $BACKEND_PID
echo

# Start Django in background
python3 manage.py runserver 0.0.0.0:8000 &
DJANGO_PID=$!

# Trap to kill Django when script exits
trap "kill $DJANGO_PID 2>/dev/null" EXIT

# Start Vue frontend in foreground
cd frontend
npm run dev
