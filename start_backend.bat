@echo off
echo === MyTest - AI 驱动的自动化测试平台 ===
echo.

echo [1/3] 安装后端依赖...
pip install -r requirements.txt -q

echo [2/3] 执行数据库迁移...
python manage.py migrate --run-syncdb 2>nul
python manage.py migrate

echo [3/3] 启动后端服务 (http://localhost:8000)...
python manage.py runserver 0.0.0.0:8000
