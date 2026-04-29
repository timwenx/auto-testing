<template>
  <el-dialog
    :model-value="visible"
    title="Agent 用例调整"
    width="800px"
    :close-on-click-modal="false"
    @close="$emit('close')"
  >
    <div class="agent-refine-container">
      <!-- 对话历史 -->
      <div class="chat-messages" ref="chatContainer">
        <div
          v-for="(msg, idx) in messages"
          :key="idx"
          class="chat-bubble"
          :class="msg.role"
        >
          <div class="bubble-header">
            <span v-if="msg.role === 'agent'" class="role-tag agent">Agent</span>
            <span v-else class="role-tag user">你</span>
            <span class="bubble-time">{{ msg.time }}</span>
          </div>
          <div class="bubble-content">
            <!-- Agent 消息 -->
            <template v-if="msg.role === 'agent'">
              <p>{{ msg.message }}</p>
              <!-- 建议标签 -->
              <div v-if="msg.suggestions && msg.suggestions.length" class="suggestions">
                <el-tag
                  v-for="(sug, si) in msg.suggestions"
                  :key="si"
                  class="suggestion-tag"
                  effect="plain"
                  @click="handleSuggestionClick(sug)"
                >
                  {{ sug }}
                </el-tag>
              </div>
              <!-- 更新预览 -->
              <div v-if="msg.updatedTestcase" class="updated-preview">
                <el-divider content-position="left">修改后的用例</el-divider>
                <div
                  class="markdown-body"
                  v-html="renderMarkdown(msg.updatedTestcase.markdown_content || buildMarkdown(msg.updatedTestcase))"
                ></div>
              </div>
            </template>
            <!-- 用户消息 -->
            <template v-else>
              <p>{{ msg.text }}</p>
            </template>
          </div>
        </div>

        <!-- 加载中 -->
        <div v-if="loading" class="chat-bubble agent loading-bubble">
          <div class="bubble-header">
            <span class="role-tag agent">Agent</span>
          </div>
          <div class="bubble-content">
            <el-icon class="is-loading"><Loading /></el-icon>
            <span style="margin-left: 8px">Agent 正在分析...</span>
          </div>
        </div>
      </div>

      <!-- 输入区 -->
      <div class="input-area">
        <el-input
          v-model="userInput"
          type="textarea"
          :rows="3"
          placeholder="输入你的修改意见，或点击上方建议标签..."
          :disabled="loading"
          @keydown.enter.ctrl="handleSend"
        />
        <div class="input-actions">
          <span class="hint">Ctrl+Enter 发送</span>
          <div>
            <el-button
              size="small"
              type="success"
              :disabled="!canConfirm"
              @click="handleConfirm"
            >
              确认用例
            </el-button>
            <el-button
              size="small"
              type="primary"
              :loading="loading"
              :disabled="!userInput || loading"
              @click="handleSend"
            >
              发送
            </el-button>
          </div>
        </div>
      </div>
    </div>
  </el-dialog>
</template>

<script setup>
import { ref, watch, nextTick, computed } from 'vue'
import { marked } from 'marked'
import { agentRefine, agentConfirm } from '../api'
import { ElMessage } from 'element-plus'

const props = defineProps({
  visible: { type: Boolean, default: false },
  testcaseId: { type: Number, default: null },
})

const emit = defineEmits(['close', 'updated'])

marked.setOptions({ breaks: true, gfm: true })

const messages = ref([])
const userInput = ref('')
const loading = ref(false)
const chatContainer = ref(null)
const hasUpdate = ref(false)

// 是否可以确认（至少有一次 update 或 Agent 已经修改过用例）
const canConfirm = computed(() => hasUpdate.value || messages.value.some(m => m.role === 'agent' && m.updatedTestcase))

// 打开时自动发起首次提问
watch(() => props.visible, async (val) => {
  if (val && props.testcaseId) {
    messages.value = []
    hasUpdate.value = false
    await fetchAgentResponse('')
  }
})

const scrollToBottom = () => {
  nextTick(() => {
    if (chatContainer.value) {
      chatContainer.value.scrollTop = chatContainer.value.scrollHeight
    }
  })
}

const now = () => {
  const d = new Date()
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
}

const fetchAgentResponse = async (feedback) => {
  loading.value = true
  try {
    const { data } = await agentRefine({
      testcase_id: props.testcaseId,
      user_feedback: feedback,
    })

    const agentMsg = {
      role: 'agent',
      message: data.message || '',
      suggestions: data.suggestions || [],
      updatedTestcase: data.updated_testcase || null,
      time: now(),
    }
    messages.value.push(agentMsg)

    if (data.action === 'update' && data.updated_testcase) {
      hasUpdate.value = true
      emit('updated', data.testcase)
    }

    scrollToBottom()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || 'Agent 请求失败')
  } finally {
    loading.value = false
  }
}

const handleSend = async () => {
  if (!userInput.value || loading.value) return
  const text = userInput.value.trim()
  messages.value.push({ role: 'user', text, time: now() })
  userInput.value = ''
  scrollToBottom()
  await fetchAgentResponse(text)
}

const handleSuggestionClick = async (suggestion) => {
  if (loading.value) return
  const text = `请考虑：${suggestion}`
  messages.value.push({ role: 'user', text, time: now() })
  scrollToBottom()
  await fetchAgentResponse(text)
}

const handleConfirm = async () => {
  try {
    await agentConfirm({ testcase_id: props.testcaseId })
    ElMessage.success('用例已确认为 ready 状态')
    emit('close')
    emit('updated')
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '确认失败')
  }
}

const renderMarkdown = (md) => {
  if (!md) return ''
  return marked.parse(md)
}

const buildMarkdown = (tc) => {
  let md = `# ${tc.name || ''}\n\n`
  if (tc.description) md += `**描述:** ${tc.description}\n\n`
  if (tc.steps) md += `## 测试步骤\n${tc.steps}\n\n`
  if (tc.expected_result) md += `## 预期结果\n${tc.expected_result}\n\n`
  return md
}
</script>

<style scoped>
.agent-refine-container {
  display: flex;
  flex-direction: column;
  height: 60vh;
}

.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  margin-bottom: 12px;
  background-color: #fafafa;
}

.chat-bubble {
  margin-bottom: 16px;
}

.bubble-header {
  display: flex;
  align-items: center;
  margin-bottom: 6px;
  gap: 8px;
}

.role-tag {
  font-size: 12px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
}

.role-tag.agent {
  background-color: #ecf5ff;
  color: #409eff;
}

.role-tag.user {
  background-color: #f0f9eb;
  color: #67c23a;
}

.bubble-time {
  font-size: 11px;
  color: #c0c4cc;
}

.bubble-content {
  padding: 10px 14px;
  border-radius: 8px;
  line-height: 1.6;
  font-size: 14px;
}

.chat-bubble.agent .bubble-content {
  background-color: #ffffff;
  border: 1px solid #e4e7ed;
  margin-left: 8px;
}

.chat-bubble.user .bubble-content {
  background-color: #ecf5ff;
  border: 1px solid #d9ecff;
  margin-right: 8px;
  margin-left: auto;
  max-width: 80%;
}

.chat-bubble.user {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}

.bubble-content p {
  margin: 0 0 8px 0;
}

.bubble-content p:last-child {
  margin-bottom: 0;
}

.suggestions {
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.suggestion-tag {
  cursor: pointer;
  transition: all 0.2s;
}

.suggestion-tag:hover {
  border-color: #409eff;
  color: #409eff;
}

.updated-preview {
  margin-top: 12px;
}

.updated-preview .markdown-body {
  max-height: 30vh;
  overflow-y: auto;
  padding: 12px;
  background-color: #f6f8fa;
  border-radius: 6px;
  line-height: 1.6;
}

.input-area {
  flex-shrink: 0;
}

.input-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 8px;
}

.input-actions .hint {
  font-size: 12px;
  color: #c0c4cc;
}

.loading-bubble .bubble-content {
  display: flex;
  align-items: center;
}
</style>
