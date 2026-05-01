<template>
  <div v-if="route.meta?.noLayout" class="login-wrapper">
    <router-view />
  </div>
  <div v-else class="layout">
    <div class="sidebar-overlay" :class="{ visible: mobileMenuOpen }" @click="mobileMenuOpen = false" />
    <div class="sidebar" :class="{ collapsed: sidebarCollapsed, 'mobile-open': mobileMenuOpen }">
      <div class="logo">{{ sidebarCollapsed ? 'MT' : 'MyTest' }}</div>
      <el-menu
        :default-active="sidebarActive"
        router
        background-color="#304156"
        text-color="#bfcbd9"
        active-text-color="#409eff"
        @select="handleMenuSelect"
      >
        <el-menu-item index="/">
          <el-icon><Odometer /></el-icon>
          <span>工作台</span>
        </el-menu-item>
        <el-menu-item index="/projects">
          <el-icon><Folder /></el-icon>
          <span>项目</span>
        </el-menu-item>
        <el-menu-item index="/scripts">
          <el-icon><Document /></el-icon>
          <span>脚本</span>
        </el-menu-item>
        <el-menu-item index="/plans">
          <el-icon><List /></el-icon>
          <span>测试方案</span>
        </el-menu-item>
        <el-menu-item index="/executions">
          <el-icon><VideoPlay /></el-icon>
          <span>执行记录</span>
        </el-menu-item>
        <el-menu-item index="/settings">
          <el-icon><Setting /></el-icon>
          <span>系统设置</span>
        </el-menu-item>
      </el-menu>
    </div>
    <div class="main-area">
      <div class="header">
        <div style="display: flex; align-items: center">
          <div class="sidebar-toggle" @click="toggleSidebar">
            <el-icon :size="20"><Fold v-if="!sidebarCollapsed" /><Expand v-else /></el-icon>
          </div>
          <el-breadcrumb separator="/" class="breadcrumb">
            <el-breadcrumb-item :to="'/'">首页</el-breadcrumb-item>
            <el-breadcrumb-item v-if="breadcrumbs.parent" :to="breadcrumbs.parentPath">
              {{ breadcrumbs.parent }}
            </el-breadcrumb-item>
            <el-breadcrumb-item v-if="breadcrumbs.current">
              {{ breadcrumbs.current }}
            </el-breadcrumb-item>
          </el-breadcrumb>
        </div>
        <div class="header-right">
          <span class="username">{{ currentUser }}</span>
          <el-button text @click="handleLogout">
            <el-icon><SwitchButton /></el-icon> 退出
          </el-button>
        </div>
      </div>
      <div class="content">
        <router-view />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'

const route = useRoute()
const router = useRouter()

const sidebarCollapsed = ref(false)
const mobileMenuOpen = ref(false)
const isMobile = ref(false)

function checkMobile() {
  isMobile.value = window.innerWidth <= 768
  if (!isMobile.value) {
    mobileMenuOpen.value = false
  }
}

onMounted(() => {
  checkMobile()
  window.addEventListener('resize', checkMobile)
})

onUnmounted(() => {
  window.removeEventListener('resize', checkMobile)
})

function toggleSidebar() {
  if (isMobile.value) {
    mobileMenuOpen.value = !mobileMenuOpen.value
  } else {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }
}

function handleMenuSelect() {
  if (isMobile.value) {
    mobileMenuOpen.value = false
  }
}

const currentUser = computed(() => localStorage.getItem('mytest_user') || 'admin')

const sidebarActive = computed(() => {
  const path = route.path
  if (path.startsWith('/projects')) return '/projects'
  if (path.startsWith('/scripts')) return '/scripts'
  if (path.startsWith('/plans') || path.startsWith('/plan-executions')) return '/plans'
  if (path.startsWith('/executions')) return '/executions'
  return path
})

const breadcrumbs = computed(() => {
  const meta = route.meta || {}
  return {
    parent: meta.parent ? getParentTitle(meta.parent) : null,
    parentPath: meta.parentPath || null,
    current: meta.title && meta.title !== '工作台' ? meta.title : null,
  }
})

const parentTitles = {
  Projects: '项目',
  TestPlans: '测试方案',
  Executions: '执行记录',
  Scripts: '脚本',
  Settings: '系统设置',
}

function getParentTitle(name) {
  return parentTitles[name] || name
}

async function handleLogout() {
  try {
    await ElMessageBox.confirm('确认退出登录？', '提示', { type: 'warning' })
  } catch { return }
  localStorage.removeItem('mytest_token')
  localStorage.removeItem('mytest_user')
  router.push('/login')
}
</script>

<style scoped>
.login-wrapper {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.username {
  font-size: 14px;
  color: #606266;
  font-weight: 500;
}
.breadcrumb {
  line-height: 1;
}
</style>
