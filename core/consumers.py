"""
WebSocket Consumer — 执行过程实时事件推送。

ExecutionConsumer 为每个 execution_id 维护一个 channel group，
Agent 执行过程中的步骤事件通过 group_send 广播到所有连接的客户端。
"""
import json
import logging

from asgiref.sync import async_to_sync
from channels.generic.websocket import WebsocketConsumer

logger = logging.getLogger(__name__)


class ExecutionConsumer(WebsocketConsumer):
    """
    WebSocket consumer for real-time execution observation.

    URL: /ws/execution/<execution_id>/

    接收事件类型:
      - step_start:     工具调用开始
      - step_complete:  工具调用完成
      - execution_end:  执行结束
      - agent_thinking: Claude 文本回复
      - browser_frame:  浏览器截图帧（Phase 2）
    """

    def connect(self):
        self.execution_id = self.scope['url_route']['kwargs']['execution_id']
        self.group_name = f'execution_{self.execution_id}'

        # 保存 ASGI 事件循环引用，供工作线程通过 run_coroutine_threadsafe 推送事件
        import asyncio
        from .event_emitter import set_asgi_event_loop
        try:
            set_asgi_event_loop(asyncio.get_running_loop())
        except RuntimeError:
            pass

        self.accept()
        logger.info("[WS] Client connected to execution %s", self.execution_id)

        # 加入 channel group（self.channel_layer 由 ASGI handler 注入）
        async_to_sync(self.channel_layer.group_add)(
            self.group_name,
            self.channel_name,
        )

        # 查询当前执行状态，一并发送给客户端
        execution_status = 'unknown'
        try:
            from .models import ExecutionRecord
            record = ExecutionRecord.objects.get(pk=self.execution_id)
            execution_status = record.status
        except Exception:
            pass

        # 发送连接确认（含当前执行状态）
        self.send(text_data=json.dumps({
            'type': 'connection_established',
            'execution_id': self.execution_id,
            'execution_status': execution_status,
        }))

    def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            async_to_sync(self.channel_layer.group_discard)(
                self.group_name,
                self.channel_name,
            )

    def receive(self, text_data=None, bytes_data=None):
        """客户端发来的消息（当前未使用，预留扩展）"""
        pass

    # ── Channel layer 事件处理器 ──

    def step_event(self, event):
        """从 channel layer group_send 接收的步骤事件，转发给 WebSocket 客户端"""
        data = event.get('data', {})
        event_type = data.get('type', 'unknown')
        data_size = len(json.dumps(data))
        logger.debug("[WS] step_event received: type=%s, size=%d bytes, execution=%s",
                     event_type, data_size, self.execution_id)
        self.send(text_data=json.dumps(data))
