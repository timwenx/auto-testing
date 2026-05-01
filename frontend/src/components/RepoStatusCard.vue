<template>
  <el-card>
    <template #header>
      <div class="card-header">
        <span>Git 仓库</span>
        <el-tag :type="statusType" size="small">{{ statusText }}</el-tag>
      </div>
    </template>

    <el-descriptions :column="2" size="small" v-if="project">
      <el-descriptions-item label="仓库地址">{{ project.repo_url || '未配置' }}</el-descriptions-item>
      <el-descriptions-item label="本地路径">{{ project.local_repo_path || '未拉取' }}</el-descriptions-item>
    </el-descriptions>

    <div style="margin-top: 16px; text-align: center">
      <el-button
        v-if="!project?.repo_url"
        type="info"
        disabled
      >
        请先配置 Git 仓库地址
      </el-button>
      <el-button
        v-else
        type="primary"
        :loading="pulling"
        @click="handlePull"
      >
        {{ project?.local_repo_path ? '重新拉取仓库' : '拉取仓库' }}
      </el-button>
    </div>

    <div v-if="pulling" style="margin-top: 12px; text-align: center; color: #909399; font-size: 13px">
      <el-icon class="is-loading"><Loading /></el-icon> 正在拉取仓库代码...
    </div>
  </el-card>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { repoPull, getProject } from '../api.js'

const props = defineProps({
  project: { type: Object, default: null },
})
const emit = defineEmits(['ready'])

const pulling = ref(false)

const statusType = computed(() => {
  if (!props.project?.repo_url) return 'info'
  if (pulling.value) return 'warning'
  if (props.project?.local_repo_path) return 'success'
  return 'info'
})

const statusText = computed(() => {
  if (!props.project?.repo_url) return '未配置'
  if (pulling.value) return '拉取中'
  if (props.project?.local_repo_path) return '已就绪'
  return '未拉取'
})

async function handlePull() {
  if (!props.project?.id) return
  pulling.value = true
  try {
    await repoPull(props.project.id)
    // 刷新项目数据以更新 local_repo_path
    try {
      const { data } = await getProject(props.project.id)
      Object.assign(props.project, data)
    } catch { /* ignore refresh error */ }
    ElMessage.success('仓库拉取成功')
    emit('ready')
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '仓库拉取失败')
  } finally {
    pulling.value = false
  }
}
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>
