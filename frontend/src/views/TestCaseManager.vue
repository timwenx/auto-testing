<template>
  <div class="testcase-manager">
    <!-- 面包屑导航 -->
    <el-breadcrumb separator="/" style="margin-bottom: 16px">
      <el-breadcrumb-item :to="{ path: '/projects' }">项目列表</el-breadcrumb-item>
      <el-breadcrumb-item :to="{ path: '/projects/' + projectId }">
        {{ project?.name || '项目' }}
      </el-breadcrumb-item>
      <el-breadcrumb-item>用例管理</el-breadcrumb-item>
    </el-breadcrumb>

    <!-- 步骤条 -->
    <el-card style="margin-bottom: 16px">
      <el-steps :active="activeStep" finish-status="success" align-center>
        <el-step title="拉取仓库" />
        <el-step title="代码分析" />
        <el-step title="选择目标" />
        <el-step title="生成用例" />
        <el-step title="确认保存" />
      </el-steps>
    </el-card>

    <!-- 步骤1: 拉取仓库 -->
    <div v-if="activeStep === 0">
      <RepoStatusCard
        :project="project"
        @ready="onRepoReady"
        @project-updated="onProjectUpdated"
      />
    </div>

    <!-- 步骤2-3: 代码分析 + 选择目标 -->
    <div v-if="activeStep >= 1 && activeStep <= 2">
      <CodeAnalysisPanel
        :key="'analysis-' + analysisKey"
        :project-id="projectId"
        :auto-start="activeStep === 1"
        @analysis-complete="onAnalysisComplete"
        @items-selected="onItemsSelected"
        @back="activeStep = 0"
      />
    </div>

    <!-- 步骤4: 生成用例 -->
    <div v-if="activeStep === 3">
      <div style="display: flex; gap: 16px; align-items: flex-start">
        <div style="flex: 1">
          <BatchTestCaseEditor
            :key="'batch-' + batchKey"
            :project-id="projectId"
            :selected-items="selectedItems"
            :descriptions="itemDescriptions"
            :precondition-id="selectedPreconditionId"
            :initial-cases="initialDraftCases"
            @back="activeStep = 2"
            @save-complete="onSaveComplete"
          />
        </div>
        <div style="width: 320px; flex-shrink: 0">
          <PreconditionSelector
            v-model:selected-id="selectedPreconditionId"
          />
        </div>
      </div>
    </div>

    <!-- 步骤5: 保存完成 -->
    <div v-if="activeStep === 4">
      <el-card>
        <el-result icon="success" title="用例保存成功" :sub-title="'已保存 ' + savedCount + ' 条测试用例'">
          <template #extra>
            <el-button type="primary" @click="goBackToProject">返回项目详情</el-button>
            <el-button @click="restart">继续添加</el-button>
          </template>
        </el-result>
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getProject, getRepoAnalysis, getGenerationDraft, clearGenerationDraft } from '../api.js'
import RepoStatusCard from '../components/RepoStatusCard.vue'
import CodeAnalysisPanel from '../components/CodeAnalysisPanel.vue'
import PreconditionSelector from '../components/PreconditionSelector.vue'
import BatchTestCaseEditor from '../components/BatchTestCaseEditor.vue'

const route = useRoute()
const router = useRouter()
const projectId = ref(Number(route.params.id))

const project = ref(null)
const activeStep = ref(0)
const selectedItems = ref([])
const itemDescriptions = ref({})
const selectedPreconditionId = ref(null)
const savedCount = ref(0)
const analysisKey = ref(0)
const batchKey = ref(0)

// Initial draft data from server (used to restore BatchTestCaseEditor state)
const initialDraftCases = ref(null)
const initialDraftItems = ref(null)
const initialDraftDescriptions = ref(null)
const initialDraftPreconditionId = ref(null)

onMounted(async () => {
  try {
    const { data } = await getProject(projectId.value)
    project.value = data

    // Auto-restore wizard state based on persisted data
    await restoreWizardState(data)
  } catch (e) {
    ElMessage.error('加载项目失败')
  }
})

async function restoreWizardState(projectData) {
  // Step 0: Check if repo is already pulled
  if (!projectData.local_repo_path) {
    // No repo yet, stay at step 0
    return
  }

  // Check for existing generation draft first (highest priority - has generated cases)
  try {
    const { data } = await getGenerationDraft(projectId.value)
    const draft = data.draft || {}
    if (draft.generated_cases && draft.generated_cases.length > 0) {
      // Restore all state from the draft
      initialDraftCases.value = draft.generated_cases
      initialDraftItems.value = draft.selected_items || []
      initialDraftDescriptions.value = draft.descriptions || {}
      initialDraftPreconditionId.value = draft.precondition_id || null
      selectedItems.value = draft.selected_items || []
      itemDescriptions.value = draft.descriptions || {}
      selectedPreconditionId.value = draft.precondition_id || null
      activeStep.value = 3
      return
    }
  } catch (e) {
    // Draft fetch failed, continue with analysis check
  }

  // Check for existing repo analysis
  try {
    const { data } = await getRepoAnalysis(projectId.value)
    const analysis = data.analysis

    if (!analysis) {
      // Repo pulled but no analysis yet → step 0 (user clicks "next" to start)
      return
    }

    if (analysis.status === 'analyzing') {
      // Analysis in progress → step 1
      activeStep.value = 1
      return
    }

    if (analysis.status === 'completed') {
      // Analysis completed → step 2 (user can select targets)
      activeStep.value = 2
      return
    }

    if (analysis.status === 'failed') {
      // Analysis failed → step 1 (show failure, allow retry)
      activeStep.value = 1
      return
    }
  } catch (e) {
    // Analysis check failed, stay at step 0
  }
}

function onRepoReady() {
  activeStep.value = 1
}

function onProjectUpdated(data) {
  project.value = data
}

function onAnalysisComplete() {
  activeStep.value = 2
}

function onItemsSelected(items, descriptions) {
  selectedItems.value = items
  itemDescriptions.value = descriptions
  activeStep.value = 3
}

function onSaveComplete(count) {
  savedCount.value = count
  activeStep.value = 4
}

function goBackToProject() {
  router.push({ name: 'ProjectDetail', params: { id: projectId.value } })
}

function restart() {
  activeStep.value = 0
  selectedItems.value = []
  itemDescriptions.value = {}
  selectedPreconditionId.value = null
  initialDraftCases.value = null
  initialDraftItems.value = null
  initialDraftDescriptions.value = null
  initialDraftPreconditionId.value = null
  // Force child components to remount with fresh state
  analysisKey.value++
  batchKey.value++
  // Clear the server-side draft
  clearGenerationDraft(projectId.value).catch(() => {})
}
</script>

<style scoped>
.testcase-manager {
  max-width: 1200px;
  margin: 0 auto;
  padding: 16px;
}
</style>
