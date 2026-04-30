"""
截图流服务 — 同线程轮询模型，在 Agent 的 Playwright 线程中定期截图并推送。

用法:
    stream = ScreenshotStream()
    stream.start(page, execution_id)
    ...  # 在 Agent 循环中定期调用 stream.maybe_capture()
    stream.stop()

注意: 不能从独立线程调用 page.screenshot()，因为 Playwright sync API
      的 greenlet 绑定在初始化线程上，跨线程调用会导致 greenlet.error。
"""
import base64
import logging
import time

logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_INTERVAL = 0.5  # 500ms
DEFAULT_QUALITY = 60    # JPEG quality


class ScreenshotStream:
    """
    同线程轮询截图 — 在 Agent 主循环（Playwright 所在线程）中调用
    maybe_capture()，每隔一定时间对 page 截图并通过 WebSocket 推送。
    """

    def __init__(self, interval=None, quality=None):
        self.interval = interval or DEFAULT_INTERVAL
        self.quality = quality or DEFAULT_QUALITY
        self._page = None
        self._execution_id = None
        self._last_capture_time = 0

    def start(self, page, execution_id):
        """
        启动截图流。

        Args:
            page: Playwright Page 实例
            execution_id: 执行记录 ID
        """
        self._page = page
        self._execution_id = execution_id
        self._last_capture_time = time.time()
        logger.info("[ScreenshotStream] Started for execution %s (interval=%.1fs)",
                     execution_id, self.interval)

    def stop(self):
        """停止截图流"""
        self._page = None
        self._execution_id = None
        logger.info("[ScreenshotStream] Stopped")

    def is_running(self):
        """检查截图流是否正在运行"""
        return self._page is not None

    def maybe_capture(self):
        """
        在 Playwright 所在线程中调用。如果距上次截图已超过 interval，
        则执行截图并通过 event_emitter 推送。
        """
        if not self._page or self._page.is_closed():
            return

        now = time.time()
        if now - self._last_capture_time < self.interval:
            return

        self._last_capture_time = now
        try:
            screenshot_bytes = self._page.screenshot(
                type='jpeg',
                quality=self.quality,
            )
            b64_str = base64.b64encode(screenshot_bytes).decode('ascii')
            data_url = f'data:image/jpeg;base64,{b64_str}'

            from .event_emitter import _emit_step_event
            _emit_step_event(self._execution_id, 'browser_frame', {
                'image': data_url,
            })
        except Exception as e:
            # 静默失败 — 截图错误不应中断 Agent 执行
            logger.debug("[ScreenshotStream] Screenshot failed: %s", e)
