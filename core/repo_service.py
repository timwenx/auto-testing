"""
仓库服务 — Git 仓库克隆、更新、文件树和代码搜索
"""
import logging
import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from django.conf import settings

logger = logging.getLogger(__name__)

# 默认忽略的目录和文件
IGNORED_DIRS = {
    '.git', 'node_modules', '__pycache__', '.venv', 'venv', 'env',
    'dist', 'build', '.idea', '.vscode', '.next', '.nuxt', 'coverage',
}
MAX_FILE_SIZE = 50 * 1024  # 50KB
MAX_TREE_DEPTH = 3
MAX_TREE_FILES = 500
MAX_SEARCH_RESULTS = 20


def _get_repo_base_path() -> Path:
    """获取仓库克隆根目录"""
    from .models import SystemSetting
    base = SystemSetting.get('repo_base_path', 'repos')
    path = settings.BASE_DIR / base
    path.mkdir(parents=True, exist_ok=True)
    return path


def _build_auth_url(repo_url: str, username: str, password: str) -> str:
    """将凭证嵌入 HTTPS URL（用于 git clone/pull）"""
    if not username and not password:
        return repo_url
    parsed = urlparse(repo_url)
    if parsed.scheme not in ('http', 'https'):
        return repo_url
    # 构建 https://user:pass@host/path 格式
    auth = username
    if password:
        auth = f"{username}:{password}" if username else password
    netloc = f"{auth}@{parsed.hostname}"
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, ''))


def clone_or_update_repo(project) -> str:
    """
    克隆或更新项目仓库。
    返回本地仓库路径。失败时抛出 RuntimeError。
    """
    if not project.repo_url:
        raise RuntimeError("项目未配置 Git 仓库地址")

    base_path = _get_repo_base_path()
    repo_dir = base_path / f"project_{project.id}"

    if repo_dir.exists() and (repo_dir / '.git').exists():
        # 已存在 → git pull
        logger.info("Updating repo for project #%s at %s", project.id, repo_dir)
        auth_url = _build_auth_url(project.repo_url, project.repo_username, project.repo_password)
        try:
            result = subprocess.run(
                ['git', 'pull', '--ff-only'],
                capture_output=True, text=True, timeout=120,
                cwd=str(repo_dir),
                env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'},
            )
            if result.returncode != 0:
                logger.warning("git pull failed: %s", result.stderr)
                # pull 失败不阻断流程，使用已有代码
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.warning("git pull error: %s", e)
    else:
        # 需要 clone
        logger.info("Cloning repo for project #%s from %s", project.id, project.repo_url)
        if repo_dir.exists():
            import shutil
            shutil.rmtree(repo_dir, ignore_errors=True)

        auth_url = _build_auth_url(project.repo_url, project.repo_username, project.repo_password)
        try:
            result = subprocess.run(
                ['git', 'clone', '--depth', '1', auth_url, str(repo_dir)],
                capture_output=True, text=True, timeout=300,
                env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'},
            )
            if result.returncode != 0:
                raise RuntimeError(f"Git clone 失败: {result.stderr.strip()}")
        except FileNotFoundError:
            raise RuntimeError("Git 未安装或不在 PATH 中")
        except subprocess.TimeoutExpired:
            raise RuntimeError("Git clone 超时（300秒），仓库可能过大")

    # 更新项目的本地路径
    project.local_repo_path = str(repo_dir)
    project.save(update_fields=['local_repo_path'])

    return str(repo_dir)


def get_repo_file_tree(project, max_depth: int = MAX_TREE_DEPTH) -> str:
    """
    获取仓库的目录树结构（字符串格式），用于注入 AI prompt。
    返回格式化的目录树文本。
    """
    if not project.local_repo_path:
        raise RuntimeError("仓库未克隆，请先克隆仓库")

    repo_path = Path(project.local_repo_path)
    if not repo_path.exists():
        raise RuntimeError("本地仓库路径不存在")

    lines = []
    file_count = 0

    def _walk(dir_path: Path, prefix: str = '', depth: int = 0):
        nonlocal file_count
        if depth >= max_depth or file_count >= MAX_TREE_FILES:
            return

        try:
            entries = sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            return

        for entry in entries:
            if entry.name in IGNORED_DIRS or entry.name.startswith('.'):
                continue
            if file_count >= MAX_TREE_FILES:
                lines.append(f"{prefix}... (已达到最大文件数 {MAX_TREE_FILES})")
                return

            if entry.is_dir():
                lines.append(f"{prefix}{entry.name}/")
                _walk(entry, prefix + '  ', depth + 1)
            else:
                # 显示文件大小
                size = entry.stat().st_size
                if size > MAX_FILE_SIZE:
                    size_str = f" ({size // 1024}KB)"
                else:
                    size_str = ''
                lines.append(f"{prefix}{entry.name}{size_str}")
                file_count += 1

    _walk(repo_path)
    return '\n'.join(lines)


def read_file_content(project, file_path: str) -> str:
    """
    读取仓库中指定文件的内容。
    file_path 是相对于仓库根目录的路径。
    超大文件只读取前 N 行。
    """
    if not project.local_repo_path:
        raise RuntimeError("仓库未克隆")

    full_path = Path(project.local_repo_path) / file_path
    if not full_path.exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")

    if not full_path.is_file():
        raise ValueError(f"不是文件: {file_path}")

    # 安全检查：不允许路径穿越
    try:
        full_path.resolve().relative_to(Path(project.local_repo_path).resolve())
    except ValueError:
        raise ValueError("非法的文件路径")

    size = full_path.stat().st_size
    if size > MAX_FILE_SIZE:
        # 只读前 500 行
        with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = []
            for i, line in enumerate(f):
                if i >= 500:
                    lines.append(f"\n... (文件过大，已截断，共 {size // 1024}KB)")
                    break
                lines.append(line)
            return ''.join(lines)

    with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
        return f.read()


def search_code(project, keyword: str) -> list[dict]:
    """
    在仓库中搜索关键词，返回匹配的文件和行。
    返回 [{'file': relative_path, 'line_num': int, 'line': str}, ...]
    """
    if not project.local_repo_path:
        raise RuntimeError("仓库未克隆")

    repo_path = Path(project.local_repo_path)
    results = []
    keyword_lower = keyword.lower()

    def _search_in_dir(dir_path: Path, depth: int = 0):
        if depth >= MAX_TREE_DEPTH or len(results) >= MAX_SEARCH_RESULTS:
            return
        try:
            entries = sorted(dir_path.iterdir(), key=lambda p: p.name)
        except PermissionError:
            return

        for entry in entries:
            if len(results) >= MAX_SEARCH_RESULTS:
                return
            if entry.name in IGNORED_DIRS or entry.name.startswith('.'):
                continue

            if entry.is_dir():
                _search_in_dir(entry, depth + 1)
            elif entry.is_file():
                # 跳过二进制和超大文件
                if entry.stat().st_size > MAX_FILE_SIZE:
                    continue
                try:
                    with open(entry, 'r', encoding='utf-8', errors='ignore') as f:
                        for line_num, line in enumerate(f, 1):
                            if keyword_lower in line.lower():
                                rel_path = str(entry.relative_to(repo_path))
                                results.append({
                                    'file': rel_path,
                                    'line_num': line_num,
                                    'line': line.rstrip()[:200],
                                })
                                if len(results) >= MAX_SEARCH_RESULTS:
                                    return
                except (OSError, UnicodeDecodeError):
                    continue

    _search_in_dir(repo_path)
    return results
