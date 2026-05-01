import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    name: 'Dashboard',
    component: () => import('../views/Dashboard.vue'),
    meta: { title: '工作台' },
  },
  {
    path: '/projects',
    name: 'Projects',
    component: () => import('../views/Projects.vue'),
    meta: { title: '项目' },
  },
  {
    path: '/projects/:id',
    name: 'ProjectDetail',
    component: () => import('../views/ProjectDetail.vue'),
    meta: { title: '项目详情', parent: 'Projects', parentPath: '/projects' },
  },
  {
    path: '/executions',
    name: 'Executions',
    component: () => import('../views/Executions.vue'),
    meta: { title: '执行记录' },
  },
  {
    path: '/scripts',
    name: 'Scripts',
    component: () => import('../views/ScriptList.vue'),
    meta: { title: '脚本' },
  },
  {
    path: '/plans',
    name: 'TestPlans',
    component: () => import('../views/TestPlanView.vue'),
    meta: { title: '测试方案' },
  },
  {
    path: '/plan-executions/:id',
    name: 'PlanExecutionDetail',
    component: () => import('../views/PlanExecutionDetailPage.vue'),
    meta: { title: '执行详情', parent: 'TestPlans', parentPath: '/plans' },
  },
  {
    path: '/executions/:id/observe',
    name: 'ExecutionObserver',
    component: () => import('../views/ExecutionObserver.vue'),
    meta: { title: '执行观察', parent: 'Executions', parentPath: '/executions' },
  },
  {
    path: '/executions/:id/script',
    name: 'ScriptEditor',
    component: () => import('../views/ScriptEditorView.vue'),
    meta: { title: '脚本编辑', parent: 'Executions', parentPath: '/executions' },
  },
  {
    path: '/settings',
    name: 'Settings',
    component: () => import('../views/Settings.vue'),
    meta: { title: '系统设置' },
  },
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/Login.vue'),
    meta: { title: '登录', noLayout: true },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 路由守卫 — 未登录时重定向到登录页
router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('mytest_token')
  if (to.path !== '/login' && !token) {
    next('/login')
  } else if (to.path === '/login' && token) {
    next('/')
  } else {
    next()
  }
})

export default router
