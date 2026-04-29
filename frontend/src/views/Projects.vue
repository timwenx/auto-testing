<template>
  <div>
    <div class="card-header" style="margin-bottom: 16px">
      <span>项目列表</span>
      <el-button type="primary" @click="showCreate = true">
        <el-icon><Plus /></el-icon> 新建项目
      </el-button>
    </div>

    <el-table :data="projects" style="width: 100%" v-loading="loading">
      <el-table-column prop="name" label="项目名" />
      <el-table-column prop="base_url" label="目标 URL" show-overflow-tooltip />
      <el-table-column prop="repo_url" label="Git 仓库" show-overflow-tooltip>
        <template #default="{ row }">
          <span v-if="row.repo_url">{{ row.repo_url }}</span>
          <span v-else style="color: #c0c4cc">-</span>
        </template>
      </el-table-column>
      <el-table-column prop="testcase_count" label="用例数" width="80" />
      <el-table-column prop="last_execution_status" label="最近状态" width="100">
        <template #default="{ row }">
          <el-tag v-if="row.last_execution_status" :type="statusType(row.last_execution_status)" size="small">
            {{ row.last_execution_status }}
          </el-tag>
          <span v-else style="color: #c0c4cc">-</span>
        </template>
      </el-table-column>
      <el-table-column prop="updated_at" label="更新时间" width="180" />
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button size="small" text type="primary" @click="$router.push(`/projects/${row.id}`)">详情</el-button>
          <el-button size="small" text type="danger" @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 新建项目弹窗 -->
    <el-dialog v-model="showCreate" title="新建项目" width="600px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="项目名称">
          <el-input v-model="form.name" placeholder="输入项目名称" />
        </el-form-item>
        <el-form-item label="目标 URL">
          <el-input v-model="form.base_url" placeholder="https://example.com" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="3" />
        </el-form-item>
        <el-divider content-position="left">代码仓库</el-divider>
        <el-form-item label="Git 仓库地址">
          <el-input v-model="form.repo_url" placeholder="https://github.com/owner/repo.git" />
        </el-form-item>
        <el-form-item label="仓库账号">
          <el-input v-model="form.repo_username" placeholder="可选，用于 HTTPS 认证" />
        </el-form-item>
        <el-form-item label="仓库密码/Token">
          <el-input v-model="form.repo_password" type="password" show-password placeholder="可选，用于 HTTPS 认证" />
        </el-form-item>
        <el-form-item label="GitHub 地址">
          <el-input v-model="form.github_url" placeholder="可选，如与 Git 仓库地址不同" />
        </el-form-item>
        <el-form-item label="GitHub Token">
          <el-input v-model="form.github_token" type="password" show-password placeholder="可选，用于 GitHub API 访问" />
        </el-form-item>
        <div style="color: #909399; font-size: 12px; margin: -8px 0 8px 100px">
          配置仓库地址后，AI 生成用例时将自动分析项目源码
        </div>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" @click="handleCreate" :loading="creating">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getProjects, createProject, deleteProject } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'

const projects = ref([])
const loading = ref(false)
const showCreate = ref(false)
const creating = ref(false)
const form = ref({ name: '', base_url: '', description: '', repo_url: '', repo_username: '', repo_password: '', github_url: '', github_token: '' })

const statusType = (s) => {
  const map = { passed: 'success', failed: 'danger', running: 'warning', error: 'danger', pending: 'info' }
  return map[s] || 'info'
}

const loadProjects = async () => {
  loading.value = true
  try {
    const { data } = await getProjects()
    projects.value = data.results || data
  } finally {
    loading.value = false
  }
}

const handleCreate = async () => {
  if (!form.value.name) {
    ElMessage.warning('请输入项目名称')
    return
  }
  creating.value = true
  try {
    await createProject(form.value)
    ElMessage.success('创建成功')
    showCreate.value = false
    form.value = { name: '', base_url: '', description: '', repo_url: '', repo_username: '', repo_password: '', github_url: '', github_token: '' }
    await loadProjects()
  } finally {
    creating.value = false
  }
}

const handleDelete = async (row) => {
  await ElMessageBox.confirm(`确认删除项目「${row.name}」？`, '提示', { type: 'warning' })
  await deleteProject(row.id)
  ElMessage.success('已删除')
  await loadProjects()
}

onMounted(loadProjects)
</script>
