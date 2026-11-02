<template>
  <section class="measurement-library" v-loading="loading">
    <div class="toolbar">
      <el-select v-if="library.batches.length" v-model="batchId" aria-label="测量库版本" size="small" class="batch-select" @change="loadLibrary">
        <el-option v-for="batch in library.batches" :key="batch.id" :value="batch.id" :label="`${batch.version} · ${batch.source_file} · #${batch.id}`" />
      </el-select>
      <el-button size="small" type="primary" @click="openImport">导入人用中文表</el-button>
      <el-button size="small" @click="loadLibrary">刷新</el-button>
    </div>
    <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" show-icon />
    <template v-if="library.batch">
      <div class="source-line">人用 · 来源版本 {{ library.batch.version }} · {{ library.batch.source_file }} · 测量明细 {{ summary.measurement_rows }} 行 / {{ summary.measurement_ids }} 个 Id，计算明细 {{ summary.calculation_rows }} 行 / {{ summary.calculation_ids }} 个 Id</div>
      <div class="toolbar query-toolbar">
        <el-input v-model="query" placeholder="查找 Id、英文 UI 或中文 UI 名称" clearable size="small" class="search-input" />
        <el-radio-group v-model="kind" size="small" aria-label="记录类型">
          <el-radio-button value="">全部</el-radio-button><el-radio-button value="measurement">测量项</el-radio-button><el-radio-button value="calculation">计算项</el-radio-button>
        </el-radio-group>
        <el-button size="small" @click="clearFilters">清除查询条件</el-button>
      </div>
      <div class="toolbar">
        <el-radio-group v-model="scope" size="small" aria-label="测量分类">
          <el-radio-button value="">全部分类</el-radio-button><el-radio-button value="common">常规测量</el-radio-button><el-radio-button value="application">应用测量</el-radio-button><el-radio-button value="unclassified">未分类</el-radio-button>
        </el-radio-group>
        <span class="scope-hint">常规 / 应用分类仅适用于测量项；模式、应用和计算分组在列标题中筛选。</span>
      </div>
      <el-collapse v-model="expanded" class="statistics">
        <el-collapse-item name="statistics">
          <template #title>统计与导入核对 <el-tag v-if="library.batch.warnings.length" size="small" type="warning" class="warning-tag">{{ library.batch.warnings.length }} 项提示</el-tag></template>
          <p>当前版本：常规测量 {{ summary.common_rows }} 行，应用测量 {{ summary.application_rows }} 行，未分类 {{ summary.unclassified_rows }} 行。明细含 {{ summary.duplicate_rows }} 行完全重复记录；跨模式同 Id 按多条关系保留。</p>
          <p>英文 UI 使用 Description，空时显示 Id；中文 UI 使用 ChineseName。英文回退 {{ summary.english_id_fallback }} 行，中文名称缺失 {{ summary.missing_chinese }} 行。</p>
          <div v-for="group in statistics" :key="group.label" class="statistics-row"><strong>{{ group.label }}</strong><span v-for="([name, count]) in Object.entries(group.values)" :key="name" class="count-chip">{{ name || '(空白)' }} <b>{{ count }}</b></span></div>
          <ul v-if="library.batch.warnings.length" class="warnings"><li v-for="warning in library.batch.warnings" :key="warning">{{ warning }}</li></ul>
        </el-collapse-item>
      </el-collapse>
      <div class="result-line" aria-live="polite">
        <span v-if="query.trim()">名称精确命中 {{ exactCount }} 条，部分名称命中 {{ visibleRows.length - exactCount }} 条。</span>
        当前显示 {{ counts.rows }} 条关系，涉及 {{ counts.measurements }} 个测量 Id、{{ counts.calculations }} 个计算 Id。
      </div>
      <el-alert v-if="!visibleRows.length" title="当前条件未命中" type="info" :closable="false">
        <template #default><span>可清除筛选后在当前版本全库查找。</span><el-button size="small" link type="primary" @click="clearFilters">清除查询条件</el-button></template>
      </el-alert>
      <div ref="tableRegion" class="table-region">
        <ProbeDataTable :key="tableKey" table-id="human-measurement-library" :rows="rows" :columns="columns" :height="tableHeight" :page-size="50" auto-apply-filters :actions-width="76" @filtered="visibleRows = $event">
          <template #actions="{ row }"><el-button size="small" link type="primary" @click="detail = row">详情</el-button></template>
        </ProbeDataTable>
      </div>
    </template>
    <el-empty v-else-if="!loading && !loadError" description="尚未导入测量库，请导入人用中文表" />

    <el-dialog v-model="importVisible" title="导入人用测量库" width="min(540px, calc(100vw - 32px))" :before-close="closeImport" :close-on-click-modal="!importing" :close-on-press-escape="!importing" :show-close="!importing">
      <el-form label-width="90px" size="small">
        <el-form-item label="来源版本" for="measurement-version"><el-input id="measurement-version" v-model="importVersion" maxlength="80" placeholder="例如 1.51.90" :disabled="importing" /></el-form-item>
        <el-form-item label="人用中文表" for="measurement-file"><input id="measurement-file" ref="fileInput" type="file" accept=".xlsx" :disabled="importing" @change="selectFile" /></el-form-item>
      </el-form>
      <p class="scope-hint">读取第一个 sheet 的测量项及第三个 sheet 的计算项。新导入保留历史版本；相同文件与版本重复导入会复用原批次。</p>
      <el-alert v-if="importError" :title="importError" type="error" :closable="false" show-icon />
      <template #footer><el-button size="small" :disabled="importing" @click="closeImport()">取消</el-button><el-button size="small" type="primary" :loading="importing" :disabled="!importFile || !importVersion.trim()" @click="importWorkbook">导入</el-button></template>
    </el-dialog>
    <el-dialog :model-value="!!detail" title="测量记录详情" width="min(680px, calc(100vw - 32px))" @update:model-value="detail = null">
      <template v-if="detail">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item v-for="field in detailFields" :key="field.key" :label="field.label"><span class="detail-value">{{ field.format ? field.format(detail) : detail[field.key] || '(空白)' }}</span></el-descriptions-item>
        </el-descriptions>
        <p class="scope-hint">出处：{{ library.batch.source_file }} · {{ detail.source_sheet }} · 第 {{ detail.source_row }} 行 · 版本 {{ library.batch.version }}</p>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, nextTick, onActivated, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api/index'
import ProbeDataTable from '../components/ProbeDataTable.vue'
import { filterMeasurements, measurementCounts } from '../utils/measurementLibrary'

const library = ref({ batches: [], batch: null, entries: [] })
const batchId = ref(null), loading = ref(false), loadError = ref('')
const query = ref(''), kind = ref(''), scope = ref(''), expanded = ref([]), resetCounter = ref(0)
const visibleRows = ref([]), detail = ref(null), tableRegion = ref(null), tableHeight = ref(320)
const summary = computed(() => library.value.batch?.summary || {})
const counts = computed(() => measurementCounts(visibleRows.value))
const exactCount = computed(() => visibleRows.value.filter(row => row.match === 'exact').length)
const enabledLabel = value => ({ enabled: '已启用', disabled: '未启用', unknown: '待核对' })[value] || '(空白)'
const kindLabel = value => value === 'measurement' ? '测量项' : '计算项'
const matchLabel = value => ({ exact: '名称精确命中', partial: '部分名称命中' })[value] || ''
const columns = [
  { key: 'cn_name', label: '中文 UI 名称', width: 190, fixed: true },
  { key: 'en_name', label: '英文 UI 名称', width: 210 },
  { key: 'item_id', label: 'Id', width: 200 },
  { key: 'kind', label: '记录类型', width: 100, format: row => kindLabel(row.kind), filterLabel: kindLabel },
  { key: 'mode', label: '模式', width: 140 },
  { key: 'categories', label: '应用', width: 150, multiValue: true },
  { key: 'group', label: '计算分组', width: 130 },
  { key: 'unit', label: '单位', width: 100 },
  { key: 'enabled_label', label: '启用状态', width: 140 },
  { key: 'match_label', label: '名称匹配', width: 140 },
  { key: 'name_note', label: '名称提示', width: 220 },
  { key: 'source_sheet', label: '来源 sheet', width: 140, visible: false },
  { key: 'source_row', label: '来源行', width: 90, visible: false }
].map(column => ({ visible: true, fixed: false, ...column }))
const detailFields = [
  { key: 'item_id', label: 'Id' }, { key: 'cn_name', label: '中文 UI 名称' },
  { key: 'en_name', label: '英文 UI 名称' }, { key: 'description', label: '原始 Description' },
  ...columns.filter(column => ['kind', 'mode', 'categories', 'group', 'unit'].includes(column.key)).map(column => ({ ...column, format: column.key === 'categories' ? row => row.categories.join('；') || '(空白)' : column.format })),
  { key: 'enabled_label', label: '启用状态' }, { key: 'enabled_raw', label: '原始 IsEnabled' },
  { key: 'name_note', label: '名称提示' }
]
const statistics = computed(() => [
  { label: '测量模式', values: summary.value.modes || {} },
  { label: '应用分类', values: summary.value.categories || {} },
  { label: '计算分组', values: summary.value.groups || {} },
  { label: '计算启用状态', values: Object.fromEntries(Object.entries(summary.value.enabled || {}).map(([key, value]) => [enabledLabel(key), value])) }
])
const rows = computed(() => filterMeasurements(library.value.entries, { q: query.value, kind: kind.value, scope: scope.value }).map(row => ({
  ...row, match_label: matchLabel(row.match),
  enabled_label: row.kind === 'calculation' ? enabledLabel(row.enabled) + (row.enabled === 'unknown' && row.enabled_raw ? ` (${row.enabled_raw})` : '') : '',
  name_note: [!row.description ? '英文使用 Id' : '', !row.cn_name ? '中文名缺失' : ''].filter(Boolean).join('；')
})))
const tableKey = computed(() => `${batchId.value}:${kind.value}:${scope.value}:${resetCounter.value}`)
watch(kind, value => { if (value === 'calculation') scope.value = '' })
watch(scope, value => { if (value) kind.value = 'measurement' })
function clearFilters() { query.value = ''; kind.value = ''; scope.value = ''; resetCounter.value++ }
let requestId = 0
async function loadLibrary() {
  const current = ++requestId
  loading.value = true; loadError.value = ''
  try {
    const result = await api.get('/measurements', { params: batchId.value ? { batch_id: batchId.value } : {} })
    if (current !== requestId) return
    library.value = result; batchId.value = result.batch?.id ?? null
    detail.value = null
    await nextTick(); resizeTable()
  } catch (error) {
    if (current === requestId) {
      loadError.value = error.response?.data?.detail || '测量库读取失败，请重试'
      library.value = { ...library.value, batch: null, entries: [] }; detail.value = null
    }
  } finally { if (current === requestId) loading.value = false }
}

const importVisible = ref(false), importVersion = ref(''), importFile = ref(null), importing = ref(false), importError = ref(''), fileInput = ref(null)
function openImport() { importFile.value = null; importVersion.value = ''; importError.value = ''; importVisible.value = true; nextTick(() => { if (fileInput.value) fileInput.value.value = '' }) }
function selectFile(event) { importFile.value = event.target.files[0] || null; importError.value = '' }
async function closeImport(done) {
  if (importing.value) return false
  if (importFile.value || importVersion.value.trim()) {
    try { await ElMessageBox.confirm('所选文件尚未导入，确定放弃？', '尚未导入', { confirmButtonText: '放弃', cancelButtonText: '继续导入', type: 'warning' }) }
    catch { return false }
  }
  importVisible.value = false
  if (typeof done === 'function') done()
  return true
}
onBeforeRouteLeave(async () => !importVisible.value || await closeImport())
async function importWorkbook() {
  importing.value = true; importError.value = ''
  const data = new FormData(); data.append('file', importFile.value); data.append('version', importVersion.value.trim())
  try {
    const result = await api.post('/measurements/import', data, { timeout: 120000 })
    importVisible.value = false; batchId.value = result.batch_id; clearFilters()
    ElMessage.success(result.reused ? '相同文件已入库，已打开原批次' : '测量库导入完成')
    await loadLibrary()
  } catch (error) { importError.value = error.response?.data?.detail || '导入失败，请检查表格后重试' }
  finally { importing.value = false }
}

function resizeTable() {
  if (tableRegion.value) tableHeight.value = Math.max(180, window.innerHeight - tableRegion.value.getBoundingClientRect().top - 105)
}
let observer
onMounted(() => { observer = new ResizeObserver(resizeTable); observer.observe(document.querySelector('.measurement-library')); window.addEventListener('resize', resizeTable); loadLibrary() })
watch([expanded, tableRegion], () => nextTick(resizeTable), { deep: true })
onActivated(() => nextTick(resizeTable))
onBeforeUnmount(() => { requestId++; observer?.disconnect(); window.removeEventListener('resize', resizeTable) })
</script>

<style scoped>
.measurement-library{width:100%;min-width:0}.toolbar{display:flex;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:8px}.toolbar h1{font-size:20px;margin:0 8px 0 0}.toolbar .el-button+.el-button{margin-left:0}.batch-select{width:370px;max-width:100%}.search-input{width:360px;max-width:100%}.source-line,.scope-hint,.result-line{font-size:12px;color:var(--el-text-color-secondary);line-height:1.7}.source-line{margin:8px 0}.result-line{margin:6px 0}.statistics :deep(.el-collapse-item__header){height:34px;line-height:34px;font-size:12px}.statistics :deep(.el-collapse-item__content){padding-bottom:8px}.statistics p{margin:4px 0}.statistics-row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:6px}.count-chip{background:var(--el-fill-color-light);border-radius:3px;padding:0 5px;white-space:nowrap}.warning-tag{margin-left:8px}.warnings{padding-left:20px;color:var(--el-color-warning-dark-2);margin:6px 0}.table-region{min-width:0;width:100%}.detail-value{white-space:pre-wrap;word-break:break-word;user-select:text}
</style>
