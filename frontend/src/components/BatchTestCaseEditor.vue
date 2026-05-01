<template>
  <el-card>
    <template #header>
      <div class="card-header">
        <span>批量用例生成</span>
        <div>
          <el-button size="small" @click="$emit('back')">返回选择</el-button>
          <el-button
            v-if="!generatedCases.length"
            type="primary"
            size="small"
            :loading="generating"
            :disabled="!selectedItems?.length"
            @click="handleGenerate"
          >
            {{ generating ? '生成中...' : '生成用例' }}
          </el-button>
          <el-button
            v-if="generatedCases.length"
            type="success"
            :loading="saving"
            @click="handleSave"
          >
            全部保存 ({{ generatedCases.length }} 条)
          </el-button>
        </div>
      </div>
    </template>

    <!-- 生成中 -->
    <div v-if="generating" style="text-align: center; padding: 40px 0">
      <el-icon class="is-loading" style="font-size: 32px; color: #409eff"><Loading /></el-icon>
      <p style="margin-top: 12px; color: #606266">正在生成测试用例...</p>
      <p style="color: #909399; font-size: 13px">
        为 {{ selectedItems?.length || 0 }} 个目标生成用例，可能需要 1-2 分钟
      </p>
    </div>

    <!-- 已生成用例列表 -->
    <div v-else-if="generatedCases.length">
      <div style="margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center">
        <span style="color: #606266">
          共生成 <strong>{{ generatedCases.length }}</strong> 条用例
        </span>
        <div>
          <el-button size="small" @click="handleAddEmpty">手动新增</el-button>
          <el-button size="small" @click="handleGenerate">重新生成</el-button>
        </div>
      </div>

      <el-table :data="generatedCases" style="width: 100%" size="small">
        <el-table-column prop="name" label="用例名称" min-width="180">
          <template #default="{ row }">
            <span>{{ row.name || '未命名' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="feature_group" label="功能点" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.feature_group" size="small" effect="plain">{{ row.feature_group }}</el-tag>
            <span v-else style="color: #c0c4cc">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="sort_order" label="序号" width="60" />
        <el-table-column prop="target_page_or_api" label="目标" min-width="120">
          <template #default="{ row }">
            <span style="color: #909399; font-size: 12px">{{ row.target_page_or_api || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="priority" label="优先级" width="80">
          <template #default="{ row }">
            <el-tag v-if="row.priority" size="small"
              :type="row.priority === 'P0' ? 'danger' : row.priority === 'P1' ? 'warning' : 'info'">
              {{ row.priority }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="test_type" label="类型" width="80">
          <template #default="{ row }">
            <el-tag v-if="row.test_type" size="small" effect="plain">{{ row.test_type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="source_item" label="来源" min-width="120">
          <template #default="{ row }">
            <span style="color: #909399; font-size: 12px">{{ row.source_item || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row, $index }">
            <el-button size="small" link type="primary" @click="handlePreview(row)">查看</el-button>
            <el-button size="small" link type="warning" @click="handleEdit(row, $index)">编辑</el-button>
            <el-button size="small" link type="danger" @click="handleRemove($index)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 初始状态 -->
    <div v-else style="text-align: center; padding: 40px 0; color: #909399">
      点击「生成用例」开始为选中的目标批量生成测试用例
    </div>

    <!-- 预览对话框 -->
    <el-dialog v-model="showPreview" title="用例详情" width="600px">
      <div v-if="previewCase" style="max-height: 60vh; overflow-y: auto">
        <h4 style="margin-top: 0">{{ previewCase.name }}</h4>
        <p v-if="previewCase.description"><strong>描述：</strong>{{ previewCase.description }}</p>
        <p><strong>测试步骤：</strong></p>
        <div style="white-space: pre-wrap; background: #f5f7fa; padding: 12px; border-radius: 4px; font-size: 13px">
          {{ previewCase.steps }}
        </div>
        <p style="margin-top: 12px"><strong>预期结果：</strong></p>
        <div style="white-space: pre-wrap; background: #f0f9eb; padding: 12px; border-radius: 4px; font-size: 13px">
          {{ previewCase.expected_result }}
        </div>
        <div v-if="previewCase.markdown_content" style="margin-top: 12px">
          <p><strong>Markdown 内容：</strong></p>
          <div style="white-space: pre-wrap; background: #f5f7fa; padding: 12px; border-radius: 4px; font-size: 13px; max-height: 300px; overflow-y: auto">
            {{ previewCase.markdown_content }}
          </div>
        </div>
      </div>
    </el-dialog>

    <!-- 编辑对话框 -->
    <el-dialog v-model="showEdit" title="编辑用例" width="600px">
      <el-form v-if="editingCase" label-width="80px" size="small">
        <el-form-item label="用例名称">
          <el-input v-model="editingCase.name" />
        </el-form-item>
        <el-form-item label="功能点">
          <el-input v-model="editingCase.feature_group" placeholder="输入功能点，如「用户登录」" />
        </el-form-item>
        <el-form-item label="排序序号">
          <el-input-number v-model="editingCase.sort_order" :min="0" :max="9999" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="editingCase.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="目标">
          <el-input v-model="editingCase.target_page_or_api" />
        </el-form-item>
        <el-form-item label="优先级">
          <el-select v-model="editingCase.priority" style="width: 100%">
            <el-option label="P0" value="P0" />
            <el-option label="P1" value="P1" />
            <el-option label="P2" value="P2" />
          </el-select>
        </el-form-item>
        <el-form-item label="测试类型">
          <el-select v-model="editingCase.test_type" style="width: 100%">
            <el-option label="功能" value="功能" />
            <el-option label="边界" value="边界" />
            <el-option label="异常" value="异常" />
            <el-option label="安全" value="安全" />
          </el-select>
        </el-form-item>
        <el-form-item label="测试步骤">
          <el-input v-model="editingCase.steps" type="textarea" :rows="5" />
        </el-form-item>
        <el-form-item label="预期结果">
          <el-input v-model="editingCase.expected_result" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showEdit = false">取消</el-button>
        <el-button type="primary" @click="handleSaveEdit">保存修改</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { batchGenerateTestcases, batchSaveTestcases } from '../api.js'

const props = defineProps({
  projectId: { type: Number, required: true },
  selectedItems: { type: Array, default: () => [] },
  descriptions: { type: Object, default: () => ({}) },
  preconditionId: { type: Number, default: null },
  initialCases: { type: Array, default: null },
})
const emit = defineEmits(['back', 'save-complete'])

const generating = ref(false)
const saving = ref(false)
const generatedCases = ref(props.initialCases || [])

const showPreview = ref(false)
const previewCase = ref(null)

const showEdit = ref(false)
const editingCase = ref(null)
const editingIndex = ref(-1)

async function handleGenerate() {
  if (!props.selectedItems?.length) {
    return ElMessage.warning('请先选择目标')
  }
  generating.value = true
  try {
    const { data } = await batchGenerateTestcases(props.projectId, {
      selected_items: props.selectedItems,
      descriptions: props.descriptions,
      precondition_id: props.preconditionId,
    })
    generatedCases.value = data.testcases || []
    if (generatedCases.value.length === 0) {
      ElMessage.warning('未生成任何用例，请调整目标或描述后重试')
    } else {
      ElMessage.success(`已生成 ${generatedCases.value.length} 条用例`)
    }
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '生成失败')
  } finally {
    generating.value = false
  }
}

async function handleSave() {
  if (!generatedCases.value.length || saving.value) return
  saving.value = true
  try {
    const { data } = await batchSaveTestcases(props.projectId, {
      testcases: generatedCases.value,
    })
    ElMessage.success(`已保存 ${data.count || generatedCases.value.length} 条用例`)
    emit('save-complete', data.count || generatedCases.value.length)
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '保存失败')
  } finally {
    saving.value = false
  }
}

function handlePreview(tc) {
  previewCase.value = { ...tc }
  showPreview.value = true
}

function handleEdit(tc, index) {
  editingCase.value = JSON.parse(JSON.stringify(tc))
  editingIndex.value = index
  showEdit.value = true
}

function handleSaveEdit() {
  if (editingIndex.value >= 0 && editingCase.value) {
    generatedCases.value[editingIndex.value] = { ...editingCase.value }
    showEdit.value = false
    ElMessage.success('已更新')
  }
}

async function handleRemove(index) {
  try {
    await ElMessageBox.confirm('确定删除此用例？', '提示', { type: 'warning' })
    generatedCases.value.splice(index, 1)
  } catch {
    // cancelled
  }
}

function handleAddEmpty() {
  generatedCases.value.push({
    name: '新用例',
    description: '',
    steps: '',
    expected_result: '',
    priority: 'P1',
    test_type: '功能',
    target_page_or_api: '',
    feature_group: '',
    markdown_content: '',
    source_item: '手动新增',
  })
  ElMessage.success('已添加空用例')
}
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>
