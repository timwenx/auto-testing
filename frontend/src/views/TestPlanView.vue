<template>
  <div class="test-plan-view">
    <div style="display: flex; gap: 16px; height: calc(100vh - 120px)">
      <!-- 左侧：方案列表 -->
      <el-card style="width: 280px; flex-shrink: 0" body-style="padding: 0">
        <template #header>
          <div style="display: flex; justify-content: space-between; align-items: center">
            <span>方案列表</span>
            <el-button size="small" type="primary" @click="openCreateDialog">
              <el-icon><Plus /></el-icon> 新建
            </el-button>
          </div>
        </template>
        <div style="margin: 8px 12px">
          <el-input v-model="planSearch" placeholder="搜索方案..." clearable size="small" />
        </div>
        <div v-loading="loadingPlans" style="max-height: calc(100vh - 220px); overflow-y: auto">
          <div
            v-for="plan in filteredPlans"
            :key="plan.id"
            class="plan-item"
            :class="{ active: selectedPlan?.id === plan.id }"
            @click="selectPlan(plan)"
          >
            <div class="plan-item-name">{{ plan.name }}</div>
            <div class="plan-item-meta">
              <el-tag :type="planStatusType(plan.status)" size="small">{{ plan.status }}</el-tag>
              <span style="color: #909399; font-size: 12px">{{ plan.project_name || '-' }}</span>
              <span style="color: #909399; font-size: 12px">{{ plan.item_count }} 项</span>
            </div>
          </div>
          <el-empty v-if="!filteredPlans.length && !loadingPlans" description="暂无方案" :image-size="60" />
        </div>
      </el-card>

      <!-- 右侧：方案编辑器 -->
      <el-card v-if="selectedPlan" style="flex: 1; overflow-y: auto" body-style="padding: 16px">
        <template #header>
          <div style="display: flex; justify-content: space-between; align-items: center">
            <div>
              <span style="font-size: 16px; font-weight: 600">{{ selectedPlan.name }}</span>
              <el-tag :type="planStatusType(selectedPlan.status)" size="small" style="margin-left: 8px">{{ selectedPlan.status }}</el-tag>
            </div>
            <div>
              <el-button size="small" type="primary" @click="handleExecutePlan" :loading="executingPlan">
                <el-icon><VideoPlay /></el-icon> 执行方案
              </el-button>
              <el-button size="small" @click="openEditDialog">编辑</el-button>
              <el-button size="small" type="danger" @click="handleDeletePlan">删除</el-button>
            </div>
          </div>
        </template>

        <el-descriptions :column="2" size="small" border style="margin-bottom: 16px">
          <el-descriptions-item label="项目">{{ selectedPlan.project_name }}</el-descriptions-item>
          <el-descriptions-item label="描述">{{ selectedPlan.description || '-' }}</el-descriptions-item>
          <el-descriptions-item label="子项数量">{{ selectedPlan.item_count }}</el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ selectedPlan.created_at }}</el-descriptions-item>
        </el-descriptions>

        <!-- API 信息（默认折叠） -->
        <el-collapse style="margin-bottom: 16px">
          <el-collapse-item title="API 调用信息">
            <div class="api-info">
              <div class="api-field">
                <label>API Token:</label>
                <code>{{ tokenDisplay }}</code>
                <el-button size="small" text @click="copyToken">复制</el-button>
                <el-button size="small" text type="warning" @click="handleRegenerateToken">重新生成</el-button>
              </div>
              <div class="api-field">
                <label>触发执行:</label>
                <code class="code-block">curl -X POST {{ apiUrl }}/api/plans/{{ selectedPlan.id }}/execute/ -H "X-Plan-Token: {{ selectedPlan.api_token }}" -H "Content-Type: application/json"</code>
                <el-button size="small" text @click="copyCurlExec">复制</el-button>
              </div>
              <div class="api-field">
                <label>带参数执行:</label>
                <code class="code-block">curl -X POST {{ apiUrl }}/api/plans/{{ selectedPlan.id }}/execute/ -H "X-Plan-Token: {{ selectedPlan.api_token }}" -H "Content-Type: application/json" -d '{"parameter_overrides": {"param_xxx": "值"}}'</code>
              </div>
              <div class="api-field">
                <label>同步执行:</label>
                <code class="code-block">curl -X POST "{{ apiUrl }}/api/plans/{{ selectedPlan.id }}/execute/?sync=true" -H "X-Plan-Token: {{ selectedPlan.api_token }}" -H "Content-Type: application/json"</code>
                <el-button size="small" text @click="copyCurlSync">复制</el-button>
              </div>
              <div class="api-field">
                <label>查询状态:</label>
                <code class="code-block">curl "{{ apiUrl }}/api/plan-executions/{id}/status/" -H "X-Plan-Token: {{ selectedPlan.api_token }}"</code>
              </div>
              <div class="api-field">
                <label>JUnit 报告:</label>
                <code class="code-block">curl "{{ apiUrl }}/api/plan-executions/{id}/report/" -H "X-Plan-Token: {{ selectedPlan.api_token }}"</code>
              </div>
            </div>
          </el-collapse-item>
        </el-collapse>

        <!-- 方案子项列表 -->
        <div style="margin-bottom: 16px">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px">
            <h4 style="margin: 0">方案子项</h4>
            <el-button size="small" @click="showAddItem = true">
              <el-icon><Plus /></el-icon> 添加子项
            </el-button>
          </div>
          <el-table :data="planItems" size="small" empty-text="暂无子项" row-key="id">
            <el-table-column prop="sort_order" label="序号" width="60" />
            <el-table-column prop="item_type" label="类型" width="110">
              <template #default="{ row }">
                <el-tag
                  :type="row.item_type === 'script' ? '' : row.item_type === 'agent_testcase' ? 'success' : 'warning'"
                  size="small"
                >
                  {{ row.item_type === 'script' ? '脚本' : row.item_type === 'agent_testcase' ? 'Agent用例' : '功能分组' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="名称" min-width="200">
              <template #default="{ row }">
                <span v-if="row.item_type === 'script'">{{ row.script_name || '-' }}</span>
                <span v-else-if="row.item_type === 'agent_testcase'">{{ row.testcase_name || '-' }}</span>
                <span v-else>{{ row.feature_group_name || '-' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="排序" width="100">
              <template #default="{ row, $index }">
                <el-button size="small" text :disabled="$index === 0" @click="handleItemMoveUp($index)">↑</el-button>
                <el-button size="small" text :disabled="$index === planItems.length - 1" @click="handleItemMoveDown($index)">↓</el-button>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="80">
              <template #default="{ row }">
                <el-button size="small" text type="danger" @click="handleRemoveItem(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <!-- 执行历史 -->
        <div>
          <h4 style="margin: 0 0 8px">执行历史</h4>
          <el-table :data="planExecutions" size="small" v-loading="loadingExecutions" empty-text="暂无执行记录">
            <el-table-column prop="id" label="ID" width="60" />
            <el-table-column prop="status" label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="execStatusType(row.status)" size="small">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="trigger_source" label="触发方式" width="100" />
            <el-table-column label="结果" min-width="160">
              <template #default="{ row }">
                <template v-if="row.summary">
                  <el-tag type="success" size="small" effect="plain">通过 {{ row.summary.passed || 0 }}</el-tag>
                  <el-tag type="danger" size="small" effect="plain" style="margin-left: 4px">失败 {{ (row.summary.failed || 0) + (row.summary.error || 0) }}</el-tag>
                </template>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column label="耗时" width="80">
              <template #default="{ row }">
                {{ row.total_duration ? row.total_duration.toFixed(1) + 's' : '-' }}
              </template>
            </el-table-column>
            <el-table-column prop="started_at" label="开始时间" width="160" />
            <el-table-column label="操作" width="80">
              <template #default="{ row }">
                <el-button size="small" text type="primary" @click="viewExecutionDetail(row)">详情</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-card>
      <el-card v-else style="flex: 1; display: flex; align-items: center; justify-content: center">
        <el-empty description="请选择或创建一个方案" :image-size="100" />
      </el-card>
    </div>

    <!-- 新建/编辑方案对话框 -->
    <el-dialog v-model="showCreateOrEdit" :title="editingPlan ? '编辑方案' : '新建方案'" width="500px">
      <el-form :model="planForm" label-width="80px">
        <el-form-item label="所属项目">
          <el-select v-model="planForm.project" placeholder="选择项目" style="width: 100%" :disabled="!!editingPlan">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="方案名称">
          <el-input v-model="planForm.name" placeholder="输入方案名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="planForm.description" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateOrEdit = false">取消</el-button>
        <el-button type="primary" @click="handleSavePlan" :loading="savingPlan">保存</el-button>
      </template>
    </el-dialog>

    <!-- 添加子项对话框 -->
    <el-dialog v-model="showAddItem" title="添加子项" width="500px">
      <el-form :model="addItemForm" label-width="80px">
        <el-form-item label="类型">
          <el-radio-group v-model="addItemForm.item_type">
            <el-radio value="script">脚本</el-radio>
            <el-radio value="feature_group">功能分组</el-radio>
            <el-radio value="agent_testcase">Agent用例</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="addItemForm.item_type === 'script'" label="选择脚本">
          <el-select v-model="addItemForm.script_id" placeholder="选择脚本" style="width: 100%" filterable>
            <el-option v-for="s in availableScripts" :key="s.id" :label="s.name" :value="s.id" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="addItemForm.item_type === 'agent_testcase'" label="选择用例">
          <el-select v-model="addItemForm.testcase_id" placeholder="选择测试用例" style="width: 100%" filterable>
            <el-option v-for="tc in availableTestcases" :key="tc.id" :label="tc.name" :value="tc.id" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="addItemForm.item_type === 'feature_group'" label="功能分组">
          <el-select v-model="addItemForm.feature_group_name" placeholder="选择功能分组" style="width: 100%" filterable allow-create>
            <el-option v-for="g in scriptFeatureGroups" :key="g.name" :label="`${g.name} (${g.count})`" :value="g.name" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddItem = false">取消</el-button>
        <el-button type="primary" @click="handleAddItem" :loading="addingItem">添加</el-button>
      </template>
    </el-dialog>

    <!-- 执行详情对话框 -->
    <el-dialog v-model="showExecDetail" title="方案执行详情" width="900px">
      <div v-loading="loadingExecDetail">
        <template v-if="execDetail">
          <el-descriptions :column="3" border size="small" style="margin-bottom: 16px">
            <el-descriptions-item label="状态">
              <el-tag :type="execStatusType(execDetail.status)" size="small">{{ execDetail.status }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="触发方式">{{ execDetail.trigger_source }}</el-descriptions-item>
            <el-descriptions-item label="通过率">
              <template v-if="execDetail.summary">
                {{ execDetail.summary.passed || 0 }}/{{ execDetail.summary.total || 0 }}
              </template>
            </el-descriptions-item>
          </el-descriptions>

          <el-table :data="execDetail.execution_records || []" size="small" empty-text="暂无子执行记录">
            <el-table-column prop="testcase_name" label="用例" min-width="160" />
            <el-table-column prop="status" label="状态" width="80">
              <template #default="{ row }">
                <el-tag :type="execStatusType(row.status)" size="small">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="execution_mode" label="模式" width="80" />
            <el-table-column prop="duration" label="耗时" width="80">
              <template #default="{ row }">{{ row.duration ? row.duration.toFixed(1) + 's' : '-' }}</template>
            </el-table-column>
            <el-table-column prop="error_message" label="错误信息" min-width="200">
              <template #default="{ row }">
                <span v-if="row.error_message" style="color: #f56c6c; font-size: 12px">{{ row.error_message }}</span>
                <span v-else style="color: #c0c4cc">-</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="80">
              <template #default="{ row }">
                <el-button size="small" text type="primary" @click="$router.push(`/executions/${row.id}/observe`)">观察</el-button>
              </template>
            </el-table-column>
          </el-table>
        </template>
      </div>
    </el-dialog>

    <!-- 参数编辑对话框（执行前） -->
    <el-dialog v-model="showParamDialog" title="方案执行参数" width="700px" :close-on-click-modal="false">
      <div v-loading="loadingParams">
        <template v-if="planParams">
          <!-- 输入参数 -->
          <div v-if="inputParamEntries.length > 0" style="margin-bottom: 20px">
            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 12px">
              <el-icon><Setting /></el-icon>
              <span style="font-weight: 600">输入参数</span>
              <el-tag size="small" type="info">{{ inputParamEntries.length }} 个</el-tag>
              <el-button size="small" text style="margin-left: auto" @click="resetAllParams">全部重置为默认值</el-button>
            </div>
            <el-form :model="paramEditValues" label-width="auto" size="small">
              <el-row :gutter="16">
                <el-col :span="12" v-for="[pname, pinfo] in inputParamEntries" :key="pname">
                  <el-form-item :label="pinfo.label || pname">
                    <div class="param-input-row">
                      <el-input
                        v-model="paramEditValues[pname]"
                        :placeholder="String(pinfo.default)"
                        clearable
                        @clear="paramEditValues[pname] = String(pinfo.default)"
                      />
                      <el-button size="small" text @click="paramEditValues[pname] = String(pinfo.default)">重置</el-button>
                    </div>
                    <!-- Conflict warning -->
                    <div v-if="pinfo.conflict" class="param-conflict-warning">
                      <el-icon color="#e6a23c"><WarningFilled /></el-icon>
                      <span>该参数在多个脚本中有不同默认值</span>
                      <el-popover trigger="hover" width="300">
                        <template #reference>
                          <el-button size="small" text type="warning">查看详情</el-button>
                        </template>
                        <div v-for="src in pinfo.sources" :key="src.script_id" style="font-size: 12px; padding: 4px 0">
                          <span style="font-weight: 500">{{ src.script_name }}:</span>
                          <code style="margin-left: 4px">{{ src.default || '(空)' }}</code>
                        </div>
                      </el-popover>
                    </div>
                  </el-form-item>
                </el-col>
              </el-row>
            </el-form>
          </div>

          <!-- 预期结果参数 -->
          <div v-if="assertParamEntries.length > 0">
            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 12px">
              <el-icon><CircleCheck /></el-icon>
              <span style="font-weight: 600">预期结果</span>
              <el-tag size="small" type="success">{{ assertParamEntries.length }} 个</el-tag>
            </div>
            <el-form :model="paramEditValues" label-width="auto" size="small">
              <el-row :gutter="16">
                <el-col :span="12" v-for="[pname, pinfo] in assertParamEntries" :key="pname">
                  <el-form-item :label="pinfo.label || pname">
                    <div class="param-input-row">
                      <el-input
                        v-model="paramEditValues[pname]"
                        :placeholder="String(pinfo.default)"
                        clearable
                        @clear="paramEditValues[pname] = String(pinfo.default)"
                      />
                      <el-button size="small" text @click="paramEditValues[pname] = String(pinfo.default)">重置</el-button>
                    </div>
                  </el-form-item>
                </el-col>
              </el-row>
            </el-form>
          </div>

          <!-- 无参数提示 -->
          <el-empty v-if="inputParamEntries.length === 0 && assertParamEntries.length === 0" description="该方案没有可配置的参数" :image-size="60" />
        </template>
      </div>
      <template #footer>
        <el-button @click="showParamDialog = false">取消</el-button>
        <el-button type="primary" @click="confirmExecuteWithParams" :loading="executingPlan">确认执行</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, reactive, watch, onMounted, onUnmounted } from 'vue'
import {
  getPlans, createPlan, getPlan, updatePlan, deletePlan,
  addPlanItem, deletePlanItem, regeneratePlanToken, reorderPlanItems,
  executePlan, getPlanExecutions, getPlanExecution, getPlanExecutionStatus,
  getPlanParameters,
  getScripts, getScriptFeatureGroups, getProjects, getProjectTestCases,
} from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'

const plans = ref([])
const selectedPlan = ref(null)
const planItems = ref([])
const planExecutions = ref([])
const projects = ref([])
const availableScripts = ref([])
const scriptFeatureGroups = ref([])
const availableTestcases = ref([])
const loadingPlans = ref(false)
const loadingExecutions = ref(false)
const loadingExecDetail = ref(false)
const executingPlan = ref(false)
const savingPlan = ref(false)
const addingItem = ref(false)
const showCreateOrEdit = ref(false)
const showAddItem = ref(false)
const showExecDetail = ref(false)
const showParamDialog = ref(false)
const loadingParams = ref(false)
const editingPlan = ref(null)
const execDetail = ref(null)
const planParams = ref(null)
const paramEditValues = reactive({})
const planSearch = ref('')

let pollTimer = null

const planForm = ref({ project: null, name: '', description: '' })
const addItemForm = ref({ item_type: 'script', script_id: null, testcase_id: null, feature_group_name: '' })

const apiUrl = window.location.origin

const filteredPlans = computed(() => {
  if (!planSearch.value) return plans.value
  const q = planSearch.value.toLowerCase()
  return plans.value.filter(p =>
    p.name.toLowerCase().includes(q) || (p.project_name || '').toLowerCase().includes(q)
  )
})

const tokenDisplay = computed(() => {
  if (!selectedPlan.value?.api_token) return ''
  const t = String(selectedPlan.value.api_token)
  return t.length > 12 ? t.slice(0, 8) + '****' + t.slice(-4) : t
})

// Parameter dialog computed
const inputParamEntries = computed(() => {
  if (!planParams.value?.parameters) return []
  return Object.entries(planParams.value.parameters).filter(([, v]) => v.group !== 'assertion')
})
const assertParamEntries = computed(() => {
  if (!planParams.value?.parameters) return []
  return Object.entries(planParams.value.parameters).filter(([, v]) => v.group === 'assertion')
})

const planStatusType = (s) => {
  const map = { draft: 'info', active: 'success', archived: 'info' }
  return map[s] || 'info'
}

const execStatusType = (s) => {
  const map = { pending: 'info', running: 'warning', completed: 'success', failed: 'danger', error: 'danger', passed: 'success' }
  return map[s] || 'info'
}

async function loadPlans() {
  loadingPlans.value = true
  try {
    const { data } = await getPlans()
    plans.value = data.plans || data.results || data
  } finally { loadingPlans.value = false }
}

async function loadProjects() {
  try {
    const { data } = await getProjects()
    projects.value = data.results || data
  } catch { /* ignore */ }
}

async function selectPlan(plan) {
  try {
    const { data } = await getPlan(plan.id)
    selectedPlan.value = data
    planItems.value = data.items || []
    await loadExecutions()
  } catch { ElMessage.error('加载方案失败') }
}

async function loadExecutions() {
  if (!selectedPlan.value) return
  loadingExecutions.value = true
  try {
    const { data } = await getPlanExecutions({ plan: selectedPlan.value.id })
    planExecutions.value = data.executions || data.results || data
  } finally { loadingExecutions.value = false }
}

async function loadScriptsForProject(projectId) {
  try {
    const [scriptsRes, groupsRes, testcasesRes] = await Promise.all([
      getScripts({ project: projectId, status: 'active' }),
      getScriptFeatureGroups(projectId),
      getProjectTestCases(projectId),
    ])
    availableScripts.value = scriptsRes.data.scripts || scriptsRes.data.results || scriptsRes.data || []
    scriptFeatureGroups.value = groupsRes.data.groups || []
    availableTestcases.value = testcasesRes.data.results || testcasesRes.data || []
  } catch { /* ignore */ }
}

function openCreateDialog() {
  editingPlan.value = null
  planForm.value = { project: null, name: '', description: '' }
  showCreateOrEdit.value = true
}

function openEditDialog() {
  if (!selectedPlan.value) return
  editingPlan.value = selectedPlan.value
  planForm.value = {
    project: selectedPlan.value.project,
    name: selectedPlan.value.name,
    description: selectedPlan.value.description || '',
  }
  showCreateOrEdit.value = true
}

async function handleSavePlan() {
  if (!planForm.value.name) return ElMessage.warning('请输入方案名称')
  if (!planForm.value.project) return ElMessage.warning('请选择所属项目')
  savingPlan.value = true
  try {
    if (editingPlan.value) {
      await updatePlan(editingPlan.value.id, { name: planForm.value.name, description: planForm.value.description })
      ElMessage.success('方案已更新')
    } else {
      await createPlan(planForm.value)
      ElMessage.success('方案已创建')
    }
    showCreateOrEdit.value = false
    await loadPlans()
  } catch (e) { ElMessage.error(e.response?.data?.error || '保存失败') } finally { savingPlan.value = false }
}

async function handleDeletePlan() {
  if (!selectedPlan.value) return
  await ElMessageBox.confirm(`确认删除方案「${selectedPlan.value.name}」？`, '提示', { type: 'warning' })
  try {
    await deletePlan(selectedPlan.value.id)
    ElMessage.success('已删除')
    selectedPlan.value = null
    planItems.value = []
    planExecutions.value = []
    await loadPlans()
  } catch (e) { ElMessage.error(e.response?.data?.error || '删除失败') }
}

async function handleAddItem() {
  if (!selectedPlan.value) return
  addingItem.value = true
  try {
    await addPlanItem(selectedPlan.value.id, addItemForm.value)
    ElMessage.success('子项已添加')
    showAddItem.value = false
    await selectPlan(selectedPlan.value)
  } catch (e) { ElMessage.error(e.response?.data?.error || '添加失败') } finally { addingItem.value = false }
}

async function handleItemMoveUp(index) {
  if (index <= 0 || !selectedPlan.value) return
  const reordered = [...planItems.value]
  ;[reordered[index - 1], reordered[index]] = [reordered[index], reordered[index - 1]]
  await persistReorder(reordered)
}

async function handleItemMoveDown(index) {
  if (index >= planItems.value.length - 1 || !selectedPlan.value) return
  const reordered = [...planItems.value]
  ;[reordered[index], reordered[index + 1]] = [reordered[index + 1], reordered[index]]
  await persistReorder(reordered)
}

async function persistReorder(reordered) {
  const orders = reordered.map((item, i) => ({ id: item.id, sort_order: i + 1 }))
  try {
    await reorderPlanItems(selectedPlan.value.id, orders)
    planItems.value = reordered.map((item, i) => ({ ...item, sort_order: i + 1 }))
  } catch (e) { ElMessage.error(e.response?.data?.error || '排序失败') }
}

async function handleRemoveItem(item) {
  await ElMessageBox.confirm('确认移除该子项？', '提示', { type: 'warning' })
  try {
    await deletePlanItem(item.id)
    ElMessage.success('已移除')
    await selectPlan(selectedPlan.value)
  } catch (e) { ElMessage.error(e.response?.data?.error || '移除失败') }
}

async function handleExecutePlan() {
  if (!selectedPlan.value) return
  executingPlan.value = true
  try {
    // First fetch aggregated parameters
    const { data } = await getPlanParameters(selectedPlan.value.id)
    const params = data.parameters || {}
    const paramNames = Object.keys(params)

    if (paramNames.length === 0) {
      // No parameters — execute directly
      await doPlanExecute({})
    } else {
      // Show parameter dialog
      planParams.value = data
      // Initialize edit values with defaults
      for (const [pname, pinfo] of Object.entries(params)) {
        paramEditValues[pname] = String(pinfo.default ?? '')
      }
      showParamDialog.value = true
    }
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '获取参数失败')
  } finally {
    executingPlan.value = false
  }
}

function resetAllParams() {
  if (!planParams.value?.parameters) return
  for (const [pname, pinfo] of Object.entries(planParams.value.parameters)) {
    paramEditValues[pname] = String(pinfo.default ?? '')
  }
}

async function confirmExecuteWithParams() {
  // Build parameter_overrides from edited values (only changed ones)
  const overrides = {}
  if (planParams.value?.parameters) {
    for (const [pname, pinfo] of Object.entries(planParams.value.parameters)) {
      const edited = paramEditValues[pname]
      const defaultVal = String(pinfo.default ?? '')
      if (edited !== undefined && edited !== defaultVal) {
        overrides[pname] = edited
      }
    }
  }
  showParamDialog.value = false
  await doPlanExecute(overrides)
}

async function doPlanExecute(parameterOverrides) {
  executingPlan.value = true
  try {
    const headers = {}
    if (selectedPlan.value.api_token) headers['X-Plan-Token'] = String(selectedPlan.value.api_token)
    const { data } = await executePlan(selectedPlan.value.id, false, {
      headers,
      data: { parameter_overrides: parameterOverrides },
    })
    if (data.status === 'running') {
      ElMessage.success('方案执行已提交')
      startPolling(data.id)
    } else {
      ElMessage.success('方案执行完成')
    }
    await loadExecutions()
  } catch (e) { ElMessage.error(e.response?.data?.error || '执行失败') } finally { executingPlan.value = false }
}

// Use setInterval-based polling with cleanup instead of recursive setTimeout
function startPolling(execId) {
  stopPolling()
  let tries = 0
  const maxTries = 120
  pollTimer = setInterval(async () => {
    tries++
    if (tries >= maxTries) { stopPolling(); return }
    try {
      const { data } = await getPlanExecutionStatus(execId)
      if (['completed', 'failed', 'error'].includes(data.status)) {
        stopPolling()
        await loadExecutions()
        ElMessage.info(`方案执行${data.status === 'completed' ? '完成' : '失败'}`)
      }
    } catch { /* ignore */ }
  }, 1000)
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

onUnmounted(() => stopPolling())

async function handleRegenerateToken() {
  if (!selectedPlan.value) return
  await ElMessageBox.confirm('重新生成后，旧 Token 将立即失效。确认？', '提示', { type: 'warning' })
  try {
    const { data } = await regeneratePlanToken(selectedPlan.value.id)
    selectedPlan.value = { ...selectedPlan.value, api_token: data.api_token }
    ElMessage.success('Token 已重新生成')
  } catch { ElMessage.error('重新生成失败') }
}

function copyToken() {
  navigator.clipboard.writeText(String(selectedPlan.value?.api_token || ''))
  ElMessage.success('已复制')
}

function copyCurlExec() {
  const cmd = `curl -X POST ${apiUrl}/api/plans/${selectedPlan.value.id}/execute/ -H "X-Plan-Token: ${selectedPlan.value.api_token}"`
  navigator.clipboard.writeText(cmd)
  ElMessage.success('已复制')
}

function copyCurlSync() {
  const cmd = `curl -X POST "${apiUrl}/api/plans/${selectedPlan.value.id}/execute/?sync=true" -H "X-Plan-Token: ${selectedPlan.value.api_token}"`
  navigator.clipboard.writeText(cmd)
  ElMessage.success('已复制')
}

async function viewExecutionDetail(exec) {
  showExecDetail.value = true
  loadingExecDetail.value = true
  execDetail.value = null
  try {
    const { data } = await getPlanExecution(exec.id)
    execDetail.value = data
  } catch { ElMessage.error('加载执行详情失败') } finally { loadingExecDetail.value = false }
}

watch(showAddItem, async (val) => {
  if (val && selectedPlan.value?.project) {
    // 先重置表单，避免异步加载完成后覆盖用户已选择的 item_type
    addItemForm.value = { item_type: 'script', script_id: null, testcase_id: null, feature_group_name: '' }
    await loadScriptsForProject(selectedPlan.value.project)
  }
})

onMounted(async () => {
  await Promise.all([loadPlans(), loadProjects()])
})
</script>

<style scoped>
.test-plan-view {
  padding: 0;
}
.plan-item {
  padding: 10px 14px;
  cursor: pointer;
  border-bottom: 1px solid #f0f0f0;
  transition: background-color 0.2s;
}
.plan-item:hover { background-color: #f5f7fa; }
.plan-item.active { background-color: #ecf5ff; border-left: 3px solid #409eff; }
.plan-item-name { font-weight: 500; font-size: 14px; margin-bottom: 4px; }
.plan-item-meta { display: flex; align-items: center; gap: 8px; }
.api-info { display: flex; flex-direction: column; gap: 12px; }
.api-field { display: flex; align-items: flex-start; gap: 8px; }
.api-field label { font-weight: 600; font-size: 12px; color: #606266; white-space: nowrap; min-width: 80px; }
.api-field code { background: #f5f7fa; padding: 2px 8px; border-radius: 3px; font-size: 12px; word-break: break-all; }
.code-block { display: block; font-family: 'Consolas', monospace; font-size: 11px; line-height: 1.4; }
.param-input-row { display: flex; align-items: center; gap: 4px; width: 100%; }
.param-input-row .el-input { flex: 1; }
.param-conflict-warning { display: flex; align-items: center; gap: 4px; font-size: 12px; color: #e6a23c; margin-top: 4px; }

@media (max-width: 768px) {
  .test-plan-view > div:first-child {
    flex-direction: column;
    height: auto !important;
  }
  .test-plan-view > div:first-child > .el-card {
    width: 100% !important;
    max-height: 300px;
    overflow-y: auto;
  }
}
</style>
