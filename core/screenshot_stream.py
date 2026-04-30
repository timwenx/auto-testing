"""
截图流服务 — 独立守护线程，定期对 Playwright page 截图并通过 WebSocket 推送。

用法:
    stream = ScreenshotStream()
    stream.start(page, execution_id)
    ...
    stream.stop()
"""
import base64
import logging
import threading
import time

logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_INTERVAL = 0.5  # 500ms
DEFAULT_QUALITY = 60    # JPEG quality


class ScreenshotStream:
    """
    在守护线程中以固定间隔对 Playwright page 执行截图，
    编码为 base64 data URL 后通过 event_emitter 推送到 WebSocket。
    """

    def __init__(self, interval=None, quality=None):
        self.interval = interval or DEFAULT_INTERVAL
        self.quality = quality or DEFAULT_QUALITY
        self._thread = None
        self._stop_event = threading.Event()
        self._page = None
        self._execution_id = None

    def start(self, page, execution_id):
        """
        启动截图流。

        Args:
            page: Playwright Page 实例
            execution_id: 执行记录 ID
        """
        if self._thread and self._thread.is_alive():
            logger.warning("[ScreenshotStream] Already running, stop first")
            return

        self._page = page
        self._execution_id = execution_id
        self._stop_event.clear()

        self._thread = threading.Thread(
            target=self._run,
            name=f'screenshot-stream-{execution_id}',
            daemon=True,
        )
        self._thread.start()
        logger.info("[ScreenshotStream] Started for execution %s (interval=%.1fs)",
                     execution_id, self.interval)

    def stop(self):
        """停止截图流"""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self.interval * 3)
        self._page = None
        self._execution_id = None
        logger.info("[ScreenshotStream] Stopped")

    def is_running(self):
        """检查截图流是否正在运行"""
        return self._thread is not None and self._thread.is_alive()

    def _run(self):
        """守护线程主循环"""
        from .event_emitter import _emit_step_event

        while not self._stop_event.is_set():
            try:
                if self._page and not self._page.is_closed():
                    screenshot_bytes = self._page.screenshot(
                        type='jpeg',
                        quality=self.quality,
                    )
                    b64_str = base64.b64encode(screenshot_bytes).decode('ascii')
                    data_url = f'data:image/jpeg;base64,{b64_str}'

                    _emit_step_event(self._execution_id, 'browser_frame', {
                        'image': data_url,
                    })
            except Exception as e:
                # 静默失败 — 截图错误不应中断 Agent 执行
                logger.debug("[ScreenshotStream] Screenshot failed: %s", e)

            self._stop_event.wait(self.interval)
