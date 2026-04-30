#!/bin/bash
# MyTest - Backend Development Startup Script for Mac/Linux
# Usage: bash start_backend.sh

set -e

echo "========================================"
echo "  MyTest - AI Test Platform (Backend)"
echo "========================================"
echo

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python3 not found. Please install Python 3.11+."
    exit 1
fi

# Install Python dependencies
echo "[1/2] Installing Python dependencies..."
pip install -r requirements.txt -q 2>/dev/null || pip install -r requirements.txt

# Run migrations
echo "[2/2] Running database migrations..."
python3 manage.py migrate --run-syncdb 2>/dev/null || python3 manage.py migrate

# Start backend server
echo
echo "Starting Django backend..."
echo "  URL: http://localhost:8000"
echo "  Admin: http://localhost:8000/admin/"
echo "  API: http://localhost:8000/api/"
echo
echo "Press Ctrl+C to stop."
echo "========================================"
echo

python3 manage.py runserver 0.0.0.0:8000
