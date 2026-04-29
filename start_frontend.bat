@echo off
echo === MyTest Frontend ===
cd frontend
echo 安装前端依赖...
call npm install
echo 启动开发服务器 (http://localhost:3000)...
call npm run dev
