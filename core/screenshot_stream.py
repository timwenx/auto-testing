"""
截图流服务 — 同线程轮询模型，在 Agent 的 Playwright 线程中定期截图并推送。

用法:
    stream = ScreenshotStream()
    stream.start(page, execution_id)
    ...  # 在 Agent 循环中定期调用 stream.maybe_capture()
    stream.stop()

注意: 不能从独立线程调用 page.screenshot()，因为 Playwright sync API
      的 greenlet 绑定在初始化线程上，跨线程调用会导致 greenlet.error。

截图存储策略:
    maybe_capture() 将 JPEG bytes 暂存在模块级字典 _latest_frames 中，
    同时通过 WebSocket 只发送轻量时间戳通知（<100 bytes）。
    前端收到通知后通过 HTTP GET /api/executions/<id>/latest_frame/ 拉取图片。
"""
import logging
import threading
import time

logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_INTERVAL = 0.5  # 500ms
DEFAULT_QUALITY = 40    # JPEG quality (lower = smaller file)

# 模块级实时帧缓存 — {execution_id: (timestamp, jpeg_bytes)}
# 只保留每执行的最新一帧，stop() 时清除对应条目。
_latest_frames = {}
_frames_lock = threading.Lock()


def get_latest_frame(execution_id):
    """
    获取指定执行的最新截图帧。

    Args:
        execution_id: 执行记录 ID

    Returns:
        (timestamp, jpeg_bytes) 元组，若无帧则返回 (None, None)
    """
    with _frames_lock:
        entry = _latest_frames.get(execution_id)
    if entry:
        return entry
    return None, None


class ScreenshotStream:
    """
    同线程轮询截图 — 在 Agent 主循环（Playwright 所在线程）中调用
    maybe_capture()，每隔一定时间对 page 截图并通过 WebSocket 推送轻量通知。
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
        """停止截图流并清理帧缓存"""
        execution_id = self._execution_id
        self._page = None
        self._execution_id = None
        # 清理帧缓存
        if execution_id is not None:
            with _frames_lock:
                _latest_frames.pop(execution_id, None)
        logger.info("[ScreenshotStream] Stopped")

    def is_running(self):
        """检查截图流是否正在运行"""
        return self._page is not None

    def maybe_capture(self):
        """
        在 Playwright 所在线程中调用。如果距上次截图已超过 interval，
        则执行截图，暂存到 _latest_frames，并通过 WS 发送轻量通知。
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

            # 暂存到内存字典（覆盖前一帧）
            with _frames_lock:
                _latest_frames[self._execution_id] = (now, screenshot_bytes)

            logger.info("[ScreenshotStream] Captured frame for execution %s: "
                        "jpeg_bytes=%d",
                        self._execution_id, len(screenshot_bytes))

            # 通过 WebSocket 只发送轻量通知（时间戳，不含图片数据）
            from .event_emitter import _emit_step_event
            _emit_step_event(self._execution_id, 'browser_frame', {
                'ts': round(now * 1000),  # 毫秒时间戳，前端用作 cache-buster
            })
        except Exception as e:
            # 截图错误不应中断 Agent 执行，但必须以 WARNING 级别可见
            logger.warning("[ScreenshotStream] Screenshot failed for execution %s: %s",
                           self._execution_id, e)
