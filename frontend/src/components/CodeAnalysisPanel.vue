<template>
  <el-card>
    <template #header>
      <div class="card-header">
        <div style="display: flex; align-items: center; gap: 8px">
          <el-button size="small" @click="$emit('back')">返回上一步</el-button>
          <el-button
            v-if="!analyzing && analysis?.status === 'completed'"
            size="small"
            @click="confirmRestart"
          >
            重新分析
          </el-button>
          <el-button
            v-if="analysis?.status === 'completed' && analysis.discovered_items?.length"
            size="small"
            @click="toggleSelectAll"
          >
            {{ totalSelected === allItems.length ? '取消全选' : '全选' }}
          </el-button>
          <span v-if="analysis?.status === 'completed' && analysis.discovered_items?.length" style="color: #606266; font-size: 13px">
            已选 <strong>{{ totalSelected }}</strong>/{{ allItems.length }}
          </span>
        </div>
        <div style="display: flex; gap: 8px">
          <el-button
            v-if="!analyzing && !analysis"
            type="primary"
            size="small"
            :disabled="!projectId"
            @click="startAnalysis"
          >
            开始分析
          </el-button>
          <el-button
            v-if="analysis?.status === 'completed' && analysis.discovered_items?.length"
            type="primary"
            size="small"
            :disabled="totalSelected === 0"
            @click="handleNext"
          >
            下一步：生成用例
          </el-button>
        </div>
      </div>
    </template>

    <!-- 分析中 -->
    <div v-if="analyzing" style="text-align: center; padding: 40px 0">
      <!-- 正常进度 -->
      <template v-if="!isStuck">
        <el-icon class="is-loading" style="font-size: 32px; color: #409eff"><Loading /></el-icon>
        <p style="margin-top: 12px; color: #606266; font-size: 15px">正在分析仓库代码，请稍候...</p>
        <p style="color: #909399; font-size: 13px; margin-top: 4px">
          已用时 <strong>{{ formattedElapsed }}</strong>
        </p>
        <p style="color: #909399; font-size: 12px; margin-top: 8px">系统将通过 AI 识别功能模块，扫描路由、页面元素和 API 参数</p>
      </template>

      <!-- 卡住状态 -->
      <template v-else>
        <el-icon style="font-size: 32px; color: #e6a23c"><WarningFilled /></el-icon>
        <p style="margin-top: 12px; color: #e6a23c; font-size: 15px; font-weight: 600">
          分析进程似乎已中断
        </p>
        <p style="color: #909399; font-size: 13px; margin-top: 4px">
          已用时 {{ formattedElapsed }}，但服务端心跳已断开超过 30 秒
        </p>
        <p style="color: #909399; font-size: 12px; margin-top: 8px">
          这通常是因为服务器重启或分析进程异常终止
        </p>
        <div style="margin-top: 20px">
          <el-button type="warning" @click="handleResetAndRetry">返回重试</el-button>
        </div>
      </template>
    </div>

    <!-- 分析失败 -->
    <el-result
      v-else-if="analysis?.status === 'failed'"
      icon="error"
      title="分析失败"
      :sub-title="analysis.analysis_log?.slice(0, 200) || '请检查仓库配置后重试'"
    >
      <template #extra>
        <el-button type="primary" @click="confirmRestart">重新分析</el-button>
      </template>
    </el-result>

    <!-- 分析完成 — 按功能点分组展示 -->
    <div v-else-if="analysis?.status === 'completed' && analysis.discovered_items?.length">
      <el-collapse v-model="expandedGroups">
        <el-collapse-item
          v-for="group in featureGroups"
          :key="group.name"
          :name="group.name"
        >
          <template #title>
            <div class="group-header" @click.stop="toggleCollapse(group.name)">
              <el-checkbox
                :model-value="getGroupCheckState(group.name)"
                :indeterminate="getGroupCheckState(group.name) === 'indeterminate'"
                @change="(val) => toggleGroup(group.name, val)"
                @click.stop
              />
              <span class="group-name" @click.stop="toggleCollapse(group.name)">{{ group.name }}</span>
              <el-tag size="small" type="info" style="margin-left: 8px">
                {{ group.items.length }} 项
              </el-tag>
              <span
                v-if="group.description"
                class="group-desc"
              >
                {{ group.description }}
              </span>
              <span class="group-selected-count">
                {{ getGroupSelectedCount(group.name) }}/{{ group.items.length }} 已选
              </span>
            </div>
          </template>

          <el-table
            :data="group.items"
            style="width: 100%"
            size="small"
            :row-key="itemKey"
          >
            <el-table-column type="expand">
              <template #default="{ row }">
                <div style="padding: 8px 16px 16px 50px">
                  <!-- 页面元素 -->
                  <template v-if="row.type === 'page' && row.elements && row.elements.length > 0">
                    <div style="font-size: 13px; color: #606266; margin-bottom: 8px; font-weight: 600">
                      页面元素 ({{ row.elements.length }})
                    </div>
                    <el-table :data="row.elements" size="small" border style="margin-bottom: 12px">
                      <el-table-column prop="selector" label="Selector" min-width="160">
                        <template #default="{ row: elem }">
                          <code style="font-size: 12px; background: #f5f7fa; padding: 2px 6px; border-radius: 3px">
                            {{ elem.selector }}
                          </code>
                        </template>
                      </el-table-column>
                      <el-table-column prop="type" label="类型" width="90">
                        <template #default="{ row: elem }">
                          <el-tag size="small" :type="elemTypeTag(elem.type)">{{ elem.type }}</el-tag>
                        </template>
                      </el-table-column>
                      <el-table-column prop="label" label="标签" min-width="120" />
                      <el-table-column prop="description" label="说明" min-width="150">
                        <template #default="{ row: elem }">
                          <span style="color: #909399">{{ elem.description || '-' }}</span>
                        </template>
                      </el-table-column>
                    </el-table>
                  </template>
                  <!-- API 请求参数 -->
                  <template v-if="row.type === 'api' && row.params && row.params.length > 0">
                    <div style="font-size: 13px; color: #606266; margin-bottom: 8px; font-weight: 600">
                      请求参数 ({{ row.params.length }})
                    </div>
                    <el-table :data="row.params" size="small" border style="margin-bottom: 12px">
                      <el-table-column prop="name" label="参数名" min-width="120">
                        <template #default="{ row: param }">
                          <code style="font-size: 12px; background: #f5f7fa; padding: 2px 6px; border-radius: 3px">
                            {{ param.name }}
                          </code>
                        </template>
                      </el-table-column>
                      <el-table-column prop="in" label="位置" width="80">
                        <template #default="{ row: param }">
                          <el-tag size="small" :type="paramInTag(param.in)">{{ param.in }}</el-tag>
                        </template>
                      </el-table-column>
                      <el-table-column prop="type" label="类型" width="90" />
                      <el-table-column label="必填" width="60" align="center">
                        <template #default="{ row: param }">
                          <el-tag v-if="param.required" size="small" type="danger">是</el-tag>
                          <span v-else style="color: #c0c4cc">否</span>
                        </template>
                      </el-table-column>
                      <el-table-column prop="description" label="说明" min-width="150">
                        <template #default="{ row: param }">
                          <span style="color: #909399">{{ param.description || '-' }}</span>
                        </template>
                      </el-table-column>
                    </el-table>
                  </template>
                  <!-- API 响应字段 -->
                  <template v-if="row.type === 'api' && row.response_fields && row.response_fields.length > 0">
                    <div style="font-size: 13px; color: #606266; margin-bottom: 8px; font-weight: 600">
                      响应字段 ({{ row.response_fields.length }})
                    </div>
                    <el-table :data="row.response_fields" size="small" border style="margin-bottom: 12px">
                      <el-table-column prop="name" label="字段名" min-width="120">
                        <template #default="{ row: field }">
                          <code style="font-size: 12px; background: #f5f7fa; padding: 2px 6px; border-radius: 3px">
                            {{ field.name }}
                          </code>
                        </template>
                      </el-table-column>
                      <el-table-column prop="type" label="类型" width="100" />
                      <el-table-column prop="description" label="说明" min-width="150">
                        <template #default="{ row: field }">
                          <span style="color: #909399">{{ field.description || '-' }}</span>
                        </template>
                      </el-table-column>
                    </el-table>
                  </template>
                  <div
                    v-if="row.type === 'page' && (!row.elements || row.elements.length === 0)"
                    style="color: #c0c4cc; font-size: 13px"
                  >
                    未提取到页面元素信息
                  </div>
                  <div
                    v-if="row.type === 'api' && (!row.params || row.params.length === 0) && (!row.response_fields || row.response_fields.length === 0)"
                    style="color: #c0c4cc; font-size: 13px"
                  >
                    未提取到参数或响应字段信息
                  </div>
                </div>
              </template>
            </el-table-column>
            <el-table-column width="40">
              <template #default="{ row }">
                <el-checkbox
                  :model-value="selectedPaths.has(itemKey(row))"
                  @change="(val) => toggleItem(itemKey(row), val)"
                />
              </template>
            </el-table-column>
            <el-table-column prop="name" label="名称" min-width="140" />
            <el-table-column label="类型" width="70" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.type === 'api' && row.method" size="small" :type="methodTagType(row.method)">
                  {{ row.method }}
                </el-tag>
                <el-tag v-else size="small" type="success">{{ row.type === 'page' ? '页面' : 'API' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="path" label="路径" min-width="120" />
            <el-table-column prop="source_file" label="来源文件" min-width="140" />
            <el-table-column label="详情" width="70" align="center">
              <template #default="{ row }">
                <template v-if="row.type === 'page'">
                  <el-tag
                    v-if="row.elements && row.elements.length > 0"
                    size="small"
                    type="info"
                  >
                    {{ row.elements.length }} 元素
                  </el-tag>
                  <span v-else style="color: #c0c4cc">-</span>
                </template>
                <template v-else>
                  <el-tag
                    v-if="row.params && row.params.length > 0"
                    size="small"
                    type="info"
                  >
                    {{ row.params.length }} 参数
                  </el-tag>
                  <span v-else style="color: #c0c4cc">-</span>
                </template>
              </template>
            </el-table-column>
            <el-table-column prop="description" label="描述" min-width="180" />
            <el-table-column label="补充描述" min-width="200">
              <template #default="{ row }">
                <el-input
                  v-model="descriptions[row.path]"
                  placeholder="可选：补充用例描述"
                  size="small"
                />
              </template>
            </el-table-column>
          </el-table>
        </el-collapse-item>
      </el-collapse>
    </div>

    <!-- 无结果 -->
    <div v-else-if="analysis?.status === 'completed' && !analysis.discovered_items?.length">
      <el-empty description="未发现页面或 API，请检查仓库代码结构" />
    </div>

    <!-- 初始状态 -->
    <div v-else style="text-align: center; padding: 40px 0; color: #909399">
      点击「开始分析」扫描仓库中的功能模块、页面路由和 API 端点
    </div>
  </el-card>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { WarningFilled } from '@element-plus/icons-vue'
import { repoAnalyze, getRepoAnalysis, resetRepoAnalysis, checkCliAvailable, getSettings } from '../api.js'

const props = defineProps({
  projectId: { type: Number, required: true },
  autoStart: { type: Boolean, default: false },
})
const emit = defineEmits(['analysis-complete', 'items-selected', 'back'])

const analysis = ref(null)
const analyzing = ref(false)
const isStuck = ref(false)
const elapsedSeconds = ref(0)
const selectedPaths = ref(new Set())
const descriptions = ref({})
const expandedGroups = ref([])
let pollTimer = null
let pollCount = 0
let loading = false
const MAX_POLL_COUNT = 100 // ~5 minutes at 3s interval

// All items flattened from analysis
const allItems = computed(() =>
  (analysis.value?.discovered_items || [])
)

// Group items by feature_group
const featureGroups = computed(() => {
  const items = allItems.value
  const groupMap = new Map()

  for (const item of items) {
    const groupName = item.feature_group || '未分组'
    if (!groupMap.has(groupName)) {
      groupMap.set(groupName, {
        name: groupName,
        description: item.feature_description || '',
        items: [],
      })
    }
    const group = groupMap.get(groupName)
    // Use first non-empty description if current is empty
    if (!group.description && item.feature_description) {
      group.description = item.feature_description
    }
    group.items.push(item)
  }

  const groups = Array.from(groupMap.values())
  return groups
})

const totalSelected = computed(() => selectedPaths.value.size)

watch(featureGroups, (groups) => {
  if (expandedGroups.value.length === 0 && groups.length > 0) {
    expandedGroups.value = groups.map(g => g.name)
  }
}, { immediate: true })

const formattedElapsed = computed(() => {
  const s = elapsedSeconds.value
  const min = Math.floor(s / 60)
  const sec = s % 60
  return min > 0 ? `${min}分${sec}秒` : `${sec}秒`
})

watch(() => props.autoStart, (val) => {
  if (val && !analysis.value && !analyzing.value) {
    // Check if there's already an analysis
    loadExistingAnalysis()
  }
})

onMounted(() => {
  // Always check for existing analysis on mount
  loadExistingAnalysis()
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})

async function loadExistingAnalysis() {
  if (loading) return
  loading = true
  try {
    const { data } = await getRepoAnalysis(props.projectId)
    if (data.analysis) {
      if (data.analysis.status === 'completed') {
        analysis.value = data.analysis
        emit('analysis-complete')
        return
      }
      if (data.analysis.status === 'analyzing') {
        analyzing.value = true
        analysis.value = data.analysis
        startPolling()
        return
      }
    }
    // No existing analysis or status is pending/failed — only start new if autoStart
    if (props.autoStart && !analysis.value) {
      await startAnalysis()
    }
  } catch (e) {
    if (props.autoStart) {
      await startAnalysis()
    }
  } finally {
    loading = false
  }
}

async function confirmRestart() {
  try {
    await ElMessageBox.confirm('确定要重新分析吗？当前分析结果将被覆盖。', '确认重新分析', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await startAnalysis()
  } catch {
    // cancelled
  }
}

async function startAnalysis() {
  // Check CLI availability if using CLI engine
  try {
    const { data: settingsData } = await getSettings()
    const engine = settingsData.analysis_engine || 'cli'
    if (engine === 'cli') {
      const cliPath = settingsData.claude_cli_path || 'claude'
      try {
        const { data: cliData } = await checkCliAvailable(cliPath)
        if (!cliData.available) {
          ElMessage.warning(
            `Claude CLI 不可用: ${cliData.error || '未安装'}。请在设置中安装 CLI 或切换到 SDK 模式。`
          )
        }
      } catch {
        // CLI check failed, continue anyway — backend will handle fallback
      }
    }
  } catch {
    // Settings fetch failed, continue
  }

  analyzing.value = true
  analysis.value = null
  try {
    await repoAnalyze(props.projectId)
    startPolling()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '分析启动失败')
    analyzing.value = false
  }
}

function startPolling() {
  if (pollTimer) clearInterval(pollTimer)
  pollCount = 0
  pollTimer = setInterval(async () => {
    pollCount++
    if (pollCount > MAX_POLL_COUNT) {
      clearInterval(pollTimer)
      pollTimer = null
      analyzing.value = false
      ElMessage.warning('分析超时，请稍后重试')
      return
    }
    try {
      const { data } = await getRepoAnalysis(props.projectId)
      if (data.analysis) {
        analysis.value = data.analysis
        elapsedSeconds.value = data.analysis.elapsed_seconds || 0
        isStuck.value = data.analysis.is_stuck || false
        if (data.analysis.status === 'completed' || data.analysis.status === 'failed') {
          clearInterval(pollTimer)
          pollTimer = null
          analyzing.value = false
          isStuck.value = false
          if (data.analysis.status === 'completed') {
            emit('analysis-complete')
          }
        }
      }
    } catch (e) {
      // polling error, continue
    }
  }, 3000)
}

// --- Selection logic (composite key, not path-only) ---

function itemKey(item) {
  return `${item.path}::${item.source_file}::${item.name}`
}

function toggleCollapse(groupName) {
  const idx = expandedGroups.value.indexOf(groupName)
  if (idx >= 0) {
    expandedGroups.value.splice(idx, 1)
  } else {
    expandedGroups.value.push(groupName)
  }
}

function toggleItem(key, val) {
  const newSet = new Set(selectedPaths.value)
  if (val) {
    newSet.add(key)
  } else {
    newSet.delete(key)
  }
  selectedPaths.value = newSet
}

function getGroupSelectedCount(groupName) {
  const group = featureGroups.value.find(g => g.name === groupName)
  if (!group) return 0
  return group.items.filter(item => selectedPaths.value.has(itemKey(item))).length
}

function getGroupCheckState(groupName) {
  const group = featureGroups.value.find(g => g.name === groupName)
  if (!group || group.items.length === 0) return false
  const selectedCount = getGroupSelectedCount(groupName)
  if (selectedCount === 0) return false
  if (selectedCount === group.items.length) return true
  return 'indeterminate'
}

function toggleGroup(groupName, val) {
  const group = featureGroups.value.find(g => g.name === groupName)
  if (!group) return
  const newSet = new Set(selectedPaths.value)
  for (const item of group.items) {
    const key = itemKey(item)
    if (val) {
      newSet.add(key)
    } else {
      newSet.delete(key)
    }
  }
  selectedPaths.value = newSet
}

function toggleSelectAll() {
  if (totalSelected.value === allItems.value.length) {
    selectedPaths.value = new Set()
  } else {
    selectedPaths.value = new Set(allItems.value.map(item => itemKey(item)))
  }
}

function methodTagType(method) {
  const map = { GET: 'success', POST: 'warning', PUT: '', DELETE: 'danger', PATCH: 'info' }
  return map[method] || ''
}

function elemTypeTag(type) {
  const map = { input: '', button: 'warning', select: 'success', form: 'danger', table: 'info', link: '' }
  return map[type] || ''
}

function paramInTag(paramIn) {
  const map = { query: '', path: 'success', body: 'warning', header: 'info' }
  return map[paramIn] || ''
}

async function handleResetAndRetry() {
  try {
    await resetRepoAnalysis(props.projectId)
    if (pollTimer) clearInterval(pollTimer)
    pollTimer = null
    analyzing.value = false
    analysis.value = null
    isStuck.value = false
    elapsedSeconds.value = 0
    selectedPaths.value = new Set()
    descriptions.value = {}
    ElMessage.success('已重置，请重新开始分析')
  } catch (e) {
    ElMessage.error('重置失败: ' + (e.response?.data?.error || e.message))
  }
}

function handleNext() {
  const selected = allItems.value.filter(item => selectedPaths.value.has(itemKey(item)))
  emit('items-selected', selected, { ...descriptions.value })
}
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.group-header {
  display: flex;
  align-items: center;
  width: 100%;
  gap: 4px;
}
.group-name {
  font-weight: 600;
  font-size: 14px;
  color: #303133;
  margin-left: 4px;
  cursor: pointer;
  user-select: none;
}
.group-desc {
  color: #909399;
  font-size: 12px;
  margin-left: 12px;
}
.group-selected-count {
  color: #909399;
  font-size: 12px;
  margin-left: auto;
  margin-right: 8px;
}
</style>
