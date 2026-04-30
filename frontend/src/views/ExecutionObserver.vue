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
      <!-- 左侧：占位区域（Phase 2 浏览器截图流） -->
      <div class="observer-left">
        <div class="browser-placeholder">
          <div v-if="currentFrame" class="frame-container">
            <img :src="currentFrame" alt="Browser frame" class="browser-frame" />
          </div>
          <div v-else class="placeholder-content">
            <el-icon :size="48" color="var(--el-text-color-placeholder)"><Monitor /></el-icon>
            <p>浏览器画面将在 Phase 2 中可用</p>
          </div>
        </div>
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
        <div class="stats-bar" v-if="steps.length > 0">
          <el-space :size="16">
            <span class="stat-item">
              <el-icon><Operation /></el-icon>
              步骤: {{ steps.length }}
            </span>
            <span class="stat-item" v-if="stats.inputTokens > 0">
              <el-icon><Coin /></el-icon>
              Token: {{ stats.inputTokens + stats.outputTokens }}
            </span>
          </el-space>
        </div>

        <!-- 步骤时间线 -->
        <div class="timeline-container">
          <ExecutionTimeline :steps="steps" :selected-idx="selectedStepIdx" @select="handleStepSelect" />
        </div>

        <!-- 步骤详情面板 (Phase 3 完善) -->
        <div class="step-detail-panel" v-if="selectedStep">
          <div class="detail-header">
            <span class="step-icon">{{ getStepIcon(selectedStep.action) }}</span>
            <span class="detail-title">{{ selectedStep.action }}</span>
          </div>
          <div class="detail-body">
            <div v-if="selectedStep.target" class="detail-section">
              <span class="detail-label">目标:</span>
              <span class="detail-value">{{ selectedStep.target }}</span>
            </div>
            <div v-if="selectedStep.result" class="detail-section">
              <span class="detail-label">结果:</span>
              <pre class="detail-value detail-result">{{ selectedStep.result }}</pre>
            </div>
            <div v-if="selectedStep.screenshot_path" class="detail-section">
              <span class="detail-label">截图:</span>
              <el-image
                :src="'/api/executions/screenshots/?path=' + encodeURIComponent(selectedStep.screenshot_path)"
                :preview-src-list="['/api/executions/screenshots/?path=' + encodeURIComponent(selectedStep.screenshot_path)]"
                style="max-width: 300px; border-radius: 4px;"
                fit="contain"
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Monitor, Operation, Coin } from '@element-plus/icons-vue'
import { getExecution, getExecutionSteps } from '../api'
import { useExecutionObserver } from '../composables/useExecutionObserver'
import ExecutionTimeline from '../components/ExecutionTimeline.vue'

const route = useRoute()
const router = useRouter()
const executionId = computed(() => parseInt(route.params.id))

// 执行信息
const executionInfo = ref(null)

// Observer composable
const { steps, currentFrame, stats, status, error, connect, disconnect } = useExecutionObserver(executionId)

// 选中步骤
const selectedStepIdx = ref(-1)
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

function getStepIcon(action) {
  const map = {
    browser_navigate: '🌐', browser_click: '👆', browser_fill: '✏️',
    browser_press_key: '⌨️', browser_wait_for: '⏳', browser_get_text: '📋',
    browser_screenshot: '📸', list_files: '📂', read_file: '📄',
    search_code: '🔍', list_directory: '📁', report_result: '📊',
  }
  return map[action] || '⚙️'
}

function handleStepSelect(idx, step) {
  selectedStepIdx.value = selectedStepIdx.value === idx ? -1 : idx
}

function goBack() {
  router.back()
}

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
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--el-fill-color-darker);
}

.browser-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.frame-container {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 8px;
}

.browser-frame {
  max-width: 100%;
  max-height: 100%;
  border-radius: 4px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
}

.placeholder-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  color: var(--el-text-color-placeholder);
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

.stats-bar {
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

.timeline-container {
  flex: 1;
  overflow-y: auto;
  padding: 12px 0;
}

.step-detail-panel {
  border-top: 1px solid var(--el-border-color-lighter);
  max-height: 250px;
  overflow-y: auto;
  padding: 12px 16px;
  background: var(--el-fill-color-blank);
}

.detail-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.detail-title {
  font-weight: 600;
  font-size: 14px;
}

.detail-section {
  margin-bottom: 8px;
}

.detail-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-right: 8px;
}

.detail-value {
  font-size: 13px;
  color: var(--el-text-color-primary);
}

.detail-result {
  background: var(--el-fill-color-light);
  padding: 8px;
  border-radius: 4px;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
  margin-top: 4px;
  max-height: 120px;
  overflow-y: auto;
}
</style>
