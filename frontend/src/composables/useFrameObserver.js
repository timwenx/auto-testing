/**
 * useFrameObserver — 步骤截图管理 composable。
 *
 * 改为一个步骤一张截图的模式：
 * - 不再连接独立的 Frame WS 通道
 * - 通过 step_complete 事件中的 screenshot_path 刷新截图
 * - 调用 updateFrame(step) 更新当前显示的截图
 *
 * 用法:
 *   const { currentFrame, updateFrame, clearFrame, showLatestStepScreenshot } = useFrameObserver()
 */
import { ref } from 'vue'

export function useFrameObserver(_executionId) {
  // ── 响应式状态 ──
  const currentFrame = ref(null)       // 当前截图帧 URL
  const frameWsStatus = ref('idle')    // 保持接口兼容

  /**
   * 根据步骤数据更新当前截图
   * @param {Object} step - 步骤数据（包含 screenshot_path 字段）
   */
  function updateFrame(step) {
    if (!step) return

    if (step.screenshot_path) {
      currentFrame.value = `/api/executions/screenshots/?path=${encodeURIComponent(step.screenshot_path)}`
    }
  }

  /**
   * 清除当前截图
   */
  function clearFrame() {
    currentFrame.value = null
  }

  /**
   * 从步骤列表中找到最后一张截图并显示
   * @param {Array} steps - 步骤列表
   */
  function showLatestStepScreenshot(steps) {
    if (!steps || steps.length === 0) return
    for (let i = steps.length - 1; i >= 0; i--) {
      if (steps[i].screenshot_path) {
        updateFrame(steps[i])
        return
      }
    }
  }

  // 兼容旧接口（不再实际连接 WS）
  function connectFrame() {}
  function disconnectFrame() {}

  return {
    currentFrame,
    frameWsStatus,
    updateFrame,
    clearFrame,
    showLatestStepScreenshot,
    connectFrame,
    disconnectFrame,
  }
}
