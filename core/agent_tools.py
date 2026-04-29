"""
Agent 工具定义 — 为 Anthropic tool_use 定义仓库探索、浏览器操作和结果报告工具。

每个工具包含:
- schema: Anthropic tool_use 格式的工具定义 (name, description, input_schema)
- execute(input_dict, context) -> str: 执行工具并返回结果字符串

context 是一个 dict，包含:
- project: Project 对象
- page: Playwright Page 对象 (浏览器工具可用，未初始化时为 None)
"""
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════
# 仓库探索工具 (4 个)
# ══════════════════════════════════════════════════════════════════

def _execute_list_files(input_dict, context):
    """列出仓库目录树结构"""
    from . import repo_service
    project = context['project']
    max_depth = input_dict.get('max_depth', 3)
    try:
        tree = repo_service.get_repo_file_tree(project, max_depth=max_depth)
        return tree if tree else "(空目录)"
    except Exception as e:
        return f"Error: {e}"


def _execute_read_file(input_dict, context):
    """读取仓库中指定文件的内容"""
    from . import repo_service
    project = context['project']
    path = input_dict['path']
    try:
        content = repo_service.read_file_content(project, path)
        return content
    except Exception as e:
        return f"Error: {e}"


def _execute_search_code(input_dict, context):
    """在仓库中搜索关键词"""
    from . import repo_service
    project = context['project']
    keyword = input_dict['keyword']
    try:
        results = repo_service.search_code(project, keyword)
        if not results:
            return f"未找到匹配 '{keyword}' 的代码"
        lines = []
        for r in results:
            lines.append(f"{r['file']}:{r['line_num']}: {r['line']}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


def _execute_list_directory(input_dict, context):
    """列出指定目录下的文件和子目录（单层）"""
    project = context['project']
    rel_path = input_dict.get('path', '')
    try:
        if not project.local_repo_path:
            return "Error: 仓库未克隆"
        target = Path(project.local_repo_path) / rel_path
        if not target.exists():
            return f"Error: 目录不存在: {rel_path}"
        if not target.is_dir():
            return f"Error: 不是目录: {rel_path}"

        # 路径安全检查
        try:
            target.resolve().relative_to(Path(project.local_repo_path).resolve())
        except ValueError:
            return "Error: 非法的目录路径"

        IGNORED = {'.git', 'node_modules', '__pycache__', '.venv', 'venv'}
        entries = []
        for entry in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if entry.name in IGNORED or entry.name.startswith('.'):
                continue
            suffix = '/' if entry.is_dir() else ''
            entries.append(f"  {entry.name}{suffix}")
        if not entries:
            return "(空目录)"
        return "\n".join(entries)
    except Exception as e:
        return f"Error: {e}"


REPO_TOOLS = [
    {
        'schema': {
            'name': 'list_files',
            'description': '列出项目的文件目录树结构。用于了解项目整体组织和文件布局。返回格式化的目录树文本。',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'max_depth': {
                        'type': 'integer',
                        'description': '目录遍历深度，默认 3',
                        'default': 3,
                    },
                },
                'required': [],
            },
        },
        'execute': _execute_list_files,
    },
    {
        'schema': {
            'name': 'read_file',
            'description': '读取项目仓库中指定文件的完整内容。路径相对于仓库根目录。用于查看具体文件的代码实现。',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'path': {
                        'type': 'string',
                        'description': '文件的相对路径，如 "src/App.vue" 或 "package.json"',
                    },
                },
                'required': ['path'],
            },
        },
        'execute': _execute_read_file,
    },
    {
        'schema': {
            'name': 'search_code',
            'description': '在项目代码库中搜索关键词，返回匹配的文件名、行号和代码行。用于定位特定的函数、组件、路由或 API。',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'keyword': {
                        'type': 'string',
                        'description': '要搜索的关键词，如函数名、路由路径、组件名等',
                    },
                },
                'required': ['keyword'],
            },
        },
        'execute': _execute_search_code,
    },
    {
        'schema': {
            'name': 'list_directory',
            'description': '列出指定目录下的文件和子目录（单层）。用于浏览特定目录的内容。',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'path': {
                        'type': 'string',
                        'description': '相对于仓库根目录的目录路径，留空表示根目录',
                        'default': '',
                    },
                },
                'required': [],
            },
        },
        'execute': _execute_list_directory,
    },
]


# ══════════════════════════════════════════════════════════════════
# Playwright 浏览器工具 (7 个)
# ══════════════════════════════════════════════════════════════════

def _execute_browser_navigate(input_dict, context):
    """导航到指定 URL"""
    page = context.get('page')
    if not page:
        return "Error: 浏览器未初始化"
    url = input_dict['url']
    try:
        page.goto(url, wait_until='domcontentloaded', timeout=30000)
        return f"已导航到: {page.url}"
    except Exception as e:
        return f"Error navigating to {url}: {e}"


def _execute_browser_click(input_dict, context):
    """点击页面元素"""
    page = context.get('page')
    if not page:
        return "Error: 浏览器未初始化"
    selector = input_dict['selector']
    try:
        page.click(selector, timeout=10000)
        return f"已点击: {selector}"
    except Exception as e:
        return f"Error clicking {selector}: {e}"


def _execute_browser_fill(input_dict, context):
    """填写表单输入框"""
    page = context.get('page')
    if not page:
        return "Error: 浏览器未初始化"
    selector = input_dict['selector']
    value = input_dict['value']
    try:
        page.fill(selector, value, timeout=10000)
        return f"已填写 '{selector}': {value[:50]}{'...' if len(value) > 50 else ''}"
    except Exception as e:
        return f"Error filling {selector}: {e}"


def _execute_browser_press_key(input_dict, context):
    """按下键盘按键"""
    page = context.get('page')
    if not page:
        return "Error: 浏览器未初始化"
    key = input_dict['key']
    try:
        page.keyboard.press(key)
        return f"已按下按键: {key}"
    except Exception as e:
        return f"Error pressing key {key}: {e}"


def _execute_browser_wait_for(input_dict, context):
    """等待元素出现或页面加载完成"""
    page = context.get('page')
    if not page:
        return "Error: 浏览器未初始化"
    selector = input_dict.get('selector', '')
    timeout = input_dict.get('timeout', 10000)
    try:
        if selector:
            page.wait_for_selector(selector, timeout=timeout)
            return f"元素已出现: {selector}"
        else:
            page.wait_for_load_state('networkidle', timeout=timeout)
            return "页面加载完成"
    except Exception as e:
        return f"Error waiting: {e}"


def _execute_browser_get_text(input_dict, context):
    """获取页面元素的文本内容"""
    page = context.get('page')
    if not page:
        return "Error: 浏览器未初始化"
    selector = input_dict['selector']
    try:
        text = page.text_content(selector, timeout=10000)
        if text:
            text = text.strip()
            if len(text) > 2000:
                text = text[:2000] + "\n... (已截断)"
            return text
        return "(元素文本为空)"
    except Exception as e:
        return f"Error getting text from {selector}: {e}"


def _execute_browser_screenshot(input_dict, context):
    """对当前页面截图"""
    page = context.get('page')
    if not page:
        return "Error: 浏览器未初始化"
    save_path = input_dict.get('save_path', '')
    try:
        if not save_path:
            import tempfile
            fd, save_path = tempfile.mkstemp(suffix='.png', prefix='agent_screenshot_')
            os.close(fd)
        page.screenshot(path=save_path, full_page=True)
        context['last_screenshot'] = save_path
        return f"截图已保存: {save_path}"
    except Exception as e:
        return f"Error taking screenshot: {e}"


BROWSER_TOOLS = [
    {
        'schema': {
            'name': 'browser_navigate',
            'description': '在浏览器中导航到指定 URL。用于打开测试目标页面。',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'url': {
                        'type': 'string',
                        'description': '要导航到的完整 URL',
                    },
                },
                'required': ['url'],
            },
        },
        'execute': _execute_browser_navigate,
    },
    {
        'schema': {
            'name': 'browser_click',
            'description': '点击页面上的元素。使用 CSS 选择器定位元素。在点击前确保页面已加载。',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'selector': {
                        'type': 'string',
                        'description': 'CSS 选择器，如 "button.submit"、"#login-btn"、"a[href=\\"/login\\"]"',
                    },
                },
                'required': ['selector'],
            },
        },
        'execute': _execute_browser_click,
    },
    {
        'schema': {
            'name': 'browser_fill',
            'description': '在输入框中填写文本。使用 CSS 选择器定位输入框。',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'selector': {
                        'type': 'string',
                        'description': 'CSS 选择器，如 "input[name=\\"username\\"]"',
                    },
                    'value': {
                        'type': 'string',
                        'description': '要输入的文本',
                    },
                },
                'required': ['selector', 'value'],
            },
        },
        'execute': _execute_browser_fill,
    },
    {
        'schema': {
            'name': 'browser_press_key',
            'description': '按下键盘按键，如 Enter、Escape、Tab 等。',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'key': {
                        'type': 'string',
                        'description': '按键名称，如 "Enter"、"Escape"、"Tab"、"ArrowDown"',
                    },
                },
                'required': ['key'],
            },
        },
        'execute': _execute_browser_press_key,
    },
    {
        'schema': {
            'name': 'browser_wait_for',
            'description': '等待页面元素出现或页面加载完成。如果只指定 selector，等待该元素出现；不指定则等待页面 networkidle。',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'selector': {
                        'type': 'string',
                        'description': '要等待的元素 CSS 选择器，留空则等待页面加载完成',
                        'default': '',
                    },
                    'timeout': {
                        'type': 'integer',
                        'description': '超时时间（毫秒），默认 10000',
                        'default': 10000,
                    },
                },
                'required': [],
            },
        },
        'execute': _execute_browser_wait_for,
    },
    {
        'schema': {
            'name': 'browser_get_text',
            'description': '获取页面上指定元素的文本内容。用于验证页面显示是否符合预期。',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'selector': {
                        'type': 'string',
                        'description': 'CSS 选择器，如 ".error-message"、"h1"',
                    },
                },
                'required': ['selector'],
            },
        },
        'execute': _execute_browser_get_text,
    },
    {
        'schema': {
            'name': 'browser_screenshot',
            'description': '对当前页面进行截图。截图将保存为 PNG 文件。用于记录测试过程或验证页面状态。',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'save_path': {
                        'type': 'string',
                        'description': '截图保存路径，留空则自动生成临时文件',
                        'default': '',
                    },
                },
                'required': [],
            },
        },
        'execute': _execute_browser_screenshot,
    },
]


# ══════════════════════════════════════════════════════════════════
# report_result 工具
# ══════════════════════════════════════════════════════════════════

def _execute_report_result(input_dict, context):
    """接收 Agent 的测试结果报告"""
    context['report_result'] = {
        'status': input_dict['status'],
        'summary': input_dict['summary'],
        'details': input_dict.get('details', ''),
    }
    return f"结果已记录: {input_dict['status']} — {input_dict['summary']}"


REPORT_RESULT_TOOL = {
    'schema': {
        'name': 'report_result',
        'description': '报告测试执行结果。当测试完成时（无论通过或失败），必须调用此工具报告最终结果。',
        'input_schema': {
            'type': 'object',
            'properties': {
                'status': {
                    'type': 'string',
                    'enum': ['passed', 'failed', 'error'],
                    'description': '测试结果状态: passed（通过）、failed（失败）、error（异常）',
                },
                'summary': {
                    'type': 'string',
                    'description': '结果的一句话总结',
                },
                'details': {
                    'type': 'string',
                    'description': '详细的结果说明，包括测试了什么、发现的问题等',
                    'default': '',
                },
            },
            'required': ['status', 'summary'],
        },
    },
    'execute': _execute_report_result,
}


# ══════════════════════════════════════════════════════════════════
# 工具注册表
# ══════════════════════════════════════════════════════════════════

def get_all_tools():
    """返回所有工具定义列表 (repo + browser + report_result)"""
    return REPO_TOOLS + BROWSER_TOOLS + [REPORT_RESULT_TOOL]


def get_tool_schemas():
    """返回 Anthropic tool_use 格式的 schema 列表（仅 schema 部分）"""
    return [tool['schema'] for tool in get_all_tools()]


def get_tool_executor(tool_name):
    """根据工具名查找 execute 函数，未找到返回 None"""
    for tool in get_all_tools():
        if tool['schema']['name'] == tool_name:
            return tool['execute']
    return None


def get_browser_tool_names():
    """返回所有浏览器工具的名称集合"""
    return {tool['schema']['name'] for tool in BROWSER_TOOLS}


# ══════════════════════════════════════════════════════════════════
# System Prompt 构建
# ══════════════════════════════════════════════════════════════════

_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), 'templates', 'agent_execute_prompt.md')


def build_test_execution_system_prompt(testcase, base_url: str, project) -> str:
    """
    构建 Agent 执行测试用例的 system prompt。

    Args:
        testcase: TestCase 对象
        base_url: 测试目标 URL
        project: Project 对象

    Returns:
        格式化后的 system prompt 字符串
    """
    # 加载模板
    try:
        with open(_TEMPLATE_PATH, 'r', encoding='utf-8') as f:
            template = f.read()
    except FileNotFoundError:
        logger.warning("Agent prompt template not found at %s", _TEMPLATE_PATH)
        template = _get_fallback_template()

    # 准备 markdown_section
    if testcase.markdown_content:
        markdown_section = f"### 完整用例文档\n{testcase.markdown_content}"
    else:
        markdown_section = ''

    # 准备 repo_info
    repo_info = ''
    if project.repo_url:
        repo_info = f"- Git 仓库: {project.repo_url}\n- 本地路径: {project.local_repo_path or '未克隆'}"

    return template.format(
        project_name=project.name,
        base_url=base_url,
        repo_info=repo_info,
        testcase_name=testcase.name,
        testcase_description=testcase.description or '无描述',
        testcase_steps=testcase.steps or '无步骤',
        testcase_expected=testcase.expected_result or '无预期结果',
        markdown_section=markdown_section,
    )


def _get_fallback_template() -> str:
    """当模板文件不存在时的备用模板"""
    return (
        "你是一个自动化测试工程师。请使用提供的工具完成以下测试。\n\n"
        "项目: {project_name} | URL: {base_url}\n"
        "{repo_info}\n\n"
        "用例: {testcase_name}\n描述: {testcase_description}\n\n"
        "步骤:\n{testcase_steps}\n\n预期结果:\n{testcase_expected}\n\n"
        "{markdown_section}\n\n"
        "工作流程: 探索代码 → 规划测试 → 执行操作 → report_result 报告结果。"
    )
