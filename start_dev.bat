@echo off
REM MyTest - Development Startup Script
REM Usage: start_dev.bat
REM
REM Starts Django backend on :8000 and Vue frontend on :3000

echo ========================================
echo   MyTest - AI Test Platform (Dev Mode)
echo ========================================
echo.

REM Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Please install Python 3.11+.
    pause
    exit /b 1
)

REM Check Node
node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Node.js not found. Please install Node.js 18+.
    pause
    exit /b 1
)

REM Install Python dependencies
echo [1/4] Installing Python dependencies...
pip install -r requirements.txt -q
if %errorlevel% neq 0 (
    echo [WARN] pip install had issues, continuing...
)

REM Run migrations
echo [2/4] Running database migrations...
python manage.py migrate --run-syncdb 2>nul

REM Install frontend dependencies
echo [3/4] Installing frontend dependencies...
cd frontend
if not exist node_modules (
    call npm install
)
cd ..

REM Start servers
echo [4/4] Starting servers...
echo.
echo   Backend:  http://localhost:8000
echo   Frontend: http://localhost:3000
echo   Admin:    http://localhost:8000/admin/
echo.
echo   Press Ctrl+C to stop.
echo ========================================
echo.

REM Start Django in background
start "MyTest-Backend" /D "%~dp0" cmd /c "python manage.py runserver 0.0.0.0:8000"

REM Start Vue frontend in foreground
cd frontend
npm run dev
