<template>
  <div class="execution-observer">
    <!-- 顶部标题栏 -->
    <div class="observer-header">
      <el-page-header @back="goBack">
        <template #content>
          <span class="header-title">{{ replayMode ? '执行回放' : '执行观察面板' }}</span>
          <el-tag :type="statusTagType" size="small" class="header-status">{{ statusLabel }}</el-tag>
        </template>
      </el-page-header>
      <div class="header-actions">
        <el-button
          v-if="canReplay && !replayMode"
          size="small"
          type="primary"
          @click="enterReplay"
        >
          <el-icon><VideoPlay /></el-icon>
          回放
        </el-button>
        <el-button
          v-if="replayMode"
          size="small"
          @click="exitReplay"
        >
          <el-icon><Monitor /></el-icon>
          实时模式
        </el-button>
      </div>
    </div>

    <!-- 回放模式 -->
    <ExecutionReplay v-if="replayMode" :execution-id="executionId" />

    <!-- 实时模式 -->
    <div v-else class="observer-body">
      <!-- 左侧：浏览器截图流 / 历史截图画廊 -->
      <div class="observer-left" :class="{ 'pip-hidden': pipMode }">
        <!-- 已完成执行：展示截图画廊 -->
        <div v-if="isTerminalStatus" class="completed-view">
          <BrowserView
            :frame-src="currentFrame"
            :execution-status="executionInfo?.status || 'idle'"
            :pip="pipMode"
            @refresh="connect"
            @toggle-pip="pipMode = !pipMode"
          />
          <div v-if="screenshots.length > 0" class="gallery-section">
            <ScreenshotGallery :screenshots="screenshots" :show-title="true" />
          </div>
        </div>
        <!-- 进行中执行：实时浏览器画面 -->
        <BrowserView
          v-else
          :frame-src="currentFrame"
          :execution-status="status === 'running' ? 'running' : (executionInfo?.status || 'idle')"
          :phase="currentPhase"
          :pip="pipMode"
          @refresh="connect"
          @toggle-pip="pipMode = !pipMode"
        />
      </div>

      <!-- 右侧：步骤时间线 -->
      <div class="observer-right">
        <!-- 基本信息 -->
        <div class="info-bar" v-if="executionInfo">
          <el-descriptions :column="2" size="small" border>
            <el-descriptions-item label="用例">{{ executionInfo.testcase_name }}</el-descriptions-item>
            <el-descriptions-item label="模式">
              <el-tag size="small" :type="executionInfo.execution_mode === 'agent' ? 'primary' : 'info'">
                {{ executionInfo.execution_mode }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="项目">{{ executionInfo.project_name }}</el-descriptions-item>
            <el-descriptions-item label="状态">
              <el-tag size="small" :type="getStatusType(executionInfo.status)">{{ executionInfo.status }}</el-tag>
            </el-descriptions-item>
          </el-descriptions>
        </div>

        <!-- 统计栏 -->
        <ExecutionStats
          :status="status"
          :total-steps="stats.totalSteps"
          :input-tokens="stats.inputTokens"
          :output-tokens="stats.outputTokens"
          :duration="executionInfo?.duration || 0"
        />

        <!-- 步骤时间线 -->
        <div class="timeline-container">
          <ExecutionTimeline :steps="steps" :selected-idx="selectedStepIdx" @select="handleStepSelect" />
        </div>

        <!-- 步骤详情面板 -->
        <ToolDetailPanel :step="selectedStep" @close="selectedStepIdx = -1" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getExecution, getExecutionSteps } from '../api'
import { useExecutionObserver } from '../composables/useExecutionObserver'
import ExecutionTimeline from '../components/ExecutionTimeline.vue'
import ExecutionStats from '../components/ExecutionStats.vue'
import ToolDetailPanel from '../components/ToolDetailPanel.vue'
import BrowserView from '../components/BrowserView.vue'
import ExecutionReplay from '../components/ExecutionReplay.vue'
import ScreenshotGallery from '../components/ScreenshotGallery.vue'
import { VideoPlay, Monitor } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const executionId = computed(() => parseInt(route.params.id))

// 回放模式
const replayMode = ref(false)

// 终态判断
const TERMINAL_STATUSES = ['completed', 'passed', 'failed', 'error']
const isTerminalStatus = computed(() =>
  executionInfo.value && TERMINAL_STATUSES.includes(executionInfo.value.status)
)
const canReplay = computed(() => isTerminalStatus.value)

function enterReplay() {
  replayMode.value = true
  disconnect()
}

function exitReplay() {
  replayMode.value = false
  // 如果执行仍在运行，重新连接
  if (executionInfo.value?.status === 'running') {
    connect()
  }
}

// 执行信息
const executionInfo = ref(null)
const screenshots = ref([])  // 截图画廊数据

// Observer composable
const { steps, currentFrame, stats, status, error, currentPhase, connect, disconnect } = useExecutionObserver(executionId)

// 选中步骤
const selectedStepIdx = ref(-1)
const pipMode = ref(false)
const lastRestepCount = ref(0) // 追踪上次 REST 回填的步骤数
const selectedStep = computed(() => {
  if (selectedStepIdx.value >= 0 && selectedStepIdx.value < steps.value.length) {
    return steps.value[selectedStepIdx.value]
  }
  return null
})

// 状态标签
const statusTagType = computed(() => {
  if (replayMode.value) return 'warning'
  const map = { connecting: 'warning', connected: 'info', running: 'primary', completed: 'success', error: 'danger' }
  return map[status.value] || 'info'
})

const statusLabel = computed(() => {
  if (replayMode.value) return '回放中'
  const map = { idle: '空闲', connecting: '连接中', connected: '已连接', running: '执行中', completed: '已完成', error: '错误' }
  return map[status.value] || status.value
})

function getStatusType(s) {
  const map = { passed: 'success', failed: 'danger', running: 'primary', error: 'warning', pending: 'info' }
  return map[s] || 'info'
}

function handleStepSelect(idx, step) {
  selectedStepIdx.value = selectedStepIdx.value === idx ? -1 : idx
}

function goBack() {
  router.back()
}

// 断线重连后 REST 补齐：当 WebSocket 重新连接时，拉取步骤补齐中间丢失的
watch(status, async (newStatus, oldStatus) => {
  // 同步 composable 状态到 executionInfo.status
  if (executionInfo.value) {
    if (newStatus === 'running') {
      executionInfo.value.status = 'running'
    } else if (newStatus === 'completed') {
      // 如果 composable 检测到执行已结束（通过 connection_established 或 execution_end），
      // 更新 executionInfo 的状态以触发 BrowserView 显示"执行已完成"
      // 只在尚未达到终态时更新（允许 running / connected → completed）
      const terminalStatuses = ['completed', 'passed', 'failed', 'error']
      if (!terminalStatuses.includes(executionInfo.value.status)) {
        executionInfo.value = { ...executionInfo.value, status: 'completed' }
      }
    }
  }

  if (newStatus === 'connected' && oldStatus !== 'idle' && oldStatus !== 'connecting') {
    try {
      const { data } = await getExecutionSteps(executionId.value)
      if (data.step_logs && data.step_logs.length > lastRestepCount.value) {
        // 合并 REST 返回的步骤（避免与 WebSocket 实时步骤重复）
        const restSteps = data.step_logs.slice(lastRestepCount.value)
        for (const step of restSteps) {
          const exists = steps.value.some(s => s.step_num === step.step_num && s.state === 'completed')
          if (!exists) {
            steps.value.push({ ...step, state: 'completed', duration_ms: step.duration_ms || 0 })
          }
        }
        lastRestepCount.value = data.step_logs.length
      }
      // 同步 executionInfo（duration、status 等可能在断线期间变化）
      try {
        const { data: infoData } = await getExecution(executionId.value)
        if (infoData) {
          executionInfo.value = infoData
        }
      } catch (e) {
        console.warn('Failed to sync execution info after reconnect:', e)
      }
      // 如果执行已完成，直接加载完整结果并关闭 WebSocket
      if (data.status !== 'running') {
        stats.totalSteps = data.step_logs?.length || stats.totalSteps
        if (data.agent_response?.input_tokens) {
          stats.inputTokens = data.agent_response.input_tokens
          stats.outputTokens = data.agent_response.output_tokens
        }
        disconnect()
      }
    } catch (e) {
      console.warn('REST backfill after reconnect failed:', e)
    }
  }
})

// 初始化
onMounted(async () => {
  try {
    // 获取执行记录基本信息
    const { data } = await getExecution(executionId.value)
    executionInfo.value = data
  } catch (e) {
    console.error('Failed to load execution info:', e)
    return
  }

  // 分支 1: ?replay=true → 直接进入回放模式，不建连
  if (route.query.replay === 'true') {
    replayMode.value = true
    // 回放模式仍需加载步骤数据供回放组件使用
    await _loadStepData()
    return
  }

  // 分支 2: 已完成执行 → REST 拉取全部数据，不建 WS 连接
  if (TERMINAL_STATUSES.includes(executionInfo.value?.status)) {
    status.value = 'completed'
    await _loadStepData()
    return
  }

  // 分支 3: 进行中执行 → 先 REST 拉取已持久化步骤，再建 WS 连接
  await _loadStepData()
  connect()
})

/**
 * 加载步骤数据（REST 回填）
 * 利用 Task 1 的实时步骤持久化，断线重连后也能获取完整数据
 */
async function _loadStepData() {
  try {
    const { data } = await getExecutionSteps(executionId.value)
    if (data.step_logs && data.step_logs.length > 0) {
      steps.value = data.step_logs.map(step => ({
        ...step,
        state: 'completed',
        duration_ms: step.duration_ms || 0,
      }))
    }
    if (data.agent_response?.input_tokens) {
      stats.inputTokens = data.agent_response.input_tokens
      stats.outputTokens = data.agent_response.output_tokens
    }
    stats.totalSteps = data.step_logs?.length || 0
    lastRestepCount.value = data.step_logs?.length || 0

    // 加载截图数据（用于已完成执行的截图画廊）
    const allScreenshots = [
      ...(data.screenshots || []),
      ...(data.auto_screenshots || []),
    ]
    if (allScreenshots.length > 0) {
      screenshots.value = allScreenshots
    } else {
      // 从 step_logs 中提取截图路径作为 fallback
      screenshots.value = (data.step_logs || [])
        .map(s => s.screenshot_path)
        .filter(Boolean)
    }
  } catch (e) {
    console.error('Failed to load execution steps:', e)
  }
}
</script>

<style scoped>
.execution-observer {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--el-bg-color);
}

.observer-header {
  padding: 12px 20px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  background: var(--el-bg-color);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.header-title {
  font-size: 16px;
  font-weight: 600;
}

.header-status {
  margin-left: 12px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.observer-body {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.observer-left {
  width: 40%;
  min-width: 300px;
  border-right: 1px solid var(--el-border-color-lighter);
  background: var(--el-fill-color-darker);
}

.observer-left.pip-hidden {
  width: 0;
  min-width: 0;
  border-right: none;
  overflow: hidden;
}

.observer-right {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.info-bar {
  padding: 12px 16px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.timeline-container {
  flex: 1;
  overflow-y: auto;
  padding: 12px 0;
}

.completed-view {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.gallery-section {
  flex-shrink: 0;
  max-height: 200px;
  overflow-y: auto;
  padding: 8px 12px;
  border-top: 1px solid var(--el-border-color-lighter);
}
</style>
