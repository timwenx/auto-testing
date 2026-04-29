<template>
  <div>
    <el-card style="max-width: 600px">
      <template #header>
        <span>系统设置</span>
      </template>
      <el-form :model="settings" label-width="120px">
        <el-divider content-position="left">AI 引擎</el-divider>
        <el-form-item label="Claude CLI 路径">
          <el-input v-model="settings.claude_cli_path" placeholder="claude" />
          <div class="form-hint">Claude CLI 可执行文件路径，已安装则保持默认</div>
        </el-form-item>
        <el-divider content-position="left">执行引擎</el-divider>
        <el-form-item label="最大并发数">
          <el-input-number v-model="settings.max_workers" :min="1" :max="10" />
          <div class="form-hint">同时执行的最大测试用例数量</div>
        </el-form-item>
        <el-form-item label="执行超时(秒)">
          <el-input-number v-model="settings.execution_timeout" :min="30" :max="600" />
          <div class="form-hint">单个用例的最大执行时间</div>
        </el-form-item>
        <el-divider content-position="left">前端</el-divider>
        <el-form-item label="API 地址">
          <el-input v-model="settings.api_base_url" placeholder="/api" />
          <div class="form-hint">后端 API 基础地址</div>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="handleSave">保存设置</el-button>
          <el-button @click="handleReset">恢复默认</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card style="max-width: 600px; margin-top: 20px">
      <template #header>
        <span>系统信息</span>
      </template>
      <el-descriptions :column="1" border size="small">
        <el-descriptions-item label="后端状态">
          <el-tag :type="healthOk ? 'success' : 'danger'" size="small">
            {{ healthOk ? '正常' : '异常' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="版本">0.1.0</el-descriptions-item>
        <el-descriptions-item label="技术栈">Django + Vue3 + Playwright</el-descriptions-item>
      </el-descriptions>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { healthCheck } from '../api'
import { ElMessage } from 'element-plus'

const defaultSettings = {
  claude_cli_path: 'claude',
  max_workers: 3,
  execution_timeout: 120,
  api_base_url: '/api',
}

const settings = ref({ ...defaultSettings })
const healthOk = ref(false)

const handleSave = () => {
  localStorage.setItem('mytest_settings', JSON.stringify(settings.value))
  ElMessage.success('设置已保存')
}

const handleReset = () => {
  settings.value = { ...defaultSettings }
  localStorage.removeItem('mytest_settings')
  ElMessage.success('已恢复默认设置')
}

onMounted(async () => {
  // 加载本地存储的设置
  const saved = localStorage.getItem('mytest_settings')
  if (saved) {
    try {
      settings.value = { ...defaultSettings, ...JSON.parse(saved) }
    } catch {}
  }
  // 检查后端健康状态
  try {
    await healthCheck()
    healthOk.value = true
  } catch {
    healthOk.value = false
  }
})
</script>

<style scoped>
.form-hint {
  color: #909399;
  font-size: 12px;
  margin-top: 4px;
}
</style>
