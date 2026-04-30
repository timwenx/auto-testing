<template>
  <div>
    <el-card style="max-width: 600px">
      <template #header>
        <span>系统设置</span>
      </template>
      <el-form :model="settings" label-width="120px" v-loading="loading">
        <el-divider content-position="left">AI 引擎</el-divider>
        <el-form-item label="Anthropic API Key">
          <el-input v-model="settings.anthropic_api_key" placeholder="sk-ant-..." type="password" show-password />
          <div class="form-hint">Anthropic API Key，用于 AI 生成和分析测试用例</div>
        </el-form-item>
        <el-form-item label="API URL">
          <el-input v-model="settings.anthropic_base_url" placeholder="https://api.anthropic.com（留空使用默认）" />
          <div class="form-hint">Anthropic API 地址，支持自定义代理或兼容端点</div>
        </el-form-item>
        <el-form-item label="AI 模型">
          <el-input v-model="settings.anthropic_model" placeholder="claude-sonnet-4-20250514" />
          <div class="form-hint">输入模型名称，如 claude-sonnet-4-20250514、claude-opus-4-20250514</div>
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
        <el-form-item label="默认执行模式">
          <el-select v-model="settings.default_execution_mode" style="width: 200px">
            <el-option label="Script 模式" value="script" />
            <el-option label="Agent 模式" value="agent" />
          </el-select>
          <div class="form-hint">统一执行入口使用哪种模式</div>
        </el-form-item>
        <el-divider content-position="left">Agent 配置</el-divider>
        <el-form-item label="Agent 最大轮次">
          <el-input-number v-model.number="settings.agent_max_turns" :min="5" :max="50" />
          <div class="form-hint">Agent 单次执行最大工具调用轮次</div>
        </el-form-item>
        <el-form-item label="浏览器无头模式">
          <el-switch v-model="settings.agent_headless" active-text="是" inactive-text="否" />
          <div class="form-hint">无头模式下不显示浏览器窗口（生产环境建议开启）</div>
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
  anthropic_api_key: '',
  anthropic_base_url: '',
  anthropic_model: 'claude-sonnet-4-20250514',
  max_workers: 3,
  execution_timeout: 120,
  api_base_url: '/api',
  default_execution_mode: 'script',
  agent_max_turns: 20,
  agent_headless: true,
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
      anthropic_api_key: data.anthropic_api_key ?? defaultSettings.anthropic_api_key,
      anthropic_base_url: data.anthropic_base_url ?? defaultSettings.anthropic_base_url,
      anthropic_model: data.anthropic_model ?? defaultSettings.anthropic_model,
      max_workers: parseInt(data.max_workers) || defaultSettings.max_workers,
      execution_timeout: parseInt(data.execution_timeout) || defaultSettings.execution_timeout,
      api_base_url: data.api_base_url ?? defaultSettings.api_base_url,
      default_execution_mode: data.default_execution_mode ?? defaultSettings.default_execution_mode,
      agent_max_turns: parseInt(data.agent_max_turns) || defaultSettings.agent_max_turns,
      agent_headless: String(data.agent_headless ?? 'true').toLowerCase() === 'true',
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
      anthropic_api_key: String(settings.value.anthropic_api_key),
      anthropic_base_url: String(settings.value.anthropic_base_url),
      anthropic_model: String(settings.value.anthropic_model),
      max_workers: String(settings.value.max_workers),
      execution_timeout: String(settings.value.execution_timeout),
      api_base_url: String(settings.value.api_base_url),
      default_execution_mode: String(settings.value.default_execution_mode),
      agent_max_turns: String(settings.value.agent_max_turns),
      agent_headless: settings.value.agent_headless ? 'true' : 'false',
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
      anthropic_api_key: defaultSettings.anthropic_api_key,
      anthropic_base_url: defaultSettings.anthropic_base_url,
      anthropic_model: defaultSettings.anthropic_model,
      max_workers: String(defaultSettings.max_workers),
      execution_timeout: String(defaultSettings.execution_timeout),
      api_base_url: defaultSettings.api_base_url,
      default_execution_mode: defaultSettings.default_execution_mode,
      agent_max_turns: String(defaultSettings.agent_max_turns),
      agent_headless: defaultSettings.agent_headless ? 'true' : 'false',
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
