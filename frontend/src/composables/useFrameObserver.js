/**
 * useFrameObserver — 封装截图帧 WebSocket 连接管理，实时接收浏览器截图通知。
 *
 * 与 useExecutionObserver 独立：步骤事件走 step 通道，截图帧走 frame 通道。
 *
 * 用法:
 *   const { currentFrame, frameWsStatus, connectFrame, disconnectFrame } = useFrameObserver(executionId)
 *   connectFrame()   // 建立 frame WS 连接
 *   disconnectFrame() // 断开连接
 */
import { ref, onUnmounted } from 'vue'

export function useFrameObserver(executionId) {
  // ── 响应式状态 ──
  const currentFrame = ref(null)       // 当前截图帧 (HTTP URL)
  const frameWsStatus = ref('idle')    // idle | connecting | connected | error

  // ── 帧轮询（HTTP fallback） ──
  let lastFrameTime = 0               // 上次收到 browser_frame 事件的 Date.now()（ms）
  let framePollTimer = null
  const FRAME_POLL_INTERVAL = 2000    // 轮询间隔 (ms)
  const FRAME_POLL_THRESHOLD = 2000   // 多久没收到 browser_frame 后启用轮询 (ms)
  const FRAME_DEBOUNCE_MS = 500       // 帧更新 debounce 间隔（ms）
  let lastFrameUpdateTime = 0         // 上次帧更新的 Date.now()（ms）

  function _getFrameUrl(ts) {
    const id = executionId.value !== undefined ? executionId.value : executionId
    return `/api/executions/${id}/latest_frame/?t=${ts || Date.now()}`
  }

  function _startFramePolling() {
    if (framePollTimer) return
    framePollTimer = setInterval(async () => {
      // 如果最近收到过 WS 通知，不需要轮询
      if (Date.now() - lastFrameTime < FRAME_POLL_THRESHOLD) return
      try {
        // 先用 HEAD 请求验证帧可用（轻量，不传输图片数据）
        const id = executionId.value !== undefined ? executionId.value : executionId
        const response = await fetch(`/api/executions/${id}/latest_frame/?t=${Date.now()}`, { method: 'HEAD' })
        if (response.ok) {
          currentFrame.value = _getFrameUrl(Date.now())
        } else {
          console.debug('[FrameObserver] Frame poll skipped, status:', response.status)
        }
      } catch (e) {
        console.debug('[FrameObserver] Frame poll failed:', e.message)
      }
    }, FRAME_POLL_INTERVAL)
  }

  function _stopFramePolling() {
    if (framePollTimer) {
      clearInterval(framePollTimer)
      framePollTimer = null
    }
  }

  // ── WebSocket 管理 ──
  let ws = null
  let reconnectAttempts = 0
  let reconnectTimer = null
  let pingTimer = null
  const MAX_RECONNECT_ATTEMPTS = 5
  const RECONNECT_BASE_DELAY = 1000
  const PING_INTERVAL = 20000    // 前端 ping 间隔 (ms)

  // ── 心跳 / Ping 管理 ──

  function _startPing() {
    _stopPing()
    pingTimer = setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ping' }))
      }
    }, PING_INTERVAL)
  }

  function _stopPing() {
    if (pingTimer) {
      clearInterval(pingTimer)
      pingTimer = null
    }
  }

  // ── Stale 检测 — WebSocket 断线后 REST 轮询兜底 ──
  let stalePollTimer = null
  const STALE_THRESHOLD = 10000   // 断线超过此时间(ms)后启用 REST 轮询
  const STALE_POLL_INTERVAL = 3000 // REST 轮询间隔 (ms)

  function _startStalePoll() {
    if (stalePollTimer) return
    stalePollTimer = setInterval(async () => {
      // WebSocket 已重连成功，停止轮询
      if (ws && ws.readyState === WebSocket.OPEN) {
        _stopStalePoll()
        return
      }
      try {
        // 通过 HTTP 拉取最新帧（使用 latest_frame 端点）
        const id = executionId.value !== undefined ? executionId.value : executionId
        const response = await fetch(`/api/executions/${id}/latest_frame/`, { method: 'HEAD' })
        if (response.ok) {
          currentFrame.value = _getFrameUrl(Date.now())
        }
      } catch (e) {
        console.warn('[FrameObserver] Stale poll failed:', e)
      }
    }, STALE_POLL_INTERVAL)
  }

  function _stopStalePoll() {
    if (stalePollTimer) {
      clearInterval(stalePollTimer)
      stalePollTimer = null
    }
  }

  function _getWsUrl() {
    const id = executionId.value !== undefined ? executionId.value : executionId
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${protocol}//${window.location.host}/ws/execution/${id}/frame/`
  }

  function _scheduleReconnect() {
    if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
      frameWsStatus.value = 'error'
      return
    }

    const delay = RECONNECT_BASE_DELAY * Math.pow(2, reconnectAttempts)
    reconnectAttempts++
    frameWsStatus.value = 'connecting'
    reconnectTimer = setTimeout(() => {
      _connectWs()
    }, delay)
  }

  function _connectWs() {
    const url = _getWsUrl()
    frameWsStatus.value = 'connecting'

    try {
      ws = new WebSocket(url)
    } catch (e) {
      frameWsStatus.value = 'error'
      return
    }

    ws.onopen = () => {
      reconnectAttempts = 0
      _startPing()
      _stopStalePoll()
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        _handleEvent(data)
      } catch (e) {
        console.warn('[FrameObserver] Failed to parse event:', e)
      }
    }

    ws.onclose = (event) => {
      _stopPing()
      // 正常关闭不重连
      if (event.code === 1000) return

      ws = null

      // 启动 stale 检测：延迟 STALE_THRESHOLD 后检查是否仍在断线状态
      setTimeout(() => {
        if (!ws || ws.readyState !== WebSocket.OPEN) {
          _startStalePoll()
        }
      }, STALE_THRESHOLD)

      _scheduleReconnect()
    }

    ws.onerror = (event) => {
      console.error('[FrameObserver] WebSocket error:', event)
      // onclose 会紧接着被触发
    }
  }

  function _handleEvent(data) {
    switch (data.type) {
      case 'connection_established':
        frameWsStatus.value = 'connected'
        // 启动帧轮询兜底
        _startFramePolling()
        break

      case 'browser_frame':
        // 轻量通知（仅时间戳），通过 HTTP 拉取实际图片（debounce 500ms）
        lastFrameTime = Date.now()
        if (Date.now() - lastFrameUpdateTime < FRAME_DEBOUNCE_MS) break
        lastFrameUpdateTime = Date.now()
        currentFrame.value = _getFrameUrl(data.ts || Date.now())
        break

      case 'frame_heartbeat':
        // Watchdog 在浏览器工具执行期间发送的心跳通知（debounce 500ms）
        lastFrameTime = Date.now()
        if (Date.now() - lastFrameUpdateTime >= FRAME_DEBOUNCE_MS) {
          lastFrameUpdateTime = Date.now()
          currentFrame.value = _getFrameUrl(Date.now())
        }
        break

      case 'heartbeat':
        // 服务端心跳，连接仍然活跃，无需处理
        break

      case 'pong':
        // 服务端回复 ping，连接仍然活跃，无需处理
        break

      default:
        console.debug('[FrameObserver] Unknown event type:', data.type)
    }
  }

  // ── 公开方法 ──

  function connectFrame() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return
    reconnectAttempts = 0
    _connectWs()
  }

  function disconnectFrame() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    _stopPing()
    _stopStalePoll()
    _stopFramePolling()
    if (ws) {
      ws.close(1000, 'Manual disconnect')
      ws = null
    }
    frameWsStatus.value = 'idle'
  }

  // 组件卸载时自动断开
  onUnmounted(() => {
    disconnectFrame()
  })

  return {
    currentFrame,
    frameWsStatus,
    connectFrame,
    disconnectFrame,
  }
}
