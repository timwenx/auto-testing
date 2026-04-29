<template>
  <div v-if="route.path === '/login'" class="login-wrapper">
    <router-view />
  </div>
  <div v-else class="layout">
    <div class="sidebar">
      <div class="logo">MyTest</div>
      <el-menu
        :default-active="route.path"
        router
        background-color="#304156"
        text-color="#bfcbd9"
        active-text-color="#409eff"
      >
        <el-menu-item index="/">
          <el-icon><Odometer /></el-icon>
          <span>仪表盘</span>
        </el-menu-item>
        <el-menu-item index="/projects">
          <el-icon><Folder /></el-icon>
          <span>项目管理</span>
        </el-menu-item>
        <el-menu-item index="/executions">
          <el-icon><VideoPlay /></el-icon>
          <span>执行记录</span>
        </el-menu-item>
        <el-menu-item index="/ai">
          <el-icon><MagicStick /></el-icon>
          <span>AI 助手</span>
        </el-menu-item>
        <el-menu-item index="/settings">
          <el-icon><Setting /></el-icon>
          <span>系统设置</span>
        </el-menu-item>
      </el-menu>
    </div>
    <div class="main-area">
      <div class="header">
        <span class="page-title">{{ pageTitle }}</span>
        <el-button text @click="router.push('/login')">
          <el-icon><User /></el-icon>
        </el-button>
      </div>
      <div class="content">
        <router-view />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const pageTitleMap = {
  '/': '仪表盘',
  '/projects': '项目管理',
  '/executions': '执行记录',
  '/ai': 'AI 助手',
  '/settings': '系统设置',
  '/login': '登录',
}

const pageTitle = computed(() => {
  const path = route.path
  if (pageTitleMap[path]) return pageTitleMap[path]
  if (path.startsWith('/projects/')) return '项目详情'
  return 'MyTest'
})
</script>

<style scoped>
.login-wrapper {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}
</style>
