<template>
  <div style="padding: 16px">
    <el-page-header @back="$router.back()" title="返回" content="方案执行详情" />
    <div style="margin-top: 16px">
      <PlanExecutionDetail :execution-id="parseInt($route.params.id)" />
    </div>
  </div>
</template>

<script setup>
import PlanExecutionDetail from '../components/PlanExecutionDetail.vue'
</script>
