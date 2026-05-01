<template>
  <div>
    <el-card>
      <template #header>
        <div class="card-header">
          <span>脚本管理</span>
          <el-select v-model="projectFilter" placeholder="筛选项目" clearable size="small" style="width: 200px" />
        </div>
      </template>

      <el-table :data="filteredScripts" style="width: 100%" v-loading="loading">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="project_name" label="项目" width="130" />
        <el-table-column prop="name" label="脚本名称" min-width="180" show-overflow-tooltip />
        <el-table-column prop="feature_group" label="功能分组" width="130" show-overflow-tooltip>
          <template #default="{ row }">{{ row.feature_group || '未分组' }}</template>
        </el-table-column>
        <el-table-column label="步骤数" width="80">
          <template #default="{ row }">{{ row.script_data?.steps?.length || 0 }}</template>
        </el-table-column>
        <el-table-column label="参数数" width="80">
          <template #default="{ row }">{{ Object.keys(row.script_data?.parameters || {}).length }}</template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="scriptStatusType(row.status)" size="small">{{ scriptStatusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="version" label="版本" width="60" />
        <el-table-column prop="updated_at" label="更新时间" width="170" />
        <el-table-column label="操作" width="240" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="editScript(row)">编辑</el-button>
            <el-button size="small" text type="success" @click="executeScriptRow(row)">执行</el-button>
            <el-button size="small" text type="warning" @click="addToPlan(row)">加入方案</el-button>
            <el-button size="small" text type="danger" @click="deleteScriptModel(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && filteredScripts.length === 0" description="暂无脚本，可从执行记录中转换生成" />
    </el-card>

    <!-- 参数填写弹窗 -->
    <el-dialog v-model="showParamDialog" title="执行参数" width="640px">
      <template v-if="paramRow">
        <div v-if="inputParamKeys.length" style="background:var(--el-fill-color-lighter);padding:16px;border-radius:8px;margin-bottom:12px">
          <div style="font-size:13px;font-weight:600;margin-bottom:8px;color:var(--el-text-color-primary)">动态参数</div>
          <el-form :model="paramValues" label-width="auto" size="small">
            <el-form-item v-for="key in inputParamKeys" :key="key" :label="paramRow.script_data.parameters[key].label || key">
              <el-input v-model="paramValues[key]" :placeholder="paramRow.script_data.parameters[key].default" clearable @clear="paramValues[key] = paramRow.script_data.parameters[key].default || ''" />
            </el-form-item>
          </el-form>
        </div>
        <div v-if="assertParamKeys.length" style="background:#f0f9eb;padding:16px;border-radius:8px">
          <div style="font-size:13px;font-weight:600;margin-bottom:8px;color:var(--el-text-color-primary)">预期结果</div>
          <el-form :model="paramValues" label-width="auto" size="small">
            <el-form-item v-for="key in assertParamKeys" :key="key" :label="paramRow.script_data.parameters[key].label || key">
              <el-input v-model="paramValues[key]" :placeholder="paramRow.script_data.parameters[key].default" clearable @clear="paramValues[key] = paramRow.script_data.parameters[key].default || ''" />
            </el-form-item>
          </el-form>
        </div>
        <el-empty v-if="!paramKeys.length" description="无参数" :image-size="48" />
      </template>
      <template #footer>
        <el-button @click="showParamDialog = false">取消</el-button>
        <el-button type="primary" @click="confirmExecute" :loading="executing">确认执行</el-button>
      </template>
    </el-dialog>

    <!-- 加入方案选择弹窗 -->
    <el-dialog v-model="showPlanDialog" title="选择方案" width="500px">
      <el-table :data="availablePlans" v-loading="planLoading" size="small" highlight-current-row @current-change="selectPlanRow" ref="planTableRef">
        <el-table-column width="55">
          <template #default="{ row }"><el-radio v-model="selectedPlanId" :value="row.id">&nbsp;</el-radio></template>
        </el-table-column>
        <el-table-column prop="name" label="方案名称" min-width="200" />
        <el-table-column prop="project_name" label="项目" width="120" />
        <el-table-column prop="status" label="状态" width="80">
          <template #default="{ row }"><el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small">{{ row.status }}</el-tag></template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="showPlanDialog = false">取消</el-button>
        <el-button type="primary" :disabled="!selectedPlanId" @click="confirmAddToPlan">确认添加</el-button>
      </template>
    </el-dialog>

    <!-- 编辑脚本弹窗 -->
    <el-dialog v-model="showEditDialog" title="编辑脚本" width="600px">
      <el-form :model="editForm" label-width="80px" size="small">
        <el-form-item label="脚本名称"><el-input v-model="editForm.name" /></el-form-item>
        <el-form-item label="功能分组">
          <el-autocomplete v-model="editForm.feature_group" :fetch-suggestions="queryFeatureGroups" placeholder="输入或选择功能分组" clearable />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="editForm.status">
            <el-option label="草稿" value="draft" />
            <el-option label="活跃" value="active" />
            <el-option label="已归档" value="archived" />
          </el-select>
        </el-form-item>
        <el-form-item label="脚本数据">
          <el-input v-model="editForm.script_data_str" type="textarea" :rows="10" placeholder="JSON 格式脚本内容" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showEditDialog = false">取消</el-button>
        <el-button type="primary" @click="confirmEdit" :loading="editLoading">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  getScripts, getProjects, updateScript, deleteScript as deleteScriptApi,
  executeScript, getPlans, addPlanItem,
} from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'

const router = useRouter()

const scripts = ref([])
const projects = ref([])
const loading = ref(false)
const projectFilter = ref(null)

const showParamDialog = ref(false)
const paramRow = ref(null)
const paramValues = ref({})
const executing = ref(false)

const showPlanDialog = ref(false)
const availablePlans = ref([])
const planLoading = ref(false)
const selectedPlanId = ref(null)
let pendingScriptForPlan = null

const showEditDialog = ref(false)
const editForm = ref({ name: '', feature_group: '', status: 'active', script_data_str: '' })
const editLoading = ref(false)
let editingScriptId = null

const filteredScripts = computed(() => {
  if (!projectFilter.value) return scripts.value
  return scripts.value.filter(s => s.project === projectFilter.value)
})

const paramKeys = computed(() =>
  paramRow.value ? Object.keys(paramRow.value.script_data?.parameters || {}) : []
)
const inputParamKeys = computed(() =>
  paramKeys.value.filter(k => paramRow.value.script_data.parameters[k]?.group !== 'assertion')
)
const assertParamKeys = computed(() =>
  paramKeys.value.filter(k => paramRow.value.script_data.parameters[k]?.group === 'assertion')
)

const scriptStatusType = (s) => {
  const map = { active: 'success', draft: 'warning', archived: 'info' }
  return map[s] || 'info'
}
const scriptStatusLabel = (s) => {
  const map = { active: '活跃', draft: '草稿', archived: '已归档' }
  return map[s] || s
}

async function loadScripts() {
  loading.value = true
  try {
    const params = {}
    if (projectFilter.value) params.project = projectFilter.value
    const { data } = await getScripts(params)
    scripts.value = data.scripts || data.results || data
  } finally { loading.value = false }
}

async function loadProjects() {
  const { data } = await getProjects()
  projects.value = data.results || data
}

function editScript(row) {
  editingScriptId = row.id
  editForm.value = {
    name: row.name,
    feature_group: row.feature_group,
    status: row.status,
    script_data_str: JSON.stringify(row.script_data || {}, null, 2),
  }
  showEditDialog.value = true
}

async function confirmEdit() {
  editLoading.value = true
  try {
    let scriptData
    try { scriptData = JSON.parse(editForm.value.script_data_str) } catch { ElMessage.error('脚本数据不是有效的 JSON'); return }
    await updateScript(editingScriptId, {
      name: editForm.value.name, feature_group: editForm.value.feature_group,
      status: editForm.value.status, script_data: scriptData,
    })
    ElMessage.success('脚本已更新')
    showEditDialog.value = false
    await loadScripts()
  } catch (e) { ElMessage.error(e.response?.data?.error || '更新失败') } finally { editLoading.value = false }
}

function executeScriptRow(row) {
  paramRow.value = row
  const params = row.script_data?.parameters || {}
  paramValues.value = {}
  for (const [name, info] of Object.entries(params)) paramValues.value[name] = info.default || ''
  showParamDialog.value = true
}

async function confirmExecute() {
  if (!paramRow.value) return
  executing.value = true
  try {
    const overrides = {}
    for (const [k, v] of Object.entries(paramValues.value)) if (v) overrides[k] = v
    const { data } = await executeScript(paramRow.value.id, { parameter_overrides: overrides })
    showParamDialog.value = false
    ElMessage.success('脚本执行已启动')
    router.push(`/executions/${data.id}/observe`)
  } catch (e) { ElMessage.error(e.response?.data?.error || '执行失败') } finally { executing.value = false }
}

async function addToPlan(row) {
  pendingScriptForPlan = row
  selectedPlanId.value = null
  showPlanDialog.value = true
  planLoading.value = true
  try {
    // Filter plans by the script's project
    const params = {}
    if (row.project) params.project = row.project
    const { data } = await getPlans(params)
    availablePlans.value = data.plans || data.results || data
  } finally { planLoading.value = false }
}

function selectPlanRow(row) { if (row) selectedPlanId.value = row.id }

async function confirmAddToPlan() {
  if (!selectedPlanId.value || !pendingScriptForPlan) return
  try {
    await addPlanItem(selectedPlanId.value, { item_type: 'script', script: pendingScriptForPlan.id })
    ElMessage.success('已添加到方案')
    showPlanDialog.value = false
  } catch (e) { ElMessage.error(e.response?.data?.error || '添加失败') }
}

async function deleteScriptModel(row) {
  try {
    await ElMessageBox.confirm(`确定删除脚本「${row.name}」？`, '确认删除')
    await deleteScriptApi(row.id)
    scripts.value = scripts.value.filter(s => s.id !== row.id)
    ElMessage.success('已删除')
  } catch { /* cancelled */ }
}

function queryFeatureGroups(query, cb) {
  const groups = [...new Set(scripts.value.map(s => s.feature_group).filter(Boolean))]
  cb(groups.filter(g => g.includes(query)).map(g => ({ value: g })))
}

onMounted(async () => { await Promise.all([loadScripts(), loadProjects()]) })
</script>

<style scoped>
.card-header { display: flex; justify-content: space-between; align-items: center; }
</style>
