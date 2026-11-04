<template>
  <div class="probe-data-table" :class="{ 'fill-height': fillHeight }">
    <div class="table-actions"><slot name="toolbar" /><div class="table-tools" :class="{ 'is-grouped': groupTools }"><span>{{ filtered.length }} / {{ rows.length }} 条</span><TableColumnSettings :model-value="layout" :defaults="columns" @update:model-value="applyLayout" /><el-button v-if="Object.values(filters).some(v => v != null)" size="small" @click="clearFilters">清除筛选</el-button></div></div>
    <el-table :key="structureKey" :data="displayRows" border stripe size="small" :height="fillHeight ? '100%' : height" :max-height="fillHeight || height ? undefined : 360" @header-dragend="resize">
      <el-table-column v-for="column in visibleColumns" :key="column.key" :prop="column.key" :width="column.width" :fixed="column.fixed" show-overflow-tooltip>
        <template #header><span class="column-heading">{{ column.label }}<el-popover :ref="el => { if (el) popovers[column.key] = el }" v-if="column.filter !== false && (rows.length || filters[column.key] != null || filterKey === column.key)" trigger="click" :width="220" placement="bottom-start" @before-enter="openFilter(column.key)" @before-leave="finishFilter(column.key)">
          <template #reference><el-button class="filter-button" size="small" text :type="filters[column.key] != null ? 'primary' : 'info'" :icon="Filter" :aria-label="'筛选' + column.label" :title="'筛选' + column.label" :aria-expanded="filterKey === column.key" /></template>
          <el-input v-model="filterSearch" size="small" placeholder="搜索候选值" clearable />
          <div class="filter-tools"><el-button size="small" link @click="selectVisible(true)">全选搜索结果</el-button><el-button size="small" link @click="selectVisible(false)">清空搜索结果</el-button></div>
          <el-checkbox-group v-model="draftValues" class="filter-options"><el-checkbox v-for="value in visibleValues" :key="value" :value="value" :label="value">{{ filterLabel(value) }}</el-checkbox></el-checkbox-group>
          <p v-if="autoApplyFilters" class="filter-hint">关闭浮层时自动应用选择</p>
          <div class="filter-tools"><el-button size="small" @click="resetFilter(column.key)">不限</el-button><el-button size="small" type="primary" @click="applyFilter(column.key)">应用</el-button></div>
        </el-popover></span></template>
        <template #default="{row, $index}"><slot name="cell" :row="row" :column="column" :index="$index">{{ format(row, column) }}</slot></template>
      </el-table-column>
      <el-table-column v-if="$slots.actions" label="操作" fixed="right" :width="actionsWidth"><template #default="{row}"><slot name="actions" :row="row" /></template></el-table-column>
    </el-table>
    <el-pagination v-if="pageSize && filtered.length > pageSize" v-model:current-page="page" :page-size="pageSize" :total="filtered.length" small layout="prev, pager, next, total" class="table-pagination" />
  </div>
</template>
<script setup>
import { ref, computed, watch } from 'vue'
import { Filter } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import TableColumnSettings from './TableColumnSettings.vue'
import { loadColumnLayout, normalizeColumnLayout, saveColumnLayout } from '../utils/tableColumnLayout'
import { probeStatusLabel } from '../utils/probeWorkspace'
import { probeFilterValue, probeFilterOptions, filterProbeRows, selectVisibleFilterValues } from '../utils/probeTableFilters'
const props = defineProps({ rows: { type: Array, required: true }, columns: { type: Array, required: true }, tableId: { type: String, required: true }, height: Number, fillHeight: Boolean, actionsWidth: { type: Number, default: 180 }, pageSize: { type: Number, default: 0 }, autoApplyFilters: Boolean, groupTools: Boolean })
const emit = defineEmits(['filtered'])
const storage = { getItem: key => localStorage.getItem(key), setItem: (key, value) => localStorage.setItem(key, value) }
const key = `probe-${props.tableId}-layout-v1`
const layout = ref(loadColumnLayout(storage, key, props.columns, ElMessage.warning))
const visibleColumns = computed(() => layout.value.filter(c => c.visible))
const structureKey = computed(() => visibleColumns.value.map(c => c.key + ':' + c.fixed).join('|'))
function applyLayout(value) { layout.value = normalizeColumnLayout(props.columns, value); saveColumnLayout(storage, key, layout.value, ElMessage.warning) }
function resize(width, old, column) { applyLayout(layout.value.map(c => c.key === column.property ? { ...c, width } : c)) }
const filters = ref({}), filterKey = ref(''), filterSearch = ref(''), draftValues = ref([])
const filtered = computed(() => filterProbeRows(props.rows, filters.value, props.columns.filter(column => column.multiValue).map(column => column.key)))
const page = ref(1)
const displayRows = computed(() => props.pageSize ? filtered.value.slice((page.value - 1) * props.pageSize, page.value * props.pageSize) : filtered.value)
watch(filtered, rows => { page.value = 1; emit('filtered', rows) }, { immediate: true })
const allValues = computed(() => probeFilterOptions(props.rows, filterKey.value, props.columns.find(column => column.key === filterKey.value)?.multiValue))
const visibleValues = computed(() => allValues.value.filter(value => filterLabel(value).toLowerCase().includes(filterSearch.value.toLowerCase())))
function openFilter(key) { if (props.autoApplyFilters && filterKey.value && filterKey.value !== key) finishFilter(filterKey.value); filterKey.value = key; filterSearch.value = ''; draftValues.value = [...(filters.value[key] ?? allValues.value)] }
function finishFilter(key) { if (filterKey.value !== key) return; if (props.autoApplyFilters) filters.value = { ...filters.value, [key]: [...draftValues.value] }; filterKey.value = '' }
function clearFilters() { const key = filterKey.value; filterKey.value = ''; filters.value = {}; if (key) closePopover(key) }
function selectVisible(checked) { draftValues.value = selectVisibleFilterValues(draftValues.value, visibleValues.value, checked) }
const popovers = {}
function filterLabel(value) { const column = props.columns.find(column => column.key === filterKey.value); return column?.filterLabel ? column.filterLabel(value) : value ? filterKey.value.endsWith('_status') ? probeStatusLabel(value) : value : '(空白)' }
function closePopover(key) { popovers[key]?.hide() }
function resetFilter(key) { filters.value = { ...filters.value, [key]: null }; if (props.autoApplyFilters) filterKey.value = ''; closePopover(key) }
function applyFilter(key) { filters.value = { ...filters.value, [key]: [...draftValues.value] }; closePopover(key) }
function format(row, column) { const value = row[column.key]; return column.format ? column.format(row) : column.key.endsWith('_status') ? probeStatusLabel(value) : probeFilterValue(value) }
watch(() => props.columns.map(c => c.key).join('|'), () => { layout.value = normalizeColumnLayout(props.columns, layout.value) })
</script>
<style scoped>
.table-actions,.filter-tools,.column-heading{display:flex;align-items:center;gap:6px;flex-wrap:wrap}.table-actions{justify-content:flex-end;margin:4px 0}.table-actions .el-button+.el-button{margin-left:0}.column-heading{justify-content:space-between;flex-wrap:nowrap}.filter-button{width:24px;height:24px;padding:3px}.filter-tools{margin-top:7px}.filter-options{display:flex;flex-direction:column;align-items:flex-start;max-height:220px;overflow:auto;margin-top:8px}.filter-options .el-checkbox{margin:0;width:100%;height:auto;min-height:26px;white-space:normal}.probe-data-table{width:100%;overflow:hidden}
.table-pagination{margin-top:8px;justify-content:flex-end}.filter-hint{font-size:12px;color:var(--el-text-color-secondary);margin:8px 0}
.fill-height{display:flex;flex-direction:column;flex:1;min-height:0}.fill-height>.el-table{flex:1;min-height:0}.fill-height>.table-actions,.fill-height>.table-pagination{flex-shrink:0}
.table-tools{display:contents}.table-tools.is-grouped{display:flex;align-items:center;justify-content:flex-end;flex-wrap:wrap;gap:6px;max-width:100%}.table-tools>span{white-space:nowrap}
</style>
