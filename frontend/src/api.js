import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
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

// ─── 执行 ───
export const getExecutions = (params) => api.get('/executions/', { params })
export const getExecution = (id) => api.get(`/executions/${id}/`)
export const executeTestCase = (testcaseId) => api.post(`/testcases/${testcaseId}/execute/`)
export const executeProject = (projectId) => api.post(`/projects/${projectId}/execute-all/`)

// ─── AI ───
export const getAIConversations = (params) => api.get('/ai/conversations/', { params })
export const aiGenerateTestCase = (data) => api.post('/ai/generate-testcase/', data)
export const aiAnalyzeResult = (data) => api.post('/ai/analyze-result/', data)

// ─── 系统 ───
export const healthCheck = () => api.get('/health/')
export const getStats = () => api.get('/stats/')

export default api
