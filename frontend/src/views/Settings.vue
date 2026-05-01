<template>
  <div v-loading="loading">
    <el-form :model="settings" label-width="120px">
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px">

        <el-card>
          <template #header><span>AI 引擎</span></template>
          <el-form-item label="API Key">
            <el-input v-model="settings.anthropic_api_key" placeholder="sk-ant-..." type="password" show-password />
            <div class="form-hint">Anthropic API Key，用于 AI 生成和分析测试用例</div>
          </el-form-item>
          <el-form-item label="API URL">
            <el-input v-model="settings.anthropic_base_url" placeholder="https://api.anthropic.com（留空使用默认）" />
            <div class="form-hint">Anthropic API 地址，支持自定义代理或兼容端点</div>
          </el-form-item>
          <el-form-item label="AI 模型">
            <el-input v-model="settings.anthropic_model" placeholder="claude-sonnet-4-20250514" />
            <div class="form-hint">如 claude-sonnet-4-20250514、claude-opus-4-20250514</div>
          </el-form-item>
        </el-card>

        <el-card>
          <template #header><span>执行引擎</span></template>
          <el-form-item label="最大并发数">
            <el-input-number v-model.number="settings.max_workers" :min="1" :max="10" />
            <div class="form-hint">同时执行的最大测试用例数量</div>
          </el-form-item>
          <el-form-item label="执行超时(秒)">
            <el-input-number v-model.number="settings.execution_timeout" :min="30" :max="600" />
            <div class="form-hint">单个用例的最大执行时间</div>
          </el-form-item>
        </el-card>

        <el-card>
          <template #header><span>Agent 配置</span></template>
          <el-form-item label="最大轮次">
            <el-input-number v-model.number="settings.agent_max_turns" :min="5" :max="120" />
            <div class="form-hint">Agent 单次执行最大工具调用轮次</div>
          </el-form-item>
          <el-form-item label="无头模式">
            <el-switch v-model="settings.agent_headless" active-text="是" inactive-text="否" />
            <div class="form-hint">无头模式下不显示浏览器窗口（生产环境建议开启）</div>
          </el-form-item>
        </el-card>

        <el-card>
          <template #header><span>代码分析引擎</span></template>
          <el-form-item label="分析引擎">
            <el-radio-group v-model="settings.analysis_engine">
              <el-radio value="cli">Claude CLI</el-radio>
              <el-radio value="sdk">Anthropic SDK</el-radio>
            </el-radio-group>
            <div class="form-hint">CLI 模式更全面；SDK 模式无需安装 CLI</div>
          </el-form-item>
          <el-form-item label="CLI 路径" v-if="settings.analysis_engine === 'cli'">
            <div style="display: flex; gap: 8px; align-items: center; width: 100%">
              <el-input v-model="settings.claude_cli_path" placeholder="claude" style="flex: 1" />
              <el-button size="small" @click="checkCli" :loading="cliChecking">
                {{ cliAvailable === null ? '检测' : (cliAvailable ? '已就绪 ✓' : '未安装 ✗') }}
              </el-button>
            </div>
            <div v-if="cliVersion" class="form-hint" style="color: #67c23a">版本: {{ cliVersion }}</div>
            <div v-if="cliAvailable === false" class="form-hint" style="color: #f56c6c">
              未检测到 Claude CLI，请先安装: npm install -g @anthropic-ai/claude-code
            </div>
          </el-form-item>
          <el-form-item label="CLI 超时(秒)" v-if="settings.analysis_engine === 'cli'">
            <el-input-number v-model.number="settings.claude_cli_timeout" :min="60" :max="600" />
            <div class="form-hint">CLI 分析大型仓库的超时时间</div>
          </el-form-item>
        </el-card>

        <el-card>
          <template #header><span>Git 仓库</span></template>
          <el-form-item label="存储路径">
            <el-input v-model="settings.repo_base_path" placeholder="repos">
              <template #prepend>BASE_DIR/</template>
            </el-input>
            <div class="form-hint">Git 仓库克隆的本地根目录（相对于项目根目录）</div>
          </el-form-item>
        </el-card>

        <el-card>
          <template #header><span>前端</span></template>
          <el-form-item label="API 地址">
            <el-input v-model="settings.api_base_url" placeholder="/api" />
            <div class="form-hint">后端 API 基础地址</div>
          </el-form-item>
        </el-card>

      </div>

      <div style="margin-top: 16px; display: flex; gap: 8px">
        <el-button type="primary" @click="handleSave" :loading="saving">保存设置</el-button>
        <el-button @click="handleReset">恢复默认</el-button>
      </div>
    </el-form>

    <el-card style="margin-top: 16px">
      <template #header><span>系统信息</span></template>
      <el-descriptions :column="3" border size="small">
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
import { getSettings, updateSettings, healthCheck, checkCliAvailable } from '../api'
import { ElMessage } from 'element-plus'

const defaultSettings = {
  anthropic_api_key: '',
  anthropic_base_url: '',
  anthropic_model: 'claude-sonnet-4-20250514',
  max_workers: 3,
  execution_timeout: 120,
  repo_base_path: 'repos',
  api_base_url: '/api',
  agent_max_turns: 20,
  agent_headless: true,
  claude_cli_path: 'claude',
  analysis_engine: 'cli',
  claude_cli_timeout: 300,
}

const settings = ref({ ...defaultSettings })
const healthOk = ref(false)
const loading = ref(false)
const saving = ref(false)
const cliAvailable = ref(null)
const cliVersion = ref('')
const cliChecking = ref(false)

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
      repo_base_path: data.repo_base_path ?? defaultSettings.repo_base_path,
      api_base_url: data.api_base_url ?? defaultSettings.api_base_url,
      agent_max_turns: parseInt(data.agent_max_turns) || defaultSettings.agent_max_turns,
      agent_headless: String(data.agent_headless ?? 'true').toLowerCase() === 'true',
      claude_cli_path: data.claude_cli_path ?? defaultSettings.claude_cli_path,
      analysis_engine: (data.analysis_engine === 'sdk' ? 'sdk' : 'cli'),
      claude_cli_timeout: parseInt(data.claude_cli_timeout) || defaultSettings.claude_cli_timeout,
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
      repo_base_path: String(settings.value.repo_base_path),
      api_base_url: String(settings.value.api_base_url),
      agent_max_turns: String(settings.value.agent_max_turns),
      agent_headless: settings.value.agent_headless ? 'true' : 'false',
      claude_cli_path: String(settings.value.claude_cli_path),
      analysis_engine: String(settings.value.analysis_engine),
      claude_cli_timeout: String(settings.value.claude_cli_timeout),
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
      repo_base_path: defaultSettings.repo_base_path,
      api_base_url: defaultSettings.api_base_url,
      agent_max_turns: String(defaultSettings.agent_max_turns),
      agent_headless: defaultSettings.agent_headless ? 'true' : 'false',
      claude_cli_path: defaultSettings.claude_cli_path,
      analysis_engine: defaultSettings.analysis_engine,
      claude_cli_timeout: String(defaultSettings.claude_cli_timeout),
    })
    settings.value = { ...defaultSettings }
    ElMessage.success('已恢复默认设置')
  } catch (e) {
    ElMessage.error('恢复默认失败')
  } finally {
    saving.value = false
  }
}

const checkCli = async () => {
  cliChecking.value = true
  try {
    const { data } = await checkCliAvailable(settings.value.claude_cli_path)
    cliAvailable.value = data.available
    cliVersion.value = data.version || ''
    if (!data.available) {
      ElMessage.warning(data.error || 'Claude CLI 未安装或不可用')
    }
  } catch (e) {
    cliAvailable.value = false
    cliVersion.value = ''
    ElMessage.error('CLI 检测失败')
  } finally {
    cliChecking.value = false
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
