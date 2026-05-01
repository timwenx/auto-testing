<template>
  <div class="script-editor">
    <!-- 顶部标题栏 -->
    <div class="editor-header">
      <el-page-header @back="goBack">
        <template #content>
          <span class="header-title">脚本编辑器</span>
          <el-tag v-if="script" size="small" type="success" class="header-tag">
            {{ script.steps?.length || 0 }} 步 / {{ paramCount }} 个参数
          </el-tag>
        </template>
      </el-page-header>
      <div class="header-actions">
        <el-button size="small" @click="loadScript" :loading="loading">
          <el-icon><Refresh /></el-icon> 刷新
        </el-button>
        <el-button size="small" type="primary" @click="handleSave" :disabled="!script || saving" :loading="saving">
          <el-icon><Check /></el-icon> 保存
        </el-button>
        <el-button size="small" type="success" @click="handleExecute" :disabled="!script" :loading="executing">
          <el-icon><VideoPlay /></el-icon> 执行回放
        </el-button>
      </div>
    </div>

    <!-- 加载中 -->
    <div v-if="loading && !script" class="editor-loading">
      <el-icon :size="32" class="is-loading"><Loading /></el-icon>
      <span>{{ converting ? '正在转换脚本...' : '加载中...' }}</span>
    </div>

    <!-- 未转换状态 -->
    <div v-else-if="!script && !loading" class="editor-empty">
      <el-empty description="尚未生成回放脚本">
        <el-button type="primary" @click="handleConvert" :loading="converting">从执行记录生成脚本</el-button>
      </el-empty>
    </div>

    <!-- 编辑器主体 -->
    <div v-else-if="script" class="editor-body">
      <!-- 动态参数面板 -->
      <div class="params-section" v-if="inputParamKeys.length > 0">
        <div class="section-title">
          <el-icon><Setting /></el-icon>
          <span>动态参数</span>
          <el-tag size="small" type="info">{{ inputParamKeys.length }} 个</el-tag>
        </div>
        <el-form :model="paramValues" label-width="auto" size="small" class="params-form">
          <el-row :gutter="16">
            <el-col :span="12" v-for="key in inputParamKeys" :key="key">
              <el-form-item :label="script.parameters[key].label || key">
                <div class="param-input-row">
                  <el-input
                    v-model="paramValues[key]"
                    :placeholder="script.parameters[key].default"
                    clearable
                    @clear="paramValues[key] = script.parameters[key].default"
                  />
                  <el-button
                    size="small" text
                    @click="paramValues[key] = script.parameters[key].default"
                  >重置</el-button>
                </div>
              </el-form-item>
            </el-col>
          </el-row>
        </el-form>
      </div>

      <!-- 预期结果参数面板 -->
      <div class="params-section" v-if="assertParamKeys.length > 0">
        <div class="section-title">
          <el-icon><CircleCheck /></el-icon>
          <span>预期结果</span>
          <el-tag size="small" type="success">{{ assertParamKeys.length }} 个</el-tag>
        </div>
        <el-form :model="paramValues" label-width="auto" size="small" class="params-form">
          <el-row :gutter="16">
            <el-col :span="12" v-for="key in assertParamKeys" :key="key">
              <el-form-item :label="script.parameters[key].label || key">
                <div class="param-input-row">
                  <el-input
                    v-model="paramValues[key]"
                    :placeholder="script.parameters[key].default"
                    clearable
                    @clear="paramValues[key] = script.parameters[key].default"
                  />
                  <el-button
                    size="small" text
                    @click="paramValues[key] = script.parameters[key].default"
                  >重置</el-button>
                </div>
              </el-form-item>
            </el-col>
          </el-row>
        </el-form>
      </div>

      <!-- 步骤列表 -->
      <div class="steps-section">
        <div class="section-title">
          <el-icon><List /></el-icon>
          <span>执行步骤</span>
          <el-switch
            v-model="showAdvanced"
            active-text="高级模式"
            inactive-text=""
            size="small"
            style="margin-left: auto;"
          />
        </div>
        <el-table :data="script.steps" size="small" stripe border row-key="step_num">
          <el-table-column type="expand" v-if="showAdvanced">
            <template #default="{ row }">
              <div class="step-expand">
                <pre class="step-json">{{ JSON.stringify(row.inputs, null, 2) }}</pre>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="step_num" label="#" width="50" />
          <el-table-column label="操作" width="120">
            <template #default="{ row }">
              <el-tag size="small" :type="toolTagType(row.tool_name)">
                {{ toolLabel(row.tool_name) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="描述" min-width="200">
            <template #default="{ row }">
              {{ row.description }}
            </template>
          </el-table-column>
          <el-table-column label="参数" min-width="150" v-if="!showAdvanced">
            <template #default="{ row }">
              <template v-if="row.tool_name === 'browser_assert'">
                <el-tag size="small" type="success" class="param-tag">
                  {{ row.inputs?.operator }} {{ row.inputs?.expected }}
                </el-tag>
              </template>
              <template v-else>
                <template v-for="pName in (row.parameters || [])" :key="pName">
                  <el-tag size="small" type="warning" class="param-tag">
                    {{ script.parameters[pName]?.label || pName }}
                  </el-tag>
                </template>
                <span v-if="!row.parameters?.length" class="no-params">-</span>
              </template>
            </template>
          </el-table-column>
          <el-table-column label="排序" width="80">
            <template #default="{ $index }">
              <el-button size="small" text :disabled="$index === 0" @click="moveStepUp($index)">&#9650;</el-button>
              <el-button size="small" text :disabled="$index === script.steps.length - 1" @click="moveStepDown($index)">&#9660;</el-button>
            </template>
          </el-table-column>
          <el-table-column label="启用" width="70">
            <template #default="{ row }">
              <el-switch v-model="row.enabled" size="small" />
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  getReplayScript, convertToScript, updateReplayScript, replayExecute,
} from '../api'
import { Refresh, Check, VideoPlay, Setting, List, Loading, CircleCheck } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const executionId = computed(() => parseInt(route.params.id))

const script = ref(null)
const loading = ref(false)
const converting = ref(false)
const saving = ref(false)
const executing = ref(false)
const showAdvanced = ref(false)
const paramValues = reactive({})

const allParamKeys = computed(() => Object.keys(script.value?.parameters || {}))
const inputParamKeys = computed(() => allParamKeys.value.filter(k => script.value.parameters[k]?.group !== 'assertion'))
const assertParamKeys = computed(() => allParamKeys.value.filter(k => script.value.parameters[k]?.group === 'assertion'))
const paramCount = computed(() => allParamKeys.value.length)

function toolLabel(name) {
  const map = {
    browser_navigate: '导航', browser_click: '点击', browser_fill: '填写',
    browser_fill_form: '表单', browser_select: '选择', browser_press_key: '按键',
    browser_batch_action: '批量', browser_assert: '断言',
  }
  return map[name] || name
}

function toolTagType(name) {
  const map = {
    browser_navigate: 'primary', browser_click: 'success', browser_fill: 'warning',
    browser_fill_form: 'warning', browser_select: 'info', browser_press_key: '',
    browser_batch_action: 'danger', browser_assert: 'success',
  }
  return map[name] || 'info'
}

async function loadScript() {
  loading.value = true
  try {
    const { data } = await getReplayScript(executionId.value)
    script.value = data
    initParamValues()
  } catch (e) {
    if (e.response?.status !== 404) {
      console.error('Failed to load script:', e)
    }
  } finally {
    loading.value = false
  }
}

function initParamValues() {
  if (!script.value?.parameters) return
  for (const [key, param] of Object.entries(script.value.parameters)) {
    paramValues[key] = param.default || ''
  }
}

async function handleConvert() {
  converting.value = true
  loading.value = true
  try {
    const { data } = await convertToScript(executionId.value)
    script.value = data
    initParamValues()
  } catch (e) {
    console.error('Convert failed:', e)
    ElMessage.error(e.response?.data?.error || '转换失败')
  } finally {
    converting.value = false
    loading.value = false
  }
}

async function handleSave() {
  if (!script.value) return
  saving.value = true
  try {
    // 将当前 paramValues 写回 script 的 parameter defaults
    for (const [key, val] of Object.entries(paramValues)) {
      if (script.value.parameters[key]) {
        script.value.parameters[key].default = val
      }
    }
    await updateReplayScript(executionId.value, {
      parameters: script.value.parameters,
      steps: script.value.steps,
    })
    ElMessage.success('保存成功')
  } catch (e) {
    console.error('Save failed:', e)
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

async function handleExecute() {
  if (!script.value) return
  executing.value = true
  try {
    const overrides = {}
    for (const [key, val] of Object.entries(paramValues)) {
      if (val && val !== script.value.parameters[key]?.default) {
        overrides[key] = val
      }
    }
    const { data } = await replayExecute(executionId.value, {
      parameter_overrides: overrides,
    })
    ElMessage.success('回放已启动')
    router.push(`/executions/${data.id}/observe`)
  } catch (e) {
    console.error('Execute failed:', e)
    ElMessage.error(e.response?.data?.error || '执行失败')
  } finally {
    executing.value = false
  }
}

function goBack() {
  router.back()
}

function moveStepUp(index) {
  if (index <= 0) return
  const steps = script.value.steps
  const [item] = steps.splice(index, 1)
  steps.splice(index - 1, 0, item)
  renumberSteps()
}

function moveStepDown(index) {
  const steps = script.value.steps
  if (index >= steps.length - 1) return
  const [item] = steps.splice(index, 1)
  steps.splice(index + 1, 0, item)
  renumberSteps()
}

function renumberSteps() {
  script.value.steps.forEach((s, i) => { s.step_num = i + 1 })
}

onMounted(() => {
  loadScript()
})
</script>

<style scoped>
.script-editor {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--el-bg-color);
}

.editor-header {
  padding: 12px 20px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  background: var(--el-bg-color);
  display: flex;
  align-items: center;
  justify-content: space-between;
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

.editor-loading,
.editor-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--el-text-color-placeholder);
  font-size: 14px;
}

.editor-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
}

.params-section,
.steps-section {
  margin-bottom: 20px;
}

.section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 12px;
  color: var(--el-text-color-primary);
}

.params-form {
  background: var(--el-fill-color-lighter);
  padding: 16px;
  border-radius: 8px;
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

.param-tag {
  margin-right: 4px;
  margin-bottom: 2px;
}

.no-params {
  color: var(--el-text-color-placeholder);
}

.step-expand {
  padding: 8px 16px;
}

.step-json {
  font-size: 12px;
  background: var(--el-fill-color-darker);
  padding: 8px 12px;
  border-radius: 4px;
  margin: 0;
  max-height: 200px;
  overflow-y: auto;
}
</style>
