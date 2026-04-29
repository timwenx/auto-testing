<template>
  <div>
    <el-card>
      <template #header>
        <div class="card-header">
          <span>AI 对话记录</span>
          <el-select v-model="typeFilter" placeholder="筛选类型" clearable size="small" style="width: 150px">
            <el-option label="生成用例" value="generate" />
            <el-option label="分析结果" value="analyze" />
            <el-option label="自由对话" value="chat" />
          </el-select>
        </div>
      </template>

      <el-table :data="conversations" style="width: 100%" v-loading="loading">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="conversation_type" label="类型" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="typeTag(row.conversation_type)">
              {{ typeLabel(row.conversation_type) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="project_name" label="项目" width="150" />
        <el-table-column prop="user_message" label="用户消息" show-overflow-tooltip />
        <el-table-column prop="created_at" label="时间" width="180" />
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="showDetail(row)">查看</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 详情弹窗 -->
    <el-dialog v-model="showDetailDialog" title="AI 对话详情" width="700px">
      <template v-if="detailConv">
        <h4>用户消息</h4>
        <div class="msg-block user">{{ detailConv.user_message }}</div>
        <h4 style="margin-top: 16px">AI 回复</h4>
        <pre class="msg-block ai">{{ detailConv.ai_response }}</pre>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { getAIConversations } from '../api'

const conversations = ref([])
const loading = ref(false)
const typeFilter = ref('')
const showDetailDialog = ref(false)
const detailConv = ref(null)

const typeLabel = (t) => ({ generate: '生成', analyze: '分析', chat: '对话' })[t] || t
const typeTag = (t) => ({ generate: 'primary', analyze: 'success', chat: 'info' })[t] || 'info'

const loadConversations = async () => {
  loading.value = true
  try {
    const params = {}
    if (typeFilter.value) params.type = typeFilter.value
    const { data } = await getAIConversations(params)
    conversations.value = data.results || data
  } finally {
    loading.value = false
  }
}

const showDetail = (row) => {
  detailConv.value = row
  showDetailDialog.value = true
}

watch(typeFilter, loadConversations)
onMounted(loadConversations)
</script>

<style scoped>
.msg-block {
  background: #f5f7fa;
  padding: 16px;
  border-radius: 4px;
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
}
.msg-block.ai {
  background: #ecf5ff;
  font-family: 'Consolas', monospace;
  font-size: 13px;
  max-height: 400px;
  overflow-y: auto;
}
</style>
