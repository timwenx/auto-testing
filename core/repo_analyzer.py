"""
仓库分析服务 — 通过 Claude CLI 或 Anthropic SDK 分析仓库代码，发现前端页面路由和 REST API 端点

核心流程：
1. clone_or_update_repo 确保代码最新
2. 根据 analysis_engine 设置选择 CLI 或 SDK 模式:
   - CLI 模式: 直接调用 Claude Code CLI（自动读取仓库文件）
   - SDK 模式: 手动搜索路由关键词 + 读取代码片段 + 调用 API
3. 解析响应存入 RepoAnalysis.discovered_items
"""
import json
import logging
import re
import threading

from django.utils import timezone

from . import repo_service
from .ai_engine import _get_client, _get_model

logger = logging.getLogger(__name__)

ANALYSIS_SYSTEM_PROMPT = """你是一个专业的代码分析工程师。你的任务是从项目源代码中识别所有对外暴露的前端页面路由和 REST API 端点，并提取关键的交互元素和 API 参数信息。

## 分析要求

### 要提取的内容
1. **前端页面路由**: Vue Router / React Router / Angular Router 中定义的可访问页面路径
   - 路由路径 (path)
   - 页面/组件名称
   - 页面功能描述
   - **页面交互元素**: 从组件模板中提取关键交互元素（按钮、表单、输入框、下拉框、表格）的 CSS 选择器。优先级: `#id` > `[name=xxx]` > `[data-testid=xxx]` > `.class-name`。每个页面最多 10 个元素。
   - 每个元素需包含: selector、type（input|button|select|form|table|link）、label（中文描述）、description（可选详细说明）

2. **REST API 端点**: 对外暴露的 HTTP API 接口
   - URL 路径
   - HTTP 方法 (GET/POST/PUT/DELETE/PATCH)
   - 功能描述
   - **请求参数**: 从 Controller/View 函数签名、装饰器参数、Serializer/Schema 定义中提取。每个 API 最多 10 个参数。
     每个参数需包含: name、in（query|path|body|header）、type、required（布尔值）、description
   - **响应字段**: 从返回的 Serializer/Schema/DTO 定义中提取。最多 10 个字段。
     每个字段需包含: name、type、description
   - 包括以下技术栈的路由定义：
     - Spring Boot: @GetMapping, @PostMapping, @PutMapping, @DeleteMapping, @RequestMapping
     - Flask: @app.route, @blueprint.route
     - Django: urlpatterns, path(), re_path()
     - Express: app.get, app.post, router.get, router.post
     - FastAPI: @app.get, @app.post

### 页面元素提取规则
- 分析 Vue/React 组件模板（template/JSX），提取关键交互元素的 id、class、name、data-testid 等属性
- **优先提取稳定的 selector**: `id` > `name` > `data-testid` > `class`（框架可能生成动态 class）
- 只提取**有实际测试价值**的元素：按钮、表单、输入框、下拉框、表格、链接，忽略纯展示元素
- 如果元素有 placeholder 或 label 文本，将其作为 description

### API 参数提取规则
- 从 Controller/View 的函数签名中提取 query/path 参数
- 从 @RequestBody / Serializer / Schema 类定义中提取 body 参数
- 从 @RequestHeader / header 定义中提取 header 参数
- 从返回类型的 Serializer/Schema 中提取响应字段

### 不要包含的内容（排除）
- 内部 Service 层类和方法
- DAO / Repository 层
- 工具类和辅助函数
- Controller 内部的私有方法（只提取带路由注解/装饰器的公开端点）
- 中间件、拦截器、过滤器
- 配置文件
- 数据库迁移

### 返回格式
返回一个 JSON 对象（不要用 markdown 代码块包裹），结构如下：
{
  "pages": [
    {
      "path": "/users",
      "name": "用户管理页",
      "description": "用户列表的增删改查",
      "source_file": "src/views/UserManager.vue",
      "elements": [
        {"selector": "#search-input", "type": "input", "label": "搜索框", "description": "用户名模糊搜索"},
        {"selector": ".btn-add-user", "type": "button", "label": "新增用户"},
        {"selector": "#user-form", "type": "form", "label": "用户表单"},
        {"selector": "[name='role']", "type": "select", "label": "角色选择"}
      ]
    }
  ],
  "apis": [
    {
      "path": "/api/users",
      "method": "GET",
      "name": "获取用户列表",
      "description": "分页查询用户列表",
      "source_file": "src/controllers/UserController.java",
      "params": [
        {"name": "page", "in": "query", "type": "integer", "required": false, "description": "页码"},
        {"name": "size", "in": "query", "type": "integer", "required": false, "description": "每页数量"}
      ],
      "response_fields": [
        {"name": "id", "type": "integer", "description": "用户ID"},
        {"name": "username", "type": "string", "description": "用户名"}
      ]
    }
  ]
}

### 重要约束
- 每个页面的 elements 最多 10 个，每个 API 的 params 和 response_fields 各最多 10 个
- elements/params/response_fields 可以为空数组（如果无法提取）
- 如果无法识别页面或 API（比如纯后端服务没有前端路由），对应的数组返回空即可
- 只返回 JSON，不要其他文字"""

# 搜索路由定义的关键词（SDK 模式使用）
_ROUTE_KEYWORDS = [
    'router', 'routes', 'path(', 're_path(',
    '@RequestMapping', '@GetMapping', '@PostMapping', '@PutMapping', '@DeleteMapping',
    '@app.route', '@blueprint.route', '@router.',
    'urlpatterns',
]

# 搜索表单/参数定义的关键词（SDK 模式使用 — 用于丰富 elements 和 params 信息）
_FORM_KEYWORDS = [
    # Vue/React 表单组件
    'el-form', 'el-input', 'el-button', 'el-select',
    '<form', '<input', '<button', '<select', '<textarea',
    'data-testid',
    # API 参数定义
    '@RequestParam', '@PathVariable', '@RequestBody', '@RequestHeader',
    'serializer', 'Serializer', 'Schema',
    'RequestParam', 'PathParam', 'QueryParam',
    # Django DRF
    'serializers.Serializer', 'APIView',
]


def analyze_repo(project) -> 'RepoAnalysis':
    """
    分析项目仓库代码，发现页面路由和 API 端点。

    根据 analysis_engine 系统设置选择 CLI 或 SDK 分析模式。

    Args:
        project: Project 模型实例

    Returns:
        RepoAnalysis 实例（含 discovered_items 和分析日志）
    """
    from .models import RepoAnalysis

    analysis = RepoAnalysis.objects.create(
        project=project,
        status='analyzing',
        local_repo_path=project.local_repo_path or '',
        started_at=timezone.now(),
        last_heartbeat=timezone.now(),
    )

    # 后台心跳线程：每 10 秒更新 last_heartbeat
    _stop_heartbeat = threading.Event()
    _analysis_id = analysis.id

    def _heartbeat_loop():
        while not _stop_heartbeat.wait(10):
            try:
                from django.db import close_old_connections
                close_old_connections()
                obj = RepoAnalysis.objects.get(pk=_analysis_id)
                obj.last_heartbeat = timezone.now()
                obj.save(update_fields=['last_heartbeat'])
                logger.debug("[RepoAnalyzer] Heartbeat for analysis #%s", _analysis_id)
            except Exception as e:
                logger.warning("[RepoAnalyzer] Heartbeat failed: %s", e)

    heartbeat_thread = threading.Thread(target=_heartbeat_loop, daemon=True)
    heartbeat_thread.start()

    try:
        # 1. 确保仓库代码最新
        logger.info("[RepoAnalyzer] Cloning/updating repo for project #%s", project.id)
        local_path = repo_service.clone_or_update_repo(project)
        analysis.local_repo_path = local_path
        analysis.save(update_fields=['local_repo_path'])

        # 2. 根据设置选择分析引擎
        from .cli_service import get_cli_settings
        settings = get_cli_settings()
        engine = settings['analysis_engine']

        if engine == 'cli':
            logger.info("[RepoAnalyzer] Using CLI engine for project #%s", project.id)
            raw_text = _analyze_with_cli(project, local_path)
        else:
            logger.info("[RepoAnalyzer] Using SDK engine for project #%s", project.id)
            raw_text = _analyze_with_sdk(project, local_path)

        # 3. 解析响应
        items = _parse_analysis_response(raw_text)

        # 保存前检查是否已被重置
        analysis.refresh_from_db()
        if analysis.status == 'failed':
            logger.info("[RepoAnalyzer] Analysis #%s was reset, discarding results", analysis.id)
            return analysis

        analysis.discovered_items = items
        analysis.analysis_log = raw_text[:10000]  # 保留原始响应（截断）
        analysis.status = 'completed'
        analysis.save()

        logger.info("[RepoAnalyzer] Analysis complete for project #%s: %d items found",
                     project.id, len(items))
        return analysis

    except Exception as e:
        logger.exception("[RepoAnalyzer] Analysis failed for project #%s: %s", project.id, e)
        analysis.refresh_from_db()
        if analysis.status != 'analyzing':
            return analysis
        analysis.status = 'failed'
        analysis.analysis_log = str(e)[:5000]
        analysis.save()
        return analysis

    finally:
        _stop_heartbeat.set()
        heartbeat_thread.join(timeout=2)


def _analyze_with_cli(project, local_path: str) -> str:
    """
    使用 Claude CLI 分析仓库代码。

    CLI 直接读取工作目录下的文件，无需手动搜索和收集代码片段。

    Args:
        project: Project 模型实例
        local_path: 仓库本地路径

    Returns:
        CLI 返回的原始文本响应
    """
    from .cli_service import call_cli

    # CLI 模式：构造简洁提示词，CLI 自动读取 cwd 下的文件
    user_prompt = f"""请分析当前目录下的项目代码，提取所有前端页面路由和 REST API 端点。

项目名称: {project.name}
项目描述: {project.description or '无'}

{ANALYSIS_SYSTEM_PROMPT}"""

    return call_cli(
        prompt=user_prompt,
        cwd=local_path,
    )


def _analyze_with_sdk(project, local_path: str) -> str:
    """
    使用 Anthropic SDK 分析仓库代码（原有逻辑）。

    手动搜索路由关键词和表单/参数关键词，收集代码片段，然后调用 Claude API。

    Args:
        project: Project 模型实例
        local_path: 仓库本地路径

    Returns:
        API 返回的原始文本响应
    """
    # 获取目录树
    logger.info("[RepoAnalyzer-SDK] Getting file tree for project #%s", project.id)
    file_tree = repo_service.get_repo_file_tree(project)

    # 搜索路由相关文件（优先级高）
    code_snippets = []
    seen_files = set()
    max_files = 15

    # 第一轮：搜索路由定义关键词（高优先级）
    for keyword in _ROUTE_KEYWORDS:
        try:
            results = repo_service.search_code(project, keyword)
            for r in results:
                if r['file'] not in seen_files:
                    seen_files.add(r['file'])
                    try:
                        content = repo_service.read_file_content(project, r['file'])
                        if len(content) > 4000:
                            content = content[:4000] + "\n... (已截断)"
                        code_snippets.append(f"### 文件: {r['file']}\n```\n{content}\n```")
                    except Exception as e:
                        logger.warning("[RepoAnalyzer-SDK] Failed to read %s: %s", r['file'], e)
                if len(code_snippets) >= max_files:
                    break
        except Exception as e:
            logger.warning("[RepoAnalyzer-SDK] Search '%s' failed: %s", keyword, e)
        if len(code_snippets) >= max_files:
            break

    # 第二轮：搜索表单/参数关键词（补充上下文，如果有剩余配额）
    if len(code_snippets) < max_files:
        for keyword in _FORM_KEYWORDS:
            try:
                results = repo_service.search_code(project, keyword)
                for r in results:
                    if r['file'] not in seen_files:
                        seen_files.add(r['file'])
                        try:
                            content = repo_service.read_file_content(project, r['file'])
                            if len(content) > 4000:
                                content = content[:4000] + "\n... (已截断)"
                            code_snippets.append(f"### 文件: {r['file']}\n```\n{content}\n```")
                        except Exception as e:
                            logger.warning("[RepoAnalyzer-SDK] Failed to read %s: %s", r['file'], e)
                    if len(code_snippets) >= max_files:
                        break
            except Exception as e:
                logger.warning("[RepoAnalyzer-SDK] Search '%s' failed: %s", keyword, e)
            if len(code_snippets) >= max_files:
                break

    # 构造 Claude API 请求
    code_section = "\n\n".join(code_snippets) if code_snippets else "（未找到路由相关代码文件）"

    user_message = f"""## 项目目录结构
```
{file_tree}
```

## 路由相关代码文件
{code_section}

请分析以上项目代码，提取所有前端页面路由和 REST API 端点。"""

    client = _get_client()
    model = _get_model()

    logger.info("[RepoAnalyzer-SDK] Calling Claude API for project #%s (model: %s)", project.id, model)
    response = client.messages.create(
        model=model,
        max_tokens=8192,
        system=ANALYSIS_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text.strip()


def _parse_analysis_response(raw_text: str) -> list:
    """
    解析 Claude 返回的 JSON 响应，转为统一的 discovered_items 列表。

    输入格式: {"pages": [...], "apis": [...]}
    输出格式: [
      {"type": "page"|"api", "path", "name", "method", "description", "source_file",
       "elements": [...], "params": [...], "response_fields": [...]},
      ...
    ]

    新字段(elements/params/response_fields)缺失时默认空数组，保持向后兼容。
    """
    # 尝试提取 JSON
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        # 尝试从 markdown 代码块中提取
        match = re.search(r'```(?:json)?\s*([\s\S]*?)```', raw_text)
        if match:
            data = json.loads(match.group(1).strip())
        else:
            # 最后尝试提取花括号
            match = re.search(r'\{[\s\S]*\}', raw_text)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    logger.error("[RepoAnalyzer] Cannot parse response as JSON: %s", raw_text[:500])
                    return []
            else:
                logger.error("[RepoAnalyzer] Cannot parse response as JSON: %s", raw_text[:500])
                return []

    if not isinstance(data, dict):
        return []

    items = []

    # 处理 pages
    for page in data.get('pages') or []:
        items.append({
            'type': 'page',
            'path': page.get('path', ''),
            'name': page.get('name', ''),
            'method': None,
            'description': page.get('description', ''),
            'source_file': page.get('source_file', ''),
            'elements': page.get('elements') or [],
            'params': [],
            'response_fields': [],
        })

    # 处理 apis
    for api in data.get('apis') or []:
        items.append({
            'type': 'api',
            'path': api.get('path', ''),
            'name': api.get('name', ''),
            'method': api.get('method', ''),
            'description': api.get('description', ''),
            'source_file': api.get('source_file', ''),
            'elements': [],
            'params': api.get('params') or [],
            'response_fields': api.get('response_fields') or [],
        })

    return items
