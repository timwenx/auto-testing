"""
执行引擎 — 嵌入式 PlaywrightRunner，通过 AI 生成 Playwright 代码并执行
"""
import logging
import os
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


def _get_max_workers() -> int:
    """获取最大并发数（从 SystemSetting 读取）"""
    from .models import SystemSetting
    try:
        return int(SystemSetting.get('max_workers', '3'))
    except (ValueError, TypeError):
        return 3


_executor = None


def _get_executor() -> ThreadPoolExecutor:
    """延迟初始化线程池"""
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=_get_max_workers())
    return _executor

EXECUTE_PROMPT = """你是一个自动化测试脚本生成器。请根据以下测试用例信息，生成一段 Playwright Python 测试脚本。

测试用例: {name}
描述: {description}

{content_section}

目标 URL: {base_url}

{code_context}

要求：
1. 使用 playwright.sync_api
2. 脚本应可独立运行
3. 包含必要的等待和断言
4. 处理常见异常
5. 使用 test_ 前缀的函数名
6. 在脚本末尾打印 "TEST_PASSED" 或 "TEST_FAILED: <原因>"

只返回 Python 代码，不要其他文字。"""


def _generate_playwright_code(testcase, base_url: str) -> str:
    """通过 AI 生成 Playwright 测试代码"""
    from .ai_engine import _call_claude

    # 优先使用 markdown_content，fallback 到 steps/expected_result
    if testcase.markdown_content:
        content_section = f"## 完整测试用例文档\n{testcase.markdown_content}"
    else:
        content_section = (
            f"测试步骤:\n{testcase.steps}\n\n"
            f"预期结果:\n{testcase.expected_result}"
        )

    # 如果项目有 Git 仓库，附加目录结构帮助 AI 理解技术栈
    code_context = ''
    try:
        project = testcase.project
        if project.repo_url and project.local_repo_path:
            from .repo_service import get_repo_file_tree
            tree = get_repo_file_tree(project, max_depth=2)
            code_context = f"## 项目目录结构\n```\n{tree}\n```\n请根据以上目录结构理解项目的前端技术栈和文件组织。"
    except Exception:
        pass

    prompt = EXECUTE_PROMPT.format(
        name=testcase.name,
        description=testcase.description,
        content_section=content_section,
        base_url=base_url,
        code_context=code_context,
    )
    return _call_claude(prompt, timeout=180)


def _run_playwright_script(code: str, timeout: int = 120) -> dict:
    """执行 Playwright 脚本并返回结果"""
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.py', delete=False, encoding='utf-8'
    ) as f:
        f.write(code)
        script_path = f.name

    try:
        start = time.time()
        result = subprocess.run(
            ['python', script_path],
            capture_output=True, text=True, timeout=timeout,
            encoding='utf-8',
            cwd=os.path.dirname(script_path),
        )
        duration = time.time() - start

        log = result.stdout
        error = result.stderr
        passed = 'TEST_PASSED' in log

        # 把生成的脚本也记录到日志中（方便调试）
        script_log = f"=== Generated Script ===\n{code}\n=== End Script ===\n\n{log}"

        return {
            'status': 'passed' if passed else 'failed',
            'log': script_log,
            'error_message': error,
            'duration': round(duration, 2),
            'script': code,
        }
    except subprocess.TimeoutExpired:
        return {
            'status': 'error',
            'log': '',
            'error_message': f'执行超时（{timeout}秒）',
            'duration': timeout,
            'script': code,
        }
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass


def execute_testcase_sync(testcase, base_url: str) -> dict:
    """同步执行单个测试用例（阻塞调用）"""
    from .models import SystemSetting
    try:
        timeout = int(SystemSetting.get('execution_timeout', '120'))
    except (ValueError, TypeError):
        timeout = 120

    try:
        code = _generate_playwright_code(testcase, base_url)
        return _run_playwright_script(code, timeout=timeout)
    except Exception as e:
        return {
            'status': 'error',
            'log': '',
            'error_message': str(e),
            'duration': 0,
            'script': '',
        }


def execute_testcase_async(testcase, base_url: str, callback=None):
    """异步执行测试用例（提交到线程池）"""
    def _task():
        result = execute_testcase_sync(testcase, base_url)
        if callback:
            callback(testcase, result)
        return result

    return _get_executor().submit(_task)
