"""
批量测试用例生成服务 — 根据仓库分析结果批量生成测试用例

核心流程：
1. 接收用户从分析结果中勾选的 items + 用户描述
2. 加载可选的前置条件模板
3. 构造 Claude API 请求，批量生成结构化测试用例
4. 返回用例列表（不直接保存 DB，让用户确认后再保存）
"""
import json
import logging
import re

from .ai_engine import _get_client, _get_model, _load_template

logger = logging.getLogger(__name__)

BATCH_GENERATE_SYSTEM_PROMPT = """你是一个专业的 QA 测试工程师。你需要根据提供的分析结果和用户描述，批量生成高质量的测试用例。

## 任务说明
用户从代码分析中选择了若干页面/API 目标，请为每个目标生成测试用例。
- 一个目标生成 1-3 条用例（正常流程为主，必要时补充边界和异常）
- 如果提供了前置条件，插入到每条用例的"前置条件"部分

## 返回格式
返回一个 JSON 数组（不要用 markdown 代码块包裹），每个元素包含：
{
  "name": "用例名称（简短，用于列表展示）",
  "description": "用例描述",
  "steps": "测试步骤（自然语言，分步骤描述）",
  "expected_result": "预期结果",
  "priority": "P0 或 P1 或 P2",
  "test_type": "功能/边界/异常/安全",
  "feature_group": "所属功能模块（根据测试目标自动归类，如「用户登录」「订单管理」，相同功能用相同名称）",
  "markdown_content": "按模板格式生成的完整 Markdown 测试用例文档",
  "target_page_or_api": "对应的页面路径或 API 端点",
  "source_item": "来源目标名称",
  "test_context": {
    "context_type": "page 或 api",
    "path": "对应的路径",
    "method": "HTTP方法（仅API填写）"
  }
}

按功能点聚合输出，同一功能点内的用例按执行顺序排列。只返回 JSON 数组，不要其他文字。"""

# 单次生成的最大目标数（避免超 token）
MAX_ITEMS_PER_BATCH = 15


def generate_testcases_for_items(project, selected_items, user_descriptions,
                                 precondition_template=None) -> list:
    """
    批量生成测试用例。

    Args:
        project: Project 模型实例
        selected_items: list[dict] — 用户勾选的 discovered_items 子集
        user_descriptions: dict — key 为 item 的 path, value 为用户输入的描述
        precondition_template: PreconditionTemplate 实例（可选）

    Returns:
        list[dict] — 生成的用例列表
    """
    all_generated = []
    template = _load_template()

    # 分批处理：避免单次请求超 token
    for batch_start in range(0, len(selected_items), MAX_ITEMS_PER_BATCH):
        batch = selected_items[batch_start:batch_start + MAX_ITEMS_PER_BATCH]
        batch_result = _generate_batch(
            project, batch, user_descriptions, precondition_template, template
        )
        all_generated.extend(batch_result)

    return all_generated


def _generate_batch(project, items, user_descriptions, precondition_template, template) -> list:
    """处理一批 items 的生成"""
    # 构建目标描述
    targets_desc = []
    for item in items:
        path = item.get('path', '')
        item_type = item.get('type', '')
        method = item.get('method', '')
        name = item.get('name', '')
        auto_desc = item.get('description', '')
        feature_group = item.get('feature_group', '')

        user_desc = user_descriptions.get(path, '')

        desc = f"### 目标: {name}\n"
        desc += f"- 类型: {'页面' if item_type == 'page' else 'API'}\n"
        desc += f"- 路径: {path}\n"
        if feature_group:
            desc += f"- 所属功能: {feature_group}\n"
        if method:
            desc += f"- 方法: {method}\n"
        if auto_desc:
            desc += f"- 描述: {auto_desc}\n"
        if user_desc:
            desc += f"- 用户补充: {user_desc}\n"
        targets_desc.append(desc)

    targets_section = "\n".join(targets_desc)

    # 前置条件部分
    precondition_section = ""
    if precondition_template:
        precondition_section = f"""## 前置条件（必须插入到每条用例中）

### {precondition_template.name}
{precondition_template.steps}

{precondition_template.markdown_content}
"""

    # 模板部分
    template_section = ""
    if template:
        template_section = f"请按照以下 Markdown 模板格式生成 markdown_content 字段：\n\n{template}"

    user_message = f"""## 项目信息
- 项目名称: {project.name}
- 项目 URL: {project.base_url or '未配置'}

## 选中的测试目标
{targets_section}

{precondition_section}

{template_section}

请为以上 {len(items)} 个目标生成测试用例。每个目标至少生成 1 条正常流程用例，必要时补充边界和异常用例。"""

    client = _get_client()
    model = _get_model()

    logger.info("[BatchGenerator] Generating testcases for project #%s, %d items (model: %s)",
                project.id, len(items), model)
    print(f"[BatchGenerator] 调用 AI API: 项目#{project.id}, {len(items)} 个目标, 模型={model}")

    try:
        response = client.messages.create(
            model=model,
            max_tokens=16384,
            system=BATCH_GENERATE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as e:
        print(f"[BatchGenerator] AI API 调用失败: {e}")
        logger.exception("[BatchGenerator] AI API call failed for project #%s", project.id)
        return []

    if getattr(response, 'stop_reason', None) == 'max_tokens':
        logger.warning("[BatchGenerator] Response truncated (hit max_tokens limit, model=%s)", model)
        print("[BatchGenerator] 警告: AI 响应被截断，尝试修复...")

    raw_text = response.content[0].text.strip()
    print(f"[BatchGenerator] AI 返回 {len(raw_text)} 字符, 解析中...")

    # 解析 JSON
    result = _parse_testcases_response(raw_text)
    print(f"[BatchGenerator] 解析结果: {len(result)} 条用例")
    return result


def generate_testcases_single(project, item, user_description, precondition=None) -> dict:
    """
    为单个目标生成测试用例（用于重新生成单条）。

    Args:
        project: Project 模型实例
        item: dict — 单个 discovered_item
        user_description: str — 用户描述
        precondition: PreconditionTemplate 实例（可选）

    Returns:
        dict — 生成的测试用例（单条）
    """
    results = generate_testcases_for_items(
        project, [item],
        {item.get('path', ''): user_description},
        precondition_template=precondition,
    )
    if not results:
        logger.warning("[BatchGenerator] Single generation returned no results for item: %s",
                       item.get('path', 'unknown'))
    return results[0] if results else {}


def _parse_testcases_response(raw_text: str) -> list:
    """从 AI 响应中解析测试用例 JSON 数组，支持截断修复"""
    # 1. 直接解析
    try:
        result = json.loads(raw_text)
        return result if isinstance(result, list) else []
    except json.JSONDecodeError:
        pass

    # 2. 从 markdown 代码块中提取（贪婪匹配，避免 markdown_content 内嵌的 ``` 截断）
    match = re.search(r'```(?:json)?\s*([\s\S]*)```', raw_text)
    if match:
        try:
            result = json.loads(match.group(1).strip())
            return result if isinstance(result, list) else []
        except json.JSONDecodeError:
            pass

    # 3. 提取最外层 [...]
    match = re.search(r'\[[\s\S]*\]', raw_text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # 4. 修复截断的 JSON（AI 输出被 max_tokens 截断导致缺少闭合括号）
    repaired = _repair_truncated_json(raw_text)
    if repaired is not None:
        return repaired

    logger.error("[BatchGenerator] Cannot parse testcases response (first 300): %s", raw_text[:300])
    logger.error("[BatchGenerator] Response tail (last 200): %s", raw_text[-200:])
    return []


def _repair_truncated_json(text: str) -> list | None:
    """尝试修复被截断的 JSON 数组：从最后一个完整的 } 开始截断，补上 ]"""
    # 找到 JSON 数组起始
    bracket_start = text.find('[')
    if bracket_start == -1:
        return None

    array_text = text[bracket_start:]

    # 策略：从后往前找每一个 }，尝试补全
    for i in range(len(array_text) - 1, -1, -1):
        if array_text[i] == '}':
            candidate = array_text[:i + 1] + ']'
            try:
                result = json.loads(candidate)
                if isinstance(result, list) and len(result) > 0:
                    logger.warning("[BatchGenerator] Repaired truncated JSON: recovered %d items", len(result))
                    print(f"[BatchGenerator] 修复截断 JSON: 恢复了 {len(result)} 条用例")
                    return result
            except json.JSONDecodeError:
                continue

    return None
