<template>
  <ProbeDataTable :rows="rows" :columns="columns" :table-id="tableId" :page-size="20" :actions-width="undo ? 145 : 90">
    <template #actions="{ row }"><el-button size="small" link @click="detail = row">完整对照</el-button><el-button v-if="undo" size="small" link type="warning" :disabled="busy" @click="$emit('undo', row.key)">撤销</el-button></template>
  </ProbeDataTable>
  <el-dialog :model-value="!!detail" title="完整变更对照" width="min(1000px, calc(100vw - 32px))" append-to-body @update:model-value="detail = null">
    <template v-if="detail"><p>{{ detail.label }} · {{ detail.field_label }} · 影响 {{ detail.affected_count }} 条</p><div class="change-comparison"><section><strong>修改前</strong><pre>{{ detail.before_label }}</pre></section><section><strong>修改后</strong><pre>{{ detail.after_label }}</pre></section></div><details v-if="detail.entity === 'evidence'"><summary>查看完整冻结证据</summary><div class="change-comparison"><section><strong>修改前证据</strong><MeasurementFrozenEvidence :enrichment="detail.before?.enrichment" :document="beforeDocument" /></section><section><strong>修改后证据</strong><MeasurementFrozenEvidence :enrichment="detail.after?.enrichment" :document="afterDocument" /></section></div></details></template>
  </el-dialog>
</template>
<script setup>
import { computed, ref } from 'vue'
import ProbeDataTable from './ProbeDataTable.vue'
import MeasurementFrozenEvidence from './MeasurementFrozenEvidence.vue'
import { workspaceChangeRows, formatManagedChange } from '../utils/measurementWorkspace'
const props = defineProps({ changes: { type: Array, default: () => [] }, tableId: { type: String, required: true }, undo: Boolean, busy: Boolean, beforeDocument: Object, afterDocument: Object })
defineEmits(['undo'])
const rows = computed(() => workspaceChangeRows(props.changes).map(change => ({ ...change,
  before_label: formatManagedChange(change, change.before, props.beforeDocument),
  after_label: formatManagedChange(change, change.after, props.afterDocument)
}))), detail = ref(null)
const columns = [
  { key: 'label', label: '项目 / 字典', width: 180, fixed: true },
  { key: 'type_label', label: '变更', width: 85 },
  { key: 'field_label', label: '字段', width: 110 },
  { key: 'affected_count', label: '影响记录数', width: 100 },
  { key: 'before_label', label: '修改前', width: 260 },
  { key: 'after_label', label: '修改后', width: 260 }
].map(column => ({ visible: true, fixed: false, ...column }))
</script>
<style scoped>
.change-comparison{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.change-comparison pre{max-height:55vh;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;background:var(--el-fill-color-light);padding:10px;font-size:12px;user-select:text}
</style>
