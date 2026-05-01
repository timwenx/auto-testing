"""
script_executor.py — 回放脚本执行引擎。

从结构化 JSON 脚本逐步执行 Playwright 浏览器操作，
通过 WebSocket 实时推送步骤事件，复用现有观察面板。
"""
import os
import sys
import time
import logging
import threading

logger = logging.getLogger(__name__)


def _compare(actual, expected, operator):
    """数值比较"""
    ops = {
        'eq': lambda a, e: a == e, 'gt': lambda a, e: a > e,
        'gte': lambda a, e: a >= e, 'lt': lambda a, e: a < e,
        'lte': lambda a, e: a <= e, 'neq': lambda a, e: a != e,
    }
    fn = ops.get(operator)
    return fn(actual, expected) if fn else False


def _compare_text(actual, expected, operator):
    """文本比较"""
    ops = {
        'equals': lambda a, e: a == e, 'contains': lambda a, e: e in a,
        'not_equals': lambda a, e: a != e, 'not_contains': lambda a, e: e not in a,
    }
    fn = ops.get(operator)
    return fn(actual, expected) if fn else False


class ReplayExecutor:
    """脚本回放执行器，复用 AgentRunner 的 Playwright 生命周期模式"""

    def __init__(self, execution_record, source_record):
        self._record = execution_record
        self._source = source_record
        self._playwright = None
        self._browser = None
        self._page = None
        self._execution_id = execution_record.pk

    def run(self, script, parameter_overrides=None):
        """
        执行回放脚本。

        Args:
            script: 结构化脚本 JSON（含 parameters 和 steps）
            parameter_overrides: 用户覆盖的参数值
        """
        from .script_converter import resolve_parameters
        from .event_emitter import _emit_step_event
        from .agent_service import format_step_action, _extract_target

        resolved_steps = resolve_parameters(script, parameter_overrides)
        total = len(resolved_steps)

        if total == 0:
            self._finish('passed', '没有可执行的步骤', 0)
            return

        start_time = time.time()
        step_logs = []

        try:
            self._ensure_browser()
            _emit_step_event(self._execution_id, 'phase_change', {
                'phase': 'browser_ready',
            })

            for i, step in enumerate(resolved_steps):
                step_num = i + 1
                tool_name = step['tool_name']
                inputs = step.get('inputs', {})

                # 推送 step_start
                _emit_step_event(self._execution_id, 'step_start', {
                    'step_num': step_num,
                    'action': tool_name,
                    'target': _extract_target(tool_name, inputs),
                })
                _emit_step_event(self._execution_id, 'phase_change', {
                    'phase': 'executing_step',
                    'step_num': step_num,
                    'tool_name': tool_name,
                })

                step_start = time.time()
                error_msg = ''
                try:
                    self._execute_step(tool_name, inputs)
                except Exception as e:
                    error_msg = str(e)
                    logger.warning('[Replay] Step %d failed: %s', step_num, e)

                duration_ms = int((time.time() - step_start) * 1000)

                # 自动截图
                screenshot_path = self._auto_screenshot(step_num)

                step_log = {
                    'step_num': step_num,
                    'action': format_step_action(tool_name, inputs),
                    'tool_name': tool_name,
                    'target': _extract_target(tool_name, inputs),
                    'result': error_msg or 'OK',
                    'screenshot_path': screenshot_path,
                    'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                    'duration_ms': duration_ms,
                }
                step_logs.append(step_log)

                # 推送 step_complete
                _emit_step_event(self._execution_id, 'step_complete', {
                    'step_num': step_num,
                    'action': tool_name,
                    'target': step_log['target'],
                    'result': error_msg or 'OK',
                    'screenshot_path': screenshot_path,
                    'duration_ms': duration_ms,
                })

                # 持久化到 DB
                self._persist_step(step_log)

                # 失败立即停止
                if error_msg:
                    self._finish('failed', f'步骤 {step_num} 失败: {error_msg}',
                                 time.time() - start_time, step_logs)
                    return

            self._finish('passed', f'全部 {total} 步执行成功',
                         time.time() - start_time, step_logs)

        except Exception as e:
            logger.exception('[Replay] Execution failed')
            self._finish('error', str(e), time.time() - start_time, step_logs)

        finally:
            self._cleanup_browser()

    def _ensure_browser(self):
        """初始化 Playwright 浏览器"""
        if self._page is not None:
            return

        from .models import SystemSetting

        import asyncio
        from playwright.sync_api import sync_playwright

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
            # 自动接受所有弹窗（confirm/alert/prompt），和 agent 模式行为一致
            self._page.on('dialog', lambda dialog: dialog.accept())
        finally:
            if restore_policy is not None:
                asyncio.set_event_loop_policy(restore_policy)

    def _cleanup_browser(self):
        """清理浏览器资源"""
        try:
            if self._page and not self._page.is_closed():
                self._page.close()
        except Exception as e:
            logger.warning('[Replay] Page close error: %s', e)
        try:
            if self._browser:
                self._browser.close()
        except Exception as e:
            logger.warning('[Replay] Browser close error: %s', e)
        try:
            if self._playwright:
                self._playwright.stop()
        except Exception as e:
            logger.warning('[Replay] Playwright stop error: %s', e)
        finally:
            self._playwright = None
            self._browser = None
            self._page = None

    def _execute_step(self, tool_name, inputs):
        """根据 tool_name 分发到对应的 Playwright 操作"""
        page = self._page
        if not page or page.is_closed():
            raise RuntimeError('浏览器页面不可用')

        if tool_name == 'browser_navigate':
            url = inputs.get('url', '')
            wait_until = inputs.get('wait_until', 'domcontentloaded')
            page.goto(url, wait_until=wait_until, timeout=30000)

        elif tool_name == 'browser_click':
            selector = inputs.get('selector', '')
            page.click(selector, timeout=10000)
            if inputs.get('wait_for_navigation'):
                page.wait_for_load_state('domcontentloaded', timeout=15000)
            elif inputs.get('wait_for'):
                page.wait_for_selector(inputs['wait_for'], timeout=10000)

        elif tool_name == 'browser_fill':
            selector = inputs.get('selector', '')
            value = inputs.get('value', '')
            page.fill(selector, value, timeout=10000)

        elif tool_name == 'browser_fill_form':
            fields = inputs.get('fields', [])
            for f in fields:
                page.fill(f['selector'], f['value'], timeout=10000)
            submit = inputs.get('submit_selector', '')
            if submit:
                page.click(submit, timeout=10000)
                page.wait_for_load_state('domcontentloaded', timeout=15000)

        elif tool_name == 'browser_select':
            selector = inputs.get('selector', '')
            value = inputs.get('value', '')
            label = inputs.get('label', '')
            if label:
                page.select_option(selector, label=label, timeout=10000)
            elif value:
                page.select_option(selector, value=value, timeout=10000)

        elif tool_name == 'browser_press_key':
            key = inputs.get('key', '')
            page.keyboard.press(key)

        elif tool_name == 'browser_batch_action':
            actions = inputs.get('actions', [])
            delay = inputs.get('delay_between', 20)
            for act in actions:
                act_type = act.get('type', '')
                sel = act.get('selector', '')
                if not sel:
                    continue  # 跳过无 selector 的占位 action（旧数据重建）
                if act_type == 'click':
                    page.click(sel, timeout=10000)
                elif act_type == 'fill':
                    page.fill(sel, act.get('value', ''), timeout=10000)
                elif act_type == 'select':
                    if act.get('label'):
                        page.select_option(sel, label=act['label'], timeout=10000)
                    elif act.get('value'):
                        page.select_option(sel, value=act['value'], timeout=10000)
                elif act_type == 'press_key':
                    page.keyboard.press(act.get('key', ''))
                elif act_type == 'wait':
                    page.wait_for_timeout(act.get('timeout', 5000))
                if delay > 0:
                    page.wait_for_timeout(delay)

        elif tool_name == 'browser_assert':
            assert_type = inputs.get('assert_type', '')
            selector = inputs.get('selector', '')
            operator = inputs.get('operator', '')
            expected = inputs.get('expected', '')
            message = inputs.get('message', '')

            if assert_type == 'element_count':
                actual = page.locator(selector).count()
                expected_int = int(expected)
                if not _compare(actual, expected_int, operator):
                    desc = message or f'元素数量断言失败: count("{selector}") {operator} {expected_int}, 实际={actual}'
                    raise AssertionError(desc)
            elif assert_type == 'text_content':
                text = page.locator(selector).first.text_content(timeout=10000)
                actual = (text or '').strip()
                expected_str = str(expected)
                if not _compare_text(actual, expected_str, operator):
                    desc = message or f'文本断言失败: text("{selector}") {operator} "{expected_str}", 实际="{actual}"'
                    raise AssertionError(desc)

    def _auto_screenshot(self, step_num):
        """自动截图"""
        if not self._page or self._page.is_closed():
            return ''
        try:
            from django.conf import settings as django_settings
            screenshot_dir = os.path.join(
                str(django_settings.MEDIA_ROOT),
                str(self._execution_id),
            )
            os.makedirs(screenshot_dir, exist_ok=True)
            save_path = os.path.join(screenshot_dir, f'step_{step_num}.png')
            self._page.screenshot(path=save_path, full_page=True)
            return save_path
        except Exception as e:
            logger.warning('[Replay] Screenshot failed: %s', e)
            return ''

    def _persist_step(self, step_log):
        """实时持久化步骤到 DB（在独立线程中写入，绕过 async-safety 检查）"""
        try:
            from .models import ExecutionRecord

            def _save():
                try:
                    record = ExecutionRecord.objects.get(pk=self._execution_id)
                    current_logs = list(record.step_logs or [])
                    current_logs.append(step_log)
                    record.step_logs = current_logs
                    record.tool_calls_count = len(current_logs)
                    record.save(update_fields=['step_logs', 'tool_calls_count'])
                except Exception as exc:
                    logger.warning('[Replay] Step persist write failed: %s', exc)

            # Playwright 运行在 async 事件循环中，Django 5 的 async-safety 检查
            # 会拒绝同步 ORM 操作。通过独立线程写入绕过此限制。
            t = threading.Thread(target=_save, daemon=True)
            t.start()
            t.join(timeout=5)
        except Exception as e:
            logger.warning('[Replay] Persist error: %s', e)

    def _finish(self, status, message, duration, step_logs=None):
        """完成执行，更新记录并推送事件"""
        from .event_emitter import _emit_step_event
        from .models import ExecutionRecord

        def _save_finish():
            try:
                record = ExecutionRecord.objects.get(pk=self._execution_id)
                record.status = status
                record.duration = round(duration, 2)
                record.error_message = '' if status == 'passed' else message
                record.log = message
                record.save()
            except Exception as exc:
                logger.warning('[Replay] Finish save failed: %s', exc)

        try:
            t = threading.Thread(target=_save_finish, daemon=True)
            t.start()
            t.join(timeout=5)

            _emit_step_event(self._execution_id, 'execution_end', {
                'status': status,
                'total_steps': step_logs and len(step_logs) or 0,
            })
        except Exception as e:
            logger.warning('[Replay] Finish error: %s', e)
