<template>
  <div class="execution-timeline">
    <el-timeline v-if="steps.length > 0">
      <el-timeline-item
        v-for="(step, idx) in steps"
        :key="idx"
        :type="getStepType(step)"
        :hollow="step.state === 'running'"
        :timestamp="step.timestamp"
        placement="top"
      >
        <div class="step-card" :class="{ 'step-running': step.state === 'running', 'step-selected': selectedIdx === idx }"
             @click="$emit('select', idx, step)">
          <!-- 思维气泡 -->
          <template v-if="step.action === '__thinking__'">
            <div class="thinking-bubble">
              <span class="thinking-icon">🤖</span>
              <span class="thinking-label">Agent 思考中</span>
              <p class="thinking-text">{{ step.result }}</p>
            </div>
          </template>
          <!-- 普通步骤 -->
          <template v-else>
            <div class="step-header">
              <span class="step-icon">{{ getStepIcon(step.action) }}</span>
              <span class="step-action">{{ getStepLabel(step) }}</span>
              <el-tag v-if="step.state === 'running'" size="small" type="primary" effect="plain" class="step-status-tag">
                执行中
              </el-tag>
              <el-tag v-else-if="step.state === 'completed'" size="small" type="success" effect="plain" class="step-status-tag">
                ✓
              </el-tag>
            </div>
            <div v-if="step.target" class="step-target">{{ step.target }}</div>
            <div v-if="step.duration_ms" class="step-duration">
              {{ step.duration_ms >= 1000 ? (step.duration_ms / 1000).toFixed(1) + 's' : step.duration_ms + 'ms' }}
            </div>
          </template>
        </div>
      </el-timeline-item>
    </el-timeline>
    <div v-else class="timeline-empty">
      <el-icon class="is-loading" :size="24"><Loading /></el-icon>
      <span>等待步骤事件...</span>
    </div>
  </div>
</template>

<script setup>
import { Loading } from '@element-plus/icons-vue'

defineProps({
  steps: { type: Array, default: () => [] },
  selectedIdx: { type: Number, default: -1 },
})

defineEmits(['select'])

// ── 工具图标映射 ──
const ICON_MAP = {
  browser_navigate: '🌐',
  browser_click: '👆',
  browser_fill: '✏️',
  browser_press_key: '⌨️',
  browser_wait_for: '⏳',
  browser_get_text: '📋',
  browser_screenshot: '📸',
  list_files: '📂',
  read_file: '📄',
  search_code: '🔍',
  list_directory: '📁',
  report_result: '📊',
}

function getStepIcon(action) {
  return ICON_MAP[action] || '⚙️'
}

function getStepLabel(step) {
  if (step.action === 'browser_fill' && step.target) {
    return `填写 ${step.target}`
  }
  if (step.action === 'browser_navigate') {
    return `导航到 ${step.target || ''}`
  }
  if (step.action === 'browser_click') {
    return `点击 ${step.target || ''}`
  }
  if (step.action === 'browser_screenshot') {
    return '截图'
  }
  if (step.action === 'report_result') {
    return `报告结果: ${step.target || ''}`
  }
  return step.action || '未知操作'
}

function getStepType(step) {
  if (step.state === 'running') return 'primary'
  if (step.state === 'thinking') return 'info'
  return 'success'
}
</script>

<style scoped>
.execution-timeline {
  padding: 0 8px;
}

.step-card {
  padding: 8px 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: background-color 0.2s;
  border: 1px solid transparent;
}

.step-card:hover {
  background-color: var(--el-fill-color-light);
}

.step-card.step-running {
  background-color: var(--el-color-primary-light-9);
  border-color: var(--el-color-primary-light-5);
}

.step-card.step-selected {
  background-color: var(--el-fill-color);
  border-color: var(--el-color-primary);
}

.step-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.step-icon {
  font-size: 16px;
  flex-shrink: 0;
}

.step-action {
  font-weight: 500;
  font-size: 14px;
  color: var(--el-text-color-primary);
}

.step-status-tag {
  margin-left: auto;
}

.step-target {
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  word-break: break-all;
  padding-left: 24px;
}

.step-duration {
  margin-top: 2px;
  font-size: 11px;
  color: var(--el-text-color-placeholder);
  padding-left: 24px;
}

.thinking-bubble {
  background-color: var(--el-fill-color-light);
  border-radius: 8px;
  padding: 8px 12px;
  border-left: 3px solid var(--el-color-info);
}

.thinking-icon {
  margin-right: 6px;
}

.thinking-label {
  font-weight: 500;
  font-size: 13px;
  color: var(--el-text-color-regular);
}

.thinking-text {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
  white-space: pre-wrap;
}

.timeline-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 40px 0;
  color: var(--el-text-color-placeholder);
}
</style>
