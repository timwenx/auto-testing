/**
 * useExecutionObserver — 封装 WebSocket 连接管理，实时监听执行过程事件。

 * 用法:
 *   const { steps, currentFrame, stats, status, connect, disconnect } = useExecutionObserver(executionId)
 *   connect()  // 建立连接
 *   disconnect() // 断开连接
 */
import { ref, reactive, onUnmounted } from 'vue'

export function useExecutionObserver(executionId) {
  // ── 响应式状态 ──
  const steps = ref([])                // 步骤列表
  const currentFrame = ref(null)       // 当前截图帧 (data URL)
  const stats = reactive({
    inputTokens: 0,
    outputTokens: 0,
    totalSteps: 0,
    duration: 0,
    startTime: null,
  })
  const status = ref('idle')           // idle | connecting | connected | running | completed | error
  const error = ref(null)

  // ── WebSocket 管理 ──
  let ws = null
  let reconnectAttempts = 0
  let reconnectTimer = null
  const MAX_RECONNECT_ATTEMPTS = 5
  const RECONNECT_BASE_DELAY = 1000

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
      status.value = 'connected'
      reconnectAttempts = 0
      error.value = null
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
      // 正常关闭（执行结束）不重连
      if (status.value === 'completed') return
      if (event.code === 1000) return

      ws = null
      _scheduleReconnect()
    }

    ws.onerror = (event) => {
      console.error('[Observer] WebSocket error:', event)
      // onclose 会紧接着被触发，由 onclose 处理重连
    }
  }

  function _handleEvent(data) {
    switch (data.type) {
      case 'connection_established':
        // 连接确认，不做额外处理
        break

      case 'step_start':
        status.value = 'running'
        steps.value.push({
          step_num: data.step_num,
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
        // 查找对应的 step_start 并更新，或直接添加
        const existingIdx = steps.value.findIndex(
          s => s.step_num === data.step_num && s.state === 'running'
        )
        const stepData = {
          step_num: data.step_num,
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

      case 'browser_frame':
        currentFrame.value = data.image || null
        break

      case 'execution_end':
        status.value = 'completed'
        stats.totalSteps = data.total_steps || steps.value.length
        stats.inputTokens = data.input_tokens || 0
        stats.outputTokens = data.output_tokens || 0
        // 关闭 WebSocket
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.close(1000, 'Execution completed')
        }
        break

      default:
        console.debug('[Observer] Unknown event type:', data.type)
    }
  }

  // ── 公开方法 ──

  function connect() {
    if (ws && ws.readyState === WebSocket.OPEN) return
    reconnectAttempts = 0
    _connectWs()
  }

  function disconnect() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
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
    connect,
    disconnect,
  }
}
