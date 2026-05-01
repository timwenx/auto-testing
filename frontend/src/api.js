import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

// AI 专用实例（更长超时）
const aiApi = axios.create({
  baseURL: '/api',
  timeout: 120000,
  headers: { 'Content-Type': 'application/json' },
})

// ─── 项目 ───
export const getProjects = (params) => api.get('/projects/', { params })
export const getProject = (id) => api.get(`/projects/${id}/`)
export const createProject = (data) => api.post('/projects/', data)
export const updateProject = (id, data) => api.put(`/projects/${id}/`, data)
export const deleteProject = (id) => api.delete(`/projects/${id}/`)

// ─── 测试用例 ───
export const getTestCases = (params) => api.get('/testcases/', { params })
export const getTestCase = (id) => api.get(`/testcases/${id}/`)
export const createTestCase = (data) => api.post('/testcases/', data)
export const updateTestCase = (id, data) => api.put(`/testcases/${id}/`, data)
export const deleteTestCase = (id) => api.delete(`/testcases/${id}/`)
export const getProjectTestCases = (projectId) => api.get(`/projects/${projectId}/testcases/`)
export const reorderTestcases = (projectId, orders) => api.post(`/projects/${projectId}/testcases/reorder/`, { orders })
export const getFeatureGroups = (projectId) => api.get(`/projects/${projectId}/feature-groups/`)

// ─── 执行 ───
export const getExecutions = (params) => api.get('/executions/', { params })
export const getExecution = (id) => api.get(`/executions/${id}/`)
export const getExecutionSteps = (id) => api.get(`/executions/${id}/steps/`)
export const executeTestCaseAgent = (testcaseId) => aiApi.post(`/testcases/${testcaseId}/execute-agent/`)
export const executeProjectAgent = (projectId) => aiApi.post(`/projects/${projectId}/execute-agent/`)

// ─── 脚本回放 ───
export const convertToScript = (id) => aiApi.post(`/executions/${id}/convert-script/`)
export const getReplayScript = (id) => api.get(`/executions/${id}/replay-script/`)
export const updateReplayScript = (id, data) => api.put(`/executions/${id}/replay-script/update/`, data)
export const replayExecute = (id, overrides) => aiApi.post(`/executions/${id}/replay-execute/`, overrides || {})

// ─── AI ───
export const getAIConversations = (params) => api.get('/ai/conversations/', { params })
export const aiGenerateTestCase = (data) => aiApi.post('/ai/generate-testcase/', data)
export const aiAnalyzeResult = (data) => aiApi.post('/ai/analyze-result/', data)
export const aiAdjustTestCase = (data) => aiApi.post('/ai/adjust-testcase/', data)

// ─── Agent API ───
export const agentGenerate = (data) => aiApi.post('/agent/generate/', data)
export const agentRefine = (data) => aiApi.post('/agent/refine/', data)
export const agentConfirm = (data) => aiApi.post('/agent/confirm/', data)
export const agentExecute = (data) => aiApi.post('/agent/execute/', data)

// ─── 系统 ───
export const healthCheck = () => api.get('/health/')
export const getStats = () => api.get('/stats/')

// ─── 系统设置 ───
export const getSettings = () => api.get('/settings/')
export const updateSettings = (data) => api.put('/settings/', { settings: data })
export const checkCliAvailable = (cliPath) => api.get('/settings/cli-check/', { params: { cli_path: cliPath } })

// ─── 仓库分析 + 批量用例生成 ───
export const repoPull = (projectId) => aiApi.post(`/projects/${projectId}/repo/pull/`)
export const repoAnalyze = (projectId) => aiApi.post(`/projects/${projectId}/repo/analyze/`)
export const getRepoAnalysis = (projectId) => api.get(`/projects/${projectId}/repo/analysis/`)
export const resetRepoAnalysis = (projectId) => api.post(`/projects/${projectId}/repo/analysis/reset/`)
export const getRepoAnalysisList = (projectId) => api.get(`/projects/${projectId}/repo/analysis/list/`)
export const batchGenerateTestcases = (projectId, data) => aiApi.post(`/projects/${projectId}/batch-generate/`, data)
export const batchSaveTestcases = (projectId, data) => api.post(`/projects/${projectId}/batch-save/`, data)

// ─── 生成草稿（页面状态持久化） ───
export const getGenerationDraft = (projectId) => api.get(`/projects/${projectId}/generation-draft/`)
export const saveGenerationDraft = (projectId, draft) => api.post(`/projects/${projectId}/generation-draft/`, { draft })
export const clearGenerationDraft = (projectId) => api.delete(`/projects/${projectId}/generation-draft/`)

// ─── 前置条件模板 ───
export const getPreconditions = () => api.get('/preconditions/')
export const createPrecondition = (data) => api.post('/preconditions/create/', data)
export const updatePrecondition = (id, data) => api.put(`/preconditions/${id}/`, data)
export const deletePrecondition = (id) => api.delete(`/preconditions/${id}/delete/`)

// ─── Script API ───
export const getScripts = (params) => api.get('/scripts/', { params })
export const getScript = (id) => api.get(`/scripts/${id}/`)
export const convertToScriptModel = (data) => aiApi.post('/scripts/convert/', data)
export const updateScript = (id, data) => api.put(`/scripts/${id}/update/`, data)
export const deleteScript = (id) => api.delete(`/scripts/${id}/delete/`)
export const executeScript = (id, data) => aiApi.post(`/scripts/${id}/execute/`, data || {})
export const getScriptFeatureGroups = (projectId) => api.get('/scripts/feature-groups/', { params: { project: projectId } })

// ─── Feature 分组执行 ───
export const executeFeatureGroup = (projectId, featureGroup) =>
  aiApi.post(`/projects/${projectId}/features/${encodeURIComponent(featureGroup)}/execute/`)
export const getFeatureGroupsDetail = (projectId) =>
  api.get(`/projects/${projectId}/feature-groups/`, { params: { detailed: true } })

// ─── TestPlan API ───
export const getPlans = (params) => api.get('/plans/', { params })
export const createPlan = (data) => api.post('/plans/create/', data)
export const getPlan = (id) => api.get(`/plans/${id}/`)
export const updatePlan = (id, data) => api.put(`/plans/${id}/update/`, data)
export const deletePlan = (id) => api.delete(`/plans/${id}/delete/`)
export const addPlanItem = (planId, data) => api.post(`/plans/${planId}/items/`, data)
export const reorderPlanItems = (planId, orders) => api.put(`/plans/${planId}/items/reorder/`, { orders })
export const deletePlanItem = (itemId) => api.delete(`/plans/items/${itemId}/delete/`)
export const regeneratePlanToken = (planId) => api.post(`/plans/${planId}/regenerate-token/`)

// ─── PlanExecution API ───
export const executePlan = (planId, sync = false) =>
  aiApi.post(`/plans/${planId}/execute/${sync ? '?sync=true' : ''}`)
export const getPlanExecutions = (params) => api.get('/plan-executions/', { params })
export const getPlanExecution = (id) => api.get(`/plan-executions/${id}/`)
export const getPlanExecutionStatus = (id) => api.get(`/plan-executions/${id}/status/`)
export const getPlanExecutionReport = (id) => api.get(`/plan-executions/${id}/report/`)

export default api
