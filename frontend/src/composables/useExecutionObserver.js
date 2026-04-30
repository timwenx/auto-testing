/**
 * useExecutionObserver — 封装步骤事件 WebSocket 连接管理，实时监听执行过程事件。
 *
 * 仅负责步骤事件（step_start / step_complete / agent_thinking / phase_change / execution_end）
 * 和连接管理。截图帧事件由独立的 useFrameObserver 处理。
 *
 * 用法:
 *   const { steps, stats, status, connect, disconnect } = useExecutionObserver(executionId)
 *   connect()  // 建立连接
 *   disconnect() // 断开连接
 */
import { ref, reactive, onUnmounted } from 'vue'
import { getExecutionSteps, getExecution } from '../api'

export function useExecutionObserver(executionId) {
  // ── 响应式状态 ──
  const steps = ref([])                // 步骤列表
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

  /**
   * 立即拉取缺失的步骤（断线重连后，利用实时持久化的步骤数据回填）。
   */
  async function _fetchMissingSteps() {
    try {
      const id = executionId.value !== undefined ? executionId.value : executionId
      const { data } = await getExecutionSteps(id)

      if (data.step_logs && data.step_logs.length > steps.value.length) {
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
    } catch (e) {
      console.warn('[Observer] _fetchMissingSteps failed:', e)
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
        const serverSteps = data.completed_steps || 0

        // 重连时清除旧的阶段描述，避免闪现过期状态
        currentPhase.value = null

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
          // 检查是否有缺失的步骤需要回填（断线重连场景）
          if (serverSteps > steps.value.length) {
            _fetchMissingSteps()
          }
        }
        break
      }

      case 'step_start':
        status.value = 'running'
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
        currentPhase.value = data || null
        break

      case 'execution_end':
        status.value = 'completed'
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
    stats,
    status,
    error,
    currentPhase,
    connect,
    disconnect,
  }
}
