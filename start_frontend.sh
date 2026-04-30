#!/bin/bash
# MyTest - Frontend Development Startup Script for Mac/Linux
# Usage: bash start_frontend.sh

set -e

echo "========================================"
echo "  MyTest - Frontend Development"
echo "========================================"
echo

# Check Node
if ! command -v node &> /dev/null; then
    echo "[ERROR] Node.js not found. Please install Node.js 18+."
    echo "  Install with: brew install node"
    exit 1
fi

# Show Node version
echo "Node version: $(node --version)"
echo "npm version: $(npm --version)"
echo

# Navigate to frontend
cd frontend

# Install dependencies if needed
if [ ! -d "node_modules" ]; then
    echo "Installing dependencies..."
    npm install --legacy-peer-deps 2>/dev/null || npm install
fi

# Start development server
echo
echo "Starting Vue frontend development server..."
echo "  URL: http://localhost:3000"
echo
echo "Press Ctrl+C to stop."
echo "========================================"
echo

npm run dev
