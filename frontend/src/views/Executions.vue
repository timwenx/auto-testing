<template>
  <div>
    <el-card>
      <template #header>
        <div class="card-header">
          <span>执行记录</span>
          <div style="display: flex; gap: 8px; flex-wrap: wrap; align-items: center">
            <el-select v-model="filters.execution_mode" placeholder="执行模式" clearable size="small" style="width: 120px">
              <el-option label="Script" value="script" />
              <el-option label="Agent" value="agent" />
              <el-option label="Replay" value="replay" />
              <el-option label="方案" value="plan" />
            </el-select>
            <el-select v-model="filters.status" placeholder="状态" clearable size="small" style="width: 110px">
              <el-option label="通过" value="passed" />
              <el-option label="失败" value="failed" />
              <el-option label="运行中" value="running" />
              <el-option label="异常" value="error" />
            </el-select>
            <el-select v-model="filters.project" placeholder="项目" clearable size="small" style="width: 160px">
              <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
            </el-select>
            <el-date-picker
              v-model="filters.dateRange"
              type="daterange"
              range-separator="至"
              start-placeholder="开始日期"
              end-placeholder="结束日期"
              size="small"
              value-format="YYYY-MM-DD"
              style="width: 240px"
            />
          </div>
        </div>
      </template>
      <el-table :data="executions" style="width: 100%" v-loading="loading" row-key="id">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="expand-content">
              <template v-if="row.step_logs && row.step_logs.length">
                <h4 class="expand-section-title">执行步骤</h4>
                <el-timeline style="margin: 12px 0 16px">
                  <el-timeline-item v-for="step in row.step_logs" :key="step.step_num" :timestamp="step.timestamp || ''" placement="top" :type="step.action === '报告结果' ? 'success' : 'primary'">
                    <div class="step-item">
                      <strong>Step {{ step.step_num }}</strong>: {{ step.action }}
                      <span v-if="step.target" class="step-target">→ {{ step.target }}</span>
                      <el-button v-if="step.screenshot_path" size="small" text type="primary" @click="previewImage(step.screenshot_path)" style="margin-left: 8px">查看截图</el-button>
                    </div>
                    <div v-if="step.result" class="step-result">{{ truncate(step.result, 200) }}</div>
                  </el-timeline-item>
                </el-timeline>
              </template>
              <ScreenshotGallery v-if="row.screenshots && row.screenshots.length" :screenshots="row.screenshots" :show-title="true" />
              <template v-if="row.agent_response && row.agent_response.response_text">
                <h4 class="expand-section-title">Agent 响应</h4>
                <pre class="log-block agent-response">{{ row.agent_response.response_text }}</pre>
              </template>
              <template v-if="row.error_message">
                <h4 class="expand-section-title" style="color: #f56c6c">错误信息</h4>
                <pre class="log-block error">{{ row.error_message }}</pre>
              </template>
              <template v-if="row._plan_sub_records && row._plan_sub_records.length">
                <h4 class="expand-section-title">方案子执行记录</h4>
                <el-table :data="row._plan_sub_records" size="small" border style="margin-bottom: 12px">
                  <el-table-column prop="testcase_name" label="用例" min-width="160" show-overflow-tooltip />
                  <el-table-column prop="execution_mode" label="模式" width="80">
                    <template #default="{ row: sub }"><el-tag :type="sub.execution_mode === 'agent' ? 'primary' : 'info'" size="small">{{ sub.execution_mode || 'script' }}</el-tag></template>
                  </el-table-column>
                  <el-table-column prop="status" label="状态" width="80">
                    <template #default="{ row: sub }"><el-tag :type="statusType(sub.status)" size="small">{{ sub.status }}</el-tag></template>
                  </el-table-column>
                  <el-table-column prop="duration" label="耗时" width="70">
                    <template #default="{ row: sub }">{{ sub.duration ? sub.duration + 's' : '-' }}</template>
                  </el-table-column>
                </el-table>
              </template>
              <el-empty v-if="!hasExpandContent(row)" description="无详情数据" :image-size="48" />
            </div>
          </template>
        </el-table-column>

        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="project_name" label="项目" width="130" />
        <el-table-column prop="testcase_name" label="用例" width="180" show-overflow-tooltip />
        <el-table-column prop="execution_mode" label="模式" width="80">
          <template #default="{ row }">
            <el-tag :type="executionModeType(row)" size="small">{{ row.execution_mode || 'script' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="80">
          <template #default="{ row }"><el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="duration" label="耗时" width="70">
          <template #default="{ row }">{{ row.duration ? row.duration + 's' : '-' }}</template>
        </el-table-column>
        <el-table-column prop="tool_calls_count" label="工具调用" width="80">
          <template #default="{ row }">{{ row.tool_calls_count || '-' }}</template>
        </el-table-column>
        <el-table-column prop="created_at" label="执行时间" width="170" />
        <el-table-column label="操作" min-width="240" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status === 'running'" size="small" text type="primary" @click="navigateToObserver(row.id)">观察</el-button>
            <el-button v-if="['agent', 'replay'].includes(row.execution_mode) && isTerminalStatus(row.status)" size="small" text type="warning" @click="navigateToReplay(row.id)">回放</el-button>
            <el-button v-if="row.execution_mode === 'agent' && isTerminalStatus(row.status)" size="small" text type="success" @click="navigateToScriptEditor(row.id)">{{ row.replay_script ? '编辑脚本' : '生成脚本' }}</el-button>
            <el-button size="small" text type="primary" @click="showDetail(row)">详情</el-button>
            <el-button size="small" text type="warning" @click="showLog(row)">日志</el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- Pagination -->
      <div style="display: flex; justify-content: flex-end; margin-top: 16px" v-if="total > pageSize">
        <el-pagination
          small
          layout="prev, pager, next, total"
          :total="total"
          :page-size="pageSize"
          v-model:current-page="currentPage"
          @current-change="loadExecutions"
        />
      </div>
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
            <el-tag :type="detailRecord.execution_mode === 'agent' ? 'primary' : 'info'" size="small">{{ detailRecord.execution_mode || 'script' }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="statusType(detailRecord.status)" size="small">{{ detailRecord.status }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="耗时">{{ detailRecord.duration ? detailRecord.duration + 's' : '-' }}</el-descriptions-item>
          <el-descriptions-item label="工具调用">{{ detailRecord.tool_calls_count || '-' }}</el-descriptions-item>
          <el-descriptions-item label="AI 模型">{{ detailRecord.ai_model || '-' }}</el-descriptions-item>
          <el-descriptions-item label="时间" :span="3">{{ detailRecord.created_at }}</el-descriptions-item>
        </el-descriptions>
        <template v-if="detailRecord.step_logs && detailRecord.step_logs.length">
          <h4>执行步骤</h4>
          <el-timeline style="margin: 12px 0">
            <el-timeline-item v-for="step in detailRecord.step_logs" :key="step.step_num" :timestamp="step.timestamp || ''" placement="top" :type="step.action === '报告结果' ? 'success' : 'primary'">
              <div class="step-item">
                <strong>Step {{ step.step_num }}</strong>: {{ step.action }}
                <span v-if="step.target" class="step-target">→ {{ step.target }}</span>
                <el-button v-if="step.screenshot_path" size="small" text type="primary" @click="previewImage(step.screenshot_path)" style="margin-left: 8px">查看截图</el-button>
              </div>
              <div v-if="step.result" class="step-result">{{ truncate(step.result, 150) }}</div>
            </el-timeline-item>
          </el-timeline>
        </template>
        <ScreenshotGallery :screenshots="detailRecord.screenshots" :show-title="true" />
        <template v-if="detailRecord.agent_response && detailRecord.agent_response.response_text">
          <h4>Agent 响应</h4>
          <pre class="log-block agent-response">{{ detailRecord.agent_response.response_text }}</pre>
        </template>
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
          <el-descriptions-item label="状态"><el-tag :type="statusType(logRecord.status)" size="small">{{ logRecord.status }}</el-tag></el-descriptions-item>
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

    <!-- 图片预览 -->
    <el-dialog v-model="showImageDialog" title="截图预览" width="80%" top="5vh">
      <div style="text-align: center"><img :src="previewImageUrl" style="max-width: 100%; max-height: 70vh" /></div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { getExecutions, getProjects } from '../api'
import { ElMessage } from 'element-plus'
import ScreenshotGallery from '../components/ScreenshotGallery.vue'

const router = useRouter()
const POLL_INTERVAL = 5000

const executions = ref([])
const projects = ref([])
const loading = ref(false)
const filters = ref({ project: null, status: null, execution_mode: null, dateRange: null })

const currentPage = ref(1)
const pageSize = 20
const total = ref(0)

const showDetailDialog = ref(false)
const detailRecord = ref(null)
const showLogDialog = ref(false)
const logRecord = ref(null)
const showImageDialog = ref(false)
const previewImageUrl = ref('')
let pollTimer = null

const statusType = (s) => {
  const map = { passed: 'success', failed: 'danger', running: 'warning', error: 'danger', pending: 'info' }
  return map[s] || 'info'
}

const executionModeType = (row) => {
  if (row.plan_execution) return 'warning'
  return (row.execution_mode || 'script') === 'agent' ? 'primary' : 'info'
}

const truncate = (text, len) => text ? (text.length > len ? text.slice(0, len) + '...' : text) : ''

const hasExpandContent = (row) => {
  return (row.step_logs && row.step_logs.length) || (row.screenshots && row.screenshots.length) ||
    (row.agent_response && row.agent_response.response_text) || row.error_message ||
    (row._plan_sub_records && row._plan_sub_records.length)
}

const previewImage = (path) => { previewImageUrl.value = `/api/executions/screenshots/?path=${encodeURIComponent(path)}`; showImageDialog.value = true }

const loadExecutions = async () => {
  loading.value = true
  try {
    const params = { page: currentPage.value, page_size: pageSize }
    if (filters.value.project) params.project = filters.value.project
    if (filters.value.status) params.status = filters.value.status
    if (filters.value.execution_mode && filters.value.execution_mode !== 'plan') {
      params.execution_mode = filters.value.execution_mode
    }
    if (filters.value.execution_mode === 'plan') params.plan_execution = 'true'
    if (filters.value.dateRange && filters.value.dateRange.length === 2) {
      params.created_after = filters.value.dateRange[0]
      params.created_before = filters.value.dateRange[1]
    }
    const { data } = await getExecutions(params)
    executions.value = data.results || data
    total.value = data.count ?? (Array.isArray(data) ? data.length : 0)
  } finally { loading.value = false }

  // Auto-poll for running executions
  const hasRunning = executions.value.some(r => r.status === 'running')
  if (hasRunning && !pollTimer) {
    pollTimer = setInterval(loadExecutions, POLL_INTERVAL)
  } else if (!hasRunning && pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

onUnmounted(() => { if (pollTimer) { clearInterval(pollTimer); pollTimer = null } })

const showDetail = (row) => { detailRecord.value = row; showDetailDialog.value = true }
const showLog = (row) => { logRecord.value = row; showLogDialog.value = true }
const navigateToObserver = (id) => router.push({ name: 'ExecutionObserver', params: { id } })
const navigateToReplay = (id) => router.push({ name: 'ExecutionObserver', params: { id }, query: { replay: 'true' } })
const navigateToScriptEditor = (id) => router.push({ name: 'ScriptEditor', params: { id } })
const isTerminalStatus = (s) => ['passed', 'failed', 'error'].includes(s)

// Reload when filters change
watch(() => [filters.value.project, filters.value.status, filters.value.execution_mode, filters.value.dateRange], () => {
  currentPage.value = 1
  loadExecutions()
}, { deep: true })

onMounted(async () => {
  const [, p] = await Promise.all([loadExecutions(), getProjects()])
  projects.value = p.data.results || p.data
})
</script>

<style scoped>
.card-header { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }
.expand-content { padding: 12px 24px; }
.expand-section-title { margin: 8px 0; font-size: 14px; font-weight: 600; }
.log-block { background: #1e1e1e; color: #d4d4d4; padding: 16px; border-radius: 4px; font-family: 'Consolas', monospace; font-size: 13px; line-height: 1.6; overflow-x: auto; white-space: pre-wrap; max-height: 400px; overflow-y: auto; }
.log-block.error { background: #2d1b1b; color: #f56c6c; }
.log-block.agent-response { background: #1a2332; color: #a8d4ff; }
.step-item { font-size: 14px; }
.step-target { color: #909399; font-size: 12px; }
.step-result { color: #909399; font-size: 12px; margin-top: 4px; word-break: break-all; }
</style>
