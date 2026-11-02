<template>
  <el-button :icon="Setting" size="small" @click="open">列设置</el-button>
  <el-dialog v-model="visible" title="列设置" width="min(560px, calc(100vw - 32px))" :before-close="requestClose">
    <p class="layout-hint">拖动或上下移动调整顺序；列宽单位为像素，固定列显示在左侧。</p>
    <div class="layout-list">
      <div v-for="(column, index) in draft" :key="column.key" class="layout-row" @dragover.prevent @drop.prevent="drop(column.key)">
        <span class="drag-handle" draggable="true" @dragstart="startDrag($event, column.key)" @dragend="dragKey = null" aria-label="拖动调整列顺序">⠿</span>
        <el-checkbox v-model="column.visible" :aria-label="'显示' + column.label">{{ column.label }}</el-checkbox>
        <el-input-number v-model="column.width" :min="30" :step="10" size="small" controls-position="right" :aria-label="column.label + '列宽'" style="width: 88px; flex-shrink: 0" />
        <el-checkbox v-model="column.fixed" :disabled="!column.visible" :aria-label="'固定' + column.label">固定</el-checkbox>
        <el-button :icon="ArrowUp" size="small" :disabled="index === 0" :aria-label="'上移' + column.label" @click="move(index, -1)" />
        <el-button :icon="ArrowDown" size="small" :disabled="index === draft.length - 1" :aria-label="'下移' + column.label" @click="move(index, 1)" />
      </div>
    </div>
    <template #footer>
      <div class="layout-footer">
        <el-button size="small" @click="draft = normalizeColumnLayout(defaults)">恢复默认布局</el-button>
        <span class="layout-footer-actions"><el-button size="small" @click="requestClose()">取消</el-button><el-button size="small" type="primary" @click="apply">应用</el-button></span>
      </div>
    </template>
  </el-dialog>
</template>
<script setup>
import { ref, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Setting, ArrowUp, ArrowDown } from '@element-plus/icons-vue'
import { normalizeColumnLayout, moveLayoutColumn } from '../utils/tableColumnLayout'
const props = defineProps({ modelValue: { type: Array, required: true }, defaults: { type: Array, required: true } })
const emit = defineEmits(['update:modelValue'])
const visible = ref(false), draft = ref([]), baseline = ref(''), dragKey = ref(null)
const dirty = computed(() => JSON.stringify(draft.value) !== baseline.value)
const open = () => { draft.value = props.modelValue.map(column => ({ ...column })); baseline.value = JSON.stringify(draft.value); visible.value = true }
const move = (index, direction) => { const target = draft.value[index + direction]; if (target) draft.value = moveLayoutColumn(draft.value, draft.value[index].key, target.key) }
const startDrag = (event, key) => { dragKey.value = key; event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', key) }
const drop = key => { if (dragKey.value) draft.value = moveLayoutColumn(draft.value, dragKey.value, key); dragKey.value = null }
const requestClose = async done => {
  if (dirty.value) {
    try { await ElMessageBox.confirm('列设置尚未应用，确定放弃修改？', '未应用的列设置', { confirmButtonText: '放弃修改', cancelButtonText: '继续设置', type: 'warning' }) }
    catch { return }
  }
  visible.value = false
  if (typeof done === 'function') done()
}
const apply = () => {
  if (!draft.value.some(column => column.visible)) { ElMessage.warning('至少需要显示一列'); return }
  emit('update:modelValue', normalizeColumnLayout(props.defaults, draft.value)); visible.value = false
}
</script>
<style scoped>
.layout-hint { font-size: 12px; color: var(--el-text-color-secondary); margin: 0 0 10px; }
.layout-list { max-height: 55vh; overflow: auto; }
.layout-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; min-height: 38px; border-bottom: 1px solid var(--el-border-color-lighter); }
.layout-row > .el-checkbox:first-of-type { flex: 1 0 120px; min-width: 0; margin-right: 0; }
.layout-row > .el-checkbox { margin-right: 0; }
.layout-row > .el-button + .el-button { margin-left: 0; }
.drag-handle { cursor: grab; color: var(--el-text-color-placeholder); padding: 4px; }
.layout-footer { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
.layout-footer-actions { display: inline-flex; gap: 8px; }
.layout-footer-actions > .el-button + .el-button { margin-left: 0; }
</style>
