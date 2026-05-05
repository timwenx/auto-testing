<template>
  <div v-loading="loading">
    <!-- 顶部标题栏 -->
    <div class="detail-header">
      <el-page-header @back="router.push('/scripts')">
        <template #content>
          <span class="header-title">{{ script?.name || '脚本详情' }}</span>
          <el-tag v-if="script" :type="scriptStatusType(script.status)" size="small" class="header-tag">
            {{ scriptStatusLabel(script.status) }}
          </el-tag>
        </template>
      </el-page-header>
      <div class="header-actions">
        <el-button size="small" type="primary" @click="handleSave" :disabled="!script" :loading="saving">
          保存
        </el-button>
        <el-button size="small" type="success" @click="handleExecute" :disabled="!script" :loading="executing">
          执行
        </el-button>
        <el-button size="small" type="danger" @click="handleDelete" :disabled="!script">
          删除
        </el-button>
      </div>
    </div>

    <div v-if="script" class="detail-body">
      <!-- 基本信息卡片 -->
      <el-card class="section-card">
        <template #header><span>基本信息</span></template>
        <el-form :model="form" label-width="80px" size="small">
          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="脚本名称">
                <el-input v-model="form.name" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="功能分组">
                <el-autocomplete v-model="form.feature_group" :fetch-suggestions="queryFeatureGroups" placeholder="输入或选择功能分组" clearable style="width: 100%" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="状态">
                <el-select v-model="form.status">
                  <el-option label="草稿" value="draft" />
                  <el-option label="活跃" value="active" />
                  <el-option label="已归档" value="archived" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-descriptions :column="2" size="small">
                <el-descriptions-item label="版本">{{ script.version }}</el-descriptions-item>
                <el-descriptions-item label="更新时间">{{ script.updated_at }}</el-descriptions-item>
              </el-descriptions>
            </el-col>
          </el-row>
        </el-form>
      </el-card>

      <!-- 参数面板 -->
      <el-card v-if="inputParamKeys.length > 0 || assertParamKeys.length > 0" class="section-card">
        <template #header><span>参数 ({{ allParamKeys.length }})</span></template>
        <div v-if="inputParamKeys.length > 0" class="params-group">
          <div class="params-group-title">动态参数</div>
          <el-form :model="paramValues" label-width="auto" size="small">
            <el-row :gutter="16">
              <el-col :span="12" v-for="key in inputParamKeys" :key="key">
                <el-form-item :label="scriptData.parameters[key].label || key">
                  <div class="param-input-row">
                    <el-input v-model="paramValues[key]" :placeholder="scriptData.parameters[key].default" clearable
                      @clear="paramValues[key] = scriptData.parameters[key].default || ''" />
                    <el-button size="small" text @click="paramValues[key] = scriptData.parameters[key].default">重置</el-button>
                  </div>
                </el-form-item>
              </el-col>
            </el-row>
          </el-form>
        </div>
        <div v-if="assertParamKeys.length > 0" class="params-group">
          <div class="params-group-title">预期结果</div>
          <el-form :model="paramValues" label-width="auto" size="small">
            <el-row :gutter="16">
              <el-col :span="12" v-for="key in assertParamKeys" :key="key">
                <el-form-item :label="scriptData.parameters[key].label || key">
                  <div class="param-input-row">
                    <el-input v-model="paramValues[key]" :placeholder="scriptData.parameters[key].default" clearable
                      @clear="paramValues[key] = scriptData.parameters[key].default || ''" />
                    <el-button size="small" text @click="paramValues[key] = scriptData.parameters[key].default">重置</el-button>
                  </div>
                </el-form-item>
              </el-col>
            </el-row>
          </el-form>
        </div>
      </el-card>

      <!-- 步骤列表 -->
      <el-card class="section-card">
        <template #header>
          <div style="display: flex; align-items: center; justify-content: space-between">
            <span>执行步骤 ({{ steps.length }})</span>
            <el-switch v-model="showAdvanced" active-text="高级模式" inactive-text="" size="small" />
          </div>
        </template>
        <el-table ref="stepsTableRef" :data="steps" size="small" stripe border row-key="step_num">
          <el-table-column width="40" align="center">
            <template #default><el-icon class="drag-handle" style="cursor: grab; color: #c0c4cc"><Rank /></el-icon></template>
          </el-table-column>
          <el-table-column type="expand" v-if="showAdvanced">
            <template #default="{ row }">
              <div style="padding: 8px 16px">
                <pre style="font-size: 12px; background: var(--el-fill-color-darker); padding: 8px 12px; border-radius: 4px; margin: 0; max-height: 200px; overflow-y: auto">{{ JSON.stringify(row.inputs, null, 2) }}</pre>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="step_num" label="#" width="50" />
          <el-table-column label="操作" width="120">
            <template #default="{ row }">
              <el-tag size="small" :type="toolTagType(row.tool_name)">{{ toolLabel(row.tool_name) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="描述" min-width="200">
            <template #default="{ row }">{{ row.description }}</template>
          </el-table-column>
          <el-table-column label="参数" min-width="150" v-if="!showAdvanced">
            <template #default="{ row }">
              <template v-if="row.tool_name === 'browser_assert'">
                <el-tag size="small" type="success">{{ row.inputs?.operator }} {{ row.inputs?.expected }}</el-tag>
              </template>
              <template v-else>
                <template v-for="pName in (row.parameters || [])" :key="pName">
                  <el-tag size="small" type="warning" style="margin-right: 4px">{{ scriptData.parameters?.[pName]?.label || pName }}</el-tag>
                </template>
                <span v-if="!row.parameters?.length" style="color: var(--el-text-color-placeholder)">-</span>
              </template>
            </template>
          </el-table-column>
          <el-table-column label="启用" width="70">
            <template #default="{ row }">
              <el-switch v-model="row.enabled" size="small" />
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <!-- JSON 编辑 (高级) -->
      <el-card v-if="showAdvanced" class="section-card">
        <template #header><span>原始 JSON</span></template>
        <el-input v-model="scriptDataStr" type="textarea" :rows="12" placeholder="JSON 格式脚本内容" />
      </el-card>
    </div>

    <!-- 执行参数弹窗 -->
    <el-dialog v-model="showExecDialog" title="执行参数" width="640px">
      <div v-if="inputExecKeys.length" style="background: var(--el-fill-color-lighter); padding: 16px; border-radius: 8px; margin-bottom: 12px">
        <div style="font-size: 13px; font-weight: 600; margin-bottom: 8px; color: var(--el-text-color-primary)">动态参数</div>
        <el-form :model="execParamValues" label-width="auto" size="small">
          <el-form-item v-for="key in inputExecKeys" :key="key" :label="scriptData.parameters[key].label || key">
            <el-input v-model="execParamValues[key]" :placeholder="scriptData.parameters[key].default" clearable
              @clear="execParamValues[key] = scriptData.parameters[key].default || ''" />
          </el-form-item>
        </el-form>
      </div>
      <div v-if="assertExecKeys.length" style="background: #f0f9eb; padding: 16px; border-radius: 8px">
        <div style="font-size: 13px; font-weight: 600; margin-bottom: 8px; color: var(--el-text-color-primary)">预期结果</div>
        <el-form :model="execParamValues" label-width="auto" size="small">
          <el-form-item v-for="key in assertExecKeys" :key="key" :label="scriptData.parameters[key].label || key">
            <el-input v-model="execParamValues[key]" :placeholder="scriptData.parameters[key].default" clearable
              @clear="execParamValues[key] = scriptData.parameters[key].default || ''" />
          </el-form-item>
        </el-form>
      </div>
      <el-empty v-if="!allParamKeys.length" description="无参数" :image-size="48" />
      <template #footer>
        <el-button @click="showExecDialog = false">取消</el-button>
        <el-button type="primary" @click="confirmExecute" :loading="executing">确认执行</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Rank } from '@element-plus/icons-vue'
import { getScript, updateScript, deleteScript as deleteScriptApi, executeScript, getScripts } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useTableSortable } from '../composables/useTableSortable'

const route = useRoute()
const router = useRouter()
const scriptId = computed(() => parseInt(route.params.id))

const script = ref(null)
const loading = ref(false)
const saving = ref(false)
const executing = ref(false)
const showAdvanced = ref(false)
const showExecDialog = ref(false)
const stepsTableRef = ref(null)

const { initSortable: initStepsSortable, destroy: destroyStepsSortable } = useTableSortable(
  stepsTableRef,
  (oldIndex, newIndex) => {
    const [item] = steps.value.splice(oldIndex, 1)
    steps.value.splice(newIndex, 0, item)
    steps.value.forEach((s, i) => { s.step_num = i + 1 })
  }
)

const form = ref({ name: '', feature_group: '', status: 'active' })
const scriptData = ref({ parameters: {}, steps: [] })
const scriptDataStr = ref('{}')
const paramValues = reactive({})
const execParamValues = reactive({})
const featureGroupOptions = ref([])

const allParamKeys = computed(() => Object.keys(scriptData.value.parameters || {}))
const inputParamKeys = computed(() => allParamKeys.value.filter(k => scriptData.value.parameters[k]?.group !== 'assertion'))
const assertParamKeys = computed(() => allParamKeys.value.filter(k => scriptData.value.parameters[k]?.group === 'assertion'))
const inputExecKeys = computed(() => inputParamKeys.value)
const assertExecKeys = computed(() => assertParamKeys.value)
const steps = computed(() => scriptData.value.steps || [])

const scriptStatusType = (s) => ({ active: 'success', draft: 'warning', archived: 'info' }[s] || 'info')
const scriptStatusLabel = (s) => ({ active: '活跃', draft: '草稿', archived: '已归档' }[s] || s)

function toolLabel(name) {
  const map = { browser_navigate: '导航', browser_click: '点击', browser_fill: '填写', browser_fill_form: '表单', browser_select: '选择', browser_press_key: '按键', browser_batch_action: '批量', browser_assert: '断言' }
  return map[name] || name
}

function toolTagType(name) {
  const map = { browser_navigate: 'primary', browser_click: 'success', browser_fill: 'warning', browser_fill_form: 'warning', browser_select: 'info', browser_press_key: '', browser_batch_action: 'danger', browser_assert: 'success' }
  return map[name] || 'info'
}

async function loadScript() {
  loading.value = true
  try {
    const { data } = await getScript(scriptId.value)
    script.value = data
    form.value = { name: data.name, feature_group: data.feature_group || '', status: data.status }
    scriptData.value = data.script_data || { parameters: {}, steps: [] }
    scriptDataStr.value = JSON.stringify(scriptData.value, null, 2)
    initParamValues()
  } catch (e) {
    ElMessage.error('加载脚本失败')
    router.push('/scripts')
  } finally {
    loading.value = false
  }
}

function initParamValues() {
  for (const [key, param] of Object.entries(scriptData.value.parameters || {})) {
    paramValues[key] = param.default || ''
  }
}

async function loadFeatureGroups() {
  try {
    const { data } = await getScripts()
    const list = data.scripts || data.results || data
    featureGroupOptions.value = [...new Set(list.map(s => s.feature_group).filter(Boolean))]
  } catch { /* ignore */ }
}

function queryFeatureGroups(query, cb) {
  cb(featureGroupOptions.value.filter(g => g.includes(query)).map(g => ({ value: g })))
}

async function handleSave() {
  saving.value = true
  try {
    // 高级模式下先同步 JSON 编辑器内容
    if (showAdvanced.value) {
      try {
        scriptData.value = JSON.parse(scriptDataStr.value)
      } catch {
        ElMessage.error('JSON 格式错误，请检查')
        return
      }
    }
    await updateScript(scriptId.value, {
      name: form.value.name,
      feature_group: form.value.feature_group,
      status: form.value.status,
      script_data: scriptData.value,
    })
    ElMessage.success('保存成功')
    await loadScript()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '保存失败')
  } finally {
    saving.value = false
  }
}

async function handleDelete() {
  try {
    await ElMessageBox.confirm(`确定删除脚本「${script.value.name}」？`, '确认删除')
    await deleteScriptApi(scriptId.value)
    ElMessage.success('已删除')
    router.push('/scripts')
  } catch { /* cancelled */ }
}

function handleExecute() {
  for (const [key, param] of Object.entries(scriptData.value.parameters || {})) {
    execParamValues[key] = param.default || ''
  }
  showExecDialog.value = true
}

async function confirmExecute() {
  executing.value = true
  try {
    const overrides = {}
    for (const [k, v] of Object.entries(execParamValues)) if (v) overrides[k] = v
    const { data } = await executeScript(scriptId.value, { parameter_overrides: overrides })
    showExecDialog.value = false
    ElMessage.success('脚本执行已启动')
    router.push(`/executions/${data.id}/observe`)
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '执行失败')
  } finally {
    executing.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadScript(), loadFeatureGroups()])
  initStepsSortable()
})

onUnmounted(() => {
  destroyStepsSortable()
})
</script>

<style scoped>
.detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.header-title {
  font-size: 16px;
  font-weight: 600;
}

.header-tag {
  margin-left: 12px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.detail-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.section-card :deep(.el-card__header) {
  padding: 12px 20px;
  font-weight: 600;
  font-size: 14px;
}

.params-group {
  margin-bottom: 16px;
}

.params-group:last-child {
  margin-bottom: 0;
}

.params-group-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
  color: var(--el-text-color-primary);
}

.param-input-row {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}

.param-input-row .el-input {
  flex: 1;
}
</style>
