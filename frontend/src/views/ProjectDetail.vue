<template>
  <div v-loading="loading">
    <!-- 项目信息 -->
    <el-card style="margin-bottom: 16px" v-if="project">
      <template #header>
        <div class="card-header">
          <span>{{ project.name }}</span>
          <el-button type="primary" size="small" @click="handleExecuteAll" :loading="executingAll">
            <el-icon><VideoPlay /></el-icon> 批量执行
          </el-button>
        </div>
      </template>
      <el-descriptions :column="2" size="small">
        <el-descriptions-item label="目标 URL">{{ project.base_url || '-' }}</el-descriptions-item>
        <el-descriptions-item label="用例数">{{ testcases.length }}</el-descriptions-item>
        <el-descriptions-item label="描述" :span="2">{{ project.description || '-' }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <!-- 测试用例列表 -->
    <el-card>
      <template #header>
        <div class="card-header">
          <span>测试用例</span>
          <div>
            <el-button size="small" type="success" @click="showAIGenerate = true">
              <el-icon><MagicStick /></el-icon> AI 生成
            </el-button>
            <el-button size="small" type="primary" @click="showCreate = true">
              <el-icon><Plus /></el-icon> 新建用例
            </el-button>
          </div>
        </div>
      </template>
      <el-table :data="testcases" style="width: 100%">
        <el-table-column prop="name" label="用例名称" />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="is_ai_generated" label="来源" width="80">
          <template #default="{ row }">
            <el-tag v-if="row.is_ai_generated" type="info" size="small">AI</el-tag>
            <span v-else>手动</span>
          </template>
        </el-table-column>
        <el-table-column prop="execution_count" label="执行次数" width="90" />
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="handleExecute(row)">执行</el-button>
            <el-button size="small" text @click="showDetail(row)">详情</el-button>
            <el-button size="small" text type="danger" @click="handleDeleteTC(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 用例详情弹窗 -->
    <el-dialog v-model="showDetailDialog" title="用例详情" width="600px">
      <template v-if="detailTC">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="名称">{{ detailTC.name }}</el-descriptions-item>
          <el-descriptions-item label="描述">{{ detailTC.description || '-' }}</el-descriptions-item>
          <el-descriptions-item label="测试步骤">
            <pre style="white-space: pre-wrap; margin: 0">{{ detailTC.steps }}</pre>
          </el-descriptions-item>
          <el-descriptions-item label="预期结果">
            <pre style="white-space: pre-wrap; margin: 0">{{ detailTC.expected_result }}</pre>
          </el-descriptions-item>
        </el-descriptions>
      </template>
    </el-dialog>

    <!-- 新建用例弹窗 -->
    <el-dialog v-model="showCreate" title="新建测试用例" width="500px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="用例名称">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="测试步骤">
          <el-input v-model="form.steps" type="textarea" :rows="4" placeholder="用自然语言描述测试步骤" />
        </el-form-item>
        <el-form-item label="预期结果">
          <el-input v-model="form.expected_result" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" @click="handleCreateTC">创建</el-button>
      </template>
    </el-dialog>

    <!-- AI 生成弹窗 -->
    <el-dialog v-model="showAIGenerate" title="AI 生成测试用例" width="500px">
      <el-form label-width="80px">
        <el-form-item label="需求描述">
          <el-input
            v-model="aiRequirement"
            type="textarea"
            :rows="4"
            placeholder="描述你想测试的功能，例如：用户登录功能，需要测试正常登录、密码错误、账号不存在等场景"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAIGenerate = false">取消</el-button>
        <el-button type="primary" @click="handleAIGenerate" :loading="aiGenerating">
          <el-icon><MagicStick /></el-icon> 生成
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import {
  getProject, getProjectTestCases, createTestCase,
  deleteTestCase, executeTestCase, executeProject, aiGenerateTestCase,
} from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'

const route = useRoute()
const projectId = route.params.id

const loading = ref(false)
const project = ref(null)
const testcases = ref([])
const showCreate = ref(false)
const showDetailDialog = ref(false)
const showAIGenerate = ref(false)
const detailTC = ref(null)
const executingAll = ref(false)
const aiGenerating = ref(false)
const aiRequirement = ref('')
const form = ref({ name: '', description: '', steps: '', expected_result: '' })

const statusType = (s) => {
  const map = { draft: 'info', ready: '', running: 'warning', passed: 'success', failed: 'danger' }
  return map[s] || 'info'
}

const loadData = async () => {
  loading.value = true
  try {
    const [p, tc] = await Promise.all([
      getProject(projectId),
      getProjectTestCases(projectId),
    ])
    project.value = p.data
    testcases.value = tc.data.results || tc.data
  } finally {
    loading.value = false
  }
}

const handleCreateTC = async () => {
  if (!form.value.name) return ElMessage.warning('请输入用例名称')
  await createTestCase({ ...form.value, project: parseInt(projectId) })
  ElMessage.success('创建成功')
  showCreate.value = false
  form.value = { name: '', description: '', steps: '', expected_result: '' }
  await loadData()
}

const handleDeleteTC = async (row) => {
  await ElMessageBox.confirm(`确认删除用例「${row.name}」？`, '提示', { type: 'warning' })
  await deleteTestCase(row.id)
  ElMessage.success('已删除')
  await loadData()
}

const handleExecute = async (row) => {
  try {
    await executeTestCase(row.id)
    ElMessage.success('已提交执行')
    row.status = 'running'
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '执行失败')
  }
}

const handleExecuteAll = async () => {
  executingAll.value = true
  try {
    const { data } = await executeProject(projectId)
    ElMessage.success(`已提交 ${data.length} 个用例执行`)
    await loadData()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '执行失败')
  } finally {
    executingAll.value = false
  }
}

const handleAIGenerate = async () => {
  if (!aiRequirement.value) return ElMessage.warning('请输入需求描述')
  aiGenerating.value = true
  try {
    const { data } = await aiGenerateTestCase({
      project_id: parseInt(projectId),
      requirement: aiRequirement.value,
    })
    ElMessage.success(`AI 生成了 ${data.length} 个测试用例`)
    showAIGenerate.value = false
    aiRequirement.value = ''
    await loadData()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || 'AI 生成失败')
  } finally {
    aiGenerating.value = false
  }
}

const showDetail = (row) => {
  detailTC.value = row
  showDetailDialog.value = true
}

onMounted(loadData)
</script>
