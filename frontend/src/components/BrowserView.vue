<template>
  <div class="browser-view" :class="{ 'pip-mode': pip, 'fullscreen-mode': fullscreen }">
    <!-- 画面区 -->
    <div class="frame-wrapper">
      <transition name="fade" mode="out-in">
        <img
          v-if="frameSrc && !imgError"
          :key="frameKey"
          :src="frameSrc"
          alt="Browser frame"
          class="browser-frame"
          @error="imgError = true"
        />
        <div v-else class="frame-placeholder">
          <el-icon :size="32" :color="placeholderIconColor" :class="{ 'is-loading': placeholderLoading }"><Loading /></el-icon>
          <span>{{ placeholderText }}</span>
        </div>
      </transition>
    </div>

    <!-- 控制栏 -->
    <div class="frame-controls">
      <el-tooltip content="刷新连接" placement="top">
        <el-button size="small" circle @click="$emit('refresh')">
          <el-icon><Refresh /></el-icon>
        </el-button>
      </el-tooltip>
      <el-tooltip :content="pip ? '退出画中画' : '画中画模式'" placement="top">
        <el-button size="small" circle @click="$emit('toggle-pip')">
          <el-icon><CopyDocument /></el-icon>
        </el-button>
      </el-tooltip>
      <el-tooltip :content="fullscreen ? '退出全屏' : '全屏'" placement="top">
        <el-button size="small" circle @click="$emit('toggle-fullscreen')">
          <el-icon><FullScreen /></el-icon>
        </el-button>
      </el-tooltip>
      <span class="frame-fps" v-if="frameSrc">{{ fpsDisplay }}</span>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, computed } from 'vue'
import { Loading, Refresh, CopyDocument, FullScreen } from '@element-plus/icons-vue'

const props = defineProps({
  frameSrc: { type: String, default: null },
  pip: { type: Boolean, default: false },
  fullscreen: { type: Boolean, default: false },
  executionStatus: { type: String, default: 'idle' },
  phase: { type: [String, Object], default: null },
})

defineEmits(['refresh', 'toggle-pip', 'toggle-fullscreen'])

// 帧计数器（用于 key 触发 transition）
const frameCount = ref(0)
const frameKey = computed(() => `frame-${frameCount.value}`)

// 图片加载失败时回退到占位符
const imgError = ref(false)

// FPS 统计
const fps = ref(0)
let frameTimestamps = []

watch(() => props.frameSrc, () => {
  if (!props.frameSrc) return
  imgError.value = false
  frameCount.value++

  // FPS 计算
  const now = Date.now()
  frameTimestamps.push(now)
  // 保留最近 5 秒的帧
  frameTimestamps = frameTimestamps.filter(t => now - t < 5000)
  const elapsed = (now - Math.min(...frameTimestamps)) / 1000
  fps.value = elapsed > 0 ? Math.round(frameTimestamps.length / elapsed) : 0
})

const fpsDisplay = computed(() => {
  if (fps.value <= 0) return ''
  return `${fps.value} fps`
})

// 阶段描述映射
const PHASE_TEXT = {
  initializing_browser: '正在启动浏览器...',
  browser_ready: '浏览器就绪',
  waiting_for_claude: '正在等待 Claude 响应...',
  executing_step: '正在执行步骤...',
}

const placeholderText = computed(() => {
  const execStatus = props.executionStatus
  if (execStatus === 'completed' || execStatus === 'passed') {
    return '执行已完成'
  }
  if (execStatus === 'failed') {
    return '执行失败'
  }
  if (execStatus === 'error') {
    return '执行异常'
  }
  // 有阶段信息时优先显示阶段描述
  if (props.phase) {
    const phaseKey = typeof props.phase === 'object' ? props.phase.phase : props.phase
    const phaseData = typeof props.phase === 'object' ? props.phase : {}
    if (PHASE_TEXT[phaseKey]) {
      // executing_step 阶段显示步骤编号和工具名
      if (phaseKey === 'executing_step' && phaseData.step_num) {
        const toolName = phaseData.tool_name ? `: ${phaseData.tool_name}` : ''
        return `正在执行步骤 ${phaseData.step_num}${toolName}...`
      }
      return PHASE_TEXT[phaseKey]
    }
  }
  if (execStatus === 'running') {
    return '等待浏览器启动...'
  }
  if (execStatus === 'connected') {
    return '已连接，等待执行...'
  }
  if (execStatus === 'idle' || execStatus === 'connecting') {
    return '连接中...'
  }
  return '等待中...'
})

const placeholderLoading = computed(() => {
  const execStatus = props.executionStatus
  return execStatus !== 'completed' && execStatus !== 'passed' && execStatus !== 'failed' && execStatus !== 'error'
})

const placeholderIconColor = computed(() => {
  const execStatus = props.executionStatus
  if (execStatus === 'completed' || execStatus === 'passed') return 'var(--el-color-success)'
  if (execStatus === 'failed' || execStatus === 'error') return 'var(--el-color-danger)'
  return 'var(--el-text-color-placeholder)'
})
</script>

<style scoped>
.browser-view {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  position: relative;
}

.browser-view.pip-mode {
  position: fixed;
  bottom: 20px;
  right: 20px;
  width: 320px;
  height: 200px;
  z-index: 1000;
  border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25);
  overflow: hidden;
  background: #000;
}

.browser-view.fullscreen-mode {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  z-index: 9999;
  background: #000;
}

.frame-wrapper {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: #1a1a2e;
}

.browser-frame {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  border-radius: 2px;
}

.frame-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  color: var(--el-text-color-placeholder);
  font-size: 14px;
}

.frame-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  background: var(--el-fill-color-darker);
  border-top: 1px solid var(--el-border-color-darker);
}

.frame-fps {
  margin-left: auto;
  font-size: 11px;
  color: var(--el-text-color-placeholder);
}

/* 帧切换过渡 */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0.6;
}
</style>
