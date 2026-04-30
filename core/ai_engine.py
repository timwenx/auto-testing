"""
AI 引擎 — 通过 Anthropic SDK 生成和分析测试用例
支持代码感知用例生成和对话式调整
"""
import json
import re
import logging
import os
from pathlib import Path

from django.conf import settings as django_settings

logger = logging.getLogger(__name__)

# ── 常量 ──

_TEMPLATE_PATH = Path(__file__).parent / 'templates' / 'testcase_template.md'

# ── 延迟初始化 Anthropic 客户端 ──

_client = None


def _get_api_key() -> str:
    """获取 API Key：优先从 SystemSetting 读取，fallback 到环境变量"""
    from .models import SystemSetting
    key = SystemSetting.get('anthropic_api_key', '')
    if not key:
        key = getattr(django_settings, 'ANTHROPIC_API_KEY', '')
    return key


def _get_model() -> str:
    """获取 AI 模型名"""
    from .models import SystemSetting
    return SystemSetting.get('anthropic_model', 'claude-sonnet-4-20250514')


def _get_base_url() -> str:
    """获取 Anthropic API Base URL，留空则使用默认地址"""
    from .models import SystemSetting
    return SystemSetting.get('anthropic_base_url', '').strip()


def _get_client():
    """延迟初始化并返回 Anthropic 客户端（单例），支持自定义 base_url"""
    global _client
    api_key = _get_api_key()
    if not api_key:
        raise RuntimeError(
            "请在系统设置中配置 Anthropic API Key，或设置环境变量 ANTHROPIC_API_KEY"
        )
    base_url = _get_base_url()
    if _client is None or _client.api_key != api_key or getattr(_client, '_custom_base_url', None) != base_url:
        import anthropic
        kwargs = {'api_key': api_key}
        if base_url:
            kwargs['base_url'] = base_url
        _client = anthropic.Anthropic(**kwargs)
        _client._custom_base_url = base_url
    return _client


def _call_claude(prompt: str, timeout: int = 120) -> str:
    """调用 Anthropic SDK 并返回响应文本"""
    client = _get_client()
    model = _get_model()
    try:
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.error("Anthropic API error: %s", e)
        raise RuntimeError(f"AI 调用失败: {e}")


def _call_claude_messages(messages: list, timeout: int = 120) -> str:
    """调用 Anthropic SDK（支持多轮对话），返回响应文本"""
    client = _get_client()
    model = _get_model()
    try:
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            messages=messages,
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.error("Anthropic API error: %s", e)
        raise RuntimeError(f"AI 调用失败: {e}")


def _extract_json_array(raw: str) -> list:
    """从 AI 响应中提取 JSON 数组"""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError(f"AI 返回的内容不是有效 JSON:\n{raw[:500]}")


def _extract_json_object(raw: str) -> dict:
    """从 AI 响应中提取 JSON 对象"""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError(f"AI 返回的内容不是有效 JSON:\n{raw[:500]}")


def _load_template() -> str:
    """加载 Markdown 测试用例模板"""
    try:
        with open(_TEMPLATE_PATH, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        logger.warning("Testcase template not found at %s", _TEMPLATE_PATH)
        return ""


def _gather_code_context(project, requirement: str, target: str = '') -> str:
    """
    收集项目代码上下文：目录结构 + 相关代码片段。
    降级策略：如果仓库操作失败，返回空字符串（不阻断生成）。
    """
    from . import repo_service

    if not project.repo_url:
        return ""

    parts = []

    # 尝试克隆/更新仓库
    try:
        repo_service.clone_or_update_repo(project)
    except Exception as e:
        logger.warning("Failed to clone/update repo: %s", e)
        return ""

    # 获取文件树
    try:
        tree = repo_service.get_repo_file_tree(project)
        parts.append(f"## 项目目录结构\n```\n{tree}\n```")
    except Exception as e:
        logger.warning("Failed to get file tree: %s", e)

    # 根据 target 和 requirement 搜索相关代码
    search_keywords = []
    if target:
        search_keywords.append(target)
    # 从 requirement 中提取可能的路由/接口/文件名关键词
    for pattern in [r'/api/\w+', r'\w+\.vue', r'\w+\.py', r'\w+\.js']:
        matches = re.findall(pattern, requirement)
        search_keywords.extend(matches)

    if search_keywords:
        code_snippets = []
        seen_files = set()
        for keyword in search_keywords[:5]:  # 最多搜索 5 个关键词
            try:
                results = repo_service.search_code(project, keyword)
                for r in results:
                    if r['file'] not in seen_files:
                        seen_files.add(r['file'])
                        try:
                            content = repo_service.read_file_content(project, r['file'])
                            # 截取相关部分，控制总长度
                            if len(content) > 3000:
                                content = content[:3000] + "\n... (已截断)"
                            code_snippets.append(
                                f"### 文件: {r['file']}\n```\n{content}\n```"
                            )
                        except Exception as e:
                            logger.warning("Failed to read %s: %s", r['file'], e)
                        if len(code_snippets) >= 5:  # 最多 5 个文件
                            break
            except Exception as e:
                logger.warning("Failed to search for '%s': %s", keyword, e)

        if code_snippets:
            parts.append("## 相关代码文件\n" + "\n\n".join(code_snippets))

    return "\n\n".join(parts) if parts else ""


# ── Prompts ──

GENERATE_PROMPT = """你是一个专业的 QA 测试工程师。请根据以下需求描述和项目代码，生成一组产品级测试用例。

需求描述：
{requirement}

{target_section}

项目信息：
- 项目名称: {project_name}
- 项目 URL: {base_url}

{code_context}

{template_section}

请以 JSON 数组格式返回，每个元素包含以下字段：
- name: 用例名称（简短，用于列表展示）
- description: 用例描述
- steps: 测试步骤（自然语言，分步骤描述）
- expected_result: 预期结果
- priority: 优先级（P0/P1/P2）
- test_type: 测试类型（功能/边界/异常/安全）
- markdown_content: 完整的 Markdown 测试用例文档（按照上述模板格式）

要求：
1. 仔细分析提供的代码文件，理解路由、视图、组件、API 等逻辑
2. 覆盖正向、反向、边界值和异常场景
3. markdown_content 必须是完整的产品级测试用例文档，包含前置条件、测试数据、详细步骤、预期结果等
4. 步骤描述清晰可执行，包含具体的输入数据和验证点
5. 只返回 JSON 数组，不要其他文字
"""

ADJUST_PROMPT = """你是一个专业的 QA 测试工程师。你正在与用户对话式地调整测试用例。

## 当前测试用例
{current_cases}

## 用户反馈
{user_feedback}

请根据用户反馈修改测试用例。返回修改后的完整 JSON 数组，格式与之前相同：
- name: 用例名称
- description: 用例描述
- steps: 测试步骤
- expected_result: 预期结果
- priority: 优先级（P0/P1/P2）
- test_type: 测试类型（功能/边界/异常/安全）
- markdown_content: 完整的 Markdown 测试用例文档

要求：
1. 保留用户未要求修改的部分
2. 根据反馈新增、修改或删除用例
3. 确保 markdown_content 是完整的测试用例文档
4. 只返回 JSON 数组，不要其他文字
"""

ANALYZE_PROMPT = """你是一个专业的 QA 测试工程师。请分析以下测试执行结果，给出分析报告。

测试用例: {testcase_name}
执行状态: {status}
执行日志:
{log}

错误信息:
{error_message}

请以 JSON 格式返回，包含以下字段：
- summary: 一句话总结
- root_cause: 根因分析
- suggestion: 改进建议
- severity: 严重程度 (low/medium/high)
- is_flaky: 是否可能是偶发问题 (true/false)

只返回 JSON，不要其他文字。
"""


def generate_testcases(project_name: str, base_url: str, requirement: str,
                       project=None, target: str = '') -> list[dict]:
    """
    通过 AI 生成测试用例。

    Args:
        project_name: 项目名称
        base_url: 项目 URL
        requirement: 需求描述
        project: Project 对象（可选，用于代码感知生成）
        target: 测试目标（可选，如「用户登录页面」「/api/users/」）
    """
    # 收集代码上下文
    code_context = ''
    if project:
        code_context = _gather_code_context(project, requirement, target)

    # 加载模板
    template = _load_template()

    target_section = f"测试目标：{target}" if target else ""
    template_section = f"请严格按照以下 Markdown 模板格式生成 markdown_content 字段：\n\n{template}" if template else ""

    prompt = GENERATE_PROMPT.format(
        requirement=requirement,
        target_section=target_section,
        project_name=project_name,
        base_url=base_url,
        code_context=code_context,
        template_section=template_section,
    )
    raw = _call_claude(prompt)
    return _extract_json_array(raw)


def adjust_testcases(project, conversation_history: list, user_feedback: str,
                     current_cases: list) -> list[dict]:
    """
    对话式调整测试用例。

    Args:
        project: Project 对象
        conversation_history: 之前的对话历史 [{role, content}, ...]
        user_feedback: 用户反馈
        current_cases: 当前的用例列表

    Returns:
        调整后的用例列表
    """
    current_cases_str = json.dumps(current_cases, ensure_ascii=False, indent=2)

    # 构建多轮对话消息
    messages = []
    for msg in conversation_history:
        messages.append({"role": msg['role'], "content": msg['content']})

    # 添加当前轮次的 prompt
    adjust_prompt = ADJUST_PROMPT.format(
        current_cases=current_cases_str,
        user_feedback=user_feedback,
    )
    messages.append({"role": "user", "content": adjust_prompt})

    raw = _call_claude_messages(messages)
    return _extract_json_array(raw)


def analyze_execution(testcase_name: str, status: str, log: str, error_message: str) -> dict:
    """通过 AI 分析执行结果"""
    prompt = ANALYZE_PROMPT.format(
        testcase_name=testcase_name,
        status=status,
        log=log,
        error_message=error_message,
    )
    raw = _call_claude(prompt)
    return _extract_json_object(raw)
