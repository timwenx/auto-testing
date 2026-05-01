<template>
  <div>
    <el-card>
      <template #header>
        <div class="card-header">
          <span>脚本管理</span>
          <el-select v-model="projectFilter" placeholder="筛选项目" clearable size="small" style="width: 200px">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </div>
      </template>
      <el-table :data="filteredScripts" style="width: 100%" v-loading="loading">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="project_name" label="项目" width="130" />
        <el-table-column prop="testcase_name" label="用例" min-width="180" show-overflow-tooltip />
        <el-table-column prop="execution_mode" label="来源" width="80">
          <template #default="{ row }">
            <el-tag :type="row.execution_mode === 'agent' ? 'primary' : 'success'" size="small">
              {{ row.execution_mode }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="步骤数" width="80">
          <template #default="{ row }">
            {{ row.replay_script?.steps?.length || 0 }}
          </template>
        </el-table-column>
        <el-table-column label="参数数" width="80">
          <template #default="{ row }">
            {{ Object.keys(row.replay_script?.parameters || {}).length }}
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="170" />
        <el-table-column label="操作" width="250" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="editScript(row)">编辑</el-button>
            <el-button size="small" text type="success" @click="executeScript(row)">执行</el-button>
            <el-button size="small" text type="warning" @click="openReplaySelect(row)">回放</el-button>
            <el-button size="small" text type="danger" @click="deleteScript(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 回放选择弹窗 -->
    <el-dialog v-model="showReplayDialog" title="选择回放记录" width="700px">
      <el-table :data="replayExecutions" v-loading="replayLoading" size="small"
                highlight-current-row @current-change="selectReplayRow" ref="replayTableRef">
        <el-table-column width="55">
          <template #default="{ row }">
            <el-radio v-model="selectedReplayId" :value="row.id">&nbsp;</el-radio>
          </template>
        </el-table-column>
        <el-table-column prop="id" label="ID" width="60" />
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
        <el-table-column prop="created_at" label="执行时间" min-width="160" />
      </el-table>
      <template #footer>
        <el-button @click="showReplayDialog = false">取消</el-button>
        <el-button type="primary" :disabled="!selectedReplayId" @click="confirmReplay">确认回放</el-button>
      </template>
    </el-dialog>

    <!-- 参数填写弹窗 -->
    <el-dialog v-model="showParamDialog" title="执行参数" width="640px">
      <template v-if="paramRow">
        <div v-if="paramKeys.length" style="background:var(--el-fill-color-lighter);padding:16px;border-radius:8px">
          <el-form :model="paramValues" label-width="auto" size="small">
            <el-form-item v-for="key in paramKeys" :key="key" :label="paramRow.replay_script.parameters[key].label || key">
              <el-input
                v-model="paramValues[key]"
                :placeholder="paramRow.replay_script.parameters[key].default"
                clearable
                @clear="paramValues[key] = paramRow.replay_script.parameters[key].default || ''"
              />
            </el-form-item>
          </el-form>
        </div>
        <el-empty v-else description="无动态参数" :image-size="48" />
      </template>
      <template #footer>
        <el-button @click="showParamDialog = false">取消</el-button>
        <el-button type="primary" @click="confirmExecute" :loading="executing">确认执行</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { getExecutions, getProjects, updateReplayScript, replayExecute } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'

const router = useRouter()

const scripts = ref([])
const projects = ref([])
const loading = ref(false)
const projectFilter = ref(null)
const showReplayDialog = ref(false)
const replayExecutions = ref([])
const replayLoading = ref(false)
const selectedReplayId = ref(null)
const showParamDialog = ref(false)
const paramRow = ref(null)
const paramValues = ref({})
const executing = ref(false)
const paramKeys = computed(() => paramRow.value ? Object.keys(paramRow.value.replay_script?.parameters || {}) : [])
let replayScriptRow = null

const filteredScripts = computed(() => {
  if (!projectFilter.value) return scripts.value
  return scripts.value.filter(s => s.project === projectFilter.value)
})

async function loadScripts() {
  loading.value = true
  try {
    const { data } = await getExecutions({ has_replay_script: 'true' })
    scripts.value = (data.results || data).filter(s => s.replay_script)
  } finally {
    loading.value = false
  }
}

function editScript(row) {
  router.push({ name: 'ScriptEditor', params: { id: row.id } })
}

function executeScript(row) {
  paramRow.value = row
  const params = row.replay_script?.parameters || {}
  paramValues.value = {}
  for (const [name, info] of Object.entries(params)) {
    paramValues.value[name] = info.default || ''
  }
  showParamDialog.value = true
}

async function confirmExecute() {
  if (!paramRow.value) return
  executing.value = true
  try {
    const overrides = {}
    for (const [k, v] of Object.entries(paramValues.value)) {
      if (v) overrides[k] = v
    }
    const { data } = await replayExecute(paramRow.value.id, { parameter_overrides: overrides })
    showParamDialog.value = false
    ElMessage.success('回放已启动')
    router.push(`/executions/${data.id}/observe`)
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '执行失败')
  } finally {
    executing.value = false
  }
}

const statusType = (s) => {
  const map = { passed: 'success', failed: 'danger', running: 'warning', error: 'danger' }
  return map[s] || 'info'
}

async function openReplaySelect(row) {
  replayScriptRow = row
  selectedReplayId.value = null
  showReplayDialog.value = true
  replayLoading.value = true
  try {
    const { data } = await getExecutions({ source_execution: row.id })
    replayExecutions.value = data.results || data
  } finally {
    replayLoading.value = false
  }
}

function selectReplayRow(row) {
  if (row) selectedReplayId.value = row.id
}

function confirmReplay() {
  if (!selectedReplayId.value) return
  showReplayDialog.value = false
  router.push({ name: 'ExecutionObserver', params: { id: selectedReplayId.value }, query: { replay: 'true' } })
}

async function deleteScript(row) {
  try {
    await ElMessageBox.confirm('确定删除该脚本？删除后需要重新生成。', '确认删除')
    await updateReplayScript(row.id, { delete: true })
    scripts.value = scripts.value.filter(s => s.id !== row.id)
    ElMessage.success('已删除')
  } catch {
    // cancelled
  }
}

watch(projectFilter, () => {})

onMounted(async () => {
  const [, p] = await Promise.all([
    loadScripts(),
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
</style>
