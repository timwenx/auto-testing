# AI 自动化测试系统设计文档

**版本**: v1.0 | **更新时间**: 2026-04-29 | **状态**: 系统架构定义

---

## 📋 目录

1. [系统概述](#系统概述)
2. [核心工作流](#核心工作流)
3. [功能分层](#功能分层)
4. [技术架构](#技术架构)
5. [数据模型](#数据模型)
6. [集成步骤](#集成步骤)
7. [使用示例](#使用示例)
8. [API 接口规范](#api-接口规范)

---

## 系统概述

### 目的

构建一套**代码智能分析 + 自动化测试用例生成 + Agent 多轮对话调整 + Playwright 自动执行**的完整工作流。用户无需手写测试脚本，只需指定**测试功能**和**测试页面/接口**，系统自动：

1. **分析代码逻辑** → 反向推导测试场景
2. **生成初版用例** → 结构化步骤和期望结果
3. **多轮对话优化** → Agent 主动提问、补充场景
4. **自动执行验证** → Playwright 页面交互 + 结果上报

### 核心价值

- **降低测试编写成本** 60%+
- **自动化场景补全** （异常、权限、边界值）
- **可复用的测试库** （存储到数据库）
- **完整的执行记录** （截图 + 步骤日志）

---

## 核心工作流

```
┌─────────────────────────────────────────────────────────────┐
│                      用户输入请求                            │
│  "我需要测试登录页面的用户名输入验证功能"                    │
└──────────────────────┬──────────────────────────────────────┘
                       │
           ┌───────────▼───────────┐
           │  Claude CLI 代码分析   │
           │ (repo_service 读取代码)│
           │ • 查找登录页面代码     │
           │ • 分析验证逻辑        │
           │ • 提取 CSS 选择器     │
           └───────────┬───────────┘
                       │
        ┌──────────────▼──────────────┐
        │    生成初版测试用例(v1)     │
        │ • 步骤：打开页面→输入→点击  │
        │ • 选择器：#username-input   │
        │ • 预期结果：验证成功/失败   │
        │ 存储到数据库 (TestCase v1)  │
        └──────────────┬──────────────┘
                       │
        ┌──────────────▼──────────────┐
        │   Agent 多轮对话调整(v2~vN)  │
        │ Agent 提问：               │
        │ • 是否需要测试为空场景？    │
        │ • 是否需要测试特殊字符？    │
        │ • 是否需要登录权限验证？    │
        │ 用户回应 → Agent 修改用例   │
        │ 循环直到用户确认"可以执行"  │
        │ 最终用例保存 (TestCase vN)  │
        └──────────────┬──────────────┘
                       │
        ┌──────────────▼──────────────┐
        │   Agent 自动执行测试       │
        │ 解析用例 → 调用浏览工具    │
        │ • browser_navigate(url)    │
        │ • browser_fill(selector)   │
        │ • browser_click(selector)  │
        │ • browser_get_text()       │
        │ • browser_screenshot()     │
        │ 执行所有步骤 → 验证结果    │
        │ report_result() 上报结果   │
        └──────────────┬──────────────┘
                       │
        ┌──────────────▼──────────────┐
        │   保存执行记录到数据库      │
        │ (TestRun + 截图 + 日志)    │
        │ 展示给用户：PASS/FAIL       │
        │ 提供下载报告选项           │
        └──────────────────────────────┘
```

---

## 功能分层

### 第一层：Project（仓库配置）

**职责**：管理 Git 项目的连接和本地克隆

```
Project
├── name: 项目名称
├── repo_url: 被测项目 Git 地址 (如 GitLab/GitHub)
├── repo_username: Git 账号
├── repo_password: Git 密码/Token
├── local_repo_path: 本地克隆路径
├── target_base_url: 测试目标 URL (如 http://localhost:8000)
├── target_username: 目标应用账号
├── target_password: 目标应用密码
└── created_at: 创建时间
```

**初始化流程**：
```
用户提供 repo_url + 账号密码 
  → repo_service.clone_repo(project)
  → git clone 到 local_repo_path
  → 项目准备就绪
```

---

### 第二层：TestCase（测试用例）

**职责**：存储结构化的测试用例

```
TestCase
├── project_id: 关联项目
├── name: 用例名称
├── description: 用例描述
├── target_page_or_api: 测试目标页面/接口
├── steps: 测试步骤 (Markdown 或 JSON)
├── expected_result: 预期结果
├── markdown_content: 完整用例文档 (可选)
├── version: 用例版本号 (初版=1, 调整后递增)
├── status: 用例状态 (draft/approved/deprecated)
├── created_by: 生成方式 (claude_cli/manual/agent)
├── created_at: 创建时间
├── updated_at: 最后更新时间
└── conversation_history: 对话记录 (JSON)
```

**典型结构示例**：
```json
{
  "name": "用户名输入验证",
  "description": "测试登录页面的用户名输入验证功能",
  "steps": [
    {"action": "navigate", "target": "http://app.local/login", "desc": "打开登录页面"},
    {"action": "fill", "selector": "#username-input", "value": "invalid@", "desc": "输入非法用户名"},
    {"action": "click", "selector": "button.submit", "desc": "点击登录按钮"},
    {"action": "wait_for", "selector": ".error-message", "desc": "等待错误提示出现"},
    {"action": "get_text", "selector": ".error-message", "desc": "验证错误信息内容"}
  ],
  "expected_result": "页面显示'用户名格式错误'提示信息"
}
```

---

### 第三层：TestRun（测试执行记录）

**职责**：记录每次测试执行的详细结果

```
TestRun
├── testcase_id: 关联用例
├── project_id: 关联项目
├── status: 执行结果 (passed/failed/error)
├── summary: 一句话总结
├── details: 详细说明
├── started_at: 开始时间
├── ended_at: 结束时间
├── duration_ms: 执行耗时
├── screenshots: 截图路径列表 (JSON)
├── step_logs: 逐步执行日志 (JSON)
└── agent_response: Agent 返回的信息 (JSON)
```

---

### 第四层：Repository Service（仓库服务）

**职责**：代码分析和文件操作

**现有接口**（基于 `repo_service.py`）：

```python
# 文件树遍历
get_repo_file_tree(project, max_depth=3) -> str

# 文件内容读取
read_file_content(project, path) -> str

# 代码搜索
search_code(project, keyword) -> List[{file, line_num, line}]

# 需要新增接口
find_page_or_api(project, target_name) -> List[str]
  # 根据页面名/API路由查找对应代码

extract_selectors(project, file_path) -> Dict
  # 从 HTML/Vue/React 代码提取 CSS 选择器

analyze_test_logic(project, file_path, function_name) -> str
  # 分析测试逻辑，返回关键步骤和验证点
```

---

### 第五层：Agent Service（AI 工作流）

**职责**：调用 Claude API / Anthropic Agent

#### 初版用例生成（Claude CLI）

```python
def generate_testcase_claude_cli(
    project: Project,
    test_feature: str,        # "用户名输入验证"
    test_target: str,         # "登录页面"
) -> TestCase:
    """
    步骤:
    1. 在本地仓库中查找登录页面代码
    2. 分析代码实现逻辑
    3. 推测验证规则
    4. 生成测试步骤
    5. 保存到数据库并返回
    """
```

#### 多轮对话调整（Anthropic Agent）

```python
def refine_testcase_with_agent(
    testcase: TestCase,
    project: Project,
    user_feedback: str = None,
) -> str:  # Agent 提问/修改内容
    """
    步骤:
    1. 如果 user_feedback 存在，Agent 基于反馈修改用例
    2. 如果 user_feedback 不存在，Agent 主动提问补充场景
    3. 保存修改历史到 conversation_history
    4. 返回 Agent 的提问或修改建议
    5. 用户 confirm() 后才进入执行阶段
    """
```

#### 自动执行测试（Anthropic Agent + Tools）

```python
def execute_testcase_with_agent(
    testcase: TestCase,
    project: Project,
) -> TestRun:
    """
    步骤:
    1. 构建 Agent system_prompt（包含用例、项目信息）
    2. 初始化 Playwright 浏览器
    3. Agent 调用 11 个浏览工具完成测试
    4. 每个工具调用后 Agent 评估结果
    5. 最后调用 report_result() 上报结果
    6. 保存 TestRun 到数据库
    """
```

---

## 技术架构

### 整体架构图

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend (Vue/React)                      │
│  • 项目配置页面 → Project CRUD                             │
│  • 用例生成/编辑页面 → TestCase CRUD                       │
│  • 执行结果页面 → TestRun 查看 + 报告下载                 │
│  • 对话调整界面 → 与 Agent 实时对话                        │
└──────────────────┬──────────────────────────────────────────┘
                   │ REST API
┌──────────────────▼──────────────────────────────────────────┐
│                Django Backend (core app)                     │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  Views 层:                                                   │
│  • ProjectViewSet → /api/projects/                         │
│  • TestCaseViewSet → /api/testcases/                       │
│  • TestRunViewSet → /api/testruns/                         │
│  • AgentAPIView → /api/agent/generate, /refine, /execute   │
│                                                              │
│  Services 层:                                                │
│  • repo_service.py → 代码分析、文件操作                    │
│  • agent_service.py → Claude CLI + Anthropic Agent         │
│  • execution_engine.py → 浏览器控制、步骤执行             │
│  • middleware.py → 项目上下文注入                          │
│                                                              │
│  Models 层 (models.py):                                     │
│  • Project, TestCase, TestRun                              │
│                                                              │
└──────────────────┬──────────────────────────────────────────┘
                   │
      ┌────────────┼────────────┐
      │            │            │
      ▼            ▼            ▼
  ┌────────┐  ┌─────────┐  ┌──────────────┐
  │ SQLite │  │   Git   │  │ Anthropic    │
  │ 数据库  │  │  仓库   │  │ API + Tools  │
  │        │  │ (本地)  │  │              │
  └────────┘  └─────────┘  └──────────────┘
      │
      ▼
┌──────────────────────────────────────────┐
│  Screenshots / Logs / Reports (文件系统)  │
└──────────────────────────────────────────┘
```

### 工具清单

#### 仓库探索工具 (4 个)

| 工具名 | 功能 | 输入 | 输出 |
|------|------|------|------|
| `list_files` | 列出目录树 | max_depth | 格式化目录树文本 |
| `read_file` | 读文件内容 | path | 文件内容 |
| `search_code` | 代码搜索 | keyword | 匹配行列表 |
| `list_directory` | 列单层目录 | path | 文件/目录列表 |

#### 浏览器工具 (7 个)

| 工具名 | 功能 | 输入 | 输出 |
|------|------|------|------|
| `browser_navigate` | 打开 URL | url | 导航后的 URL |
| `browser_click` | 点击元素 | selector | 操作确认 |
| `browser_fill` | 输入文本 | selector, value | 输入确认 |
| `browser_press_key` | 按键 | key | 按键确认 |
| `browser_wait_for` | 等待元素/加载 | selector, timeout | 等待完成 |
| `browser_get_text` | 获取文本 | selector | 元素文本 |
| `browser_screenshot` | 截图 | save_path | 图片路径 |

#### 报告工具 (1 个)

| 工具名 | 功能 | 输入 | 输出 |
|------|------|------|------|
| `report_result` | 上报测试结果 | status, summary, details | 结果记录 |

---

## 数据模型

### 核心模型定义（models.py 补充）

```python
# 已有的 Project 模型需要补充字段
class Project(models.Model):
    name = models.CharField(max_length=100, unique=True)
    
    # Git 仓库配置
    repo_url = models.URLField()
    repo_username = models.CharField(max_length=100, blank=True)
    repo_password = models.CharField(max_length=500, blank=True)  # 建议加密
    local_repo_path = models.CharField(max_length=500, blank=True)
    
    # 测试基础配置
    target_base_url = models.URLField()
    target_username = models.CharField(max_length=100, blank=True)
    target_password = models.CharField(max_length=500, blank=True)  # 建议加密
    
    # 元数据
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return self.name


class TestCase(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('approved', 'Approved'),
        ('deprecated', 'Deprecated'),
    ]
    
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='testcases')
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    
    # 测试目标
    target_page_or_api = models.CharField(max_length=500)  # 如 "LoginPage" 或 "/api/login"
    
    # 用例内容
    steps = models.JSONField(default=list)  # 步骤数组
    expected_result = models.TextField()
    markdown_content = models.TextField(blank=True)  # 完整文档
    
    # 版本和状态
    version = models.IntegerField(default=1)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    created_by = models.CharField(max_length=50)  # "claude_cli" / "manual" / "agent"
    
    # 对话历史
    conversation_history = models.JSONField(default=list)  # [{role: "user"/"assistant", content: "..."}]
    
    # 时间戳
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.project.name} - {self.name} (v{self.version})"


class TestRun(models.Model):
    STATUS_CHOICES = [
        ('passed', 'Passed'),
        ('failed', 'Failed'),
        ('error', 'Error'),
    ]
    
    testcase = models.ForeignKey(TestCase, on_delete=models.CASCADE, related_name='runs')
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='test_runs')
    
    # 执行结果
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    summary = models.CharField(max_length=500)
    details = models.TextField(blank=True)
    
    # 执行日志
    screenshots = models.JSONField(default=list)  # 截图路径列表
    step_logs = models.JSONField(default=list)    # 逐步执行日志
    agent_response = models.JSONField(default=dict)  # Agent 返回的原始响应
    
    # 时间
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField()
    duration_ms = models.IntegerField()  # 执行耗时（毫秒）
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.testcase.name} - {self.status} ({self.created_at})"
```

---

## 集成步骤

### Step 1: 更新 models.py

```bash
# 1. 编辑 My_Test/core/models.py，补充上述 TestCase 和 TestRun 模型
# 2. 创建迁移
python manage.py makemigrations
python manage.py migrate
```

### Step 2: 实现 agent_service.py

```python
# My_Test/core/agent_service.py

from anthropic import Anthropic
from .models import TestCase, TestRun, Project
from . import repo_service
from .agent_tools import get_tool_schemas, get_tool_executor

class AgentService:
    def __init__(self):
        self.client = Anthropic()
    
    def generate_testcase_v1(self, project: Project, test_feature: str, test_target: str):
        """
        初版用例生成（Claude CLI）
        返回 TestCase 对象
        """
        # 1. 查找代码
        # 2. 分析逻辑
        # 3. 生成用例
        pass
    
    def refine_with_agent(self, testcase: TestCase, project: Project, user_feedback: str = None):
        """
        多轮对话调整
        返回 Agent 提问/建议内容
        """
        pass
    
    def execute_with_agent(self, testcase: TestCase, project: Project):
        """
        自动执行测试
        返回 TestRun 对象
        """
        pass
```

### Step 3: 添加 API 端点

```python
# My_Test/core/views.py

from rest_framework.views import APIView
from rest_framework.response import Response
from .models import TestCase, TestRun, Project
from .agent_service import AgentService

class AgentAPIView(APIView):
    def post(self, request, *args, **kwargs):
        """
        POST /api/agent/generate
        POST /api/agent/refine
        POST /api/agent/execute
        """
        action = request.data.get('action')
        
        if action == 'generate':
            # 调用 AgentService.generate_testcase_v1
            pass
        elif action == 'refine':
            # 调用 AgentService.refine_with_agent
            pass
        elif action == 'execute':
            # 调用 AgentService.execute_with_agent
            pass
```

### Step 4: Claude CLI 命令行工具

```bash
# 新建 My_Test/claude_cli.py（或在 .../bin 目录）

from core.models import Project, TestCase
from core.agent_service import AgentService

if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("Usage: claude_cli.py <project_id> <test_feature> <test_target>")
        sys.exit(1)
    
    project_id = sys.argv[1]
    test_feature = sys.argv[2]
    test_target = sys.argv[3]
    
    project = Project.objects.get(id=project_id)
    service = AgentService()
    
    testcase = service.generate_testcase_v1(project, test_feature, test_target)
    print(f"Generated TestCase: {testcase.id}")
```

---

## 使用示例

### 场景：测试用户登录页面的用户名输入验证

#### 1️⃣ 初期化项目

```bash
# Django shell
python manage.py shell

from core.models import Project

project = Project.objects.create(
    name="MyApp",
    repo_url="https://github.com/mycompany/myapp.git",
    repo_username="my_user",
    repo_password="my_token",
    target_base_url="http://localhost:8000",
    target_username="testuser",
    target_password="testpass"
)

# 克隆仓库
from core import repo_service
repo_service.clone_repo(project)
# → local_repo_path: /tmp/myapp_repo/
```

#### 2️⃣ Claude CLI 生成初版用例

```bash
# 命令行
python my_test/claude_cli.py 1 "用户名输入验证" "登录页面"

# 输出
# Generated TestCase: 42
# 用例已保存到数据库
```

#### 3️⃣ Agent 多轮对话调整

```python
# Web 页面交互（WebSocket 或轮询）
POST /api/agent/refine
{
    "testcase_id": 42,
    "user_feedback": null  # 第一次不需要反馈，Agent 主动提问
}

# 返回 Agent 提问
{
    "message": "我发现这个测试场景没有涵盖以下情况：\n1. 是否需要测试特殊字符输入（如 <>\"'）？\n2. 是否需要测试超长输入？\n3. 是否需要测试 XSS 注入？",
    "suggestions": ["特殊字符", "超长输入", "XSS注入"]
}

# 用户回应
POST /api/agent/refine
{
    "testcase_id": 42,
    "user_feedback": "是的，需要测试特殊字符和超长输入，但不需要 XSS 注入"
}

# Agent 修改用例并再次提问
# ...循环直到用户 confirm()
```

#### 4️⃣ 自动执行测试

```python
# 用户点击"执行"按钮
POST /api/agent/execute
{
    "testcase_id": 42
}

# 返回 TestRun
{
    "test_run_id": 123,
    "status": "passed",
    "summary": "用例执行成功，所有验证通过",
    "details": "共 5 步，耗时 3.2s...",
    "screenshots": ["/media/screenshots/run_123_step1.png", ...],
    "duration_ms": 3200
}
```

---

## API 接口规范

### 项目管理

```http
# 创建项目
POST /api/projects/
Content-Type: application/json
{
    "name": "MyApp",
    "repo_url": "https://github.com/mycompany/myapp.git",
    "repo_username": "user",
    "repo_password": "token",
    "target_base_url": "http://localhost:8000",
    "target_username": "test",
    "target_password": "pass"
}

# 获取项目列表
GET /api/projects/

# 获取单个项目
GET /api/projects/{id}/

# 克隆仓库
POST /api/projects/{id}/clone/
```

### 用例管理

```http
# 创建用例（手动）
POST /api/testcases/
{
    "project_id": 1,
    "name": "用户名输入验证",
    "description": "测试登录页面的用户名输入验证",
    "target_page_or_api": "LoginPage",
    "steps": [...]
    "expected_result": "错误提示出现"
}

# 获取用例列表
GET /api/testcases/?project_id=1

# 获取单个用例（含对话历史）
GET /api/testcases/{id}/

# 更新用例（编辑）
PATCH /api/testcases/{id}/
```

### Agent 工作流

```http
# 1. 生成初版用例（Claude CLI）
POST /api/agent/generate
{
    "project_id": 1,
    "test_feature": "用户名输入验证",
    "test_target": "登录页面"
}
↓
{
    "testcase_id": 42,
    "version": 1,
    "steps": [...],
    "markdown": "..."
}

# 2. 调整用例（Agent 多轮对话）
POST /api/agent/refine
{
    "testcase_id": 42,
    "user_feedback": "是否需要测试特殊字符？"  # 可选，首次为 null
}
↓
{
    "version": 2,
    "updated_steps": [...],
    "agent_message": "已添加特殊字符测试场景。是否还需要其他场景？"
}

# 3. 确认执行
POST /api/agent/confirm
{
    "testcase_id": 42
}
↓
{
    "status": "approved",
    "ready_to_execute": true
}

# 4. 执行测试
POST /api/agent/execute
{
    "testcase_id": 42
}
↓
{
    "test_run_id": 123,
    "status": "passed",
    "summary": "执行成功",
    "screenshots": [...],
    "duration_ms": 3200
}
```

### 执行结果查询

```http
# 获取测试运行列表
GET /api/testruns/?testcase_id=42

# 获取单个测试运行
GET /api/testruns/{id}/

# 下载报告
GET /api/testruns/{id}/report/?format=html|json|pdf
```

---

## 下一步规划

- [ ] 实现 `agent_service.py` 中的三个核心方法
- [ ] 补充 Django Models 和迁移
- [ ] 添加 REST API 端点
- [ ] Claude CLI 命令行工具
- [ ] 前端对话组件（WebSocket 实时更新）
- [ ] 报告生成和下载功能
- [ ] 敏感信息加密（repo_password, target_password）
- [ ] 多项目隔离和权限控制

---

**文档版本历史**
| 版本 | 日期 | 变更 |
|-----|------|------|
| v1.0 | 2026-04-29 | 初始版本：系统架构、工作流、数据模型 |

