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

Watchdog 模式:
    _run_with_frame_watchdog() 在浏览器工具执行期间启动一个后台线程，
    定期调用 maybe_capture() 保持截图流不断流。后台线程使用 daemon 模式，
    工具执行结束后自动退出。
"""
import logging
import threading
import time

logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_INTERVAL = 0.5  # 500ms
DEFAULT_QUALITY = 40    # JPEG quality (lower = smaller file)
WATCHDOG_INTERVAL = 2.0  # watchdog 截图间隔（秒）

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


# ══════════════════════════════════════════════════════════════════
# Watchdog — 工具执行期间后台截图
# ══════════════════════════════════════════════════════════════════

class _FrameWatchdog:
    """
    后台通知 watchdog — 在浏览器工具执行期间发送心跳通知，
    告知前端定期轮询截图。不直接调用 Playwright API（避免线程问题）。

    注意：Playwright sync API 的 greenlet 绑定是线程本地的，
    从后台线程调用 page.screenshot() 会导致 greenlet.error。
    因此采用"通知 + 前端轮询"模式替代后台截图。
    """

    def __init__(self, execution_id, interval=None):
        self._execution_id = execution_id
        self._interval = interval or WATCHDOG_INTERVAL
        self._stop_event = threading.Event()
        self._thread = None

    def start(self):
        """启动后台心跳线程"""
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name='frame-watchdog',
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        """停止后台心跳线程"""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None

    def _run(self):
        """定期发送心跳通知，促使前端轮询截图"""
        while not self._stop_event.is_set():
            try:
                # 只发送轻量通知，不调用 Playwright API
                from .event_emitter import _emit_step_event
                _emit_step_event(self._execution_id, 'frame_heartbeat', {
                    'ts': round(time.time() * 1000),
                })
                logger.debug("[FrameWatchdog] 发送心跳通知 execution_id=%s", self._execution_id)
            except Exception as e:
                logger.warning("[FrameWatchdog] 心跳异常: %s", e)
            # 等待间隔或 stop 信号
            self._stop_event.wait(timeout=self._interval)



def run_with_frame_watchdog(execution_id, fn):
    """
    在执行 fn() 期间启动后台心跳 watchdog，确保长耗时的浏览器操作
    期间前端能定期轮询截图。

    用法:
        result = run_with_frame_watchdog(execution_id, lambda: executor(input, context))

    Args:
        execution_id: 执行记录 ID（用于发送通知）
        fn: 要执行的函数（无参数，返回结果）

    Returns:
        fn() 的返回值

    注意：
        后台线程只发送轻量通知，不调用 Playwright API。
        这避免了 greenlet 线程绑定错误。前端接收通知后自行轮询截图。
    """
    if not execution_id:
        return fn()

    watchdog = _FrameWatchdog(execution_id)
    watchdog.start()
    try:
        return fn()
    finally:
        watchdog.stop()
