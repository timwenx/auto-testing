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
          <el-table :data="projects" style="width: 100%" size="small">
            <el-table-column prop="name" label="项目名" />
            <el-table-column prop="testcase_count" label="用例数" width="80" />
            <el-table-column prop="updated_at" label="更新时间" width="180" />
          </el-table>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card>
          <template #header>
            <span>最近执行</span>
          </template>
          <el-table :data="executions" style="width: 100%" size="small">
            <el-table-column prop="testcase_name" label="用例" />
            <el-table-column prop="status" label="状态" width="80">
              <template #default="{ row }">
                <el-tag :type="statusType(row.status)" size="small">
                  {{ row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="时间" width="180" />
          </el-table>
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

onMounted(async () => {
  const [s, p, e] = await Promise.all([
    getStats(),
    getProjects({ page_size: 5 }),
    getExecutions({ page_size: 5 }),
  ])
  stats.value = s.data
  projects.value = p.data.results || p.data
  executions.value = e.data.results || e.data
})
</script>
