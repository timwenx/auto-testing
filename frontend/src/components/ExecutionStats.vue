<template>
  <div class="execution-stats">
    <el-space :size="20" wrap>
      <!-- 状态指示 -->
      <span class="stat-item">
        <span class="status-dot" :class="statusClass"></span>
        <span>{{ statusLabel }}</span>
      </span>

      <!-- 耗时 -->
      <span class="stat-item">
        <el-icon><Timer /></el-icon>
        <span>{{ displayDuration }}</span>
      </span>

      <!-- 步骤数 -->
      <span class="stat-item">
        <el-icon><Operation /></el-icon>
        <span>{{ totalSteps }} 步骤</span>
      </span>

      <!-- Token 消耗 -->
      <span class="stat-item" v-if="inputTokens > 0 || outputTokens > 0">
        <el-icon><Coin /></el-icon>
        <span>输入 {{ formatTokens(inputTokens) }} / 输出 {{ formatTokens(outputTokens) }}</span>
      </span>
    </el-space>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { Timer, Operation, Coin } from '@element-plus/icons-vue'

const props = defineProps({
  status: { type: String, default: 'idle' },
  totalSteps: { type: Number, default: 0 },
  inputTokens: { type: Number, default: 0 },
  outputTokens: { type: Number, default: 0 },
  startTime: { type: [Date, Number, null], default: null },
  endTime: { type: [Date, Number, null], default: null },
  duration: { type: Number, default: 0 },
})

// 实时计时器
const elapsed = ref(0)
let timerInterval = null

function startTimer() {
  stopTimer()
  timerInterval = setInterval(() => {
    if (props.startTime) {
      elapsed.value = Math.floor((Date.now() - new Date(props.startTime).getTime()) / 1000)
    }
  }, 1000)
}

function stopTimer() {
  if (timerInterval) {
    clearInterval(timerInterval)
    timerInterval = null
  }
}

watch(() => props.status, (newStatus) => {
  if (newStatus === 'running') {
    startTimer()
  } else {
    stopTimer()
  }
})

onMounted(() => {
  if (props.status === 'running') {
    startTimer()
  }
})

onUnmounted(() => {
  stopTimer()
})

const displayDuration = computed(() => {
  // 如果有固定 duration（已完成），用它
  if (props.duration > 0 && props.status !== 'running') {
    return formatDuration(props.duration)
  }
  // 运行中用实时计时
  if (props.status === 'running' && elapsed.value > 0) {
    return formatDuration(elapsed.value)
  }
  return '0s'
})

const statusClass = computed(() => ({
  'dot-running': props.status === 'running',
  'dot-completed': props.status === 'completed',
  'dot-error': props.status === 'error',
  'dot-idle': props.status === 'idle',
}))

const statusLabel = computed(() => {
  const map = { idle: '空闲', connecting: '连接中', connected: '已连接', running: '执行中', completed: '已完成', error: '错误' }
  return map[props.status] || props.status
})

function formatDuration(seconds) {
  if (seconds < 60) return `${seconds}s`
  const min = Math.floor(seconds / 60)
  const sec = seconds % 60
  return `${min}m ${sec}s`
}

function formatTokens(count) {
  if (count >= 1000) return (count / 1000).toFixed(1) + 'k'
  return count.toString()
}
</script>

<style scoped>
.execution-stats {
  padding: 8px 16px;
  background: var(--el-fill-color-lighter);
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.stat-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  color: var(--el-text-color-regular);
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.dot-running {
  background: var(--el-color-primary);
  animation: pulse 1.5s ease-in-out infinite;
}

.dot-completed {
  background: var(--el-color-success);
}

.dot-error {
  background: var(--el-color-danger);
}

.dot-idle {
  background: var(--el-text-color-placeholder);
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
</style>
