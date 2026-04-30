/**
 * useExecutionObserver — 封装 WebSocket 连接管理，实时监听执行过程事件。

 * 用法:
 *   const { steps, currentFrame, stats, status, connect, disconnect } = useExecutionObserver(executionId)
 *   connect()  // 建立连接
 *   disconnect() // 断开连接
 */
import { ref, reactive, onUnmounted } from 'vue'
import { getExecutionSteps, getExecution } from '../api'

export function useExecutionObserver(executionId) {
  // ── 响应式状态 ──
  const steps = ref([])                // 步骤列表
  const currentFrame = ref(null)       // 当前截图帧 (HTTP URL)
  const stats = reactive({
    inputTokens: 0,
    outputTokens: 0,
    totalSteps: 0,
    duration: 0,
    startTime: null,
  })
  const status = ref('idle')           // idle | connecting | connected | running | completed | error
  const error = ref(null)
  const currentPhase = ref(null)       // 当前执行阶段（来自 phase_change 事件）

  // ── 帧轮询（HTTP fallback） ──
  let lastFrameTime = 0               // 上次收到 browser_frame 事件的 Date.now()（ms）
  let framePollTimer = null
  const FRAME_POLL_INTERVAL = 2000    // 轮询间隔 (ms)
  const FRAME_POLL_THRESHOLD = 2000   // 多久没收到 browser_frame 后启用轮询 (ms)

  function _getFrameUrl(ts) {
    const id = executionId.value !== undefined ? executionId.value : executionId
    return `/api/executions/${id}/latest_frame/?t=${ts || Date.now()}`
  }

  function _startFramePolling() {
    if (framePollTimer) return
    framePollTimer = setInterval(() => {
      // 如果执行已结束，停止轮询
      if (status.value !== 'running') {
        _stopFramePolling()
        return
      }
      // 如果最近收到过 WS 通知，不需要轮询
      if (Date.now() - lastFrameTime < FRAME_POLL_THRESHOLD) return
      // 设置新 URL 触发浏览器重新加载图片（cache-busting）
      currentFrame.value = _getFrameUrl(Date.now())
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
  let _lastDisconnectTime = 0      // 上次 WebSocket 断开的时间戳

  function _startStalePoll() {
    if (stalePollTimer) return
    stalePollTimer = setInterval(async () => {
      // WebSocket 已重连成功，停止轮询
      if (ws && ws.readyState === WebSocket.OPEN) {
        _stopStalePoll()
        return
      }
      try {
        const id = executionId.value !== undefined ? executionId.value : executionId
        const { data } = await getExecutionSteps(id)

        // 合并新步骤
        if (data.step_logs && data.step_logs.length > 0) {
          for (const step of data.step_logs) {
            const exists = steps.value.some(
              s => s.step_num === step.step_num && s.state === 'completed'
            )
            if (!exists) {
              steps.value.push({ ...step, state: 'completed', duration_ms: step.duration_ms || 0 })
            }
          }
          stats.totalSteps = data.step_logs.length
        }

        // 同步 token 统计
        if (data.agent_response?.input_tokens) {
          stats.inputTokens = data.agent_response.input_tokens
          stats.outputTokens = data.agent_response.output_tokens
        }
        if (data.duration) {
          stats.duration = data.duration
        }

        // 检测执行是否已结束
        if (data.status && data.status !== 'running') {
          _stopStalePoll()
          status.value = 'completed'
          _stopFramePolling()
          // 通过 REST 同步最终 executionInfo
          _syncExecutionInfo()
        }
      } catch (e) {
        console.warn('[Observer] Stale poll failed:', e)
      }
    }, STALE_POLL_INTERVAL)
  }

  function _stopStalePoll() {
    if (stalePollTimer) {
      clearInterval(stalePollTimer)
      stalePollTimer = null
    }
  }

  /**
   * 通过 REST 同步最新的 executionInfo（duration、status 等）。
   * 返回数据供调用方使用。
   */
  async function _syncExecutionInfo() {
    try {
      const id = executionId.value !== undefined ? executionId.value : executionId
      const { data } = await getExecution(id)
      return data
    } catch (e) {
      console.warn('[Observer] Failed to sync execution info:', e)
      return null
    }
  }

  function _getWsUrl() {
    // executionId 可能是 Vue ref/computed 或普通值
    const id = executionId.value !== undefined ? executionId.value : executionId
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${protocol}//${window.location.host}/ws/execution/${id}/`
  }

  function _scheduleReconnect() {
    if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
      status.value = 'error'
      error.value = '连接已断开，超过最大重连次数'
      return
    }

    const delay = RECONNECT_BASE_DELAY * Math.pow(2, reconnectAttempts)
    reconnectAttempts++
    status.value = 'connecting'
    reconnectTimer = setTimeout(() => {
      _connectWs()
    }, delay)
  }

  function _connectWs() {
    const url = _getWsUrl()
    status.value = 'connecting'

    try {
      ws = new WebSocket(url)
    } catch (e) {
      status.value = 'error'
      error.value = `WebSocket 创建失败: ${e.message}`
      return
    }

    ws.onopen = () => {
      reconnectAttempts = 0
      error.value = null
      _startPing()
      _stopStalePoll()
      // 注意：不在这里设置 status = 'connected'，
      // 等 connection_established 事件到来后根据 execution_status 决定
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        _handleEvent(data)
      } catch (e) {
        console.warn('[Observer] Failed to parse event:', e)
      }
    }

    ws.onclose = (event) => {
      _stopPing()
      // 正常关闭（执行结束）不重连
      if (status.value === 'completed') return
      if (event.code === 1000) return

      ws = null
      _lastDisconnectTime = Date.now()

      // 启动 stale 检测：延迟 STALE_THRESHOLD 后检查是否仍在断线状态
      // 如果仍在断线，开始 REST 轮询兜底
      setTimeout(() => {
        if (!ws || ws.readyState !== WebSocket.OPEN) {
          _startStalePoll()
        }
      }, STALE_THRESHOLD)

      _scheduleReconnect()
    }

    ws.onerror = (event) => {
      console.error('[Observer] WebSocket error:', event)
      // onclose 会紧接着被触发，由 onclose 处理重连
    }
  }

  function _handleEvent(data) {
    switch (data.type) {
      case 'connection_established': {
        // 检查后端返回的执行状态：如果已结束，直接进入 completed 状态
        const execStatus = data.execution_status
        if (execStatus && execStatus !== 'running') {
          status.value = 'completed'
          // 执行已结束，主动拉取最终数据并关闭连接
          _fetchFinalDataAndClose().then(() => {
            if (ws && ws.readyState === WebSocket.OPEN) {
              ws.close(1000, 'Execution already completed')
            }
          })
        } else {
          status.value = 'connected'
          // 执行可能已在运行中，启动帧轮询兜底
          _startFramePolling()
        }
        break
      }

      case 'step_start':
        status.value = 'running'
        _startFramePolling()
        steps.value.push({
          step_num: data.step_num,
          tool_name: data.action || '',
          action: data.action || '',
          target: data.target || '',
          result: '',
          screenshot_path: '',
          duration_ms: null,
          state: 'running',
          timestamp: data.timestamp,
        })
        break

      case 'step_complete':
        status.value = 'running'
        currentPhase.value = null  // 步骤完成，清除阶段描述
        // 查找对应的 step_start 并更新，或直接添加
        const existingIdx = steps.value.findIndex(
          s => s.step_num === data.step_num && s.state === 'running'
        )
        const stepData = {
          step_num: data.step_num,
          tool_name: data.action || '',
          action: data.action || '',
          target: data.target || '',
          result: data.result || '',
          screenshot_path: data.screenshot_path || '',
          duration_ms: data.duration_ms || 0,
          state: 'completed',
          timestamp: data.timestamp,
        }
        if (existingIdx >= 0) {
          steps.value[existingIdx] = stepData
        } else {
          steps.value.push(stepData)
        }
        stats.totalSteps = steps.value.length
        break

      case 'agent_thinking':
        // Agent 思维过程插入时间线
        steps.value.push({
          step_num: null,
          action: '__thinking__',
          target: '',
          result: data.text || '',
          screenshot_path: '',
          duration_ms: 0,
          state: 'thinking',
          timestamp: data.timestamp,
        })
        break

      case 'phase_change':
        // 执行阶段变更（不修改 steps，只更新当前阶段描述）
        currentPhase.value = data.phase || null
        break

      case 'browser_frame':
        // 轻量通知（仅时间戳），通过 HTTP 拉取实际图片
        lastFrameTime = Date.now()
        currentFrame.value = _getFrameUrl(data.ts || Date.now())
        break

      case 'frame_heartbeat':
        // Watchdog 在浏览器工具执行期间发送的心跳通知
        // 此时主线程可能已捕获新帧，通过 HTTP 拉取最新截图
        lastFrameTime = Date.now()
        if (status.value === 'running') {
          currentFrame.value = _getFrameUrl(Date.now())
        }
        break

      case 'execution_end':
        status.value = 'completed'
        _stopFramePolling()
        _stopPing()
        stats.totalSteps = data.total_steps || steps.value.length
        stats.inputTokens = data.input_tokens || 0
        stats.outputTokens = data.output_tokens || 0
        // 关闭 WebSocket
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.close(1000, 'Execution completed')
        }
        break

      case 'heartbeat':
        // 服务端心跳，连接仍然活跃，无需处理
        break

      case 'pong':
        // 服务端回复 ping，连接仍然活跃，无需处理
        break

      default:
        console.debug('[Observer] Unknown event type:', data.type)
    }
  }

  /**
   * 执行已结束时，通过 REST 拉取最终数据并关闭 WebSocket。
   */
  async function _fetchFinalDataAndClose() {
    const id = executionId.value !== undefined ? executionId.value : executionId
    _stopFramePolling()
    _stopStalePoll()
    try {
      const [stepsRes, infoRes] = await Promise.all([
        getExecutionSteps(id),
        getExecution(id),
      ])
      const data = stepsRes.data
      if (data.step_logs && data.step_logs.length > 0) {
        // 合并 REST 返回的步骤（避免与 WebSocket 实时步骤重复）
        for (const step of data.step_logs) {
          const exists = steps.value.some(s => s.step_num === step.step_num && s.state === 'completed')
          if (!exists) {
            steps.value.push({ ...step, state: 'completed', duration_ms: step.duration_ms || 0 })
          }
        }
      }
      stats.totalSteps = data.step_logs?.length || stats.totalSteps
      if (data.agent_response?.input_tokens) {
        stats.inputTokens = data.agent_response.input_tokens
        stats.outputTokens = data.agent_response.output_tokens
      }
      if (data.duration) {
        stats.duration = data.duration
      }
      // 返回最新的 executionInfo 供调用方同步
      return infoRes.data || null
    } catch (e) {
      console.warn('[Observer] Failed to fetch final execution data:', e)
      return null
    }
  }

  // ── 公开方法 ──

  function connect() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return
    reconnectAttempts = 0
    _connectWs()
  }

  function disconnect() {
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
    status.value = 'idle'
  }

  // 组件卸载时自动断开
  onUnmounted(() => {
    disconnect()
  })

  return {
    steps,
    currentFrame,
    stats,
    status,
    error,
    currentPhase,
    connect,
    disconnect,
  }
}
