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
import sys
import threading
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
        return tool_input.get('path', '')
    elif tool_name == 'search_code':
        return tool_input.get('keyword', '')
    return ''


def format_step_action(tool_name, tool_input):
    """将工具名称和输入转换为人类可读的步骤描述（action 字段）。

    供 AgentRunner._persist_step() 和 execution_engine._build_step_logs() 共用，
    保证实时写入与历史回填的数据格式一致。
    """
    if not isinstance(tool_input, dict):
        return tool_name
    if tool_name == 'browser_fill':
        return f"填写 {tool_input.get('value', '')[:30]}"
    elif tool_name == 'browser_screenshot':
        return '截图'
    elif tool_name == 'report_result':
        return f"报告结果: {tool_input.get('status', '')}"
    return tool_name


def _extract_screenshot_path(result_text):
    """从工具执行结果中提取截图路径"""
    if not result_text:
        return ''
    if '截图已保存:' in result_text:
        return result_text.split('截图已保存:')[-1].strip()
    return ''


class AgentRunner:
    """
    Agent 执行引擎。

    用法:
        runner = AgentRunner(project=project)
        result = runner.run(system_prompt="...", messages=[...], max_turns=20)
    """

    def __init__(self, project, testcase_id=None, execution_id=None, execution_record=None):
        self.project = project
        self.testcase_id = testcase_id
        self.execution_id = execution_id
        self._execution_record = execution_record  # 用于实时持久化步骤到 DB
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

    def _persist_step(self, tool_name, tool_input, result_text, step_start_time, duration_ms):
        """将单个工具调用步骤实时写入 DB。

        每次工具调用完成后调用一次，追加 step_log 到 ExecutionRecord.step_logs JSONField。
        DB 写入失败不会中断 Agent 执行流程。
        """
        if not self._execution_record:
            return

        # 已在 run() 中 _tool_calls_log.append() 之后调用，len 即为当前步骤的 1-indexed 编号
        step_num = len(self._tool_calls_log)
        step = {
            'step_num': step_num,
            'action': format_step_action(tool_name, tool_input),
            'tool_name': tool_name,
            'target': _extract_target(tool_name, tool_input),
            'result': (result_text or '')[:300],
            'screenshot_path': _extract_screenshot_path(result_text),
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'duration_ms': duration_ms,
        }

        try:
            record = self._execution_record
            # 读取当前 step_logs 并追加新步骤
            current_logs = list(record.step_logs or [])
            current_logs.append(step)

            def _save_step():
                """在独立线程中执行 DB 写入，避免 Playwright 事件循环触发 Django async-safety 检查"""
                try:
                    record.step_logs = current_logs
                    record.tool_calls_count = len(current_logs)
                    record.save(update_fields=['step_logs', 'tool_calls_count'])
                except Exception as exc:
                    logger.warning("[Agent] 步骤持久化写入失败 (step %d): %s", step_num, exc)

            # sync_playwright() 会在后台创建一个 asyncio 事件循环，
            # 导致 Django 5 的 async-safety 检查认为当前是 async 上下文，
            # 拒绝同步 ORM 操作。通过在线程中执行 DB 写入绕过此限制。
            t = threading.Thread(target=_save_step, daemon=True)
            t.start()
            t.join(timeout=5)  # 等待写入完成，最多 5 秒
        except Exception as e:
            logger.warning("[Agent] 步骤实时持久化失败 (step %d): %s", step_num, e)

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

                # 同线程截图轮询（浏览器已打开时）
                if self._screenshot_stream:
                    self._screenshot_stream.maybe_capture()

                # 推送阶段状态：等待 Claude 响应
                if self.execution_id:
                    _emit_step_event(self.execution_id, 'phase_change', {
                        'phase': 'waiting_for_claude',
                    })

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

                    # 推送阶段状态：正在执行步骤
                    if self.execution_id:
                        _emit_step_event(self.execution_id, 'phase_change', {
                            'phase': 'executing_step',
                            'step_num': len(self._tool_calls_log) + 1,
                            'tool_name': tool_name,
                        })

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
                            if tool_name in browser_tool_names and self.execution_id:
                                # 浏览器工具：启动后台心跳 watchdog，
                                # 确保长耗时操作（如 page.goto 30s）期间前端能定期轮询截图。
                                # 注意：watchdog 只发送通知，不直接调用 Playwright（避免线程问题）
                                from .screenshot_stream import run_with_frame_watchdog
                                result_text = run_with_frame_watchdog(
                                    self.execution_id,
                                    lambda: executor(tool_input, context),
                                )
                            else:
                                result_text = executor(tool_input, context)
                        except Exception as e:
                            logger.exception("[Agent] 工具执行异常: %s", tool_name)
                            result_text = f"Error: {e}"

                    # 记录日志（含 duration_ms 用于回放计时）
                    duration_ms = int((time.time() - step_start_time) * 1000)
                    self._tool_calls_log.append({
                        'turn': turn,
                        'tool': tool_name,
                        'input': tool_input,
                        'output': result_text[:500],  # 截断避免日志过大
                        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                        'duration_ms': duration_ms,
                    })

                    # 推送步骤完成事件
                    if self.execution_id:
                        screenshot_path = _extract_screenshot_path(result_text)
                        _emit_step_event(self.execution_id, 'step_complete', {
                            'step_num': len(self._tool_calls_log),
                            'action': tool_name,
                            'target': _extract_target(tool_name, tool_input),
                            'result': (result_text or '')[:300],
                            'screenshot_path': screenshot_path,
                            'duration_ms': duration_ms,
                        })

                    # 实时持久化步骤到 DB（断线重连后 REST 回填可用）
                    self._persist_step(tool_name, tool_input, result_text, step_start_time, duration_ms)

                    # 同线程截图轮询（每个工具调用之后）
                    if self._screenshot_stream:
                        self._screenshot_stream.maybe_capture()

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

            # 推送执行结束事件（放在 finally 中确保异常时也能送达）
            if self.execution_id:
                try:
                    _emit_step_event(self.execution_id, 'execution_end', {
                        'status': 'completed',
                        'total_steps': len(self._tool_calls_log),
                        'input_tokens': self._total_input_tokens,
                        'output_tokens': self._total_output_tokens,
                    })
                except Exception as e:
                    logger.warning("[Agent] Failed to emit execution_end: %s", e)

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

        # 推送阶段状态：正在初始化浏览器
        from .event_emitter import _emit_step_event
        if self.execution_id:
            _emit_step_event(self.execution_id, 'phase_change', {
                'phase': 'initializing_browser',
            })

        try:
            import asyncio
            from playwright.sync_api import sync_playwright
            from .models import SystemSetting

            # Windows 上 Django 使用 SelectorEventLoop，但 Playwright 需要
            # ProactorEventLoop 才能创建子进程（启动浏览器进程）。
            # 临时切换策略，Playwright 创建完自己的事件循环后即可恢复。
            restore_policy = None
            if sys.platform == 'win32':
                restore_policy = asyncio.get_event_loop_policy()
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

            try:
                headless_str = SystemSetting.get('agent_headless', 'true')
                headless = headless_str.strip().lower() in ('true', '1', 'yes')
                self._playwright = sync_playwright().start()
                self._browser = self._playwright.chromium.launch(headless=headless)
                self._page = self._browser.new_page()
                context['page'] = self._page
                self._browser_used = True
            finally:
                if restore_policy is not None:
                    asyncio.set_event_loop_policy(restore_policy)

        except Exception as e:
            logger.error("[Agent] 浏览器初始化失败: %s", e)
            raise RuntimeError(f"Playwright 浏览器初始化失败: {e}")

        # 启动截图流（Phase 2 — 实时浏览器画面推送 + 定时持久化）
        if self.execution_id:
            try:
                from .screenshot_stream import ScreenshotStream
                self._screenshot_stream = ScreenshotStream()
                self._screenshot_stream.start(
                    self._page, self.execution_id,
                    project_id=self.project.pk,
                )
            except Exception as e:
                logger.warning("[Agent] 截图流启动失败（非致命）: %s", e)

        # 推送阶段状态：浏览器就绪
        if self.execution_id:
            _emit_step_event(self.execution_id, 'phase_change', {
                'phase': 'browser_ready',
            })

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
