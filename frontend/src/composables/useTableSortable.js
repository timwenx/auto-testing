import { nextTick } from 'vue'
import Sortable from 'sortablejs'

/**
 * 为 el-table 提供行拖拽排序的 composable
 * @param {import('vue').Ref} tableRef - el-table 组件的 ref
 * @param {(oldIndex: number, newIndex: number) => void|Promise} onEnd - 拖拽结束回调
 */
export function useTableSortable(tableRef, onEnd) {
  let sortableInstance = null

  function initSortable() {
    destroy()
    nextTick(() => {
      if (!tableRef.value) return
      const el = tableRef.value.$el
      const tbody = el?.querySelector('.el-table__body-wrapper tbody')
      if (!tbody) return

      sortableInstance = Sortable.create(tbody, {
        animation: 150,
        handle: '.drag-handle',
        onEnd: ({ oldIndex, newIndex }) => {
          if (oldIndex === newIndex) return
          onEnd(oldIndex, newIndex)
        },
      })
    })
  }

  function destroy() {
    if (sortableInstance) {
      sortableInstance.destroy()
      sortableInstance = null
    }
  }

  return { initSortable, destroy }
}
