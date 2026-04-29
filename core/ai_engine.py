"""
AI 引擎 — 通过 Claude CLI subprocess 生成和分析测试用例
"""
import json
import subprocess
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

CLAUDE_CLI = getattr(settings, 'CLAUDE_CLI_PATH', 'claude')

GENERATE_PROMPT = """你是一个专业的 QA 测试工程师。请根据以下需求描述，生成一组测试用例。

需求描述：
{requirement}

项目信息：
- 项目名称: {project_name}
- 项目 URL: {base_url}

请以 JSON 数组格式返回，每个元素包含以下字段：
- name: 用例名称
- description: 用例描述
- steps: 测试步骤（自然语言，分步骤描述）
- expected_result: 预期结果

要求：
1. 覆盖正向和反向场景
2. 包含边界值测试
3. 步骤描述清晰可执行
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


def _call_claude(prompt: str, timeout: int = 120) -> str:
    """调用 Claude CLI 并返回响应"""
    try:
        result = subprocess.run(
            [CLAUDE_CLI, '-p', prompt],
            capture_output=True, text=True, timeout=timeout,
            encoding='utf-8',
        )
        if result.returncode != 0:
            logger.error("Claude CLI error: %s", result.stderr)
            raise RuntimeError(f"Claude CLI exited with code {result.returncode}: {result.stderr}")
        return result.stdout.strip()
    except FileNotFoundError:
        raise RuntimeError(
            f"Claude CLI not found at '{CLAUDE_CLI}'. "
            "Install with: npm install -g @anthropic-ai/claude-code"
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Claude CLI timed out after {timeout}s")


def generate_testcases(project_name: str, base_url: str, requirement: str) -> list[dict]:
    """通过 AI 生成测试用例"""
    prompt = GENERATE_PROMPT.format(
        requirement=requirement,
        project_name=project_name,
        base_url=base_url,
    )
    raw = _call_claude(prompt)
    # 尝试从响应中提取 JSON
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # 尝试查找 JSON 块
        import re
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError(f"AI 返回的内容不是有效 JSON:\n{raw[:500]}")


def analyze_execution(testcase_name: str, status: str, log: str, error_message: str) -> dict:
    """通过 AI 分析执行结果"""
    prompt = ANALYZE_PROMPT.format(
        testcase_name=testcase_name,
        status=status,
        log=log,
        error_message=error_message,
    )
    raw = _call_claude(prompt)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        import re
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError(f"AI 返回的内容不是有效 JSON:\n{raw[:500]}")
