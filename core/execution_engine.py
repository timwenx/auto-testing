"""
执行引擎 — 嵌入式 PlaywrightRunner，通过 AI 生成 Playwright 代码并执行
"""
import json
import logging
import os
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from django.conf import settings

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=3)

EXECUTE_PROMPT = """你是一个自动化测试脚本生成器。请根据以下测试用例信息，生成一段 Playwright Python 测试脚本。

测试用例: {name}
描述: {description}
测试步骤:
{steps}

预期结果:
{expected_result}

目标 URL: {base_url}

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
    prompt = EXECUTE_PROMPT.format(
        name=testcase.name,
        description=testcase.description,
        steps=testcase.steps,
        expected_result=testcase.expected_result,
        base_url=base_url,
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

        return {
            'status': 'passed' if passed else 'failed',
            'log': log,
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
    try:
        code = _generate_playwright_code(testcase, base_url)
        return _run_playwright_script(code)
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

    return _executor.submit(_task)
