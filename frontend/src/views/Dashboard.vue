<template>
  <div>
    <el-row :gutter="20" style="margin-bottom: 20px">
      <el-col :span="6" v-for="card in statCards" :key="card.label">
        <el-card shadow="hover">
          <div style="text-align: center">
            <div style="font-size: 32px; font-weight: bold; color: #409eff">
              {{ card.value }}
            </div>
            <div style="color: #909399; margin-top: 8px">{{ card.label }}</div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20">
      <el-col :span="12">
        <el-card>
          <template #header>
            <span>最近项目</span>
          </template>
          <el-table :data="projects" style="width: 100%" size="small" v-loading="loadingProjects">
            <el-table-column prop="name" label="项目名" />
            <el-table-column prop="testcase_count" label="用例数" width="80" />
            <el-table-column prop="updated_at" label="更新时间" width="170" />
          </el-table>
          <div style="display:flex;justify-content:flex-end;margin-top:12px" v-if="projectTotal > projectPageSize">
            <el-pagination
              small
              layout="prev, pager, next"
              :total="projectTotal"
              :page-size="projectPageSize"
              v-model:current-page="projectPage"
              @current-change="loadProjects"
            />
          </div>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card>
          <template #header>
            <span>最近执行</span>
          </template>
          <el-table :data="executions" style="width: 100%" size="small" v-loading="loadingExecutions">
            <el-table-column prop="testcase_name" label="用例" />
            <el-table-column prop="status" label="状态" width="80">
              <template #default="{ row }">
                <el-tag :type="statusType(row.status)" size="small">
                  {{ row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="时间" width="170" />
          </el-table>
          <div style="display:flex;justify-content:flex-end;margin-top:12px" v-if="executionTotal > executionPageSize">
            <el-pagination
              small
              layout="prev, pager, next"
              :total="executionTotal"
              :page-size="executionPageSize"
              v-model:current-page="executionPage"
              @current-change="loadExecutions"
            />
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { getProjects, getExecutions, getStats } from '../api'

const stats = ref({})
const projects = ref([])
const executions = ref([])
const loadingProjects = ref(false)
const loadingExecutions = ref(false)

const projectPage = ref(1)
const projectPageSize = 5
const projectTotal = ref(0)

const executionPage = ref(1)
const executionPageSize = 5
const executionTotal = ref(0)

const statCards = computed(() => [
  { label: '项目数', value: stats.value.projects ?? 0 },
  { label: '用例数', value: stats.value.testcases ?? 0 },
  { label: '执行次数', value: stats.value.executions ?? 0 },
  { label: 'AI 对话', value: stats.value.ai_conversations ?? 0 },
])

const statusType = (s) => {
  const map = { passed: 'success', failed: 'danger', running: 'warning', error: 'danger', pending: 'info' }
  return map[s] || 'info'
}

async function loadProjects() {
  loadingProjects.value = true
  try {
    const { data } = await getProjects({ page: projectPage.value, page_size: projectPageSize })
    projects.value = data.results || data
    projectTotal.value = data.count ?? (Array.isArray(data) ? data.length : 0)
  } finally {
    loadingProjects.value = false
  }
}

async function loadExecutions() {
  loadingExecutions.value = true
  try {
    const { data } = await getExecutions({ page: executionPage.value, page_size: executionPageSize })
    executions.value = data.results || data
    executionTotal.value = data.count ?? (Array.isArray(data) ? data.length : 0)
  } finally {
    loadingExecutions.value = false
  }
}

onMounted(async () => {
  const [s] = await Promise.all([
    getStats(),
    loadProjects(),
    loadExecutions(),
  ])
  stats.value = s.data
})
</script>
