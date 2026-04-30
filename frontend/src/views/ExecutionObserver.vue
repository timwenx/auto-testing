<template>
  <div class="execution-observer">
    <!-- 顶部标题栏 -->
    <div class="observer-header">
      <el-page-header @back="goBack">
        <template #content>
          <span class="header-title">执行观察面板</span>
          <el-tag :type="statusTagType" size="small" class="header-status">{{ statusLabel }}</el-tag>
        </template>
      </el-page-header>
    </div>

    <div class="observer-body">
      <!-- 左侧：浏览器截图流 -->
      <div class="observer-left" :class="{ 'pip-hidden': pipMode }">
        <BrowserView
          :frame-src="currentFrame"
          :execution-status="status === 'running' ? 'running' : (executionInfo?.status || 'idle')"
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

const route = useRoute()
const router = useRouter()
const executionId = computed(() => parseInt(route.params.id))

// 执行信息
const executionInfo = ref(null)

// Observer composable
const { steps, currentFrame, stats, status, error, connect, disconnect } = useExecutionObserver(executionId)

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
  const map = { connecting: 'warning', connected: 'info', running: 'primary', completed: 'success', error: 'danger' }
  return map[status.value] || 'info'
})

const statusLabel = computed(() => {
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
      if (executionInfo.value.status === 'running') {
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
            steps.value.push({ ...step, state: 'completed', duration_ms: 0 })
          }
        }
        lastRestepCount.value = data.step_logs.length
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
  }

  try {
    // 加载已有的步骤（REST 回填）
    const { data } = await getExecutionSteps(executionId.value)
    if (data.step_logs && data.step_logs.length > 0) {
      // 如果已经有步骤数据（可能已完成或页面刷新），预填充
      steps.value = data.step_logs.map(step => ({
        ...step,
        state: 'completed',
        duration_ms: 0,
      }))
    }
    if (data.agent_response?.input_tokens) {
      stats.inputTokens = data.agent_response.input_tokens
      stats.outputTokens = data.agent_response.output_tokens
    }
    stats.totalSteps = data.step_logs?.length || 0
    lastRestepCount.value = data.step_logs?.length || 0
  } catch (e) {
    console.error('Failed to load execution steps:', e)
  }

  // 如果执行仍在运行，建立 WebSocket 连接
  if (executionInfo.value?.status === 'running') {
    connect()
  }
})
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
}

.header-title {
  font-size: 16px;
  font-weight: 600;
}

.header-status {
  margin-left: 12px;
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
</style>
