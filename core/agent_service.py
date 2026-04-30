"""
Agent 服务 — 基于 Anthropic SDK tool_use 的 Agent 循环核心。

AgentRunner 管理与 Claude 的多轮工具调用对话：
1. 发送消息 + 工具定义给 Claude
2. 如果 Claude 返回 tool_use → 执行工具 → 结果回传 → 继续
3. 如果 Claude 返回 end_turn → 提取最终文本 → 结束
4. 浏览器实例在 Agent 循环内 lazy init + finally cleanup

refine_testcase_with_agent — 无工具的单用例对话式调整。
"""
import json
import logging
import time

from .agent_tools import get_tool_schemas, get_tool_executor, get_browser_tool_names

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════
# refine_testcase_with_agent — 单用例 Agent 多轮对话
# ══════════════════════════════════════════════════════════════════

REFINE_SYSTEM_PROMPT = """你是一个资深的测试工程师 AI 助手，专注于测试用例的评审和优化。

你的职责：
1. 分析当前测试用例的完整性和覆盖度
2. 主动提问或建议补充缺失的测试场景
3. 根据用户反馈修改用例内容
4. 确保用例描述清晰、步骤可执行、预期结果明确

## 响应格式

你的回复必须是一个 JSON 对象（不要用 markdown 代码块包裹），包含以下字段：

```json
{
  "action": "question" 或 "update",
  "message": "给用户的文字说明（提问或修改说明）",
  "suggestions": ["建议1", "建议2", ...],  // 当 action=question 时，提供可选的改进建议标签
  "updated_testcase": {                    // 当 action=update 时，提供修改后的用例
    "name": "用例名称",
    "description": "用例描述",
    "steps": "测试步骤",
    "expected_result": "预期结果",
    "markdown_content": "完整的 Markdown 格式用例文档",
    "priority": "P0/P1/P2",
    "test_type": "测试类型"
  }
}
```

注意：
- 如果用户没有提供反馈（首次调用），主动分析用例并提出 2-3 个改进建议
- 如果用户提供了反馈，根据反馈修改用例并返回更新后的版本
- 每次回复中 action 必须是 "question" 或 "update" 之一
- markdown_content 应该是完整的、格式化的测试用例文档"""


def refine_testcase_with_agent(testcase, project, user_feedback=None):
    """
    对单个测试用例进行 Agent 驱动的多轮对话式调整。

    Args:
        testcase: TestCase 对象
        project: Project 对象
        user_feedback: 用户反馈文本。为空时 Agent 主动提问；非空时根据反馈修改用例。

    Returns:
        dict: {
            'action': 'question' | 'update',
            'message': str,
            'suggestions': list[str],  # 仅 question 时
            'updated_testcase': dict | None,  # 仅 update 时
        }

    Side effects:
        更新 testcase.conversation_history（追加本轮对话）
        当 action='update' 时，更新 testcase 字段并 bump version
    """
    from .ai_engine import _get_client, _get_model

    client = _get_client()
    model = _get_model()

    # 加载现有对话历史
    conversation_history = list(testcase.conversation_history or [])

    # 构建当前用例信息
    testcase_info = {
        'name': testcase.name,
        'description': testcase.description,
        'steps': testcase.steps,
        'expected_result': testcase.expected_result,
        'markdown_content': testcase.markdown_content,
        'priority': testcase.priority,
        'test_type': testcase.test_type,
        'target_page_or_api': testcase.target_page_or_api,
        'version': testcase.version,
    }

    # 构建用户消息
    if user_feedback:
        user_content = json.dumps({
            'user_feedback': user_feedback,
            'current_testcase': testcase_info,
        }, ensure_ascii=False)
    else:
        user_content = json.dumps({
            'message': '请分析这个测试用例并提出改进建议',
            'current_testcase': testcase_info,
            'project_name': project.name,
            'base_url': project.base_url,
        }, ensure_ascii=False)

    # 构建 messages（包含历史 + 当前消息）
    messages = list(conversation_history)
    messages.append({"role": "user", "content": user_content})

    # 调用 Claude API（直接调用，不走 AgentRunner）
    try:
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=REFINE_SYSTEM_PROMPT,
            messages=messages,
        )
    except Exception as e:
        logger.exception("Refine API call failed")
        raise

    # 提取回复文本
    assistant_text = ''
    for block in response.content:
        if block.type == 'text':
            assistant_text += block.text

    # 解析 JSON 回复
    try:
        result = json.loads(assistant_text)
    except json.JSONDecodeError:
        # 尝试提取 JSON 子串（Claude 可能在 JSON 前后附加文字）
        import re
        json_match = re.search(r'\{[\s\S]*\}', assistant_text)
        if json_match:
            try:
                result = json.loads(json_match.group())
            except json.JSONDecodeError:
                result = {
                    'action': 'question',
                    'message': assistant_text,
                    'suggestions': [],
                }
        else:
            result = {
                'action': 'question',
                'message': assistant_text,
                'suggestions': [],
            }

    action = result.get('action', 'question')

    # 追加到对话历史
    conversation_history.append({"role": "user", "content": user_content})
    # 截断过长的 AI 回复（避免 JSONField 膨胀）
    stored_reply = assistant_text if len(assistant_text) <= 5000 else assistant_text[:5000] + '\n...(已截断)'
    conversation_history.append({"role": "assistant", "content": stored_reply})

    # 更新 testcase 的对话历史
    testcase.conversation_history = conversation_history
    update_fields = ['conversation_history']

    # 如果是 update，更新用例字段
    if action == 'update' and result.get('updated_testcase'):
        updated = result['updated_testcase']
        testcase.name = updated.get('name', testcase.name)
        testcase.description = updated.get('description', testcase.description)
        testcase.steps = updated.get('steps', testcase.steps)
        testcase.expected_result = updated.get('expected_result', testcase.expected_result)
        testcase.markdown_content = updated.get('markdown_content', testcase.markdown_content)
        testcase.priority = updated.get('priority', testcase.priority)
        testcase.test_type = updated.get('test_type', testcase.test_type)
        testcase.version = (testcase.version or 1) + 1
        update_fields.extend([
            'name', 'description', 'steps', 'expected_result',
            'markdown_content', 'priority', 'test_type', 'version',
        ])

    testcase.save(update_fields=update_fields)

    return result


def _extract_target(tool_name, tool_input):
    """从工具输入中提取目标摘要，用于事件推送"""
    if not isinstance(tool_input, dict):
        return ''
    if tool_name == 'browser_navigate':
        return tool_input.get('url', '')
    elif tool_name in ('browser_click', 'browser_fill', 'browser_get_text', 'browser_press_key'):
        return tool_input.get('selector', '')
    elif tool_name == 'browser_wait_for':
        return tool_input.get('selector', '')
    elif tool_name == 'browser_screenshot':
        return 'screenshot'
    elif tool_name == 'report_result':
        return tool_input.get('summary', '')
    elif tool_name in ('list_files', 'list_directory'):
        return tool_input.get('path', '')
    elif tool_name == 'read_file':
        return tool_input.get('file_path', '')
    elif tool_name == 'search_code':
        return tool_input.get('query', '')
    return ''


class AgentRunner:
    """
    Agent 执行引擎。

    用法:
        runner = AgentRunner(project=project)
        result = runner.run(system_prompt="...", messages=[...], max_turns=20)
    """

    def __init__(self, project, testcase_id=None, execution_id=None):
        self.project = project
        self.testcase_id = testcase_id
        self.execution_id = execution_id
        self._playwright = None
        self._browser = None
        self._page = None
        self._screenshot_stream = None
        # 执行日志
        self._tool_calls_log = []
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        # 是否有浏览器工具被调用过（用于决定是否需要清理）
        self._browser_used = False

    def run(self, system_prompt: str, messages: list, max_turns: int = 20) -> dict:
        """
        执行 Agent 主循环。

        Args:
            system_prompt: 系统提示词
            messages: 初始消息列表 [{"role": "user", "content": "..."}]
            max_turns: 最大工具调用轮次

        Returns:
            {
                'response_text': str,       # Claude 最终文本回复
                'tool_calls_log': list,     # 工具调用记录
                'total_input_tokens': int,
                'total_output_tokens': int,
            }
        """
        from .ai_engine import _get_client, _get_model
        from .event_emitter import _emit_step_event

        client = _get_client()
        model = _get_model()
        tool_schemas = get_tool_schemas()
        browser_tool_names = get_browser_tool_names()

        # 构建运行时 context
        context = {
            'project': self.project,
            'project_id': self.project.pk,
            'testcase_id': self.testcase_id,
            'page': None,  # lazy init
            'screenshot_counter': 0,
        }

        response_text = ''
        turn = 0

        try:
            while turn < max_turns:
                turn += 1
                logger.info("[Agent] Turn %d/%d", turn, max_turns)

                # 调用 Claude API
                response = client.messages.create(
                    model=model,
                    max_tokens=4096,
                    system=system_prompt,
                    messages=messages,
                    tools=tool_schemas,
                )

                # 累计 token 统计
                self._total_input_tokens += response.usage.input_tokens
                self._total_output_tokens += response.usage.output_tokens

                # 解析响应中的 content blocks
                tool_use_blocks = []
                text_parts = []

                for block in response.content:
                    if block.type == 'text':
                        text_parts.append(block.text)
                    elif block.type == 'tool_use':
                        tool_use_blocks.append(block)

                if text_parts:
                    response_text = '\n'.join(text_parts)
                    # 推送 Agent 思维过程
                    if self.execution_id:
                        _emit_step_event(self.execution_id, 'agent_thinking', {
                            'text': response_text[:500],
                        })

                # 如果没有工具调用，Agent 循环结束
                if response.stop_reason == 'end_turn' or not tool_use_blocks:
                    logger.info("[Agent] 结束: stop_reason=%s", response.stop_reason)
                    break

                # 执行所有工具调用并收集 tool_result
                assistant_content = response.content  # 完整的 assistant content blocks
                tool_results = []

                for tool_use in tool_use_blocks:
                    tool_name = tool_use.name
                    tool_input = tool_use.input
                    logger.info("[Agent] 工具调用: %s(%s)", tool_name, tool_input)

                    # 推送步骤开始事件
                    step_start_time = time.time()
                    if self.execution_id:
                        _emit_step_event(self.execution_id, 'step_start', {
                            'step_num': len(self._tool_calls_log) + 1,
                            'action': tool_name,
                            'target': _extract_target(tool_name, tool_input),
                        })

                    # 检查是否需要初始化浏览器
                    if tool_name in browser_tool_names:
                        self._ensure_browser(context)

                    # 执行工具
                    executor = get_tool_executor(tool_name)
                    if executor is None:
                        result_text = f"Error: 未知工具 '{tool_name}'"
                    else:
                        try:
                            result_text = executor(tool_input, context)
                        except Exception as e:
                            logger.exception("[Agent] 工具执行异常: %s", tool_name)
                            result_text = f"Error: {e}"

                    # 记录日志
                    self._tool_calls_log.append({
                        'turn': turn,
                        'tool': tool_name,
                        'input': tool_input,
                        'output': result_text[:500],  # 截断避免日志过大
                        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                    })

                    # 推送步骤完成事件
                    if self.execution_id:
                        duration_ms = int((time.time() - step_start_time) * 1000)
                        screenshot_path = ''
                        if '截图已保存:' in (result_text or ''):
                            screenshot_path = result_text.split('截图已保存:')[-1].strip()
                        _emit_step_event(self.execution_id, 'step_complete', {
                            'step_num': len(self._tool_calls_log),
                            'action': tool_name,
                            'target': _extract_target(tool_name, tool_input),
                            'result': (result_text or '')[:300],
                            'screenshot_path': screenshot_path,
                            'duration_ms': duration_ms,
                        })

                    tool_results.append({
                        'type': 'tool_result',
                        'tool_use_id': tool_use.id,
                        'content': result_text,
                    })

                # 将 assistant 响应和 tool_result 追加到消息
                messages.append({"role": "assistant", "content": assistant_content})
                messages.append({"role": "user", "content": tool_results})

        finally:
            # 确保浏览器资源始终释放
            self._cleanup_browser(context)

        if turn >= max_turns:
            logger.warning("[Agent] 达到最大轮次 %d，强制结束", max_turns)

        # 推送执行结束事件
        if self.execution_id:
            _emit_step_event(self.execution_id, 'execution_end', {
                'status': 'completed',
                'total_steps': len(self._tool_calls_log),
                'input_tokens': self._total_input_tokens,
                'output_tokens': self._total_output_tokens,
            })

        return {
            'response_text': response_text,
            'tool_calls_log': self._tool_calls_log,
            'total_input_tokens': self._total_input_tokens,
            'total_output_tokens': self._total_output_tokens,
        }

    def _ensure_browser(self, context):
        """确保 Playwright 浏览器已初始化"""
        if self._page is not None:
            context['page'] = self._page
            return

        logger.info("[Agent] 初始化 Playwright 浏览器")
        try:
            from playwright.sync_api import sync_playwright
            from .models import SystemSetting
            headless_str = SystemSetting.get('agent_headless', 'true')
            headless = headless_str.strip().lower() in ('true', '1', 'yes')
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=headless)
            self._page = self._browser.new_page()
            context['page'] = self._page
            self._browser_used = True
        except Exception as e:
            logger.error("[Agent] 浏览器初始化失败: %s", e)
            raise RuntimeError(f"Playwright 浏览器初始化失败: {e}")

        # 启动截图流（Phase 2 — 实时浏览器画面推送）
        if self.execution_id:
            try:
                from .screenshot_stream import ScreenshotStream
                self._screenshot_stream = ScreenshotStream()
                self._screenshot_stream.start(self._page, self.execution_id)
            except Exception as e:
                logger.warning("[Agent] 截图流启动失败（非致命）: %s", e)

    def _cleanup_browser(self, context):
        """清理浏览器资源"""
        # 先停止截图流（在关闭 page 之前）
        if self._screenshot_stream:
            try:
                self._screenshot_stream.stop()
            except Exception as e:
                logger.warning("[Agent] 停止截图流失败: %s", e)
            self._screenshot_stream = None

        if not self._browser_used:
            return

        logger.info("[Agent] 清理 Playwright 浏览器资源")
        try:
            if self._page:
                self._page.close()
                self._page = None
        except Exception as e:
            logger.warning("[Agent] 关闭 page 失败: %s", e)

        try:
            if self._browser:
                self._browser.close()
                self._browser = None
        except Exception as e:
            logger.warning("[Agent] 关闭 browser 失败: %s", e)

        try:
            if self._playwright:
                self._playwright.stop()
                self._playwright = None
        except Exception as e:
            logger.warning("[Agent] 停止 playwright 失败: %s", e)

        context['page'] = None
