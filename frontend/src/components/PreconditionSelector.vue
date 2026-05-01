<template>
  <el-card>
    <template #header>
      <div class="card-header">
        <span>前置条件</span>
        <el-button size="small" type="primary" link @click="showCreateDialog = true">
          + 新建模板
        </el-button>
      </div>
    </template>

    <el-radio-group v-model="selectedId" style="width: 100%">
      <div class="precondition-list">
        <el-radio :value="null" style="margin-bottom: 8px">无前置条件</el-radio>
        <div v-for="tpl in preconditions" :key="tpl.id" style="margin-bottom: 8px">
          <el-radio :value="tpl.id">
            <span>{{ tpl.name }}</span>
            <el-tag v-if="tpl.is_default" size="small" type="info" style="margin-left: 4px">内置</el-tag>
          </el-radio>
          <div v-if="selectedId === tpl.id" class="preview-section">
            <div v-if="tpl.steps" style="margin-top: 4px; padding: 8px; background: #f5f7fa; border-radius: 4px; font-size: 13px; color: #606266">
              {{ tpl.steps.slice(0, 300) }}{{ tpl.steps.length > 300 ? '...' : '' }}
            </div>
            <el-button
              v-if="!tpl.is_default"
              size="small"
              type="danger"
              link
              style="margin-top: 4px"
              @click.stop="handleDelete(tpl.id)"
            >
              删除
            </el-button>
          </div>
        </div>
      </div>
    </el-radio-group>

    <el-empty v-if="!preconditions.length" description="暂无模板" :image-size="60" />

    <!-- 创建模板对话框 -->
    <el-dialog v-model="showCreateDialog" title="创建前置条件模板" width="500px">
      <el-form label-width="80px" size="small">
        <el-form-item label="名称">
          <el-input v-model="newTemplate.name" placeholder="如：SSO 统一登录" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="newTemplate.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="前置步骤">
          <el-input v-model="newTemplate.steps" type="textarea" :rows="5"
            placeholder="自然语言描述的前置步骤，如：1. 打开 SSO 登录页 2. 输入账号密码 3. 点击登录按钮" />
        </el-form-item>
        <el-form-item label="Markdown">
          <el-input v-model="newTemplate.markdown_content" type="textarea" :rows="4"
            placeholder="可选：完整的 Markdown 格式前置条件" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="handleCreate" :loading="creating">创建</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getPreconditions, createPrecondition, deletePrecondition } from '../api.js'

const props = defineProps({
  selectedId: { type: Number, default: null },
})
const emit = defineEmits(['update:selectedId'])

const selectedId = ref(props.selectedId)
const preconditions = ref([])
const showCreateDialog = ref(false)
const creating = ref(false)
const newTemplate = ref({
  name: '',
  description: '',
  steps: '',
  markdown_content: '',
})

// Sync v-model
import { watch } from 'vue'
watch(() => props.selectedId, (val) => { selectedId.value = val })
watch(selectedId, (val) => { emit('update:selectedId', val) })

onMounted(() => { loadPreconditions() })

async function loadPreconditions() {
  try {
    const { data } = await getPreconditions()
    preconditions.value = data.preconditions || []
  } catch (e) {
    // silent
  }
}

async function handleCreate() {
  if (!newTemplate.value.name || !newTemplate.value.steps) {
    return ElMessage.warning('请填写名称和前置步骤')
  }
  creating.value = true
  try {
    await createPrecondition(newTemplate.value)
    ElMessage.success('模板创建成功')
    showCreateDialog.value = false
    newTemplate.value = { name: '', description: '', steps: '', markdown_content: '' }
    await loadPreconditions()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '创建失败')
  } finally {
    creating.value = false
  }
}

async function handleDelete(id) {
  try {
    await ElMessageBox.confirm('确定删除此模板？', '提示', { type: 'warning' })
    await deletePrecondition(id)
    ElMessage.success('已删除')
    await loadPreconditions()
    if (selectedId.value === id) {
      selectedId.value = null
    }
  } catch (e) {
    if (e !== 'cancel') {
      ElMessage.error(e.response?.data?.error || '删除失败')
    }
  }
}
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.precondition-list {
  width: 100%;
}
.preview-section {
  margin-left: 24px;
}
</style>
