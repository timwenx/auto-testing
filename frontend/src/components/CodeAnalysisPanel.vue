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
      <el-icon class="is-loading" style="font-size: 32px; color: #409eff"><Loading /></el-icon>
      <p style="margin-top: 12px; color: #606266">正在分析仓库代码，请稍候...</p>
      <p style="color: #909399; font-size: 13px">系统将通过 AI 扫描路由和 API 定义</p>
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
          <div style="margin-bottom: 12px">
            <el-checkbox v-model="selectAllPages" @change="toggleAllPages">全选页面</el-checkbox>
            <span style="margin-left: 12px; color: #909399; font-size: 13px">
              已选 {{ selectedPageIndices.length }} 个页面
            </span>
          </div>
          <el-table :data="pageItems" style="width: 100%" size="small">
            <el-table-column type="selection" width="40" :selectable="() => true">
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
          <div style="margin-bottom: 12px">
            <el-checkbox v-model="selectAllApis" @change="toggleAllApis">全选 API</el-checkbox>
            <span style="margin-left: 12px; color: #909399; font-size: 13px">
              已选 {{ selectedApiIndices.length }} 个 API
            </span>
          </div>
          <el-table :data="apiItems" style="width: 100%" size="small">
            <el-table-column type="selection" width="40" :selectable="() => true">
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
import { repoAnalyze, getRepoAnalysis } from '../api.js'

const props = defineProps({
  projectId: { type: Number, required: true },
  autoStart: { type: Boolean, default: false },
})
const emit = defineEmits(['analysis-complete', 'items-selected', 'back'])

const analysis = ref(null)
const analyzing = ref(false)
const activeTab = ref('pages')
const selectedPageIndices = ref([])
const selectedApiIndices = ref([])
const descriptions = ref({})
const selectAllPages = ref(false)
const selectAllApis = ref(false)
let pollTimer = null

const pageItems = computed(() =>
  (analysis.value?.discovered_items || []).filter(i => i.type === 'page')
)
const apiItems = computed(() =>
  (analysis.value?.discovered_items || []).filter(i => i.type === 'api')
)
const totalSelected = computed(() =>
  selectedPageIndices.value.length + selectedApiIndices.value.length
)

watch(() => props.autoStart, (val) => {
  if (val && !analysis.value && !analyzing.value) {
    // Check if there's already an analysis
    checkExistingAnalysis()
  }
})

onMounted(() => {
  if (props.autoStart) {
    checkExistingAnalysis()
  }
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})

async function checkExistingAnalysis() {
  try {
    const { data } = await getRepoAnalysis(props.projectId)
    if (data.analysis && data.analysis.status === 'completed') {
      analysis.value = data.analysis
      emit('analysis-complete')
      return
    }
    if (data.analysis && data.analysis.status === 'analyzing') {
      analyzing.value = true
      analysis.value = data.analysis
      startPolling()
      return
    }
    // No existing analysis, start new
    startAnalysis()
  } catch (e) {
    startAnalysis()
  }
}

async function startAnalysis() {
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
  pollTimer = setInterval(async () => {
    try {
      const { data } = await getRepoAnalysis(props.projectId)
      if (data.analysis) {
        analysis.value = data.analysis
        if (data.analysis.status === 'completed' || data.analysis.status === 'failed') {
          clearInterval(pollTimer)
          pollTimer = null
          analyzing.value = false
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
