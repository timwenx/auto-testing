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

BATCH_GENERATE_SYSTEM_PROMPT = """你是一个专业的 QA 测试工程师。你需要根据提供的代码分析结果和用户描述，批量生成高质量的测试用例。

## 任务说明
用户从代码分析中选择了若干页面/API 目标，请为每个目标生成测试用例。
- 一个目标可能生成多条用例（正常流程、边界、异常等）
- 每条用例必须包含完整字段
- 如果提供了前置条件，插入到每条用例的"前置条件"部分

## 使用分析结果中的元素和参数信息
- 当提供了**页面元素(elements)**时，测试步骤中应直接引用这些 CSS selector 进行操作描述（如「在 `#search-input` 输入用户名」），不要猜测或虚构选择器
- 当提供了**API 参数(params)**时，请求体示例应使用这些参数名和类型
- 如果 elements 或 params 为空或缺失，则根据页面/API 描述合理推断测试步骤

## 返回格式
返回一个 JSON 数组（不要用 markdown 代码块包裹），每个元素包含：
{
  "name": "用例名称（简短，用于列表展示）",
  "description": "用例描述",
  "steps": "测试步骤（自然语言，分步骤描述，页面测试时使用提供的选择器）",
  "expected_result": "预期结果",
  "priority": "P0 或 P1 或 P2",
  "test_type": "功能/边界/异常/安全",
  "feature_group": "所属功能模块（根据测试目标自动归类，如「用户登录」「订单管理」，相同功能用相同名称）",
  "markdown_content": "完整的 Markdown 测试用例文档",
  "target_page_or_api": "对应的页面路径或 API 端点",
  "source_item": "来源目标名称（便于追踪）",
  "test_context": {
    "context_type": "page 或 api",
    "path": "对应的路径",
    "method": "HTTP方法（API类型时填写）",
    "source_file": "来源文件",
    "elements": ["传递该目标关联的元素列表（如有）"],
    "params": ["传递该目标关联的参数列表（如有）"],
    "response_fields": ["传递该目标关联的响应字段列表（如有）"]
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
        source_file = item.get('source_file', '')
        elements = item.get('elements', [])
        params = item.get('params', [])
        response_fields = item.get('response_fields', [])

        user_desc = user_descriptions.get(path, '')

        desc = f"### 目标: {name}\n"
        desc += f"- 类型: {'页面' if item_type == 'page' else 'API'}\n"
        desc += f"- 路径: {path}\n"
        if method:
            desc += f"- 方法: {method}\n"
        if source_file:
            desc += f"- 来源文件: {source_file}\n"
        if auto_desc:
            desc += f"- 自动分析描述: {auto_desc}\n"

        # 注入页面元素信息
        if elements:
            desc += f"- 页面元素 ({len(elements)} 个):\n"
            for elem in elements:
                selector = elem.get('selector', '')
                elem_type = elem.get('type', '')
                label = elem.get('label', '')
                elem_desc = elem.get('description', '')
                desc += f"  - {selector} ({elem_type}) {label}"
                if elem_desc:
                    desc += f" — {elem_desc}"
                desc += "\n"

        # 注入 API 参数信息
        if params:
            desc += f"- 请求参数 ({len(params)} 个):\n"
            for param in params:
                p_name = param.get('name', '')
                p_in = param.get('in', '')
                p_type = param.get('type', '')
                p_required = param.get('required', False)
                p_desc = param.get('description', '')
                req_mark = '必填' if p_required else '可选'
                desc += f"  - {p_name} ({p_in}, {p_type}, {req_mark})"
                if p_desc:
                    desc += f" — {p_desc}"
                desc += "\n"

        # 注入 API 响应字段信息
        if response_fields:
            desc += f"- 响应字段 ({len(response_fields)} 个):\n"
            for field in response_fields:
                f_name = field.get('name', '')
                f_type = field.get('type', '')
                f_desc = field.get('description', '')
                desc += f"  - {f_name} ({f_type})"
                if f_desc:
                    desc += f" — {f_desc}"
                desc += "\n"

        if user_desc:
            desc += f"- 用户补充描述: {user_desc}\n"
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

    response = client.messages.create(
        model=model,
        max_tokens=8192,
        system=BATCH_GENERATE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    raw_text = response.content[0].text.strip()

    # 解析 JSON
    return _parse_testcases_response(raw_text)


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
    """从 Claude 响应中解析测试用例 JSON 数组"""
    try:
        result = json.loads(raw_text)
        return result if isinstance(result, list) else []
    except json.JSONDecodeError:
        match = re.search(r'```(?:json)?\s*([\s\S]*?)```', raw_text)
        if match:
            try:
                result = json.loads(match.group(1).strip())
                return result if isinstance(result, list) else []
            except json.JSONDecodeError:
                pass
        match = re.search(r'\[[\s\S]*\]', raw_text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        logger.error("[BatchGenerator] Cannot parse testcases response: %s", raw_text[:500])
        return []
