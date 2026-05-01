<template>
  <el-card>
    <template #header>
      <div class="card-header">
        <span>代码分析</span>
        <div>
          <el-button size="small" @click="$emit('back')">返回上一步</el-button>
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
            v-if="!analyzing && analysis?.status === 'completed'"
            type="warning"
            size="small"
            @click="startAnalysis"
          >
            重新分析
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
        <p style="color: #909399; font-size: 12px; margin-top: 8px">系统将通过 AI 扫描路由和 API 定义</p>
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
        <el-button type="primary" @click="startAnalysis">重新分析</el-button>
      </template>
    </el-result>

    <!-- 分析完成 — 展示结果 -->
    <div v-else-if="analysis?.status === 'completed' && analysis.discovered_items?.length">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="页面列表" name="pages">
          <div style="margin-bottom: 12px; color: #909399; font-size: 13px">
            已选 {{ selectedPageIndices.length }} 个页面
          </div>
          <el-table :data="pageItems" style="width: 100%" size="small">
            <el-table-column width="40">
              <template #header>
                <el-checkbox v-model="selectAllPages" @change="toggleAllPages" />
              </template>
              <template #default="{ $index }">
                <el-checkbox
                  :model-value="selectedPageIndices.includes($index)"
                  @change="(val) => toggleItem('page', $index, val)"
                />
              </template>
            </el-table-column>
            <el-table-column prop="name" label="页面名称" min-width="140" />
            <el-table-column prop="path" label="路径" min-width="120" />
            <el-table-column prop="source_file" label="来源文件" min-width="140" />
            <el-table-column prop="description" label="描述" min-width="200" />
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
        </el-tab-pane>

        <el-tab-pane label="API 列表" name="apis">
          <div style="margin-bottom: 12px; color: #909399; font-size: 13px">
            已选 {{ selectedApiIndices.length }} 个 API
          </div>
          <el-table :data="apiItems" style="width: 100%" size="small">
            <el-table-column width="40">
              <template #header>
                <el-checkbox v-model="selectAllApis" @change="toggleAllApis" />
              </template>
              <template #default="{ $index }">
                <el-checkbox
                  :model-value="selectedApiIndices.includes($index)"
                  @change="(val) => toggleItem('api', $index, val)"
                />
              </template>
            </el-table-column>
            <el-table-column prop="name" label="API 名称" min-width="140" />
            <el-table-column prop="method" label="方法" width="80">
              <template #default="{ row }">
                <el-tag v-if="row.method" size="small" :type="methodTagType(row.method)">
                  {{ row.method }}
                </el-tag>
                <span v-else style="color: #c0c4cc">-</span>
              </template>
            </el-table-column>
            <el-table-column prop="path" label="路径" min-width="120" />
            <el-table-column prop="source_file" label="来源文件" min-width="140" />
            <el-table-column prop="description" label="描述" min-width="200" />
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
        </el-tab-pane>
      </el-tabs>

      <!-- 底部汇总 -->
      <div style="margin-top: 16px; display: flex; justify-content: space-between; align-items: center">
        <span style="color: #606266">
          已选择 <strong>{{ totalSelected }}</strong> 个目标
          （{{ selectedPageIndices.length }} 个页面 + {{ selectedApiIndices.length }} 个 API）
        </span>
        <el-button type="primary" :disabled="totalSelected === 0" @click="handleNext">
          下一步：生成用例
        </el-button>
      </div>
    </div>

    <!-- 无结果 -->
    <div v-else-if="analysis?.status === 'completed' && !analysis.discovered_items?.length">
      <el-empty description="未发现页面或 API，请检查仓库代码结构" />
    </div>

    <!-- 初始状态 -->
    <div v-else style="text-align: center; padding: 40px 0; color: #909399">
      点击「开始分析」扫描仓库中的页面路由和 API 端点
    </div>
  </el-card>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
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
const activeTab = ref('pages')
const selectedPageIndices = ref([])
const selectedApiIndices = ref([])
const descriptions = ref({})
const selectAllPages = ref(false)
const selectAllApis = ref(false)
let pollTimer = null
let pollCount = 0
let loading = false
const MAX_POLL_COUNT = 100 // ~5 minutes at 3s interval

const pageItems = computed(() =>
  (analysis.value?.discovered_items || []).filter(i => i.type === 'page')
)
const apiItems = computed(() =>
  (analysis.value?.discovered_items || []).filter(i => i.type === 'api')
)
const totalSelected = computed(() =>
  selectedPageIndices.value.length + selectedApiIndices.value.length
)
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

function toggleItem(type, index, val) {
  const arr = type === 'page' ? selectedPageIndices : selectedApiIndices
  if (val) {
    if (!arr.value.includes(index)) arr.value.push(index)
  } else {
    arr.value = arr.value.filter(i => i !== index)
  }
}

function toggleAllPages(val) {
  selectedPageIndices.value = val ? pageItems.value.map((_, i) => i) : []
}

function toggleAllApis(val) {
  selectedApiIndices.value = val ? apiItems.value.map((_, i) => i) : []
}

function methodTagType(method) {
  const map = { GET: 'success', POST: 'warning', PUT: '', DELETE: 'danger', PATCH: 'info' }
  return map[method] || ''
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
    ElMessage.success('已重置，请重新开始分析')
  } catch (e) {
    ElMessage.error('重置失败: ' + (e.response?.data?.error || e.message))
  }
}

function handleNext() {
  const selected = []
  selectedPageIndices.value.forEach(i => selected.push(pageItems.value[i]))
  selectedApiIndices.value.forEach(i => selected.push(apiItems.value[i]))
  emit('items-selected', selected, { ...descriptions.value })
}
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>
