"""
事件推送辅助模块 — 通过 Django Channels group_send 推送实时步骤事件。

所有推送操作均包裹在 try/except 中，推送失败不影响 Agent 执行主流程。
"""
import json
import logging
import time

logger = logging.getLogger(__name__)


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
        from asgiref.sync import async_to_sync

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

        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                'type': 'step_event',
                'data': payload,
            },
        )
    except Exception as e:
        # 静默失败，不中断 Agent 执行
        logger.debug("[EventEmitter] Failed to emit %s for execution %s: %s",
                     event_type, execution_id, e)
