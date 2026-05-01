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
    <div v-show="activeStep === 0">
      <RepoStatusCard
        :project="project"
        @ready="onRepoReady"
      />
    </div>

    <!-- 步骤2-3: 代码分析 + 选择目标 -->
    <div v-show="activeStep >= 1 && activeStep <= 2">
      <CodeAnalysisPanel
        :project-id="projectId"
        :auto-start="activeStep === 1"
        @analysis-complete="onAnalysisComplete"
        @items-selected="onItemsSelected"
        @back="activeStep = 0"
      />
    </div>

    <!-- 步骤4: 生成用例 -->
    <div v-show="activeStep === 3">
      <div style="display: flex; gap: 16px; align-items: flex-start">
        <div style="flex: 1">
          <BatchTestCaseEditor
            :project-id="projectId"
            :selected-items="selectedItems"
            :descriptions="itemDescriptions"
            :precondition-id="selectedPreconditionId"
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
    <div v-show="activeStep === 4">
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
import { getProject } from '../api.js'
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

onMounted(async () => {
  try {
    const { data } = await getProject(projectId.value)
    project.value = data
    // 如果已有本地仓库路径，直接进入步骤1完成状态
    if (data.local_repo_path) {
      // 保持在步骤0，但显示已就绪状态
    }
  } catch (e) {
    ElMessage.error('加载项目失败')
  }
})

function onRepoReady() {
  activeStep.value = 1
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
}
</script>

<style scoped>
.testcase-manager {
  max-width: 1200px;
  margin: 0 auto;
  padding: 16px;
}
</style>
