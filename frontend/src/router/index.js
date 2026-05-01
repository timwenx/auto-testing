import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    name: 'Dashboard',
    component: () => import('../views/Dashboard.vue'),
  },
  {
    path: '/projects',
    name: 'Projects',
    component: () => import('../views/Projects.vue'),
  },
  {
    path: '/projects/:id',
    name: 'ProjectDetail',
    component: () => import('../views/ProjectDetail.vue'),
  },
  {
    path: '/projects/:id/testcases/manage',
    name: 'TestCaseManager',
    component: () => import('../views/TestCaseManager.vue'),
  },
  {
    path: '/executions',
    name: 'Executions',
    component: () => import('../views/Executions.vue'),
  },
  {
    path: '/scripts',
    name: 'Scripts',
    component: () => import('../views/ScriptList.vue'),
  },
  {
    path: '/plans',
    name: 'TestPlans',
    component: () => import('../views/TestPlanView.vue'),
  },
  {
    path: '/plan-executions/:id',
    name: 'PlanExecutionDetail',
    component: () => import('../views/PlanExecutionDetailPage.vue'),
  },
  {
    path: '/executions/:id/observe',
    name: 'ExecutionObserver',
    component: () => import('../views/ExecutionObserver.vue'),
  },
  {
    path: '/executions/:id/script',
    name: 'ScriptEditor',
    component: () => import('../views/ScriptEditorView.vue'),
  },
  {
    path: '/settings',
    name: 'Settings',
    component: () => import('../views/Settings.vue'),
  },
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/Login.vue'),
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
