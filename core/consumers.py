"""
WebSocket Consumer — 执行过程实时事件推送。

ExecutionConsumer 为每个 execution_id 维护一个 channel group，
Agent 执行过程中的步骤事件通过 group_send 广播到所有连接的客户端。

心跳机制:
  - 服务端每 15 秒向客户端发送 heartbeat 消息，防止代理层（Vite/http-proxy）
    因连接空闲超时而断开。
  - 客户端每 20 秒发送 ping，服务端回复 pong，用于双向保活。
"""
import json
import logging
import threading
import time

from asgiref.sync import async_to_sync
from channels.generic.websocket import WebsocketConsumer

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 15  # 服务端心跳间隔（秒）


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
      - heartbeat:      服务端心跳（保活）
    """

    def connect(self):
        self.execution_id = self.scope['url_route']['kwargs']['execution_id']
        self.group_name = f'execution_{self.execution_id}'
        self._heartbeat_timer = None

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

        # 启动服务端心跳定时器
        self._start_heartbeat()

    def disconnect(self, close_code):
        self._stop_heartbeat()
        if hasattr(self, 'group_name'):
            async_to_sync(self.channel_layer.group_discard)(
                self.group_name,
                self.channel_name,
            )

    def receive(self, text_data=None, bytes_data=None):
        """处理客户端消息：ping → 回复 pong"""
        try:
            data = json.loads(text_data)
        except (json.JSONDecodeError, TypeError):
            return

        msg_type = data.get('type', '')
        if msg_type == 'ping':
            self.send(text_data=json.dumps({
                'type': 'pong',
                'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
            }))
            logger.debug("[WS] Received ping from client, sent pong (execution=%s)",
                         self.execution_id)

    # ── 心跳管理 ──

    def _start_heartbeat(self):
        """启动后台心跳定时器，每 HEARTBEAT_INTERVAL 秒发送一次"""
        def _send_heartbeat():
            try:
                self.send(text_data=json.dumps({'type': 'heartbeat'}))
                logger.debug("[WS] Heartbeat sent to execution %s", self.execution_id)
            except Exception:
                # 发送失败说明连接已断开，停止定时器
                return
            # 重新调度下一次心跳
            self._heartbeat_timer = threading.Timer(
                HEARTBEAT_INTERVAL, _send_heartbeat
            )
            self._heartbeat_timer.daemon = True
            self._heartbeat_timer.start()

        self._heartbeat_timer = threading.Timer(
            HEARTBEAT_INTERVAL, _send_heartbeat
        )
        self._heartbeat_timer.daemon = True
        self._heartbeat_timer.start()

    def _stop_heartbeat(self):
        """停止心跳定时器"""
        timer = getattr(self, '_heartbeat_timer', None)
        if timer:
            timer.cancel()
            self._heartbeat_timer = None

    # ── Channel layer 事件处理器 ──

    def step_event(self, event):
        """从 channel layer group_send 接收的步骤事件，转发给 WebSocket 客户端"""
        data = event.get('data', {})
        event_type = data.get('type', 'unknown')
        data_size = len(json.dumps(data))
        logger.debug("[WS] step_event received: type=%s, size=%d bytes, execution=%s",
                     event_type, data_size, self.execution_id)
        self.send(text_data=json.dumps(data))
