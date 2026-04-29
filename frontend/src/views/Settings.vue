<template>
  <div>
    <el-card style="max-width: 600px">
      <template #header>
        <span>系统设置</span>
      </template>
      <el-form :model="settings" label-width="120px" v-loading="loading">
        <el-divider content-position="left">AI 引擎</el-divider>
        <el-form-item label="Claude CLI 路径">
          <el-input v-model="settings.claude_cli_path" placeholder="claude" />
          <div class="form-hint">Claude CLI 可执行文件路径，已安装则保持默认</div>
        </el-form-item>
        <el-divider content-position="left">执行引擎</el-divider>
        <el-form-item label="最大并发数">
          <el-input-number v-model.number="settings.max_workers" :min="1" :max="10" />
          <div class="form-hint">同时执行的最大测试用例数量</div>
        </el-form-item>
        <el-form-item label="执行超时(秒)">
          <el-input-number v-model.number="settings.execution_timeout" :min="30" :max="600" />
          <div class="form-hint">单个用例的最大执行时间</div>
        </el-form-item>
        <el-divider content-position="left">前端</el-divider>
        <el-form-item label="API 地址">
          <el-input v-model="settings.api_base_url" placeholder="/api" />
          <div class="form-hint">后端 API 基础地址</div>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="handleSave" :loading="saving">保存设置</el-button>
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
import { getSettings, updateSettings, healthCheck } from '../api'
import { ElMessage } from 'element-plus'

const defaultSettings = {
  claude_cli_path: 'claude',
  max_workers: 3,
  execution_timeout: 120,
  api_base_url: '/api',
}

const settings = ref({ ...defaultSettings })
const healthOk = ref(false)
const loading = ref(false)
const saving = ref(false)

const loadSettings = async () => {
  loading.value = true
  try {
    const { data } = await getSettings()
    // 后端返回 {key: value} 字典
    settings.value = {
      claude_cli_path: data.claude_cli_path ?? defaultSettings.claude_cli_path,
      max_workers: parseInt(data.max_workers) || defaultSettings.max_workers,
      execution_timeout: parseInt(data.execution_timeout) || defaultSettings.execution_timeout,
      api_base_url: data.api_base_url ?? defaultSettings.api_base_url,
    }
  } catch {
    ElMessage.warning('无法加载设置，使用默认值')
  } finally {
    loading.value = false
  }
}

const handleSave = async () => {
  saving.value = true
  try {
    await updateSettings({
      claude_cli_path: String(settings.value.claude_cli_path),
      max_workers: String(settings.value.max_workers),
      execution_timeout: String(settings.value.execution_timeout),
      api_base_url: String(settings.value.api_base_url),
    })
    ElMessage.success('设置已保存')
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

const handleReset = async () => {
  saving.value = true
  try {
    await updateSettings({
      claude_cli_path: defaultSettings.claude_cli_path,
      max_workers: String(defaultSettings.max_workers),
      execution_timeout: String(defaultSettings.execution_timeout),
      api_base_url: defaultSettings.api_base_url,
    })
    settings.value = { ...defaultSettings }
    ElMessage.success('已恢复默认设置')
  } catch (e) {
    ElMessage.error('恢复默认失败')
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  await loadSettings()
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
