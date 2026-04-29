<template>
  <div>
    <el-card>
      <template #header>
        <div class="card-header">
          <span>执行记录</span>
          <div>
            <el-select v-model="filters.project" placeholder="筛选项目" clearable size="small" style="width: 200px; margin-right: 8px">
              <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
            </el-select>
          </div>
        </div>
      </template>
      <el-table :data="executions" style="width: 100%" v-loading="loading">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="project_name" label="项目" width="150" />
        <el-table-column prop="testcase_name" label="用例" width="200" />
        <el-table-column prop="status" label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="duration" label="耗时" width="80">
          <template #default="{ row }">
            {{ row.duration ? row.duration + 's' : '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="执行时间" width="180" />
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="showLog(row)">日志</el-button>
            <el-button size="small" text type="success" @click="handleAnalyze(row)">AI 分析</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

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

    <!-- AI 分析弹窗 -->
    <el-dialog v-model="showAnalysisDialog" title="AI 分析结果" width="600px">
      <template v-if="analysis">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="总结">{{ analysis.summary }}</el-descriptions-item>
          <el-descriptions-item label="根因分析">{{ analysis.root_cause }}</el-descriptions-item>
          <el-descriptions-item label="改进建议">{{ analysis.suggestion }}</el-descriptions-item>
          <el-descriptions-item label="严重程度">
            <el-tag :type="severityType(analysis.severity)" size="small">{{ analysis.severity }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="偶发问题">
            {{ analysis.is_flaky ? '可能是' : '否' }}
          </el-descriptions-item>
        </el-descriptions>
      </template>
      <div v-else v-loading="true" style="height: 100px"></div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { getExecutions, getProjects, aiAnalyzeResult } from '../api'
import { ElMessage } from 'element-plus'

const executions = ref([])
const projects = ref([])
const loading = ref(false)
const filters = ref({ project: null })
const showLogDialog = ref(false)
const logRecord = ref(null)
const showAnalysisDialog = ref(false)
const analysis = ref(null)

const statusType = (s) => {
  const map = { passed: 'success', failed: 'danger', running: 'warning', error: 'danger', pending: 'info' }
  return map[s] || 'info'
}

const severityType = (s) => {
  const map = { low: 'success', medium: 'warning', high: 'danger' }
  return map[s] || 'info'
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
}

const showLog = (row) => {
  logRecord.value = row
  showLogDialog.value = true
}

const handleAnalyze = async (row) => {
  analysis.value = null
  showAnalysisDialog.value = true
  try {
    const { data } = await aiAnalyzeResult({ execution_id: row.id })
    analysis.value = data
  } catch (e) {
    ElMessage.error(e.response?.data?.error || 'AI 分析失败')
    showAnalysisDialog.value = false
  }
}

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
</style>
