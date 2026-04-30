<template>
  <template v-if="screenshots && screenshots.length">
    <h4 v-if="showTitle" style="margin: 16px 0 8px">截图 ({{ screenshots.length }})</h4>
    <div class="screenshot-grid">
      <el-image
        v-for="(src, idx) in screenshots"
        :key="idx"
        :src="toUrl(src)"
        :preview-src-list="previewList"
        :initial-index="idx"
        fit="cover"
        class="screenshot-thumb"
      >
        <template #error>
          <div class="screenshot-error">
            <span>加载失败</span>
          </div>
        </template>
      </el-image>
    </div>
  </template>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  screenshots: { type: Array, default: () => [] },
  showTitle: { type: Boolean, default: true },
})

const toUrl = (path) => `/api/executions/screenshots/?path=${encodeURIComponent(path)}`

const previewList = computed(() =>
  (props.screenshots || []).map(s => toUrl(s))
)
</script>

<style scoped>
.screenshot-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 12px 0;
}
.screenshot-thumb {
  width: 150px;
  height: 100px;
  border-radius: 4px;
  cursor: pointer;
  border: 1px solid #ebeef5;
}
.screenshot-error {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100px;
  color: #c0c4cc;
}
</style>
