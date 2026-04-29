<template>
  <el-card class="login-card" shadow="always">
    <template #header>
      <div style="text-align: center">
        <h2 style="margin: 0; color: #303133">MyTest</h2>
        <p style="color: #909399; margin-top: 8px; font-size: 14px">AI 驱动的自动化测试平台</p>
      </div>
    </template>
    <el-form :model="form" label-width="0" @keyup.enter="handleLogin">
      <el-form-item>
        <el-input v-model="form.username" placeholder="用户名" prefix-icon="User" size="large" />
      </el-form-item>
      <el-form-item>
        <el-input v-model="form.password" placeholder="密码" type="password" prefix-icon="Lock" size="large" show-password />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" style="width: 100%" size="large" @click="handleLogin" :loading="loading">
          登录
        </el-button>
      </el-form-item>
      <div style="text-align: center; color: #909399; font-size: 13px">
        <span>默认账号: admin / admin123</span>
      </div>
    </el-form>
  </el-card>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

const router = useRouter()
const loading = ref(false)
const form = ref({ username: '', password: '' })

const handleLogin = () => {
  if (!form.value.username || !form.value.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  // 简单的前端模拟登录（后续可接 JWT）
  if (form.value.username === 'admin' && form.value.password === 'admin123') {
    localStorage.setItem('mytest_token', 'dev-token')
    localStorage.setItem('mytest_user', form.value.username)
    ElMessage.success('登录成功')
    router.push('/')
  } else {
    ElMessage.error('用户名或密码错误')
  }
}
</script>

<style scoped>
.login-card {
  width: 400px;
  border-radius: 12px;
}
</style>
