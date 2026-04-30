"""
事件推送辅助模块 — 通过 Django Channels group_send 推送实时事件。

双通道架构:
  - _emit_step_event → 推送到 execution_{id} group（步骤事件）
  - _emit_frame_event → 推送到 frame_{id} group（截图帧事件）

所有推送操作均包裹在 try/except 中，推送失败不影响 Agent 执行主流程。
通过 asyncio.run_coroutine_threadsafe 将 group_send 调度到 ASGI 事件循环。
"""
import asyncio
import logging
import time

logger = logging.getLogger(__name__)

# ASGI 事件循环引用 — 由 WebSocket consumer 在连接时设置。
# 这样 ThreadPoolExecutor 工作线程可以通过 run_coroutine_threadsafe
# 将 group_send 调度到正确的 ASGI 事件循环上。
_asgi_event_loop = None


def set_asgi_event_loop(loop):
    """由 WebSocket consumer 调用，保存 ASGI 事件循环引用。"""
    global _asgi_event_loop
    _asgi_event_loop = loop
    logger.debug("[EventEmitter] ASGI event loop captured: %s", loop)


def _is_loop_usable():
    """检查 ASGI 事件循环是否可用（非 None 且未关闭）"""
    loop = _asgi_event_loop
    if loop is None:
        return False
    try:
        if loop.is_closed() is True:
            return False
    except Exception:
        pass
    return True


def _emit_step_event(execution_id, event_type, data):
    """
    向 execution_{id} channel group 推送步骤事件。

    推送的事件类型: step_start, step_complete, agent_thinking, phase_change, execution_end

    通过 asyncio.run_coroutine_threadsafe 调度到 ASGI 事件循环。
    推送失败只 log 不影响 Agent 主流程。
    """
    if not _is_loop_usable():
        logger.debug("[EventEmitter] ASGI event loop not available, skipping step event "
                     "type=%s execution=%s", event_type, execution_id)
        return

    try:
        from channels.layers import get_channel_layer
        channel_layer = get_channel_layer()
        if channel_layer is None:
            logger.warning("[EventEmitter] channel_layer is None, cannot send step event")
            return

        group_name = f'execution_{execution_id}'

        async def _send():
            await channel_layer.group_send(group_name, {
                'type': 'step_event',
                'data': {
                    'type': event_type,
                    **data,
                    'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                },
            })

        asyncio.run_coroutine_threadsafe(_send(), _asgi_event_loop)
        logger.debug("[EventEmitter] Step event dispatched: type=%s execution=%s",
                     event_type, execution_id)
    except Exception as e:
        logger.warning("[EventEmitter] Failed to emit step event type=%s execution=%s: %s",
                       event_type, execution_id, e)


def _emit_frame_event(execution_id, event_type, data):
    """
    向 frame_{id} channel group 推送截图帧事件。

    推送的事件类型: browser_frame, frame_heartbeat

    通过 asyncio.run_coroutine_threadsafe 调度到 ASGI 事件循环。
    推送失败只 log 不影响 Agent 主流程。
    """
    if not _is_loop_usable():
        logger.debug("[EventEmitter] ASGI event loop not available, skipping frame event "
                     "type=%s execution=%s", event_type, execution_id)
        return

    try:
        from channels.layers import get_channel_layer
        channel_layer = get_channel_layer()
        if channel_layer is None:
            logger.warning("[EventEmitter] channel_layer is None, cannot send frame event")
            return

        group_name = f'frame_{execution_id}'

        async def _send():
            await channel_layer.group_send(group_name, {
                'type': 'frame_event',
                'data': {
                    'type': event_type,
                    **data,
                },
            })

        asyncio.run_coroutine_threadsafe(_send(), _asgi_event_loop)
        logger.debug("[EventEmitter] Frame event dispatched: type=%s execution=%s",
                     event_type, execution_id)
    except Exception as e:
        logger.warning("[EventEmitter] Failed to emit frame event type=%s execution=%s: %s",
                       event_type, execution_id, e)
