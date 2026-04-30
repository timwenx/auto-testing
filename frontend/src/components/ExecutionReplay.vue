<template>
  <div class="execution-replay">
    <!-- 控制栏 -->
    <div class="replay-controls">
      <div class="controls-left">
        <el-button-group>
          <el-button size="small" :type="playing ? 'warning' : 'primary'" @click="togglePlay">
            <el-icon v-if="playing"><VideoPause /></el-icon>
            <el-icon v-else><VideoPlay /></el-icon>
            {{ playing ? '暂停' : '播放' }}
          </el-button>
          <el-button size="small" @click="restart">
            <el-icon><RefreshRight /></el-icon>
            重播
          </el-button>
        </el-button-group>
        <el-select v-model="speed" size="small" style="width: 90px; margin-left: 8px">
          <el-option label="0.5x" :value="0.5" />
          <el-option label="1x" :value="1" />
          <el-option label="2x" :value="2" />
          <el-option label="4x" :value="4" />
        </el-select>
      </div>
      <div class="controls-center">
        <span class="replay-progress-text">
          Step {{ currentStepIdx + 1 }} / {{ totalSteps }}
        </span>
      </div>
      <div class="controls-right">
        <span class="replay-time">{{ elapsedTimeFormatted }}</span>
      </div>
    </div>

    <!-- 进度条 -->
    <el-slider
      v-model="progressPercent"
      :min="0"
      :max="100"
      :show-tooltip="false"
      :disabled="allSteps.length === 0"
      @input="onProgressDrag"
      @change="onProgressSeek"
      class="replay-slider"
    />

    <!-- 主内容区 -->
    <div class="replay-body">
      <!-- 左侧：浏览器截图 -->
      <div class="replay-left">
        <BrowserView
          :frame-src="currentScreenshotUrl"
          :execution-status="playing ? 'running' : (finished ? 'completed' : 'idle')"
        />
      </div>

      <!-- 右侧：步骤时间线 -->
      <div class="replay-right">
        <div class="timeline-container">
          <ExecutionTimeline
            :steps="visibleSteps"
            :selected-idx="selectedStepIdx"
            @select="handleStepSelect"
          />
          <div v-if="!playing && visibleSteps.length === 0" class="replay-empty">
            <el-icon :size="32"><VideoPlay /></el-icon>
            <span>点击播放开始回放</span>
          </div>
        </div>
        <ToolDetailPanel :step="selectedStep" @close="selectedStepIdx = -1" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onUnmounted } from 'vue'
import { VideoPlay, VideoPause, RefreshRight } from '@element-plus/icons-vue'
import { getExecutionSteps } from '../api'
import ExecutionTimeline from './ExecutionTimeline.vue'
import BrowserView from './BrowserView.vue'
import ToolDetailPanel from './ToolDetailPanel.vue'

const props = defineProps({
  executionId: { type: [Number, String], required: true },
})

// ── 状态 ──
const allSteps = ref([])           // 完整步骤列表（从 REST 加载）
const visibleSteps = ref([])       // 当前可见的步骤（逐步追加）
const playing = ref(false)
const finished = ref(false)
const speed = ref(1)
const currentStepIdx = ref(-1)     // 当前正在播放的步骤索引
const selectedStepIdx = ref(-1)
const elapsedTime = ref(0)         // 已经过的虚拟时间 (ms)

let playTimer = null               // setTimeout 引用
let allScreenshots = []            // 执行期间的所有截图路径

// ── 计算属性 ──
const totalSteps = computed(() => allSteps.value.length)

const progressPercent = computed({
  get() {
    if (totalSteps.value === 0) return 0
    return Math.round(((currentStepIdx.value + 1) / totalSteps.value) * 100)
  },
  set() { /* 由 onProgressDrag/Seek 处理 */ },
})

const selectedStep = computed(() => {
  if (selectedStepIdx.value >= 0 && selectedStepIdx.value < visibleSteps.value.length) {
    return visibleSteps.value[selectedStepIdx.value]
  }
  return null
})

const currentScreenshotUrl = computed(() => {
  // 从当前可见步骤中找最近一个有截图的步骤
  for (let i = visibleSteps.value.length - 1; i >= 0; i--) {
    const sp = visibleSteps.value[i].screenshot_path
    if (sp) {
      return `/api/executions/screenshots/?path=${encodeURIComponent(sp)}`
    }
  }
  return null
})

const elapsedTimeFormatted = computed(() => {
  const totalSec = Math.round(elapsedTime.value / 1000)
  const min = Math.floor(totalSec / 60)
  const sec = totalSec % 60
  return `${min}:${sec.toString().padStart(2, '0')}`
})

// ── 拉取数据 ──
async function loadData() {
  try {
    const { data } = await getExecutionSteps(props.executionId)
    const stepLogs = data.step_logs || []
    allSteps.value = stepLogs.map(s => ({
      ...s,
      state: 'completed',
      duration_ms: s.duration_ms || 0,
    }))
    allScreenshots = data.screenshots || []
  } catch (e) {
    console.error('[Replay] Failed to load steps:', e)
  }
}

// ── 播放控制 ──
function togglePlay() {
  if (playing.value) {
    pause()
  } else {
    play()
  }
}

function play() {
  if (allSteps.value.length === 0) return
  // 如果已经播放完毕，重置后播放
  if (finished.value) {
    restart()
    return
  }
  playing.value = true
  scheduleNextStep()
}

function pause() {
  playing.value = false
  if (playTimer) {
    clearTimeout(playTimer)
    playTimer = null
  }
}

function restart() {
  pause()
  finished.value = false
  visibleSteps.value = []
  currentStepIdx.value = -1
  elapsedTime.value = 0
  selectedStepIdx.value = -1
  // 自动开始播放
  playing.value = true
  scheduleNextStep()
}

function scheduleNextStep() {
  if (!playing.value) return
  const nextIdx = currentStepIdx.value + 1
  if (nextIdx >= allSteps.value.length) {
    finished.value = true
    playing.value = false
    return
  }

  const step = allSteps.value[nextIdx]
  // 计算延迟：使用 duration_ms，限制在 500ms ~ 5000ms
  let delayMs = step.duration_ms || 1000
  delayMs = Math.max(500, Math.min(5000, delayMs))
  // 应用倍速
  delayMs = delayMs / speed.value

  playTimer = setTimeout(() => {
    _showStep(nextIdx)
    scheduleNextStep()
  }, delayMs)
}

function _showStep(idx) {
  currentStepIdx.value = idx
  const step = allSteps.value[idx]
  visibleSteps.value.push({ ...step })
  elapsedTime.value += step.duration_ms || 1000
}

// ── 进度条拖拽 ──
let isDragging = false

function onProgressDrag(val) {
  isDragging = true
}

function onProgressSeek(val) {
  isDragging = false
  // 计算目标步骤索引
  const targetIdx = Math.round((val / 100) * (totalSteps.value - 1))
  const wasPlaying = playing.value
  pause()

  // 重建 visibleSteps 到 targetIdx
  visibleSteps.value = []
  let accTime = 0
  for (let i = 0; i <= targetIdx; i++) {
    const step = allSteps.value[i]
    visibleSteps.value.push({ ...step })
    accTime += step.duration_ms || 1000
  }
  currentStepIdx.value = targetIdx
  elapsedTime.value = accTime
  finished.value = targetIdx >= allSteps.value.length - 1

  // 如果之前在播放，继续播放
  if (wasPlaying && !finished.value) {
    playing.value = true
    scheduleNextStep()
  }
}

// ── 步骤选择 ──
function handleStepSelect(idx) {
  selectedStepIdx.value = selectedStepIdx.value === idx ? -1 : idx
}

// ── 生命周期 ──
watch(() => props.executionId, () => {
  restart()
  loadData()
}, { immediate: true })

onUnmounted(() => {
  pause()
})
</script>

<style scoped>
.execution-replay {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--el-bg-color);
}

.replay-controls {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  background: var(--el-bg-color);
}

.controls-left {
  display: flex;
  align-items: center;
}

.controls-center {
  text-align: center;
}

.replay-progress-text {
  font-size: 13px;
  color: var(--el-text-color-regular);
  font-weight: 500;
}

.controls-right {
  text-align: right;
}

.replay-time {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  font-family: monospace;
}

.replay-slider {
  padding: 0 16px;
  margin: 4px 0;
}

.replay-body {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.replay-left {
  width: 40%;
  min-width: 300px;
  border-right: 1px solid var(--el-border-color-lighter);
  background: var(--el-fill-color-darker);
}

.replay-right {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.timeline-container {
  flex: 1;
  overflow-y: auto;
  padding: 12px 0;
}

.replay-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 60px 0;
  color: var(--el-text-color-placeholder);
  font-size: 14px;
}
</style>
