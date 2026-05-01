<template>
  <div v-loading="loading">
    <!-- 项目信息 -->
    <el-card style="margin-bottom: 16px" v-if="project">
      <template #header>
        <div class="card-header">
          <span>{{ project.name }}</span>
          <div>
            <el-button type="warning" size="small" @click="handleExecuteAllAgent" :loading="executingAllAgent">
              <el-icon><Cpu /></el-icon> Agent 批量执行
            </el-button>
          </div>
        </div>
      </template>
      <el-descriptions :column="2" size="small">
        <el-descriptions-item label="目标 URL">{{ project.base_url || '-' }}</el-descriptions-item>
        <el-descriptions-item label="用例数">{{ testcases.length }}</el-descriptions-item>
        <el-descriptions-item label="Git 仓库">{{ project.repo_url || '-' }}</el-descriptions-item>
        <el-descriptions-item label="描述">{{ project.description || '-' }}</el-descriptions-item>
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
        <el-table-column prop="priority" label="优先级" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.priority === 'P0'" type="danger" size="small">P0</el-tag>
            <el-tag v-else-if="row.priority === 'P1'" type="warning" size="small">P1</el-tag>
            <el-tag v-else-if="row.priority === 'P2'" type="info" size="small">P2</el-tag>
            <span v-else style="color: #c0c4cc">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="test_type" label="测试类型" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.test_type" size="small" effect="plain">{{ row.test_type }}</el-tag>
            <span v-else style="color: #c0c4cc">-</span>
          </template>
        </el-table-column>
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
        <el-table-column label="操作" width="400" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="openEditor(row)">编辑</el-button>
            <el-button size="small" text type="warning" @click="handleExecuteAgent(row)">Agent</el-button>
            <el-button size="small" text type="success" @click="handleAgentRefine(row)">调整</el-button>
            <el-button size="small" text @click="showDetail(row)">详情</el-button>
            <el-button size="small" text type="info" @click="handleViewExecutions(row)">执行记录</el-button>
            <el-button size="small" text type="danger" @click="handleDeleteTC(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 用例详情弹窗 -->
    <el-dialog v-model="showDetailDialog" title="用例详情" width="900px">
      <template v-if="detailTC">
        <!-- Markdown 渲染模式 -->
        <template v-if="detailTC.markdown_content">
          <div class="markdown-body" v-html="renderedMarkdown"></div>
        </template>
        <!-- 旧用例 fallback -->
        <template v-else>
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
      </template>
    </el-dialog>

    <!-- 用例编辑弹窗 -->
    <el-dialog v-model="showEditDialog" title="编辑用例" width="1000px" top="3vh">
      <template v-if="editingTC">
        <el-form label-width="80px" size="small">
          <el-form-item label="用例名称">
            <el-input v-model="editingTC.name" />
          </el-form-item>
        </el-form>
        <div class="md-editor-layout">
          <div class="md-editor-left">
            <div class="md-editor-label">Markdown 编辑</div>
            <textarea
              v-model="editingTC.markdown_content"
              class="md-textarea"
              placeholder="输入 Markdown 内容..."
            ></textarea>
          </div>
          <div class="md-editor-right">
            <div class="md-editor-label">预览</div>
            <div class="markdown-body md-preview" v-html="editPreview"></div>
          </div>
        </div>
      </template>
      <template #footer>
        <el-button @click="showEditDialog = false">取消</el-button>
        <el-button type="primary" @click="handleSaveTC" :loading="savingTC">保存</el-button>
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

    <!-- AI 生成测试用例弹窗（对话式） -->
    <el-dialog v-model="showAIGenerate" title="AI 生成测试用例" width="750px" @close="resetAIDialog">
      <!-- 输入阶段 -->
      <template v-if="!aiGeneratedCases.length && !aiGenerating">
        <el-form label-width="80px">
          <el-form-item label="需求描述">
            <el-input
              v-model="aiRequirement"
              type="textarea"
              :rows="4"
              placeholder="描述你想测试的功能，例如：用户登录功能，需要测试正常登录、密码错误、账号不存在等场景"
            />
          </el-form-item>
          <el-form-item label="测试目标">
            <el-input
              v-model="aiTarget"
              placeholder="可选，指定页面/接口，如「用户登录页面」「/api/users/」"
            />
          </el-form-item>
        </el-form>
      </template>

      <!-- 生成中 -->
      <template v-else-if="aiGenerating">
        <div style="text-align: center; padding: 40px 0">
          <el-icon class="is-loading" style="font-size: 32px; color: #409eff"><Loading /></el-icon>
          <p style="margin-top: 16px; color: #606266">
            AI 正在分析源码并生成测试用例，预计 30-60 秒…
          </p>
        </div>
      </template>

      <!-- 生成完成 — 用例列表 + 对话式反馈 -->
      <template v-else>
        <div style="max-height: 50vh; overflow-y: auto; margin-bottom: 16px">
          <div
            v-for="(tc, idx) in aiGeneratedCases"
            :key="idx"
            class="ai-case-item"
            @click="toggleCasePreview(idx)"
          >
            <div class="ai-case-header">
              <span class="ai-case-name">{{ tc.name }}</span>
              <div>
                <el-tag v-if="tc.priority === 'P0'" type="danger" size="small">P0</el-tag>
                <el-tag v-else-if="tc.priority === 'P1'" type="warning" size="small">P1</el-tag>
                <el-tag v-else-if="tc.priority === 'P2'" type="info" size="small">P2</el-tag>
                <el-tag v-if="tc.test_type" size="small" effect="plain" style="margin-left: 4px">{{ tc.test_type }}</el-tag>
              </div>
            </div>
            <transition name="el-zoom-in-top">
              <div v-if="expandedCaseIdx === idx" class="ai-case-preview markdown-body" v-html="renderCaseMarkdown(tc.markdown_content)" @click.stop></div>
            </transition>
          </div>
        </div>

        <!-- 对话式反馈区 -->
        <el-divider content-position="left">调整用例</el-divider>
        <el-input
          v-model="aiFeedback"
          type="textarea"
          :rows="3"
          placeholder="输入修改意见，如「增加并发测试场景」「登录页面增加验证码测试」"
          :disabled="aiAdjusting"
        />
        <div style="display: flex; justify-content: flex-end; margin-top: 8px">
          <el-button size="small" @click="handleAIFeedback" :loading="aiAdjusting" :disabled="!aiFeedback">
            <el-icon><ChatDotRound /></el-icon> 发送反馈
          </el-button>
        </div>
      </template>

      <template #footer>
        <el-button @click="showAIGenerate = false">取消</el-button>
        <template v-if="aiGeneratedCases.length && !aiGenerating">
          <el-button @click="handleAIGenerate" :loading="aiGenerating">重新生成</el-button>
          <el-button type="primary" @click="handleAISaveAll" :loading="aiSaving">确认保存</el-button>
        </template>
        <template v-else-if="!aiGenerating">
          <el-button type="primary" @click="handleAIGenerate" :loading="aiGenerating">
            <el-icon><MagicStick /></el-icon> 生成
          </el-button>
        </template>
      </template>
    </el-dialog>

    <!-- Agent 用例调整对话框 -->
    <AgentRefineDialog
      :visible="showAgentRefine"
      :testcase-id="agentRefineTestcaseId"
      @close="showAgentRefine = false"
      @updated="loadData"
    />

    <!-- 执行详情对话框 -->
    <el-dialog v-model="showExecutionDetail" title="执行详情" width="900px">
      <div v-loading="executionDetailLoading">
        <template v-if="executionDetail">
          <el-descriptions :column="2" border size="small" style="margin-bottom: 16px">
            <el-descriptions-item label="状态">
              <el-tag :type="statusType(executionDetail.status)" size="small">{{ executionDetail.status }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="执行模式">{{ executionDetail.execution_mode }}</el-descriptions-item>
            <el-descriptions-item label="耗时">{{ executionDetail.duration ? executionDetail.duration + 's' : '-' }}</el-descriptions-item>
            <el-descriptions-item label="工具调用">{{ executionDetail.tool_calls_count }} 次</el-descriptions-item>
            <el-descriptions-item label="AI 模型">{{ executionDetail.ai_model || '-' }}</el-descriptions-item>
            <el-descriptions-item label="创建时间">{{ executionDetail.created_at }}</el-descriptions-item>
          </el-descriptions>

          <!-- 逐步执行日志（时间线） -->
          <template v-if="executionDetail.step_logs && executionDetail.step_logs.length">
            <h4 style="margin: 16px 0 8px">逐步执行日志</h4>
            <el-timeline>
              <el-timeline-item
                v-for="step in executionDetail.step_logs"
                :key="step.step_num"
                :timestamp="step.timestamp"
                placement="top"
              >
                <el-card shadow="never" body-style="padding: 10px 14px">
                  <div style="display: flex; justify-content: space-between; align-items: center">
                    <div>
                      <el-tag size="small" effect="plain">{{ step.action }}</el-tag>
                      <span v-if="step.target" style="margin-left: 8px; font-size: 13px; color: #606266">{{ step.target }}</span>
                    </div>
                    <el-button
                      v-if="step.screenshot_path"
                      size="small"
                      text
                      type="primary"
                      @click="handlePreviewImage('/api/executions/screenshots/?path=' + encodeURIComponent(step.screenshot_path))"
                    >
                      查看截图
                    </el-button>
                  </div>
                  <div v-if="step.result" style="margin-top: 6px; font-size: 12px; color: #909399; word-break: break-all">
                    {{ step.result }}
                  </div>
                </el-card>
              </el-timeline-item>
            </el-timeline>
          </template>

          <!-- 截图缩略图 -->
          <ScreenshotGallery
            :screenshots="executionDetail.screenshots"
            :show-title="true"
          />

          <!-- Agent 原始响应 -->
          <template v-if="executionDetail.agent_response && executionDetail.agent_response.response_text">
            <h4 style="margin: 16px 0 8px">Agent 回复</h4>
            <div class="agent-response-box">
              <pre style="white-space: pre-wrap; margin: 0; font-size: 13px">{{ executionDetail.agent_response.response_text }}</pre>
            </div>
          </template>

          <!-- 原始日志 -->
          <el-collapse style="margin-top: 16px">
            <el-collapse-item title="原始执行日志">
              <pre style="white-space: pre-wrap; font-size: 12px; max-height: 300px; overflow-y: auto">{{ executionDetail.log }}</pre>
            </el-collapse-item>
          </el-collapse>
        </template>
        <el-empty v-else-if="!executionDetailLoading" description="暂无执行记录" />
      </div>
    </el-dialog>

    <!-- 图片预览 -->
    <el-dialog v-model="showImagePreview" title="截图预览" width="70%">
      <div style="text-align: center">
        <el-image :src="previewImage" fit="contain" style="max-height: 70vh" />
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { marked } from 'marked'
import {
  getProject, getProjectTestCases, createTestCase,
  updateTestCase, deleteTestCase,
  executeTestCaseAgent, executeProjectAgent,
  aiGenerateTestCase, aiAdjustTestCase,
  getExecutions,
} from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import AgentRefineDialog from './AgentRefineDialog.vue'
import ScreenshotGallery from '../components/ScreenshotGallery.vue'

const route = useRoute()
const router = useRouter()
const projectId = route.params.id

const loading = ref(false)
const project = ref(null)
const testcases = ref([])
const showCreate = ref(false)
const showDetailDialog = ref(false)
const showAIGenerate = ref(false)
const detailTC = ref(null)
const executingAllAgent = ref(false)
const showEditDialog = ref(false)
const editingTC = ref(null)
const savingTC = ref(false)
const aiGenerating = ref(false)
const aiRequirement = ref('')
const aiTarget = ref('')
const aiGeneratedCases = ref([])
const aiTestcaseIds = ref([])
const aiConversationId = ref(null)
const aiFeedback = ref('')
const aiAdjusting = ref(false)
const aiSaving = ref(false)
const expandedCaseIdx = ref(-1)
const showAgentRefine = ref(false)
const agentRefineTestcaseId = ref(null)
const showExecutionDetail = ref(false)
const executionDetail = ref(null)
const executionDetailLoading = ref(false)
const previewImage = ref('')
const showImagePreview = ref(false)
const form = ref({ name: '', description: '', steps: '', expected_result: '' })

// Configure marked for safe rendering
marked.setOptions({ breaks: true, gfm: true })

const renderedMarkdown = computed(() => {
  if (!detailTC.value?.markdown_content) return ''
  return marked.parse(detailTC.value.markdown_content)
})

const editPreview = computed(() => {
  if (!editingTC.value?.markdown_content) return '<span style="color:#999">预览区域</span>'
  return marked.parse(editingTC.value.markdown_content)
})

function openEditor(row) {
  editingTC.value = {
    id: row.id,
    name: row.name,
    markdown_content: row.markdown_content || `## 测试步骤\n\n${row.steps || ''}\n\n## 预期结果\n\n${row.expected_result || ''}`,
  }
  showEditDialog.value = true
}

async function handleSaveTC() {
  if (!editingTC.value) return
  savingTC.value = true
  try {
    await updateTestCase(editingTC.value.id, {
      name: editingTC.value.name,
      markdown_content: editingTC.value.markdown_content,
    })
    ElMessage.success('保存成功')
    showEditDialog.value = false
    loadData()
  } catch (e) {
    ElMessage.error('保存失败')
  } finally {
    savingTC.value = false
  }
}

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

const handleExecuteAgent = async (row) => {
  try {
    const { data } = await executeTestCaseAgent(row.id)
    ElMessage.success('Agent 执行已提交')
    row.status = 'running'
    // 跳转到执行观察面板
    const testRunId = data.test_run_id || data.id
    if (testRunId) {
      router.push({ name: 'ExecutionObserver', params: { id: testRunId } })
    }
  } catch (e) {
    ElMessage.error(e.response?.data?.error || 'Agent 执行失败')
  }
}

const handleExecuteAllAgent = async () => {
  executingAllAgent.value = true
  try {
    const { data } = await executeProjectAgent(projectId)
    ElMessage.success(`已提交 ${data.length} 个 Agent 执行`)
    await loadData()
    // 跳转到第一个执行的观察面板
    if (data.length > 0) {
      const firstId = data[0].test_run_id || data[0].id
      if (firstId) {
        router.push({ name: 'ExecutionObserver', params: { id: firstId } })
      }
    }
  } catch (e) {
    ElMessage.error(e.response?.data?.error || 'Agent 执行失败')
  } finally {
    executingAllAgent.value = false
  }
}

const handleAgentRefine = (row) => {
  agentRefineTestcaseId.value = row.id
  showAgentRefine.value = true
}

const handleAIGenerate = async () => {
  if (!aiRequirement.value) return ElMessage.warning('请输入需求描述')
  aiGenerating.value = true
  aiGeneratedCases.value = []
  aiConversationId.value = null
  try {
    const { data } = await aiGenerateTestCase({
      project_id: parseInt(projectId),
      requirement: aiRequirement.value,
      target: aiTarget.value || '',
    })
    // Backend returns { testcases: [...], conversation_id }
    aiGeneratedCases.value = data.testcases || []
    aiTestcaseIds.value = (data.testcases || []).map(tc => tc.id)
    aiConversationId.value = data.conversation_id || null
    if (aiGeneratedCases.value.length) {
      ElMessage.success(`AI 生成了 ${aiGeneratedCases.value.length} 个测试用例`)
    }
  } catch (e) {
    ElMessage.error(e.response?.data?.error || 'AI 生成失败')
  } finally {
    aiGenerating.value = false
  }
}

const handleAIFeedback = async () => {
  if (!aiFeedback.value) return
  aiAdjusting.value = true
  try {
    // Build current_cases for the API (strip id/created_at etc, keep relevant fields)
    const currentCases = aiGeneratedCases.value.map(tc => ({
      name: tc.name,
      description: tc.description || '',
      steps: tc.steps || '',
      expected_result: tc.expected_result || '',
      priority: tc.priority || '',
      test_type: tc.test_type || '',
      markdown_content: tc.markdown_content || '',
    }))
    const { data } = await aiAdjustTestCase({
      project_id: parseInt(projectId),
      conversation_id: aiConversationId.value,
      user_feedback: aiFeedback.value,
      current_cases: currentCases,
      testcase_ids: aiTestcaseIds.value,
    })
    aiGeneratedCases.value = data.testcases || []
    aiConversationId.value = data.conversation_id || aiConversationId.value
    aiFeedback.value = ''
    expandedCaseIdx.value = -1
    ElMessage.success('用例已更新')
  } catch (e) {
    ElMessage.error(e.response?.data?.error || 'AI 调整失败')
  } finally {
    aiAdjusting.value = false
  }
}

const handleAISaveAll = async () => {
  if (!aiGeneratedCases.value.length) return
  aiSaving.value = true
  try {
    // Cases are already saved in DB during generation and updated during adjustment.
    // Just reload from DB to refresh the list.
    const count = aiGeneratedCases.value.length
    await loadData()
    showAIGenerate.value = false
    resetAIDialog()
    ElMessage.success(`已保存 ${count} 个测试用例`)
  } finally {
    aiSaving.value = false
  }
}

const resetAIDialog = () => {
  aiGeneratedCases.value = []
  aiTestcaseIds.value = []
  aiConversationId.value = null
  aiFeedback.value = ''
  aiTarget.value = ''
  expandedCaseIdx.value = -1
}

const toggleCasePreview = (idx) => {
  expandedCaseIdx.value = expandedCaseIdx.value === idx ? -1 : idx
}

const renderCaseMarkdown = (md) => {
  if (!md) return ''
  return marked.parse(md)
}

const showDetail = (row) => {
  detailTC.value = row
  showDetailDialog.value = true
}

const handleViewExecutions = async (row) => {
  executionDetail.value = null
  executionDetailLoading.value = true
  showExecutionDetail.value = true
  try {
    const { data } = await getExecutions({ testcase: row.id })
    const records = data.results || data
    if (records.length > 0) {
      executionDetail.value = records[0]  // 最近一次执行
    }
  } catch (e) {
    // ignore
  } finally {
    executionDetailLoading.value = false
  }
}

const handlePreviewImage = (src) => {
  previewImage.value = src
  showImagePreview.value = true
}

onMounted(loadData)
</script>

<style scoped>
.markdown-body {
  max-height: 65vh;
  overflow-y: auto;
  padding: 16px;
  line-height: 1.6;
}
.markdown-body :deep(h1) {
  font-size: 1.5em;
  border-bottom: 1px solid #eaecef;
  padding-bottom: 0.3em;
  margin-bottom: 16px;
}
.markdown-body :deep(h2) {
  font-size: 1.3em;
  border-bottom: 1px solid #eaecef;
  padding-bottom: 0.3em;
  margin: 24px 0 12px;
}
.markdown-body :deep(h3) {
  font-size: 1.1em;
  margin: 18px 0 8px;
}
.markdown-body :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 12px 0;
}
.markdown-body :deep(th),
.markdown-body :deep(td) {
  border: 1px solid #dfe2e5;
  padding: 8px 12px;
  text-align: left;
}
.markdown-body :deep(th) {
  background-color: #f6f8fa;
  font-weight: 600;
}
.markdown-body :deep(code) {
  background-color: #f0f0f0;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 0.9em;
}
.markdown-body :deep(pre) {
  background-color: #f6f8fa;
  padding: 12px;
  border-radius: 6px;
  overflow-x: auto;
}
.markdown-body :deep(pre code) {
  background: none;
  padding: 0;
}
.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  padding-left: 24px;
  margin: 8px 0;
}
.markdown-body :deep(li) {
  margin: 4px 0;
}
.markdown-body :deep(blockquote) {
  border-left: 4px solid #dfe2e5;
  padding: 0 16px;
  color: #6a737d;
  margin: 12px 0;
}
.markdown-body :deep(strong) {
  font-weight: 600;
}
.ai-case-item {
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: border-color 0.2s;
}
.ai-case-item:hover {
  border-color: #409eff;
}
.ai-case-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
}
.ai-case-name {
  font-weight: 500;
  font-size: 14px;
}
.ai-case-preview {
  border-top: 1px solid #ebeef5;
  padding: 12px;
  max-height: 40vh;
  overflow-y: auto;
  background-color: #fafafa;
  cursor: default;
}
.agent-response-box {
  background-color: #f6f8fa;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  padding: 12px;
  max-height: 200px;
  overflow-y: auto;
}
.md-editor-layout {
  display: flex;
  gap: 12px;
  margin-top: 12px;
}
.md-editor-left {
  flex: 1;
  display: flex;
  flex-direction: column;
}
.md-editor-right {
  flex: 1;
  display: flex;
  flex-direction: column;
}
.md-editor-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 6px;
  font-weight: 600;
}
.md-textarea {
  flex: 1;
  min-height: 400px;
  padding: 12px;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 13px;
  line-height: 1.6;
  resize: vertical;
  outline: none;
}
.md-textarea:focus {
  border-color: #409eff;
}
.md-preview {
  flex: 1;
  min-height: 400px;
  padding: 12px;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  overflow-y: auto;
  background: #fafafa;
}
</style>
