"""
Claude CLI 服务 — 通过 subprocess 调用 Claude Code CLI 进行代码分析

核心功能：
- is_cli_available() — 检测 CLI 是否已安装且可执行
- call_cli() — 非交互式调用 CLI 并返回纯文本响应
- get_cli_settings() — 从 SystemSetting 读取 CLI 相关配置
"""
import logging
import os
import subprocess

logger = logging.getLogger(__name__)


def get_cli_settings() -> dict:
    """从 SystemSetting 读取 CLI 相关配置，提供默认值"""
    from .models import SystemSetting
    return {
        'cli_path': SystemSetting.get('claude_cli_path', 'claude'),
        'timeout': int(SystemSetting.get('claude_cli_timeout', '300') or '300'),
        'analysis_engine': SystemSetting.get('analysis_engine', 'cli'),
        'api_key': SystemSetting.get('anthropic_api_key', ''),
    }


def is_cli_available(cli_path: str = None) -> tuple:
    """
    检测 Claude CLI 是否已安装且可执行。

    Args:
        cli_path: CLI 可执行文件路径，默认从 SystemSetting 读取

    Returns:
        (bool, str) 元组: (是否可用, 版本号或错误信息)
    """
    if not cli_path:
        settings = get_cli_settings()
        cli_path = settings['cli_path']

    try:
        result = subprocess.run(
            [cli_path, '--version'],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            return True, version
        else:
            error = result.stderr.strip() or f"退出码: {result.returncode}"
            return False, error
    except FileNotFoundError:
        return False, f"CLI 未找到: {cli_path}"
    except subprocess.TimeoutExpired:
        return False, "CLI 检测超时"
    except Exception as e:
        return False, str(e)


def call_cli(prompt: str, cwd: str, model: str = None, timeout: int = None) -> str:
    """
    通过 subprocess 调用 Claude CLI 进行非交互式分析。

    使用 `claude -p <prompt> --output-format text` 模式：
    - -p: 非交互模式，直接输出到 stdout
    - --output-format text: 纯文本输出，便于解析

    Args:
        prompt: 分析提示词
        cwd: CLI 工作目录（通常为仓库本地路径）
        model: 可选，指定 AI 模型
        timeout: 超时秒数，默认从 SystemSetting 读取

    Returns:
        CLI 的纯文本响应

    Raises:
        FileNotFoundError: CLI 未安装
        subprocess.TimeoutExpired: CLI 调用超时
        RuntimeError: CLI 返回非零退出码
    """
    settings = get_cli_settings()
    cli_path = settings['cli_path']
    if timeout is None:
        timeout = settings['timeout']

    # 注入 API Key 到环境变量
    env = os.environ.copy()
    if settings['api_key']:
        env['ANTHROPIC_API_KEY'] = settings['api_key']

    # 构造命令
    cmd = [cli_path, '-p', prompt, '--output-format', 'text']
    if model:
        cmd.extend(['--model', model])

    logger.info(
        "[CLIService] Calling CLI: cwd=%s, timeout=%ds, prompt_len=%d",
        cwd, timeout, len(prompt),
    )

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env=env,
        )
    except FileNotFoundError:
        logger.error("[CLIService] CLI not found: %s", cli_path)
        raise
    except subprocess.TimeoutExpired:
        logger.error("[CLIService] CLI timeout (%ds)", timeout)
        raise

    if result.returncode != 0:
        stderr = result.stderr.strip()
        logger.error(
            "[CLIService] CLI failed (exit %d): %s",
            result.returncode, stderr[:500],
        )
        raise RuntimeError(f"Claude CLI 执行失败 (exit {result.returncode}): {stderr}")

    output = result.stdout.strip()
    logger.info("[CLIService] CLI response: %d chars", len(output))
    return output
