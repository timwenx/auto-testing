<template>
  <div>
    <!-- 统计卡片 -->
    <el-row :gutter="16" style="margin-bottom: 20px">
      <el-col :span="6" v-for="card in statCards" :key="card.label">
        <el-card shadow="hover" class="stat-card">
          <div style="display: flex; align-items: center; gap: 16px">
            <el-icon :style="{ fontSize: '36px', color: card.color }"><component :is="card.icon" /></el-icon>
            <div>
              <div style="font-size: 28px; font-weight: bold; color: #303133">{{ card.value }}</div>
              <div style="color: #909399; font-size: 13px; margin-top: 2px">{{ card.label }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 快捷操作 -->
    <el-card style="margin-bottom: 20px">
      <template #header><span>快捷操作</span></template>
      <el-row :gutter="16">
        <el-col :span="6">
          <el-button type="primary" size="large" style="width: 100%" @click="router.push('/projects')">
            <el-icon><Folder /></el-icon> 新建项目
          </el-button>
        </el-col>
        <el-col :span="6">
          <el-button size="large" style="width: 100%" @click="router.push('/plans')">
            <el-icon><List /></el-icon> 执行方案
          </el-button>
        </el-col>
        <el-col :span="6">
          <el-button size="large" style="width: 100%" @click="router.push('/executions')">
            <el-icon><VideoPlay /></el-icon> 查看执行记录
          </el-button>
        </el-col>
        <el-col :span="6">
          <el-button size="large" style="width: 100%" @click="router.push('/scripts')">
            <el-icon><Document /></el-icon> 脚本管理
          </el-button>
        </el-col>
      </el-row>
    </el-card>

    <el-row :gutter="20">
      <!-- 最近项目 -->
      <el-col :span="12">
        <el-card>
          <template #header><span>最近项目</span></template>
          <el-table :data="projects" style="width: 100%" size="small" v-loading="loadingProjects">
            <el-table-column prop="name" label="项目名" />
            <el-table-column prop="testcase_count" label="用例数" width="80" />
            <el-table-column prop="updated_at" label="更新时间" width="160" />
            <el-table-column label="操作" width="100">
              <template #default="{ row }">
                <el-button size="small" text type="primary" @click="router.push(`/projects/${row.id}`)">进入</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div style="display:flex;justify-content:flex-end;margin-top:12px" v-if="projectTotal > projectPageSize">
            <el-pagination small layout="prev, pager, next" :total="projectTotal" :page-size="projectPageSize" v-model:current-page="projectPage" @current-change="loadProjects" />
          </div>
          <el-empty v-if="!loadingProjects && !projects.length" description="暂无项目" :image-size="60">
            <el-button type="primary" size="small" @click="router.push('/projects')">创建第一个项目</el-button>
          </el-empty>
        </el-card>
      </el-col>

      <!-- 最近执行 -->
      <el-col :span="12">
        <el-card>
          <template #header>
            <div style="display: flex; justify-content: space-between; align-items: center">
              <span>最近执行</span>
              <el-select v-model="execStatusFilter" placeholder="状态" clearable size="small" style="width: 100px" @change="loadExecutions">
                <el-option label="通过" value="passed" />
                <el-option label="失败" value="failed" />
                <el-option label="运行中" value="running" />
              </el-select>
            </div>
          </template>
          <el-table :data="filteredExecutions" style="width: 100%" size="small" v-loading="loadingExecutions">
            <el-table-column prop="testcase_name" label="用例" show-overflow-tooltip />
            <el-table-column prop="status" label="状态" width="80">
              <template #default="{ row }">
                <el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="execution_mode" label="模式" width="80">
              <template #default="{ row }">
                <el-tag size="small" effect="plain">{{ row.execution_mode || 'script' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="时间" width="160" />
          </el-table>
          <div style="display:flex;justify-content:flex-end;margin-top:12px" v-if="executionTotal > executionPageSize">
            <el-pagination small layout="prev, pager, next" :total="executionTotal" :page-size="executionPageSize" v-model:current-page="executionPage" @current-change="loadExecutions" />
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { getProjects, getExecutions, getStats } from '../api'
import { Folder, List, VideoPlay, Document, Odometer, Cpu } from '@element-plus/icons-vue'

const router = useRouter()

const stats = ref({})
const projects = ref([])
const executions = ref([])
const loadingProjects = ref(false)
const loadingExecutions = ref(false)
const execStatusFilter = ref(null)

const projectPage = ref(1)
const projectPageSize = 5
const projectTotal = ref(0)

const executionPage = ref(1)
const executionPageSize = 5
const executionTotal = ref(0)

const statCards = computed(() => [
  { label: '项目数', value: stats.value.projects ?? 0, icon: Folder, color: '#409eff' },
  { label: '用例数', value: stats.value.testcases ?? 0, icon: Document, color: '#67c23a' },
  { label: '执行次数', value: stats.value.executions ?? 0, icon: VideoPlay, color: '#e6a23c' },
  { label: 'AI 对话', value: stats.value.ai_conversations ?? 0, icon: Cpu, color: '#909399' },
])

const statusType = (s) => {
  const map = { passed: 'success', failed: 'danger', running: 'warning', error: 'danger', pending: 'info' }
  return map[s] || 'info'
}

const filteredExecutions = computed(() => {
  if (!execStatusFilter.value) return executions.value
  return executions.value.filter(r => r.status === execStatusFilter.value)
})

async function loadProjects() {
  loadingProjects.value = true
  try {
    const { data } = await getProjects({ page: projectPage.value, page_size: projectPageSize })
    projects.value = data.results || data
    projectTotal.value = data.count ?? (Array.isArray(data) ? data.length : 0)
  } finally { loadingProjects.value = false }
}

async function loadExecutions() {
  loadingExecutions.value = true
  try {
    const params = { page: executionPage.value, page_size: executionPageSize }
    if (execStatusFilter.value) params.status = execStatusFilter.value
    const { data } = await getExecutions(params)
    executions.value = data.results || data
    executionTotal.value = data.count ?? (Array.isArray(data) ? data.length : 0)
  } finally { loadingExecutions.value = false }
}

onMounted(async () => {
  const [s] = await Promise.all([getStats(), loadProjects(), loadExecutions()])
  stats.value = s.data
})
</script>

<style scoped>
.stat-card {
  transition: transform 0.2s;
}
.stat-card:hover {
  transform: translateY(-2px);
}
</style>
