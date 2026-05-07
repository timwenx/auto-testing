<template>
  <div>
    <el-card>
      <template #header>
        <div class="card-header">
          <span>执行记录</span>
          <div style="display: flex; gap: 8px; flex-wrap: wrap; align-items: center">
            <el-button v-if="selectedIds.length > 0" size="small" type="danger" @click="handleBatchDeleteSelected">
              <el-icon><Delete /></el-icon> 删除选中 ({{ selectedIds.length }})
            </el-button>
            <el-popconfirm title="确定要清除所有执行记录吗？此操作不可恢复" @confirm="handleClearAll" confirm-button-text="确定清除" cancel-button-text="取消" confirm-button-type="danger">
              <template #reference>
                <el-button size="small" type="danger" plain>清除全部</el-button>
              </template>
            </el-popconfirm>
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

      <!-- 按功能点分组展示 -->
      <div v-loading="loading">
        <el-collapse v-model="expandedGroups" v-if="groupedExecutions.length">
          <el-collapse-item
            v-for="group in groupedExecutions"
            :key="group.name"
            :name="group.name"
          >
            <template #title>
              <div class="group-header" @click.stop>
                <div class="group-header-left">
                  <el-icon style="margin-right: 6px"><Folder /></el-icon>
                  <span class="group-name">{{ group.name }}</span>
                  <el-tag size="small" type="info" style="margin-left: 8px">{{ group.count }} 条</el-tag>
                  <el-tag v-if="group.passed" size="small" type="success" style="margin-left: 4px">{{ group.passed }} 通过</el-tag>
                  <el-tag v-if="group.failed" size="small" type="danger" style="margin-left: 4px">{{ group.failed }} 失败</el-tag>
                  <el-tag v-if="group.running" size="small" type="warning" style="margin-left: 4px">{{ group.running }} 运行中</el-tag>
                </div>
                <div class="group-header-right">
                  <el-button
                    v-if="group.count > 0"
                    size="small"
                    type="danger"
                    text
                    @click.stop="handleDeleteGroup(group)"
                    :loading="deletingGroup === group.name"
                  >
                    <el-icon><Delete /></el-icon> 删除此组
                  </el-button>
                  <el-button
                    v-if="group.name !== '方案执行' && group.name !== '未关联用例' && group.count > 0"
                    size="small"
                    type="success"
                    text
                    @click.stop="handleBatchConvert(group)"
                    :loading="convertingGroup === group.name"
                  >
                    <el-icon><Document /></el-icon> 生成脚本
                  </el-button>
                </div>
              </div>
            </template>
            <el-table :data="group.records" style="width: 100%" size="small" row-key="id" @expand-change="handleExpandChange" @selection-change="(val) => handleSelectionChange(val, group.name)">
              <el-table-column type="selection" width="40" />
              <el-table-column type="expand">
                <template #default="{ row }">
                  <div class="expand-content">
                    <template v-if="row._loading">
                      <div style="text-align: center; padding: 16px; color: #909399">加载中...</div>
                    </template>
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
                  <el-button size="small" text type="danger" @click="handleDeleteSingle(row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-collapse-item>
        </el-collapse>
        <el-empty v-else description="暂无执行记录" :image-size="80" />
      </div>

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
      <div v-loading="!detailRecord" style="min-height: 100px">
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
      </div>
    </el-dialog>

    <!-- 日志弹窗 -->
    <el-dialog v-model="showLogDialog" title="执行日志" width="700px">
      <div v-loading="!logRecord" style="min-height: 100px">
      <template v-if="logRecord">
        <el-descriptions :column="2" border size="small" style="margin-bottom: 16px">
          <el-descriptions-item label="用例">{{ logRecord.testcase_name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="状态"><el-tag :type="statusType(logRecord.status)" size="small">{{ logRecord.status }}</el-tag></el-descriptions-item>
          <el-descriptions-item label="耗时">{{ logRecord.duration ? logRecord.duration + 's' : '-' }}</el-descriptions-item>
          <el-descriptions-item label="时间">{{ logRecord.created_at }}</el-descriptions-item>
        </el-descriptions>
        <el-divider />
        <template v-if="logRecord.step_logs && logRecord.step_logs.length">
          <h4>执行步骤日志</h4>
          <el-timeline style="margin: 12px 0">
            <el-timeline-item v-for="step in logRecord.step_logs" :key="step.step_num" :timestamp="step.timestamp || ''" placement="top" :type="step.action === '报告结果' ? 'success' : 'primary'">
              <div class="step-item">
                <strong>Step {{ step.step_num }}</strong>: {{ step.action }}
                <span v-if="step.target" class="step-target">→ {{ step.target }}</span>
              </div>
              <div v-if="step.result" class="step-result">{{ step.result }}</div>
            </el-timeline-item>
          </el-timeline>
        </template>
        <template v-if="logRecord.agent_response && logRecord.agent_response.response_text">
          <h4>Agent 响应</h4>
          <pre class="log-block agent-response">{{ logRecord.agent_response.response_text }}</pre>
        </template>
        <el-empty v-if="!logRecord.step_logs?.length && !logRecord.agent_response?.response_text && !logRecord.error_message" description="暂无日志数据" :image-size="48" />
        <template v-if="logRecord.error_message">
          <h4 style="color: #f56c6c; margin-top: 12px">错误信息</h4>
          <pre class="log-block error">{{ logRecord.error_message }}</pre>
        </template>
      </template>
      </div>
    </el-dialog>

    <!-- 图片预览 -->
    <el-dialog v-model="showImageDialog" title="截图预览" width="80%" top="5vh">
      <div style="text-align: center"><img :src="previewImageUrl" style="max-width: 100%; max-height: 70vh" /></div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { getExecutions, getExecution, getProjects, batchConvertScripts, deleteExecution, batchDeleteExecutions } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import ScreenshotGallery from '../components/ScreenshotGallery.vue'

const router = useRouter()
const POLL_INTERVAL = 5000

const executions = ref([])
const projects = ref([])
const loading = ref(false)
const convertingGroup = ref('')
const selectedIds = ref([])
const deletingGroup = ref('')
const filters = ref({ project: null, status: null, execution_mode: null, dateRange: null })

const currentPage = ref(1)
const pageSize = 20
const total = ref(0)
const expandedGroups = ref([])

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
    (row._plan_sub_records && row._plan_sub_records.length) || row._loading
}

const handleExpandChange = async (row, expandedRows) => {
  if (expandedRows.some(r => r.id === row.id) && !row.step_logs && !row._loading) {
    row._loading = true
    try {
      const { data } = await getExecution(row.id)
      row.step_logs = data.step_logs || []
      row.screenshots = data.screenshots || []
      row.agent_response = data.agent_response || row.agent_response
      row.error_message = data.error_message || row.error_message
    } catch { /* keep existing data */ }
    finally { row._loading = false }
  }
}

const previewImage = (path) => { previewImageUrl.value = `/api/executions/screenshots/?path=${encodeURIComponent(path)}`; showImageDialog.value = true }

// 按功能点分组
const groupedExecutions = computed(() => {
  const groups = {}
  const order = []

  for (const row of executions.value) {
    let groupName
    if (row.plan_execution) {
      groupName = '方案执行'
    } else if (!row.testcase) {
      groupName = '未关联用例'
    } else {
      groupName = row.testcase_feature_group || '未分组'
    }

    if (!groups[groupName]) {
      groups[groupName] = { name: groupName, records: [], count: 0, passed: 0, failed: 0, running: 0 }
      order.push(groupName)
    }
    groups[groupName].records.push(row)
    groups[groupName].count++
    if (row.status === 'passed') groups[groupName].passed++
    else if (row.status === 'failed' || row.status === 'error') groups[groupName].failed++
    else if (row.status === 'running') groups[groupName].running++
  }

  return order.map(name => groups[name])
})

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

    // 自动展开所有分组
    expandedGroups.value = groupedExecutions.value.map(g => g.name)
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

const showDetail = async (row) => {
  detailRecord.value = null
  showDetailDialog.value = true
  try {
    const { data } = await getExecution(row.id)
    detailRecord.value = data
  } catch { detailRecord.value = row }
}
const showLog = async (row) => {
  logRecord.value = null
  showLogDialog.value = true
  try {
    const { data } = await getExecution(row.id)
    logRecord.value = data
  } catch { logRecord.value = row }
}
const navigateToObserver = (id) => router.push({ name: 'ExecutionObserver', params: { id } })
const navigateToReplay = (id) => router.push({ name: 'ExecutionObserver', params: { id }, query: { replay: 'true' } })
const navigateToScriptEditor = (id) => router.push({ name: 'ScriptEditor', params: { id } })
const isTerminalStatus = (s) => ['passed', 'failed', 'error'].includes(s)

// ─── 选择管理 ───
const groupSelections = ref({})  // groupName -> selected rows

const handleSelectionChange = (val, groupName) => {
  groupSelections.value[groupName] = val
  // 合并所有分组选中项
  selectedIds.value = Object.values(groupSelections.value).flat().map(r => r.id)
}

// ─── 删除操作 ───
const handleDeleteSingle = async (row) => {
  try {
    await ElMessageBox.confirm(`确定要删除执行记录 #${row.id}（${row.testcase_name || '批量执行'}）吗？`, '删除确认', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
    await deleteExecution(row.id)
    ElMessage.success('已删除')
    loadExecutions()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e.response?.data?.detail || '删除失败')
  }
}

const handleDeleteGroup = async (group) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除功能点「${group.name}」下的所有 ${group.count} 条执行记录吗？`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
    deletingGroup.value = group.name
    const payload = {}
    if (filters.value.project) payload.project_id = filters.value.project
    if (group.name === '方案执行') {
      payload.plan_only = true
    } else if (group.name === '未关联用例') {
      payload.feature_group = ''
    } else {
      payload.feature_group = group.name
    }
    const { data } = await batchDeleteExecutions(payload)
    ElMessage.success(data.message || `已删除 ${data.deleted} 条记录`)
    loadExecutions()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e.response?.data?.error || '删除失败')
  } finally {
    deletingGroup.value = ''
  }
}

const handleBatchDeleteSelected = async () => {
  try {
    await ElMessageBox.confirm(
      `确定要删除选中的 ${selectedIds.value.length} 条执行记录吗？`,
      '批量删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
    const { data } = await batchDeleteExecutions({ ids: selectedIds.value })
    ElMessage.success(data.message || `已删除 ${data.deleted} 条记录`)
    selectedIds.value = []
    groupSelections.value = {}
    loadExecutions()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e.response?.data?.error || '删除失败')
  }
}

const handleClearAll = async () => {
  try {
    const { data } = await batchDeleteExecutions({ clear_all: true })
    ElMessage.success(data.message || `已清除 ${data.deleted} 条记录`)
    selectedIds.value = []
    groupSelections.value = {}
    loadExecutions()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '清除失败')
  }
}

// 批量生成脚本
const handleBatchConvert = async (group) => {
  // 优先从筛选器获取项目，否则从组内记录中提取
  let projectId = filters.value.project
  if (!projectId && group.records.length) {
    projectId = group.records[0].project
  }
  if (!projectId) {
    ElMessage.warning('无法确定所属项目，请在筛选器中选择一个项目')
    return
  }
  convertingGroup.value = group.name
  try {
    // 映射显示名到实际值
    let featureGroup = group.name
    if (featureGroup === '未分组') featureGroup = ''
    const { data } = await batchConvertScripts(projectId, featureGroup)
    if (data.created > 0) {
      ElMessage.success(`成功生成 ${data.created} 个脚本${data.skipped > 0 ? `，跳过 ${data.skipped} 条（已存在或无可用数据）` : ''}`)
    } else {
      ElMessage.info(data.skipped > 0 ? `所有 ${data.skipped} 条记录已有脚本，无需重复生成` : '没有可转换的执行记录')
    }
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '批量脚本生成失败')
  } finally {
    convertingGroup.value = ''
  }
}

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
.group-header { display: flex; justify-content: space-between; align-items: center; width: 100%; padding-right: 16px; }
.group-header-left { display: flex; align-items: center; }
.group-header-right { display: flex; align-items: center; gap: 8px; }
.group-name { font-weight: 600; font-size: 14px; }

:deep(.el-collapse-item__header) { height: auto !important; min-height: 48px; padding: 8px 0; line-height: 1.5; }
</style>
