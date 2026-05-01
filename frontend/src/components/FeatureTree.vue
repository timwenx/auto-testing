<template>
  <div class="feature-tree">
    <el-tree
      ref="treeRef"
      :data="treeData"
      :props="treeProps"
      node-key="key"
      :default-expanded-keys="expandedKeys"
      :expand-on-click-node="false"
      highlight-current
      @node-click="handleNodeClick"
    >
      <template #default="{ node, data }">
        <div class="tree-node" :class="{ 'is-feature': data.type === 'feature' }">
          <div class="tree-node-content">
            <!-- 功能节点 -->
            <template v-if="data.type === 'feature'">
              <el-icon style="margin-right: 4px; color: #e6a23c"><Folder /></el-icon>
              <span class="node-label">{{ data.label }}</span>
              <el-tag size="small" type="info" style="margin-left: 6px">{{ data.count }}</el-tag>
            </template>
            <!-- 用例节点 -->
            <template v-else>
              <el-icon style="margin-right: 4px; color: #409eff"><Document /></el-icon>
              <span class="node-label">{{ data.label }}</span>
              <el-tag
                v-if="data.status"
                :type="statusType(data.status)"
                size="small"
                style="margin-left: 6px"
              >
                {{ data.status }}
              </el-tag>
              <el-tag
                v-if="data.latestExecutionStatus"
                size="small"
                :type="statusType(data.latestExecutionStatus)"
                style="margin-left: 4px"
                effect="plain"
              >
                {{ data.latestExecutionStatus }}
              </el-tag>
            </template>
          </div>
          <!-- 功能节点操作 -->
          <div v-if="data.type === 'feature'" class="tree-node-actions" @click.stop>
            <el-button
              size="small"
              type="primary"
              text
              @click.stop="$emit('execute-feature', data.rawName)"
              :loading="executingFeature === data.rawName"
            >
              <el-icon><VideoPlay /></el-icon>
            </el-button>
          </div>
        </div>
      </template>
    </el-tree>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'

const props = defineProps({
  groups: {
    type: Array,
    default: () => [],  // [{ name, count, testcases: [{ id, name, status, sort_order, latest_execution_status }] }]
  },
  executingFeature: {
    type: String,
    default: '',
  },
})

const emit = defineEmits(['select-feature', 'select-testcase', 'execute-feature'])

const treeRef = ref(null)
const expandedKeys = ref([])

const treeProps = {
  children: 'children',
  label: 'label',
}

const treeData = computed(() => {
  const result = []
  for (const group of props.groups) {
    const featureNode = {
      key: `feature:${group.name}`,
      type: 'feature',
      label: group.name,
      rawName: group.name === '未分组' ? '' : group.name,
      count: group.count || (group.testcases || []).length,
      children: (group.testcases || []).map(tc => ({
        key: `tc:${tc.id}`,
        type: 'testcase',
        label: tc.name,
        testcaseId: tc.id,
        status: tc.status,
        latestExecutionStatus: tc.latest_execution_status,
        raw: tc,
      })),
    }
    result.push(featureNode)
  }
  return result
})

// 自动展开所有功能节点
watch(treeData, (data) => {
  expandedKeys.value = data.map(d => d.key)
}, { immediate: true })

const statusType = (s) => {
  const map = { draft: 'info', ready: '', running: 'warning', passed: 'success', failed: 'danger', error: 'danger' }
  return map[s] || 'info'
}

const handleNodeClick = (data) => {
  if (data.type === 'feature') {
    emit('select-feature', data.rawName)
  } else {
    emit('select-testcase', data.raw)
  }
}
</script>

<style scoped>
.feature-tree {
  height: 100%;
  overflow-y: auto;
}
.tree-node {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex: 1;
  padding-right: 8px;
}
.tree-node-content {
  display: flex;
  align-items: center;
  overflow: hidden;
}
.node-label {
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tree-node-actions {
  display: flex;
  gap: 2px;
  opacity: 0;
  transition: opacity 0.2s;
}
.tree-node:hover .tree-node-actions {
  opacity: 1;
}
:deep(.el-tree-node__content) {
  height: 32px;
}
:deep(.el-tree-node.is-current > .el-tree-node__content) {
  background-color: #ecf5ff;
}
</style>
