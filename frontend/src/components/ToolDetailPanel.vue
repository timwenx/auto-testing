<template>
  <div class="tool-detail-panel" v-if="step">
    <!-- 头部 -->
    <div class="panel-header">
      <span class="step-icon">{{ getIcon(step.tool_name || step.action) }}</span>
      <span class="panel-title">{{ getLabel(step) }}</span>
      <el-tag v-if="step.duration_ms" size="small" type="info" class="duration-tag">
        {{ formatDuration(step.duration_ms) }}
      </el-tag>
      <el-button class="close-btn" size="small" text circle @click="$emit('close')">
        <el-icon><Close /></el-icon>
      </el-button>
    </div>

    <!-- 内容区 -->
    <div class="panel-body">
      <!-- 目标 -->
      <div v-if="step.target" class="detail-section">
        <div class="section-label">目标</div>
        <div class="section-value target-value">{{ step.target }}</div>
      </div>

      <!-- 结果 -->
      <div v-if="step.result" class="detail-section">
        <div class="section-label">结果</div>
        <pre class="section-value result-value">{{ step.result }}</pre>
      </div>

      <!-- 截图预览 -->
      <div v-if="step.screenshot_path" class="detail-section">
        <div class="section-label">截图</div>
        <el-image
          :src="screenshotUrl"
          :preview-src-list="[screenshotUrl]"
          fit="contain"
          class="screenshot-preview"
        >
          <template #error>
            <div class="image-error">
              <el-icon><Picture /></el-icon>
              <span>加载失败</span>
            </div>
          </template>
        </el-image>
      </div>

      <!-- 时间戳 -->
      <div v-if="step.timestamp" class="detail-section">
        <div class="section-label">时间</div>
        <span class="section-value">{{ step.timestamp }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Close, Picture } from '@element-plus/icons-vue'

const props = defineProps({
  step: { type: Object, default: null },
})

defineEmits(['close'])

const ICON_MAP = {
  browser_navigate: '🌐', browser_click: '👆', browser_fill: '✏️',
  browser_press_key: '⌨️', browser_wait_for: '⏳', browser_get_text: '📋',
  browser_screenshot: '📸', list_files: '📂', read_file: '📄',
  search_code: '🔍', list_directory: '📁', report_result: '📊',
}

function getIcon(action) {
  return ICON_MAP[action] || '⚙️'
}

function getLabel(step) {
  const toolName = step.tool_name || step.action || ''
  // 如果 action 已经是人类可读格式（来自实时持久化），直接使用
  if (step.tool_name && step.action !== step.tool_name) {
    return step.action
  }
  // 否则从原始工具名生成标签（兼容旧数据或 WS 实时事件）
  if (toolName === 'browser_fill') return `填写 ${step.target || ''}`
  if (toolName === 'browser_navigate') return `导航到 ${step.target || ''}`
  if (toolName === 'browser_click') return `点击 ${step.target || ''}`
  if (toolName === 'browser_screenshot') return '截图'
  if (toolName === 'report_result') return `报告结果: ${step.target || ''}`
  return step.action || '未知操作'
}

function formatDuration(ms) {
  if (ms >= 1000) return (ms / 1000).toFixed(1) + 's'
  return ms + 'ms'
}

const screenshotUrl = computed(() => {
  if (!props.step?.screenshot_path) return ''
  return '/api/executions/screenshots/?path=' + encodeURIComponent(props.step.screenshot_path)
})
</script>

<style scoped>
.tool-detail-panel {
  border-top: 1px solid var(--el-border-color-lighter);
  background: var(--el-bg-color);
  display: flex;
  flex-direction: column;
  max-height: 300px;
  overflow: hidden;
}

.panel-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  background: var(--el-fill-color-lighter);
  flex-shrink: 0;
}

.step-icon {
  font-size: 16px;
}

.panel-title {
  font-weight: 600;
  font-size: 14px;
  color: var(--el-text-color-primary);
}

.duration-tag {
  margin-left: 4px;
}

.close-btn {
  margin-left: auto;
}

.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px 16px;
}

.detail-section {
  margin-bottom: 12px;
}

.detail-section:last-child {
  margin-bottom: 0;
}

.section-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--el-text-color-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 4px;
}

.section-value {
  font-size: 13px;
  color: var(--el-text-color-primary);
}

.target-value {
  word-break: break-all;
  padding: 6px 10px;
  background: var(--el-fill-color-light);
  border-radius: 4px;
  font-family: monospace;
}

.result-value {
  background: var(--el-fill-color-light);
  padding: 8px 10px;
  border-radius: 4px;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 120px;
  overflow-y: auto;
  margin: 0;
}

.screenshot-preview {
  max-width: 280px;
  border-radius: 4px;
  border: 1px solid var(--el-border-color-lighter);
}

.image-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 20px;
  color: var(--el-text-color-placeholder);
}
</style>
