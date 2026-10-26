<template>
  <div class="version-comparison">
    <div ref="controls" class="select-area">
      <div class="select-row">
        <div class="select-item"><label>原版本：</label>
          <el-select :model-value="version1" @update:model-value="emit('update:version1', $event)" :loading="optionsLoading" :disabled="optionsLoading" placeholder="选择原版本" style="width:180px">
            <el-option v-for="version in versions" :key="version.id" :label="version.version_number" :value="version.id" />
          </el-select>
        </div>
        <div class="select-item"><label>对比版本：</label>
          <el-select :model-value="version2" @update:model-value="emit('update:version2', $event)" :loading="optionsLoading" :disabled="optionsLoading" placeholder="选择对比版本" style="width:180px">
            <el-option v-for="version in versions" :key="version.id" :label="version.version_number" :value="version.id" />
          </el-select>
        </div>
        <div class="select-item"><label>对比型号：</label>
          <el-select v-model="modelIds" multiple collapse-tags collapse-tags-tooltip placeholder="选择要对比的型号" style="width:220px" :disabled="!result || loading" popper-class="version-model-dropdown">
            <template #header>
              <el-input v-model="modelSearch" placeholder="输入搜索型号..." size="small" clearable @keydown.stop />
              <div class="model-actions">
                <el-button size="small" @click="modelIds = modelOptions.map(model => model.id)">全选</el-button>
                <el-button size="small" @click="modelIds = []">取消</el-button>
                <el-button size="small" @click="modelIds = modelOptions.filter(model => !modelIds.includes(model.id)).map(model => model.id)">反选</el-button>
                <el-button size="small" :disabled="!modelSearch.trim()" @click="modelIds = [...new Set([...modelIds, ...filteredModels.map(model => model.id)])]">选中匹配</el-button>
              </div>
            </template>
            <el-option v-for="model in filteredModels" :key="model.id" :label="model.name" :value="model.id" />
          </el-select>
        </div>
        <el-button :type="onlyDiff ? 'primary' : 'default'" :icon="Filter" size="small" @click="onlyDiff = !onlyDiff">仅差异项</el-button>
        <el-button type="primary" :loading="loading" :disabled="!canCompare" @click="compareNow">对比</el-button>
      </div>
      <div class="select-row">
        <div class="select-item"><label>对比字段：</label>
          <el-checkbox-group v-model="fields" :min="1"><el-checkbox v-for="field in VERSION_COMPARE_FIELDS" :key="field.key" :label="field.key">{{ field.label }}</el-checkbox></el-checkbox-group>
        </div>
        <div class="select-item"><label>显示列：</label>
          <el-checkbox-group v-model="nameColumns" :min="1"><el-checkbox v-for="column in VERSION_NAME_COLUMNS" :key="column.key" :label="column.key">{{ column.label }}</el-checkbox></el-checkbox-group>
        </div>
      </div>
    </div>
    <div v-loading="loading" class="comparison-body">
      <template v-if="result">
        <div class="result-header">
          <span>总配置项 <strong>{{ scopedRows.length }}</strong> · 差异项 <strong class="diff-count">{{ diffCount }}</strong> · 当前显示 {{ visibleRows.length }} 项</span>
          <div class="result-actions">
            <el-button size="small" @click="resetWidths">恢复列宽</el-button>
            <el-button :icon="Download" :loading="exporting" :disabled="loading || !visibleRows.length || !modelIds.length" @click="exportResult">导出结果</el-button>
          </div>
        </div>
        <div ref="tableContainer">
          <el-table :data="pageRows" row-key="key" size="small" border stripe :max-height="tableHeight" style="width:100%" @header-dragend="resizeColumn">
            <el-table-column v-for="column in visibleNameColumns" :key="column.key" :prop="column.key" :label="column.label" :width="widths[column.key] || column.width" :column-key="column.key" fixed show-overflow-tooltip />
            <el-table-column v-for="model in visibleModels" :key="model.id" :label="model.name" align="center">
              <el-table-column v-for="side in sides" :key="side.key" :label="side.label" align="center">
                <el-table-column v-for="field in visibleFields" :key="field.key" :label="field.label" :width="widths[field.key] || 100" :column-key="field.key" show-overflow-tooltip>
                  <template #default="{ row }"><span :class="{ 'diff-value': versionCellChanged(row, model.id, field.key) }">{{ row[side.key]?.[model.id]?.[field.key] ?? '-' }}</span></template>
                </el-table-column>
              </el-table-column>
            </el-table-column>
            <template #empty>{{ !modelIds.length ? '请选择要对比的机型' : onlyDiff ? '所选字段没有差异，可关闭“仅差异项”查看全部' : '当前机型没有配置项' }}</template>
          </el-table>
        </div>
        <el-pagination v-if="visibleRows.length" v-model:current-page="currentPage" v-model:page-size="pageSize" :page-sizes="[20, 30, 50, 100]" :total="visibleRows.length" layout="total, sizes, prev, pager, next" small class="matrix-pagination" />
        <p class="comparison-note">以原版本为基准，差异值高亮；表头拖动可调整列宽。历史快照仅供查看。</p>
      </template>
      <el-empty v-else-if="!loading" description="请选择两个不同版本进行对比" :image-size="60" />
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { Filter, Download } from '@element-plus/icons-vue'
import { exportVersionCompare } from '../api/data'
import { VERSION_COMPARE_FIELDS, VERSION_NAME_COLUMNS, versionCellChanged, versionRowChanged, scopeVersionRows, filterVersionRows, versionExportPayload, reconcileVersionModelSelection } from '../utils/versionComparison'

const props = defineProps({ versions: { type: Array, default: () => [] }, version1: Number, version2: Number, result: Object, loading: Boolean, optionsLoading: Boolean })
const emit = defineEmits(['update:version1', 'update:version2', 'compare'])
const controls = ref(null), tableContainer = ref(null)
const fields = ref(['final_config', 'current_config']), nameColumns = ref(['rd_name', 'zh_desc', 'v_code', 'ipn']), onlyDiff = ref(true)
const currentPage = ref(1), pageSize = ref(30)
const modelIds = ref([]), modelSearch = ref(''), exporting = ref(false), tableHeight = ref(400)
// Bootstrap the complete pair; canonical model IDs and names come from historical
// snapshots normalized by the server, never from today's model catalog.
const modelOptions = computed(() => props.result?.matrix_models || [])
const filteredModels = computed(() => modelOptions.value.filter(model => model.name.toLowerCase().includes(modelSearch.value.trim().toLowerCase())))
const visibleModels = computed(() => modelOptions.value.filter(model => modelIds.value.includes(model.id)))
const canCompare = computed(() => Boolean(props.version1 && props.version2 && props.version1 !== props.version2 && !props.optionsLoading))
const visibleNameColumns = computed(() => VERSION_NAME_COLUMNS.filter(column => nameColumns.value.includes(column.key)))
const visibleFields = computed(() => VERSION_COMPARE_FIELDS.filter(field => fields.value.includes(field.key)))
const rows = computed(() => props.result?.matrix_rows || [])
const scopedRows = computed(() => scopeVersionRows(rows.value, modelIds.value))
const diffCount = computed(() => scopedRows.value.filter(row => versionRowChanged(row, modelIds.value, fields.value)).length)
const visibleRows = computed(() => filterVersionRows(rows.value, modelIds.value, fields.value, onlyDiff.value))
const pageRows = computed(() => visibleRows.value.slice((currentPage.value - 1) * pageSize.value, currentPage.value * pageSize.value))
watch([visibleRows, pageSize], () => { currentPage.value = 1 })
const sides = computed(() => [
  { key: 'old_values', label: `原版本 ${props.result?.version_1?.version_number || ''}` },
  { key: 'new_values', label: `对比版本 ${props.result?.version_2?.version_number || ''}` }
])
let compareTimer, alive = true, loadedPair = '', loadedModelIds = []
const compareNow = () => { clearTimeout(compareTimer); if (canCompare.value) emit('compare') }
watch(() => [props.version1, props.version2, props.optionsLoading], () => {
  clearTimeout(compareTimer)
  modelIds.value = []
  loadedPair = ''
  loadedModelIds = []
  if (canCompare.value) compareTimer = setTimeout(compareNow, 180)
}, { immediate: true, flush: 'post' })
watch(() => props.result, result => {
  if (!result) return
  const pair = `${result.version_1.id}:${result.version_2.id}`
  const available = (result.matrix_models || []).map(model => model.id)
  modelIds.value = reconcileVersionModelSelection(modelIds.value, loadedModelIds, available, pair === loadedPair)
  loadedPair = pair
  loadedModelIds = available
})

const WIDTH_KEY = 'version-comparison-column-widths'
const readWidths = () => {
  try {
    const parsed = JSON.parse(localStorage.getItem(WIDTH_KEY) || '{}')
    return Object.fromEntries(Object.entries(parsed).filter(([key, width]) => [...VERSION_COMPARE_FIELDS, ...VERSION_NAME_COLUMNS].some(column => column.key === key) && Number.isFinite(width) && width >= 30))
  } catch { return {} }
}
const widths = ref(readWidths())
const saveWidths = () => { try { localStorage.setItem(WIDTH_KEY, JSON.stringify(widths.value)) } catch { /* Width persistence is optional. */ } }
const resizeColumn = (width, _old, column) => { if (column.columnKey && width >= 30) { widths.value = { ...widths.value, [column.columnKey]: width }; saveWidths() } }
const resetWidths = () => { widths.value = {}; saveWidths() }
const measureTable = () => { if (tableContainer.value) tableHeight.value = Math.max(200, window.innerHeight - tableContainer.value.getBoundingClientRect().top - 125) }
let resizeObserver
onMounted(() => { window.addEventListener('resize', measureTable); resizeObserver = new ResizeObserver(measureTable); if (controls.value) resizeObserver.observe(controls.value) })
watch([() => props.result, visibleRows, fields, nameColumns], () => nextTick(measureTable), { flush: 'post' })
onBeforeUnmount(() => { alive = false; clearTimeout(compareTimer); resizeObserver?.disconnect(); window.removeEventListener('resize', measureTable) })

const exportKey = () => JSON.stringify([props.version1, props.version2, modelIds.value, fields.value, nameColumns.value, onlyDiff.value])
const exportResult = async () => {
  if (!props.result || !modelIds.value.length || props.loading || exporting.value || !visibleRows.value.length) return
  const key = exportKey(), sourceResult = props.result
  const payload = versionExportPayload(sourceResult, visibleModels.value.map(model => model.id), visibleFields.value.map(field => field.key), visibleNameColumns.value.map(column => column.key), onlyDiff.value)
  exporting.value = true
  try {
    const blob = await exportVersionCompare(payload)
    if (!alive || key !== exportKey() || props.result !== sourceResult) return
    const url = URL.createObjectURL(blob), link = document.createElement('a')
    link.href = url; link.download = `版本对比_${sourceResult.version_1.version_number}_${sourceResult.version_2.version_number}.xlsx`
    document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url)
    ElMessage.success('导出成功')
  } catch (error) {
    if (alive && key === exportKey()) ElMessage.error('导出失败，请重试')
  } finally { exporting.value = false }
}
</script>

<style scoped>
.select-area { padding-bottom:12px; border-bottom:1px solid var(--el-border-color-lighter); }
.select-row { display:flex; align-items:center; flex-wrap:wrap; gap:12px 20px; margin-bottom:10px; }
.select-row:last-child { margin-bottom:0; }
.select-item { display:flex; align-items:center; gap:6px; min-width:0; }
.select-item label { white-space:nowrap; }
.select-item :deep(.el-checkbox) { margin-right:12px; }
.model-actions { display:flex; gap:6px; margin-top:8px; }
.model-actions .el-button + .el-button { margin-left:0; }
.result-header { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:8px; margin:12px 0; }
.result-actions { display:flex; align-items:center; gap:8px; }
.diff-count { color:var(--el-color-warning); }
.diff-value { color:#b45b00; background:#fff4db; font-weight:600; padding:2px 4px; border-radius:2px; }
.matrix-pagination { justify-content:flex-end; margin-top:10px; }
.comparison-note { font-size:12px; color:var(--el-text-color-secondary); margin:8px 0 0; }
.comparison-body { min-height:120px; }
</style>
