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

      <div v-loading="loading">
        <!-- 未分组脚本：直接平铺展示，无需折叠 -->
        <el-table
          v-if="ungroupedScripts.length"
          :data="ungroupedScripts"
          style="width: 100%"
          size="small"
        >
          <el-table-column prop="id" label="ID" width="60" />
          <el-table-column prop="project_name" label="项目" width="130" />
          <el-table-column prop="name" label="脚本名称" min-width="180" show-overflow-tooltip />
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

        <!-- 分组脚本：el-collapse 折叠面板 -->
        <el-collapse v-model="expandedGroups" v-if="groupedScripts.length" :class="{ 'has-top-spacing': ungroupedScripts.length }">
          <el-collapse-item
            v-for="group in groupedScripts"
            :key="group.name"
            :name="group.name"
          >
            <template #title>
              <div class="group-header" @click.stop>
                <div class="group-header-left">
                  <el-icon style="margin-right: 6px"><Folder /></el-icon>
                  <span class="group-name">{{ group.name }}</span>
                  <el-tag size="small" type="info" style="margin-left: 8px">{{ group.count }} 条</el-tag>
                  <el-tag v-if="group.active" size="small" type="success" style="margin-left: 4px">{{ group.active }} 活跃</el-tag>
                  <el-tag v-if="group.draft" size="small" type="warning" style="margin-left: 4px">{{ group.draft }} 草稿</el-tag>
                  <el-tag v-if="group.archived" size="small" type="info" style="margin-left: 4px">{{ group.archived }} 已归档</el-tag>
                </div>
              </div>
            </template>
            <el-table :data="group.scripts" style="width: 100%" size="small">
              <el-table-column prop="id" label="ID" width="60" />
              <el-table-column prop="project_name" label="项目" width="130" />
              <el-table-column prop="name" label="脚本名称" min-width="180" show-overflow-tooltip />
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
          </el-collapse-item>
        </el-collapse>

        <el-empty v-if="!loading && ungroupedScripts.length === 0 && groupedScripts.length === 0" description="暂无脚本，可从执行记录中转换生成" />
      </div>
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

  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Folder } from '@element-plus/icons-vue'
import {
  getScripts, getProjects, deleteScript as deleteScriptApi,
  executeScript, getPlans, addPlanItem,
} from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'

const router = useRouter()

const scripts = ref([])
const projects = ref([])
const loading = ref(false)
const projectFilter = ref(null)
const expandedGroups = ref([])

const showParamDialog = ref(false)
const paramRow = ref(null)
const paramValues = ref({})
const executing = ref(false)

const showPlanDialog = ref(false)
const availablePlans = ref([])
const planLoading = ref(false)
const selectedPlanId = ref(null)
let pendingScriptForPlan = null

// 按项目筛选后的完整列表
const projectFilteredScripts = computed(() => {
  if (!projectFilter.value) return scripts.value
  return scripts.value.filter(s => s.project === projectFilter.value)
})

// 未分组脚本（feature_group 为空）
const ungroupedScripts = computed(() => {
  return projectFilteredScripts.value.filter(s => !s.feature_group)
})

// 按功能点分组的脚本
const groupedScripts = computed(() => {
  const groups = {}
  const order = []

  for (const script of projectFilteredScripts.value) {
    if (!script.feature_group) continue
    const groupName = script.feature_group

    if (!groups[groupName]) {
      groups[groupName] = { name: groupName, scripts: [], count: 0, active: 0, draft: 0, archived: 0 }
      order.push(groupName)
    }
    groups[groupName].scripts.push(script)
    groups[groupName].count++
    if (script.status === 'active') groups[groupName].active++
    else if (script.status === 'draft') groups[groupName].draft++
    else if (script.status === 'archived') groups[groupName].archived++
  }

  return order.map(name => groups[name])
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

    // 自动展开所有分组
    expandedGroups.value = groupedScripts.value.map(g => g.name)
  } finally { loading.value = false }
}

async function loadProjects() {
  const { data } = await getProjects()
  projects.value = data.results || data
}

function editScript(row) {
  router.push(`/scripts/${row.id}`)
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

onMounted(async () => { await Promise.all([loadScripts(), loadProjects()]) })
</script>

<style scoped>
.card-header { display: flex; justify-content: space-between; align-items: center; }
.group-header { display: flex; justify-content: space-between; align-items: center; width: 100%; padding-right: 16px; }
.group-header-left { display: flex; align-items: center; }
.group-name { font-weight: 600; font-size: 14px; }
.has-top-spacing { margin-top: 16px; }
:deep(.el-collapse-item__header) { height: auto !important; min-height: 48px; padding: 8px 0; line-height: 1.5; }
</style>
