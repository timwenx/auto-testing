<template>
  <div class="plan-execution-detail" v-loading="loading">
    <template v-if="execution">
      <!-- 概要 -->
      <el-descriptions :column="4" border size="small" style="margin-bottom: 16px">
        <el-descriptions-item label="状态">
          <el-tag :type="statusType(execution.status)" size="small">{{ execution.status }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="触发方式">{{ execution.trigger_source }}</el-descriptions-item>
        <el-descriptions-item label="开始时间">{{ execution.started_at || '-' }}</el-descriptions-item>
        <el-descriptions-item label="完成时间">{{ execution.completed_at || '-' }}</el-descriptions-item>
      </el-descriptions>

      <!-- 统计卡片 -->
      <div v-if="execution.summary" class="summary-cards">
        <div class="summary-card">
          <div class="summary-value">{{ execution.summary.total || 0 }}</div>
          <div class="summary-label">总计</div>
        </div>
        <div class="summary-card passed">
          <div class="summary-value">{{ execution.summary.passed || 0 }}</div>
          <div class="summary-label">通过</div>
        </div>
        <div class="summary-card failed">
          <div class="summary-value">{{ (execution.summary.failed || 0) + (execution.summary.error || 0) }}</div>
          <div class="summary-label">失败</div>
        </div>
        <div class="summary-card skipped">
          <div class="summary-value">{{ execution.summary.skipped || 0 }}</div>
          <div class="summary-label">跳过</div>
        </div>
      </div>

      <!-- 子执行记录列表 -->
      <el-table :data="execution.execution_records || []" size="small" style="margin-top: 16px">
        <el-table-column prop="testcase_name" label="用例名称" min-width="160" />
        <el-table-column prop="status" label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="execution_mode" label="模式" width="70" />
        <el-table-column prop="duration" label="耗时" width="70">
          <template #default="{ row }">{{ row.duration ? row.duration.toFixed(1) + 's' : '-' }}</template>
        </el-table-column>
        <el-table-column prop="error_message" label="错误信息" min-width="200">
          <template #default="{ row }">
            <span v-if="row.error_message" style="color: #f56c6c; font-size: 12px">{{ row.error_message }}</span>
            <span v-else style="color: #67c23a">OK</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="$router.push(`/executions/${row.id}/observe`)">
              详情
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </template>
    <el-empty v-else-if="!loading" description="暂无执行记录" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getPlanExecution } from '../api'
import { ElMessage } from 'element-plus'

const props = defineProps({
  executionId: {
    type: Number,
    required: true,
  },
})

const execution = ref(null)
const loading = ref(false)

const statusType = (s) => {
  const map = { pending: 'info', running: 'warning', completed: 'success', failed: 'danger', error: 'danger', passed: 'success' }
  return map[s] || 'info'
}

async function loadData() {
  loading.value = true
  try {
    const { data } = await getPlanExecution(props.executionId)
    execution.value = data
  } catch (e) {
    ElMessage.error('加载执行详情失败')
  } finally {
    loading.value = false
  }
}

onMounted(loadData)
</script>

<style scoped>
.summary-cards {
  display: flex;
  gap: 16px;
  margin-top: 12px;
}
.summary-card {
  flex: 1;
  text-align: center;
  padding: 12px;
  border-radius: 6px;
  background: #f5f7fa;
}
.summary-card.passed {
  background: #f0f9eb;
}
.summary-card.failed {
  background: #fef0f0;
}
.summary-card.skipped {
  background: #fafafa;
}
.summary-value {
  font-size: 24px;
  font-weight: 700;
}
.summary-card.passed .summary-value {
  color: #67c23a;
}
.summary-card.failed .summary-value {
  color: #f56c6c;
}
.summary-label {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
</style>
