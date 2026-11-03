<template>
  <section class="measurement-library" v-loading="loading">
    <div class="toolbar measurement-main-toolbar">
      <div v-if="library.batch" class="query-controls">
        <el-input v-model="query" placeholder="查找 Id、英文 UI 或中文 UI 名称" :prefix-icon="Search" clearable size="small" class="search-input" />
        <el-button class="query-reset" size="small" @click="clearFilters">清除查询条件</el-button>
        <div class="classification-filter">
          <span class="filter-group-label">分类</span>
          <el-radio-group v-model="scope" size="small" aria-label="测量分类" class="measurement-classification measurement-segments scope-segments">
            <el-radio-button v-for="option in scopeOptions" :key="option.value" :value="option.value" :title="`${option.label} · ${facets.scopes[option.countKey]} 条`">{{ option.label }}</el-radio-button>
          </el-radio-group>
        </div>
      </div>
      <div class="source-controls">
        <el-select v-if="library.batches.length" v-model="batchId" aria-label="测量库版本" size="small" class="batch-select" @change="loadLibrary">
          <el-option v-for="batch in library.batches" :key="batch.id" :value="batch.id" :label="`${batch.version} · ${batch.source_file} · #${batch.id}`" />
        </el-select>
        <el-button size="small" type="primary" @click="openImport">导入人用中文表</el-button>
        <el-button size="small" @click="loadLibrary">刷新</el-button>
      </div>
    </div>
    <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" show-icon />
    <template v-if="library.batch">
      <div class="measurement-browser">
        <aside class="measurement-filter-sidebar" aria-label="测量库筛选">
          <nav class="filter-navigation application-filter-column" aria-label="应用筛选导航">
            <div class="facet-heading"><strong>应用</strong><span class="navigation-level">按应用查找</span></div>
            <div class="filter-navigation-body">
              <el-button class="navigation-all" size="small" text :type="!selectedApplications.length ? 'primary' : 'default'" :aria-pressed="!selectedApplications.length" @click="selectedApplications = []">不限应用</el-button>
              <el-checkbox-group v-model="selectedApplications" aria-label="具体应用" class="facet-options" @change="selectApplication">
                <div v-for="application in facets.categories" :key="application.value" class="facet-option">
                  <el-checkbox :value="application.value" :label="application.value">{{ application.value }}</el-checkbox><span class="facet-count">{{ application.count }}</span>
                </div>
              </el-checkbox-group>
              <p v-if="!facets.categories.length" class="navigation-empty">暂无具体应用</p>
            </div>
          </nav>
          <nav class="filter-navigation mode-filter-column" aria-label="模式筛选导航">
            <div class="facet-heading"><strong>关联模式</strong><span class="navigation-level">按模式细分</span></div>
            <div class="filter-navigation-body">
              <el-button class="navigation-all" size="small" text :type="!selectedModes.length ? 'primary' : 'default'" :aria-pressed="!selectedModes.length" @click="selectedModes = []">不限模式</el-button>
              <el-checkbox-group v-model="selectedModes" aria-label="关联模式" class="facet-options">
                <div v-for="option in facets.modes" :key="option.value" class="facet-option">
                  <el-checkbox :value="option.value" :label="option.value">{{ option.value || '未标注模式' }}</el-checkbox><span class="facet-count">{{ option.count }}</span>
                </div>
              </el-checkbox-group>
            </div>
          </nav>
          <p class="facet-hint">同组多选，应用与模式交叉筛选。未勾选表示不限；数字为列筛选前的记录数。</p>
        </aside>
        <div class="table-region">
          <el-alert v-if="!visibleRows.length" title="当前条件未命中" type="info" :closable="false">
            <template #default><span>可清除筛选后在当前版本全库查找。</span><el-button size="small" link type="primary" @click="clearFilters">清除查询条件</el-button></template>
          </el-alert>
        <ProbeDataTable :key="tableKey" table-id="human-measurement-library" :rows="rows" :columns="columns" fill-height :page-size="50" auto-apply-filters :actions-width="150" @filtered="visibleRows = $event">
          <template #toolbar>
            <div class="measurement-table-context">
              <div class="measurement-secondary-controls">
                <span class="secondary-label">记录类型</span>
                <el-radio-group v-model="kind" size="small" aria-label="记录类型" class="measurement-segments type-segments">
                  <el-radio-button value="">全部</el-radio-button><el-radio-button value="measurement">测量项</el-radio-button><el-radio-button value="calculation">计算项</el-radio-button>
                </el-radio-group>
              </div>
              <el-checkbox v-model="includePending" class="pending-toggle" :class="{ 'is-included': includePending }" size="small">包含待核对建议</el-checkbox>
              <span class="result-line" aria-live="polite">
                <template v-if="query.trim()">精确 {{ exactCount }} 条，部分命中 {{ visibleRows.length - exactCount }} 条 · </template>
                {{ counts.measurements }} 个测量 Id，{{ counts.calculations }} 个计算 Id
              </span>
              <el-popover v-model:visible="statisticsOpen" trigger="click" placement="bottom-end" :width="720" popper-class="measurement-statistics-popover" @show="focusStatistics">
                <template #reference><el-button ref="statisticsButton" size="small" text :type="library.batch.warnings.length ? 'warning' : 'info'" :aria-expanded="statisticsOpen" @keydown.esc.stop.prevent="closeStatistics">统计与导入核对 <el-tag v-if="library.batch.warnings.length" size="small" type="warning" class="warning-tag">{{ library.batch.warnings.length }} 项提示</el-tag></el-button></template>
                <div ref="statisticsPanel" class="statistics-content" tabindex="-1" @keydown.esc.stop.prevent="closeStatistics">
                  <p>来源版本 {{ library.batch.version }} · {{ library.batch.source_file }} · 测量明细 {{ summary.measurement_rows }} 行 / {{ summary.measurement_ids }} 个 Id，计算明细 {{ summary.calculation_rows }} 行 / {{ summary.calculation_ids }} 个 Id。</p>
                  <p>原表测量项分类：常规测量 {{ summary.common_rows }} 行，应用测量 {{ summary.application_rows }} 行，未分类 {{ summary.unclassified_rows }} 行。明细含 {{ summary.duplicate_rows }} 行完全重复记录；跨模式同 Id 按多条关系保留。</p>
                  <p>英文 UI 使用 Description，空时显示 Id；中文 UI 使用 ChineseName。英文回退 {{ summary.english_id_fallback }} 行，中文名称缺失 {{ summary.missing_chinese }} 行。</p>
                  <div v-for="group in statistics" :key="group.label" class="statistics-row"><strong>{{ group.label }}</strong><span v-for="([name, count]) in Object.entries(group.values)" :key="name" class="count-chip">{{ name || '(空白)' }} <b>{{ count }}</b></span></div>
                  <ul v-if="library.batch.warnings.length" class="warnings"><li v-for="warning in library.batch.warnings" :key="warning">{{ warning }}</li></ul>
                </div>
              </el-popover>
            </div>
          </template>
          <template #actions="{ row }">
            <el-button size="small" link type="primary" @click="detail = row">详情</el-button>
            <el-button v-if="row.enrichment?.candidate" size="small" link type="primary" @click="enrichmentReview.open(row)">核对建议</el-button>
          </template>
        </ProbeDataTable>
        </div>
      </div>
    </template>
    <el-empty v-else-if="!loading && !loadError" description="尚未导入测量库，请导入人用中文表" />
    <MeasurementEnrichmentReviewDialog ref="enrichmentReview" :records="library.entries" @saved="loadLibrary" />

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
import { computed, nextTick, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import api from '../api/index'
import ProbeDataTable from '../components/ProbeDataTable.vue'
import { filterMeasurements, measurementCounts, measurementFacets, projectMeasurementRow } from '../utils/measurementLibrary'
import MeasurementEnrichmentReviewDialog from '../components/MeasurementEnrichmentReviewDialog.vue'

const library = ref({ batches: [], batch: null, entries: [] })
const batchId = ref(null), loading = ref(false), loadError = ref('')
const query = ref(''), kind = ref(''), scope = ref(''), resetCounter = ref(0)
const selectedApplications = ref([]), selectedModes = ref([])
const scopeOptions = [
  { value: '', label: '全部分类', countKey: 'all' },
  { value: 'common', label: '常规测量', countKey: 'common' },
  { value: 'application', label: '应用测量', countKey: 'application' },
  { value: 'unclassified', label: '未分类', countKey: 'unclassified' }
]
const includePending = ref(true), enrichmentReview = ref(null)
const visibleRows = ref([]), detail = ref(null)
const statisticsOpen = ref(false), statisticsPanel = ref(null), statisticsButton = ref(null)
function focusStatistics() { nextTick(() => statisticsPanel.value?.focus({ preventScroll: true })) }
function closeStatistics() { statisticsOpen.value = false; nextTick(() => statisticsButton.value?.$el?.focus({ preventScroll: true })) }
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
  { key: 'mode', label: '关联模式', width: 140, multiValue: true, format: row => Array.isArray(row.mode) ? row.mode.join('；') || '(空白)' : row.mode || '(空白)' },
  { key: 'categories', label: '应用', width: 150, multiValue: true },
  { key: 'classification_basis', label: '分类依据', width: 130 },
  { key: 'enrichment_status', label: '补充状态', width: 145 },
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
  { key: 'name_note', label: '名称提示' },
  { key: 'classification_basis', label: '分类依据' }, { key: 'enrichment_status', label: '补充状态' },
  { key: 'source_mode', label: '原表模式' },
  { key: 'source_categories', label: '原表应用', format: row => row.source_categories?.join('；') || '(空白)' }
]
const statistics = computed(() => [
  { label: '测量模式', values: summary.value.modes || {} },
  { label: '应用分类', values: summary.value.categories || {} },
  { label: '计算分组', values: summary.value.groups || {} },
  { label: '计算启用状态', values: Object.fromEntries(Object.entries(summary.value.enabled || {}).map(([key, value]) => [enabledLabel(key), value])) }
])
const projectedRows = computed(() => library.value.entries.map(row => projectMeasurementRow(row, includePending.value)))
const sidebarFilters = computed(() => ({ q: query.value, kind: kind.value, scope: scope.value,
  category: selectedApplications.value.length ? selectedApplications.value : null,
  mode: selectedModes.value.length ? selectedModes.value : null }))
const facets = computed(() => measurementFacets(projectedRows.value, sidebarFilters.value))
const rows = computed(() => filterMeasurements(projectedRows.value, sidebarFilters.value).map(row => ({
  ...row, match_label: matchLabel(row.match),
  enabled_label: row.kind === 'calculation' ? enabledLabel(row.enabled) + (row.enabled === 'unknown' && row.enabled_raw ? ` (${row.enabled_raw})` : '') : '',
  name_note: [!row.description ? '英文使用 Id' : '', !row.cn_name ? '中文名缺失' : ''].filter(Boolean).join('；')
})))
const tableKey = computed(() => `${batchId.value}:${kind.value}:${scope.value}:${resetCounter.value}`)
watch(tableKey, () => { statisticsOpen.value = false })
onDeactivated(() => { statisticsOpen.value = false })
watch(scope, value => { kind.value = ''; if (value !== 'application') selectedApplications.value = [] })
function selectApplication(values) { if (values.length) scope.value = 'application' }
function clearFilters() { query.value = ''; kind.value = ''; scope.value = ''; selectedApplications.value = []; selectedModes.value = []; resetCounter.value++ }
let requestId = 0
async function loadLibrary() {
  const current = ++requestId
  loading.value = true; loadError.value = ''
  try {
    const result = await api.get('/measurements', { params: batchId.value ? { batch_id: batchId.value } : {} })
    if (current !== requestId) return
    library.value = result; batchId.value = result.batch?.id ?? null
    detail.value = null
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

onMounted(loadLibrary)
onBeforeUnmount(() => { requestId++ })
</script>

<style scoped>
.measurement-library{display:flex;flex-direction:column;flex:1;min-height:0;width:100%;min-width:0}.toolbar,.query-controls,.source-controls,.measurement-table-context{display:flex;align-items:center;flex-wrap:wrap;gap:8px}.toolbar{margin-bottom:0;flex-shrink:0}.toolbar .el-button+.el-button{margin-left:0}.query-controls{min-width:0}.source-controls{margin-left:auto;justify-content:flex-end}.batch-select{width:330px;max-width:100%}.search-input{width:440px;max-width:100%;--workspace-control-height:38px;--workspace-control-font-size:14px}.query-reset{--workspace-control-height:38px}.scope-hint,.result-line{font-size:12px;color:var(--el-text-color-secondary);line-height:1.7}.measurement-table-context{flex:1 1 520px;min-width:0}.result-line{margin-left:auto}.statistics-content{max-height:min(60vh,520px);overflow:auto;font-size:12px;line-height:1.7}.statistics-content p{margin:4px 0}.statistics-row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:6px}.count-chip{background:var(--el-fill-color-light);border-radius:3px;padding:0 5px;white-space:nowrap}.warning-tag{margin-left:6px}.warnings{padding-left:20px;color:var(--el-color-warning-dark-2);margin:6px 0}.table-region{display:flex;flex-direction:column;flex:1;min-height:180px;min-width:0;width:100%}.detail-value{white-space:pre-wrap;word-break:break-word;user-select:text}
.classification-filter{display:flex;align-items:center;flex-wrap:wrap;gap:8px;min-width:0}
.filter-group-label{font-size:12px;font-weight:600;color:var(--el-color-primary-dark-2)}
.measurement-segments{display:inline-flex;gap:3px;padding:3px;border:1px solid var(--el-border-color-light);border-radius:9px;background:var(--el-fill-color-light)}
.measurement-segments :deep(.el-radio-button .el-radio-button__inner){height:28px;padding:0 12px;border:0;border-radius:6px;background:transparent;box-shadow:none;color:var(--el-text-color-regular);transition:background-color .15s,color .15s}
.measurement-segments :deep(.el-radio-button:not(.is-active) .el-radio-button__inner:hover){background:var(--el-fill-color)}
.measurement-segments :deep(.el-radio-button.is-active .el-radio-button__inner){background:var(--el-color-primary);color:var(--el-color-white);font-weight:600;box-shadow:0 1px 3px #1d4f9a20}
.measurement-segments :deep(.el-radio-button__original-radio:focus-visible + .el-radio-button__inner){outline:2px solid var(--el-color-primary-light-3);outline-offset:1px}
.scope-segments{background:var(--el-color-primary-light-9);border-color:var(--el-color-primary-light-7)}
.type-segments :deep(.el-radio-button.is-active .el-radio-button__inner){background:var(--el-color-primary-light-8);color:var(--el-color-primary-dark-2);box-shadow:0 1px 3px #1d4f9a12}
.pending-toggle.el-checkbox{box-sizing:border-box;height:36px;margin-right:0;padding:0 10px;border:1px solid var(--el-border-color-light);border-radius:8px;background:var(--el-bg-color);transition:background-color .15s,border-color .15s}
.pending-toggle.is-included{border-color:var(--el-color-primary-light-7);background:var(--el-color-primary-light-9)}
.pending-toggle :deep(.el-checkbox__label){font-size:12px}
.pending-toggle:has(input:focus-visible){outline:2px solid var(--el-color-primary-light-3);outline-offset:1px}
.measurement-browser{display:grid;grid-template-columns:440px minmax(0,1fr);gap:14px;flex:1;min-height:0;margin-top:10px}
.measurement-filter-sidebar{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));grid-template-rows:minmax(0,1fr) auto;gap:8px 10px;min-height:0}
.filter-navigation{display:flex;flex-direction:column;min-width:0;min-height:0;border:1px solid var(--el-border-color);border-radius:8px;overflow:hidden;background:var(--el-bg-color)}
.facet-heading{display:flex;align-items:center;justify-content:space-between;gap:8px;min-height:42px;flex-shrink:0;padding:0 10px;border-bottom:1px solid var(--el-border-color-lighter);font-size:13px}
.facet-heading strong{display:flex;align-items:center;gap:7px;white-space:nowrap}
.facet-heading strong::before{content:'';width:3px;height:14px;border-radius:2px;background:var(--el-color-primary)}
.navigation-level{font-size:11px;color:var(--el-text-color-secondary);white-space:nowrap}
.application-filter-column{background:var(--el-color-primary-light-9);border-color:var(--el-color-primary-light-7)}
.application-filter-column .facet-heading{background:var(--el-color-primary-light-8);border-bottom-color:var(--el-color-primary-light-7);color:var(--el-color-primary-dark-2)}
.mode-filter-column .facet-heading{background:var(--el-fill-color-light)}
.mode-filter-column .facet-heading strong::before{background:var(--el-color-success)}
.filter-navigation-body{flex:1;min-height:0;overflow:auto;padding:8px 6px;overscroll-behavior:contain}
.navigation-all{display:flex;width:100%;justify-content:flex-start;border-radius:4px;min-height:32px;padding-left:10px;margin-bottom:4px}
.navigation-all[aria-pressed='true']{background:var(--el-color-primary-light-8);font-weight:600}
.facet-options{display:flex;flex-direction:column;gap:3px;padding-left:6px;border-left:1px solid var(--el-border-color)}
.facet-option{display:flex;align-items:center;gap:6px;min-height:34px;padding:0 6px;border-left:2px solid transparent;border-radius:4px}
.facet-option:hover{background:var(--el-fill-color-light)}
.facet-option :deep(.el-checkbox){display:flex;flex:1;min-width:0;margin:0;height:auto;min-height:34px}
.facet-option :deep(.el-checkbox__label){white-space:normal;overflow-wrap:anywhere;font-size:13px;line-height:1.5}
.facet-count{flex-shrink:0;min-width:24px;text-align:right;font-size:11px;font-variant-numeric:tabular-nums;color:var(--el-text-color-secondary)}
.facet-option:has(.is-checked){border-left-color:var(--el-color-primary);background:var(--el-color-primary-light-8)}
.mode-filter-column .facet-option:has(.is-checked){border-left-color:var(--el-color-success);background:var(--el-color-success-light-9)}
.navigation-empty,.facet-hint{font-size:11px;color:var(--el-text-color-secondary);line-height:1.7}
.facet-hint{grid-column:1/-1;margin:0 4px}
.measurement-secondary-controls{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.secondary-label{font-size:12px;color:var(--el-text-color-secondary);white-space:nowrap}
:global(.measurement-statistics-popover){max-width:calc(100vw - 24px);box-sizing:border-box}
@media(max-width:1100px){.query-controls{flex:1 1 100%}.source-controls{flex-wrap:wrap}.result-line{margin-left:0}}
@media(max-width:1100px) and (min-width:901px){.measurement-browser{grid-template-columns:340px minmax(0,1fr);gap:10px}}
@media(max-width:900px){.measurement-browser{grid-template-columns:minmax(0,1fr);grid-template-rows:auto minmax(260px,1fr)}.measurement-filter-sidebar{height:240px}.table-region{min-height:260px}}
</style>
