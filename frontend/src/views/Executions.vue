<template>
  <div>
    <el-card>
      <template #header>
        <div class="card-header">
          <span>执行记录</span>
          <div>
            <el-select v-model="filters.execution_mode" placeholder="执行模式" clearable size="small" style="width: 130px; margin-right: 8px">
              <el-option label="Script" value="script" />
              <el-option label="Agent" value="agent" />
            </el-select>
            <el-select v-model="filters.status" placeholder="状态" clearable size="small" style="width: 120px; margin-right: 8px">
              <el-option label="通过" value="passed" />
              <el-option label="失败" value="failed" />
              <el-option label="运行中" value="running" />
              <el-option label="异常" value="error" />
            </el-select>
            <el-select v-model="filters.project" placeholder="筛选项目" clearable size="small" style="width: 200px">
              <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
            </el-select>
          </div>
        </div>
      </template>
      <el-table :data="filteredExecutions" style="width: 100%" v-loading="loading">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="project_name" label="项目" width="130" />
        <el-table-column prop="testcase_name" label="用例" width="180" show-overflow-tooltip />
        <el-table-column prop="execution_mode" label="模式" width="80">
          <template #default="{ row }">
            <el-tag :type="row.execution_mode === 'agent' ? 'primary' : 'info'" size="small">
              {{ row.execution_mode || 'script' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="duration" label="耗时" width="70">
          <template #default="{ row }">
            {{ row.duration ? row.duration + 's' : '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="tool_calls_count" label="工具调用" width="80">
          <template #default="{ row }">
            {{ row.tool_calls_count || '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="执行时间" width="170" />
        <el-table-column label="操作" min-width="280" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'running'"
              size="small" text type="primary"
              @click="navigateToObserver(row.id)"
            >观察</el-button>
            <el-button
              v-if="['agent', 'replay'].includes(row.execution_mode) && isTerminalStatus(row.status)"
              size="small" text type="warning"
              @click="navigateToReplay(row.id)"
            >回放</el-button>
            <el-button
              v-if="row.execution_mode === 'agent' && isTerminalStatus(row.status)"
              size="small" text type="success"
              @click="navigateToScriptEditor(row.id)"
            >{{ row.replay_script ? '编辑脚本' : '生成脚本' }}</el-button>
            <el-button size="small" text type="primary" @click="showDetail(row)">详情</el-button>
            <el-button size="small" text type="warning" @click="showLog(row)">日志</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 详情弹窗 -->
    <el-dialog v-model="showDetailDialog" title="执行详情" width="800px" top="5vh">
      <template v-if="detailRecord">
        <div style="display: flex; justify-content: flex-end; margin-bottom: 12px; gap: 8px;" v-if="detailRecord.status === 'running' || (['agent', 'replay'].includes(detailRecord.execution_mode) && isTerminalStatus(detailRecord.status))">
          <el-button v-if="detailRecord.status === 'running'" type="primary" size="small" @click="navigateToObserver(detailRecord.id); showDetailDialog = false">
            <el-icon><Monitor /></el-icon> 观察执行
          </el-button>
          <el-button v-if="['agent', 'replay'].includes(detailRecord.execution_mode) && isTerminalStatus(detailRecord.status)" type="warning" size="small" @click="navigateToReplay(detailRecord.id); showDetailDialog = false">
            <el-icon><VideoPlay /></el-icon> 回放
          </el-button>
        </div>
        <el-descriptions :column="3" border size="small" style="margin-bottom: 16px">
          <el-descriptions-item label="用例">{{ detailRecord.testcase_name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="模式">
            <el-tag :type="detailRecord.execution_mode === 'agent' ? 'primary' : 'info'" size="small">
              {{ detailRecord.execution_mode || 'script' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="statusType(detailRecord.status)" size="small">{{ detailRecord.status }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="耗时">{{ detailRecord.duration ? detailRecord.duration + 's' : '-' }}</el-descriptions-item>
          <el-descriptions-item label="工具调用">{{ detailRecord.tool_calls_count || '-' }}</el-descriptions-item>
          <el-descriptions-item label="AI 模型">{{ detailRecord.ai_model || '-' }}</el-descriptions-item>
          <el-descriptions-item label="时间" :span="3">{{ detailRecord.created_at }}</el-descriptions-item>
        </el-descriptions>

        <!-- 步骤时间线 (Agent 模式) -->
        <template v-if="detailRecord.step_logs && detailRecord.step_logs.length">
          <h4>执行步骤</h4>
          <el-timeline style="margin: 12px 0">
            <el-timeline-item
              v-for="step in detailRecord.step_logs"
              :key="step.step_num"
              :timestamp="step.timestamp || ''"
              placement="top"
              :type="step.action === '报告结果' ? 'success' : 'primary'"
            >
              <div class="step-item">
                <strong>Step {{ step.step_num }}</strong>: {{ step.action }}
                <span v-if="step.target" class="step-target">→ {{ step.target }}</span>
                <el-button
                  v-if="step.screenshot_path"
                  size="small" text type="primary"
                  @click="previewImage(step.screenshot_path)"
                  style="margin-left: 8px"
                >查看截图</el-button>
              </div>
              <div v-if="step.result" class="step-result">{{ truncate(step.result, 150) }}</div>
            </el-timeline-item>
          </el-timeline>
        </template>

        <!-- 截图画廊 -->
        <ScreenshotGallery
          :screenshots="detailRecord.screenshots"
          :show-title="true"
        />

        <!-- Agent 响应 -->
        <template v-if="detailRecord.agent_response && detailRecord.agent_response.response_text">
          <h4>Agent 响应</h4>
          <pre class="log-block agent-response">{{ detailRecord.agent_response.response_text }}</pre>
        </template>

        <!-- 错误信息 -->
        <template v-if="detailRecord.error_message">
          <h4 style="color: #f56c6c; margin-top: 12px">错误信息</h4>
          <pre class="log-block error">{{ detailRecord.error_message }}</pre>
        </template>
      </template>
    </el-dialog>

    <!-- 日志弹窗 -->
    <el-dialog v-model="showLogDialog" title="执行日志" width="700px">
      <template v-if="logRecord">
        <el-descriptions :column="2" border size="small" style="margin-bottom: 16px">
          <el-descriptions-item label="用例">{{ logRecord.testcase_name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="statusType(logRecord.status)" size="small">{{ logRecord.status }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="耗时">{{ logRecord.duration ? logRecord.duration + 's' : '-' }}</el-descriptions-item>
          <el-descriptions-item label="时间">{{ logRecord.created_at }}</el-descriptions-item>
        </el-descriptions>
        <el-divider />
        <h4>执行日志</h4>
        <pre class="log-block">{{ logRecord.log || '暂无日志' }}</pre>
        <template v-if="logRecord.error_message">
          <h4 style="color: #f56c6c; margin-top: 12px">错误信息</h4>
          <pre class="log-block error">{{ logRecord.error_message }}</pre>
        </template>
      </template>
    </el-dialog>

    <!-- 图片预览弹窗 -->
    <el-dialog v-model="showImageDialog" title="截图预览" width="80%" top="5vh">
      <div style="text-align: center">
        <img :src="previewImageUrl" style="max-width: 100%; max-height: 70vh" />
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { getExecutions, getProjects } from '../api'
import { ElMessage } from 'element-plus'
import { Monitor, VideoPlay } from '@element-plus/icons-vue'
import ScreenshotGallery from '../components/ScreenshotGallery.vue'

const router = useRouter()

const POLL_INTERVAL = 5000

const executions = ref([])
const projects = ref([])
const loading = ref(false)
const filters = ref({ project: null, status: null, execution_mode: null })

const showDetailDialog = ref(false)
const detailRecord = ref(null)
const showLogDialog = ref(false)
const logRecord = ref(null)
const showImageDialog = ref(false)
const previewImageUrl = ref('')
let pollTimer = null

const filteredExecutions = computed(() => {
  let result = executions.value
  if (filters.value.status) {
    result = result.filter(r => r.status === filters.value.status)
  }
  if (filters.value.execution_mode) {
    result = result.filter(r => (r.execution_mode || 'script') === filters.value.execution_mode)
  }
  return result
})

const statusType = (s) => {
  const map = { passed: 'success', failed: 'danger', running: 'warning', error: 'danger', pending: 'info' }
  return map[s] || 'info'
}

const screenshotUrl = (path) => `/api/executions/screenshots/?path=${encodeURIComponent(path)}`

const truncate = (text, len) => {
  if (!text) return ''
  return text.length > len ? text.slice(0, len) + '...' : text
}

const previewImage = (path) => {
  previewImageUrl.value = screenshotUrl(path)
  showImageDialog.value = true
}

const loadExecutions = async () => {
  loading.value = true
  try {
    const params = {}
    if (filters.value.project) params.project = filters.value.project
    const { data } = await getExecutions(params)
    executions.value = data.results || data
  } finally {
    loading.value = false
  }
  // 自动轮询：有 running 记录时启动，否则停止
  const hasRunning = executions.value.some(r => r.status === 'running')
  if (hasRunning && !pollTimer) {
    pollTimer = setInterval(loadExecutions, POLL_INTERVAL)
  } else if (!hasRunning && pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

onUnmounted(() => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
})

const showDetail = (row) => {
  detailRecord.value = row
  showDetailDialog.value = true
}

const showLog = (row) => {
  logRecord.value = row
  showLogDialog.value = true
}

const navigateToObserver = (id) => {
  router.push({ name: 'ExecutionObserver', params: { id } })
}

const navigateToReplay = (id) => {
  router.push({ name: 'ExecutionObserver', params: { id }, query: { replay: 'true' } })
}

const navigateToScriptEditor = (id) => {
  router.push({ name: 'ScriptEditor', params: { id } })
}

const isTerminalStatus = (s) => ['passed', 'failed', 'error'].includes(s)

watch(() => filters.value.project, loadExecutions)

onMounted(async () => {
  const [, p] = await Promise.all([
    loadExecutions(),
    getProjects(),
  ])
  projects.value = p.data.results || p.data
})
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.log-block {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 16px;
  border-radius: 4px;
  font-family: 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.6;
  overflow-x: auto;
  white-space: pre-wrap;
  max-height: 400px;
  overflow-y: auto;
}
.log-block.error {
  background: #2d1b1b;
  color: #f56c6c;
}
.log-block.agent-response {
  background: #1a2332;
  color: #a8d4ff;
}
.step-item {
  font-size: 14px;
}
.step-target {
  color: #909399;
  font-size: 12px;
}
.step-result {
  color: #909399;
  font-size: 12px;
  margin-top: 4px;
  word-break: break-all;
}
</style>
