/**
 * Unified status type mapping for Element Plus el-tag components.
 * Centralized to avoid duplication across components.
 */

/**
 * Test case / execution record status → el-tag type
 */
export function getStatusType(status) {
  const map = {
    draft: 'info',
    ready: '',
    running: 'warning',
    passed: 'success',
    failed: 'danger',
    error: 'danger',
    pending: 'info',
  }
  return map[status] || 'info'
}

/**
 * Script status → el-tag type
 */
export function getScriptStatusType(status) {
  const map = { active: 'success', draft: 'warning', archived: 'info' }
  return map[status] || 'info'
}

/**
 * Script status → display label
 */
export function getScriptStatusLabel(status) {
  const map = { active: '活跃', draft: '草稿', archived: '已归档' }
  return map[status] || status
}

/**
 * Test plan status → el-tag type
 */
export function getPlanStatusType(status) {
  const map = { draft: 'info', active: 'success', archived: 'info' }
  return map[status] || 'info'
}

/**
 * Plan execution status → el-tag type
 */
export function getExecStatusType(status) {
  const map = {
    pending: 'info',
    running: 'warning',
    completed: 'success',
    failed: 'danger',
    error: 'danger',
    passed: 'success',
  }
  return map[status] || 'info'
}

/**
 * Execution mode → el-tag type
 */
export function getExecutionModeType(row) {
  if (row.plan_execution) return 'warning'
  return (row.execution_mode || 'script') === 'agent' ? 'primary' : 'info'
}
