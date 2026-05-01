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

export default router
