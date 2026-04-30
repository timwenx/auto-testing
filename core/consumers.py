"""
WebSocket Consumer — 执行过程实时事件推送。

ExecutionConsumer 为每个 execution_id 维护一个 channel group，
Agent 执行过程中的步骤事件通过 group_send 广播到所有连接的客户端。
"""
import json
import logging

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

        # 加入 channel group
        from channels.layers import get_channel_layer
        self.channel_layer = get_channel_layer()

        # 注意：channel_layer.add_to_group 是异步的，但 sync consumer 需要 async_to_sync
        from asgiref.sync import async_to_sync
        async_to_sync(self.channel_layer.group_add)(
            self.group_name,
            self.channel_name,
        )

        self.accept()
        logger.info("[WS] Client connected to execution %s", self.execution_id)

        # 发送连接确认
        self.send(text_data=json.dumps({
            'type': 'connection_established',
            'execution_id': self.execution_id,
        }))

    def disconnect(self, close_code):
        from asgiref.sync import async_to_sync
        async_to_sync(self.channel_layer.group_discard)(
            self.group_name,
            self.channel_name,
        )
        logger.info("[WS] Client disconnected from execution %s (code=%s)",
                     self.execution_id, close_code)

    def receive(self, text_data=None, bytes_data=None):
        """客户端发来的消息（当前未使用，预留扩展）"""
        pass

    # ── Channel layer 事件处理器 ──

    def step_event(self, event):
        """从 channel layer group_send 接收的步骤事件，转发给 WebSocket 客户端"""
        self.send(text_data=json.dumps(event['data']))
