"""
事件推送辅助模块 — 通过 Django Channels group_send 推送实时步骤事件。

所有推送操作均包裹在 try/except 中，推送失败不影响 Agent 执行主流程。
"""
import asyncio
import json
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


def _emit_step_event(execution_id, event_type, data):
    """
    向 execution_{id} channel group 推送事件。

    Args:
        execution_id: 执行记录 ID
        event_type:   事件类型 (step_start | step_complete | execution_end |
                      agent_thinking | browser_frame)
        data:         事件数据 dict（会被序列化为 JSON 发送给客户端）
    """
    if not execution_id:
        return

    try:
        from channels.layers import get_channel_layer

        channel_layer = get_channel_layer()
        if channel_layer is None:
            logger.debug("[EventEmitter] channel_layer not available, skipping event")
            return

        group_name = f'execution_{execution_id}'

        # 统一附加事件类型和时间戳
        payload = {
            'type': event_type,
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
            **data,
        }

        # 记录 browser_frame 事件的详细信息用于诊断
        if event_type == 'browser_frame':
            payload_size = len(json.dumps(payload))
            send_path = 'run_coroutine_threadsafe' if (_asgi_event_loop and _asgi_event_loop.is_running()) else 'async_to_sync'
            logger.info("[EventEmitter] browser_frame for execution %s: "
                        "payload_size=%d bytes, send_path=%s",
                        execution_id, payload_size, send_path)

        async def _send():
            await channel_layer.group_send(
                group_name,
                {
                    'type': 'step_event',
                    'data': payload,
                },
            )

        # 如果有 ASGI 事件循环且正在运行，从工作线程调度到该循环
        if _asgi_event_loop and _asgi_event_loop.is_running():
            asyncio.run_coroutine_threadsafe(_send(), _asgi_event_loop)
        else:
            # 同步上下文（ASGI 线程本身），直接用 async_to_sync
            from asgiref.sync import async_to_sync
            async_to_sync(channel_layer.group_send)(
                group_name,
                {
                    'type': 'step_event',
                    'data': payload,
                },
            )
    except Exception as e:
        # 推送失败必须以 WARNING 级别可见，不中断 Agent 执行
        logger.warning("[EventEmitter] Failed to emit %s for execution %s: %s",
                       event_type, execution_id, e)
