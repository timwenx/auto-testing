"""
执行引擎 — 嵌入式 PlaywrightRunner，通过 AI 生成 Playwright 代码并执行
"""
import json
import logging
import os
import re
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


def _strip_markdown_code_fences(text: str) -> str:
    """
    去除 AI 响应中可能包含的 markdown 代码围栏标记。
    例如 ```python ... ``` 或 ```py ... ``` 或 ``` ... ```
    只保留代码体内容。如果输入不含围栏，原样返回。
    """
    if not text:
        return text
    # 匹配 ```python / ```py / ``` 开头，到 ``` 结尾的代码块
    pattern = r'^```(?:python|py|javascript|js)?\s*\n(.*?)\n```[\s]*$'
    match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    # 有些模型只在开头加 ```，结尾没有 ``` 或格式不标准，尝试宽松匹配
    stripped = text.strip()
    if stripped.startswith('```'):
        # 去掉首行围栏标记
        first_nl = stripped.find('\n')
        if first_nl != -1:
            stripped = stripped[first_nl + 1:]
        # 去掉尾部围栏
        if stripped.rstrip().endswith('```'):
            stripped = stripped.rstrip()[:-3].rstrip()
        return stripped
    return text


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
    raw_code = _call_claude(prompt, timeout=180)
    return _strip_markdown_code_fences(raw_code)


def _run_playwright_script(code: str, timeout: int = 120) -> dict:
    """执行 Playwright 脚本并返回结果"""
    # 二次防御性清理：确保代码不含 markdown 围栏
    code = _strip_markdown_code_fences(code)
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


# ══════════════════════════════════════════════════════════════════
# Agent 模式执行
# ══════════════════════════════════════════════════════════════════

def _format_agent_log(agent_result: dict) -> str:
    """将 Agent 执行结果格式化为可读日志"""
    lines = []
    lines.append("=" * 60)
    lines.append("Agent 模式执行日志")
    lines.append("=" * 60)

    # 工具调用记录
    tool_calls = agent_result.get('tool_calls_log', [])
    if tool_calls:
        lines.append(f"\n工具调用次数: {len(tool_calls)}")
        lines.append("-" * 40)
        for i, call in enumerate(tool_calls, 1):
            lines.append(f"[{i}] {call['tool']}({json.dumps(call['input'], ensure_ascii=False)})")
            output = call.get('output', '')
            if len(output) > 200:
                output = output[:200] + '...'
            lines.append(f"    → {output}")
        lines.append("-" * 40)

    # Token 统计
    lines.append(f"输入 tokens: {agent_result.get('total_input_tokens', 0)}")
    lines.append(f"输出 tokens: {agent_result.get('total_output_tokens', 0)}")

    # 最终回复
    response_text = agent_result.get('response_text', '')
    if response_text:
        lines.append(f"\n最终回复:\n{response_text}")

    return '\n'.join(lines)


def _build_step_logs(agent_result: dict) -> list:
    """将 tool_calls_log 转换为结构化的 step_logs 格式（legacy fallback）。

    注意：主链路中步骤已通过 AgentRunner._persist_step() 实时写入 DB。
    此函数仅用于 execute_testcase_with_agent() 的返回值构建。
    """
    from .agent_service import format_step_action, _extract_target, _extract_screenshot_path

    steps = []
    tool_calls = agent_result.get('tool_calls_log', [])
    for i, call in enumerate(tool_calls, 1):
        tool_name = call['tool']
        tool_input = call.get('input', {})
        output = call.get('output', '')

        step = {
            'step_num': i,
            'action': format_step_action(tool_name, tool_input),
            'tool_name': tool_name,
            'target': _extract_target(tool_name, tool_input),
            'result': output[:300],
            'screenshot_path': _extract_screenshot_path(output),
            'timestamp': call.get('timestamp', ''),
            'duration_ms': call.get('duration_ms', 0),
        }
        steps.append(step)

    return steps


def _extract_screenshots(agent_result: dict) -> list:
    """从 tool_calls_log 中提取所有截图路径"""
    screenshots = []
    for call in agent_result.get('tool_calls_log', []):
        if call['tool'] == 'browser_screenshot':
            output = call.get('output', '')
            # 截图工具返回 "截图已保存: <path>"
            if '截图已保存:' in output:
                path = output.split('截图已保存:')[-1].strip()
                if path:
                    screenshots.append(path)
            elif '已保存' in output:
                # 兼容其他格式
                import re
                match = re.search(r'[:\s](\S+\.png)', output)
                if match:
                    screenshots.append(match.group(1))
    return screenshots


def execute_testcase_with_agent(testcase, base_url: str, execution_id=None) -> dict:
    """
    通过 Agent 模式执行测试用例。

    与 execute_testcase_sync 返回相同格式的 dict，但 script 字段存储 Agent 对话日志。

    Args:
        testcase: TestCase 对象
        base_url: 测试目标 URL
        execution_id: 执行记录 ID（用于实时事件推送，可选）
    """
    from .agent_service import AgentRunner
    from .agent_tools import build_test_execution_system_prompt

    project = testcase.project

    try:
        # 获取 max_turns 配置
        from .models import SystemSetting
        try:
            max_turns = int(SystemSetting.get('agent_max_turns', '20'))
        except (ValueError, TypeError):
            max_turns = 20

        # 构建 system prompt
        system_prompt = build_test_execution_system_prompt(testcase, base_url, project)

        # 初始用户消息
        user_message = (
            f"请执行以下测试用例:\n\n"
            f"用例: {testcase.name}\n"
            f"目标 URL: {base_url}\n\n"
            f"请先探索代码理解项目，然后使用浏览器工具逐步执行测试，最后调用 report_result 报告结果。"
        )
        messages = [{"role": "user", "content": user_message}]

        # 加载 ExecutionRecord 用于实时步骤持久化
        execution_record = None
        if execution_id:
            from .models import ExecutionRecord
            try:
                execution_record = ExecutionRecord.objects.get(pk=execution_id)
            except ExecutionRecord.DoesNotExist:
                logger.warning("ExecutionRecord %s not found, steps won't be persisted in real-time", execution_id)

        # 执行 Agent
        start = time.time()
        runner = AgentRunner(
            project=project,
            testcase_id=testcase.pk,
            execution_id=execution_id,
            execution_record=execution_record,
        )
        agent_result = runner.run(
            system_prompt=system_prompt,
            messages=messages,
            max_turns=max_turns,
        )
        duration = time.time() - start

        # 解析 report_result（如果 Agent 调用了的话）
        status = 'passed'
        log = _format_agent_log(agent_result)

        # 从 tool_calls_log 中查找 report_result 调用
        report = None
        for call in reversed(agent_result.get('tool_calls_log', [])):
            if call['tool'] == 'report_result':
                report = call['input']
                break

        if report:
            status = report.get('status', 'passed')
            summary = report.get('summary', '')
            details = report.get('details', '')
            log = f"[Agent 结果] {summary}\n{details}\n\n{log}"

        # 步骤已通过 AgentRunner._persist_step() 实时写入 DB
        # 此处仍构建 step_logs 作为返回值的一部分（用于 _save_agent_result 中的 _create_screenshot_records）
        step_logs = _build_step_logs(agent_result)
        screenshots = _extract_screenshots(agent_result)

        return {
            'status': status,
            'log': log,
            'error_message': '' if status == 'passed' else agent_result.get('response_text', ''),
            'duration': round(duration, 2),
            'script': json.dumps({
                'mode': 'agent',
                'tool_calls': agent_result.get('tool_calls_log', []),
                'input_tokens': agent_result.get('total_input_tokens', 0),
                'output_tokens': agent_result.get('total_output_tokens', 0),
            }, ensure_ascii=False, default=str),
            'step_logs': step_logs,
            'screenshots': screenshots,
            'agent_response': {
                'response_text': agent_result.get('response_text', ''),
                'total_input_tokens': agent_result.get('total_input_tokens', 0),
                'total_output_tokens': agent_result.get('total_output_tokens', 0),
            },
        }

    except Exception as e:
        logger.exception("Agent execution failed")
        return {
            'status': 'error',
            'log': '',
            'error_message': str(e),
            'duration': 0,
            'script': '',
            'step_logs': [],
            'screenshots': [],
            'agent_response': {},
        }
