# Mac 配置指南

## 系统要求

- **Python**: 3.11+  
- **Node.js**: 18+  
- **macOS**: 10.15+

## 安装步骤

### 1. 使用 Homebrew 安装依赖（推荐）

```bash
# 安装 Python 3.11+ (如果还没有)
brew install python@3.12

# 安装 Node.js (如果还没有)
brew install node
```

### 2. 验证版本

```bash
python3 --version      # 应该是 3.11+
node --version         # 应该是 18+
```

### 3. 安装虚拟环境（可选但推荐）

```bash
cd /path/to/auto-testing
python3 -m venv venv
source venv/bin/activate
```

## 启动方式

### 方式 1: 一键启动（推荐）

```bash
bash start_dev.sh
```

- 自动安装 Python 依赖
- 自动执行数据库迁移
- 启动后端（:8000）和前端（:3000）

### 方式 2: 分别启动

#### 启动后端

```bash
bash start_backend.sh
```

#### 新建终端，启动前端

```bash
cd frontend
npm run dev
```

### 方式 3: 手动启动

```bash
# 终端 1: 后端
pip install -r requirements.txt
python3 manage.py migrate --run-syncdb
python3 manage.py runserver 0.0.0.0:8000

# 终端 2: 前端
cd frontend
npm install
npm run dev
```

## 访问地址

- **前端**: http://localhost:3000
- **后端 API**: http://localhost:8000/api/
- **Django 管理后台**: http://localhost:8000/admin/

## 常见问题

### 1. 403 Forbidden 错误

如果截图访问返回 403，这通常是路径权限问题：

```bash
# 检查 media 目录权限
ls -la media/
chmod -R 755 media/

# 清理临时文件并重新运行
rm -rf /tmp/screenshot_* 2>/dev/null
python3 manage.py migrate --run-syncdb
```

### 2. npm install 出错

```bash
# 使用 legacy-peer-deps 标志
cd frontend
npm install --legacy-peer-deps
npm run dev
```

### 3. Python 模块不找到

```bash
# 重新安装所有依赖
pip install -r requirements.txt --force-reinstall

# 或在虚拟环境中
source venv/bin/activate
pip install -r requirements.txt
```

### 4. 端口已被占用

```bash
# 查找占用 8000 的进程
lsof -i :8000

# 查找占用 3000 的进程
lsof -i :3000

# 杀死进程（例如 PID 12345）
kill -9 12345
```

## 开发工作流

### 后端修改

编辑 `core/views.py` 或其他 Python 文件后，Django 会自动重新加载。

### 前端修改

编辑 `frontend/src/` 下的文件后，Vite 会自动热更新。

## 生产部署

```bash
# 构建前端
cd frontend
npm run build

# 启动生产服务器
pip install gunicorn
gunicorn backend.wsgi:application --bind 0.0.0.0:8000
```

## 其他有用命令

```bash
# 创建超级用户
python3 manage.py createsuperuser

# 清理数据库
python3 manage.py flush

# 查看数据库日志
python3 manage.py dbshell

# 运行测试
python3 manage.py test
```
