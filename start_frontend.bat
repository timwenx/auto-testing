@echo off
setlocal

echo === MyTest Frontend ===
pushd "%~dp0frontend"
if errorlevel 1 (
	echo [ERROR] Failed to enter frontend directory.
	exit /b 1
)

echo Installing frontend dependencies...
call npm install
if errorlevel 1 (
	echo [WARN] npm install failed, continuing...
)

echo Starting dev server (http://localhost:3000)...
call npm run dev

popd
