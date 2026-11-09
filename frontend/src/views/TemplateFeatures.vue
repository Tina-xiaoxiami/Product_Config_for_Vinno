<template>
  <div class="page template-matrix-page">
    <ProbeManagementActions path="/template-features">
        <span v-if="featureCatalog" class="management-meta">功能库 {{ featureCatalog.total }} · 已入模板 {{ features.filter(feature => !feature.pending).length }}</span>
        <el-button size="small" :disabled="loading || !!loadError || !featureCatalog" @click="openTemplateCatalog">从功能库添加</el-button>
        <template v-if="editMode">
          <el-tag size="small" type="warning">编辑中 — {{ pendingCount }} 项修改</el-tag>
          <el-button size="small" type="primary" @click="saveChanges" :disabled="pendingCount === 0">保存草稿</el-button>
          <el-button size="small" @click="cancelEdit">取消</el-button>
        </template>
        <template v-else>
          <el-button size="small" type="primary" @click="enterEditMode">编辑模式</el-button>
          <el-button size="small" @click="refreshData">刷新</el-button>
        </template>
    </ProbeManagementActions>
    <el-alert v-if="loadError" type="error" :closable="false" class="catalog-load-error"><template #title>{{ loadError }} <el-button link size="small" @click="refreshData">重试读取</el-button></template></el-alert>
    <TemplateFeatureCatalogDialog ref="catalogDialog" :catalog="featureCatalog" :categories="categories" :refresh-after-save="refreshCatalogPreview" />
    <el-card shadow="never" class="template-card">
      <div v-if="(draftTotal > 0 || catalogAdditionCount > 0) && !editMode" class="draft-bar">
        <span><strong>{{ draftTotal }}</strong> 条配置草稿待提交<span v-if="catalogAdditionCount"> · 新增功能 {{ catalogAdditionCount }} 项</span></span>
        <el-button size="small" type="primary" @click="submitDrafts" :loading="submitting">提交并创建版本</el-button>
        <el-button size="small" type="danger" @click="discardDrafts">废弃全部</el-button>
      </div>

      <div class="matrix-container" v-loading="loading">
        <div class="toolbar-row">
          <div class="legend">
            <span class="legend-item"><span class="dot supported"></span> 支持</span>
            <span class="legend-item"><span class="dot unsupported"></span> 不支持</span>
            <span v-if="catalogAdditionCount" class="legend-item catalog-preview-legend">待提交预览 {{ catalogAdditionCount }} 项功能</span>
            <span v-if="editMode" class="legend-item"><span class="dot pending"></span> 待保存</span>
          </div>
          <div class="toolbar-right">
            <el-switch v-model="showRegular" size="small" active-text="常规" inactive-text="常规" style="margin-right:4px" />
            <el-switch v-model="showPOC" size="small" active-text="POC" inactive-text="POC" style="margin-right:4px" />
            <TableColumnSettings title="设置" :model-value="displayColumnLayout" :defaults="columnDefaults" @update:model-value="applyColumnLayout">
              <template #options="{ openAfterClose }">
                <div class="matrix-settings-options">
                  <div class="matrix-settings-row">
                    <el-select v-model="settingsFeatureId" filterable clearable size="small" aria-label="查找模板功能" placeholder="搜索功能名称或 IPN" class="settings-feature-select">
                      <el-option v-for="feature in settingsFeatures" :key="feature.id" :label="feature.label" :value="feature.id" />
                    </el-select>
                    <el-button size="small" :disabled="!settingsFeatures.some(feature => feature.id === settingsFeatureId)" @click="editSettingsFeature(openAfterClose)">编辑显示名称</el-button>
                  </div>
                  <div v-if="!editMode" class="matrix-settings-row">
                    <span>单元格显示</span>
                    <el-radio-group v-model="showMode" size="small" aria-label="单元格显示方式">
                      <el-radio value="auto">智能</el-radio>
                      <el-radio value="supported">显示支持</el-radio>
                      <el-radio value="excluded">显示排除</el-radio>
                    </el-radio-group>
                    <el-button size="small" @click="openAfterClose(openVersions)">版本历史</el-button>
                  </div>
                </div>
              </template>
            </TableColumnSettings>
          </div>
        </div>
        <div class="filter-row">
          <el-input v-model="featureSearch" placeholder="搜索功能名称或IPN" size="small" clearable style="width:160px" />
          <el-checkbox v-model="selectAllGroups" :indeterminate="groupIndeterminate" size="small">全选</el-checkbox>
          <el-checkbox-group v-model="selectedGroupIds" size="small" class="group-filter-compact">
            <el-checkbox v-for="g in featureGroups" :key="g.id" :label="g.id" :value="g.id" size="small">{{ g.name }}</el-checkbox>
          </el-checkbox-group>
          <el-button v-if="featureSearch && searchMatchGroups.length && searchMatchGroups.length !== selectedGroupIds.length" size="small" text type="primary" @click="selectSearchResults">选中搜索结果</el-button>
        </div>

        <div class="matrix-scroll-tools">
          <span>{{ categories.length }} 个探头类别 · {{ visibleFeatureCount }} 个可见功能</span>
          <el-button size="small" aria-label="向左查看功能" @click="scrollFeatures(-1)">←</el-button>
          <el-button size="small" aria-label="向右查看功能" @click="scrollFeatures(1)">→</el-button>
        </div>
        <div ref="tableWrap" class="table-wrap" role="region" aria-label="探头功能模板矩阵" tabindex="0" @keydown.left.self.prevent="scrollFeatures(-1)" @keydown.right.self.prevent="scrollFeatures(1)">
          <el-table ref="matrixTable" :data="categories" border stripe size="small" height="100%" :fit="false" scrollbar-always-on style="width:100%" :header-cell-style="headerCellStyle" @header-dragend="resizeColumn">
            <template v-for="section in matrixSections" :key="section.key">
            <el-table-column v-if="section.kind === 'base'" :column-key="section.key" :prop="section.key" :label="section.label" :width="section.width" :fixed="section.fixed" show-overflow-tooltip>
              <template #default="{ row: cat }">
                <div v-if="section.key === 'category'" class="cat-name" :title="cat.name">{{ cat.name }}</div>
                <div v-else class="cat-apps">
                  <el-tag v-for="a in (categoryAppsMap[cat.id]?.[section.key] || [])" :key="a.id" size="small" class="app-tag" :type="section.key === 'poc' ? 'warning' : 'primary'" :title="a.name">{{ a.name }}</el-tag>
                </div>
              </template>
            </el-table-column>
            <el-table-column v-else :label="section.label" :fixed="section.fixed" align="center">
              <el-table-column v-for="column in section.columns" :key="column.key" :column-key="column.key" :prop="column.key" :label="column.label" :width="column.width" align="center">
                <template #header>
                  <span class="matrix-feature-header">
                    <span class="matrix-feature-label" :title="column.label">{{ column.label }}</span>
                    <FeatureNameMark :feature-id="column.feature.id" :name="column.label" :show-display-edit="false" />
                    <small v-if="column.feature.pending" class="catalog-preview-badge" title="待提交">待</small>
                  </span>
                </template>
                <template #default="{ row: cat }">
                  <el-popover
                    v-if="editMode"
                    trigger="click"
                    :visible="popoverKey === `${cat.id}_${column.feature.id}`"
                    placement="bottom"
                    :width="260"
                    @hide="popoverKey = ''"
                  >
                    <template #reference>
                      <div
                        class="tpl-cell"
                        :class="getCellClass(cat.id, column.feature.id)"
                        @click="openPopover(cat.id, column.feature.id)"
                        style="cursor:pointer"
                      ><div class="cell-apps" :title="getCellTooltip(cat.id, column.feature.id)" :class="{ 'is-all': isAllApps(cat.id, column.feature.id) }">{{ getCellDisplay(cat.id, column.feature.id) }}</div></div>
                    </template>
                    <div>
                      <el-alert v-if="popUnknownExcludes.length" type="warning" :closable="false" :title="`旧排除名称无法对应：${popUnknownExcludes.join('、')}。请核对当前应用后保存。`" />
                      <el-checkbox v-if="popUnknownExcludes.length" v-model="popReplaceUnknown" size="small">以本次所选应用替换旧排除名称</el-checkbox>
                      <div v-if="popoverKey && (popOldStatus !== popStatus)" style="font-size:11px;color:#e6a23c;margin-bottom:6px;padding:4px 8px;background:#fdf6ec;border-radius:4px">
                        修改: {{ {unsupported:'不支持',supported:'支持',conditional:'条件'}[popOldStatus] || popOldStatus }} → {{ {unsupported:'不支持',supported:'支持',conditional:'条件'}[popStatus] || popStatus }}
                      </div>
                      <el-radio-group v-model="popStatus" size="small" style="margin-bottom:8px">
                        <el-radio value="unsupported">不支持</el-radio>
                        <el-radio value="supported">支持 √</el-radio>
                        <el-radio value="conditional">条件 △</el-radio>
                      </el-radio-group>
                      <div v-if="popStatus === 'supported' || popStatus === 'conditional'" style="margin-top:8px">
                        <div style="margin-bottom:6px">
                          <div style="display:flex;align-items:center;gap:4px;margin-bottom:4px">
                            <el-checkbox :indeterminate="regIndeterminate" :model-value="regAllChecked" @change="toggleRegAll" size="small">全选</el-checkbox>
                            <span style="font-size:12px;font-weight:500;color:#606266">常规应用 ({{ regCheckedCount }}/{{ popCatApps.regular.length }})</span>
                          </div>
                          <el-checkbox-group v-model="popSupportedReg" size="small" style="padding-left:24px">
                            <el-checkbox v-for="a in popCatApps.regular" :key="a.id" :label="a.name" :value="a.name" style="margin-right:4px" />
                          </el-checkbox-group>
                        </div>
                        <div style="margin-bottom:6px">
                          <div style="display:flex;align-items:center;gap:4px;margin-bottom:4px">
                            <el-checkbox :indeterminate="pocIndeterminate" :model-value="pocAllChecked" @change="togglePocAll" size="small">全选</el-checkbox>
                            <span style="font-size:12px;font-weight:500;color:#606266">POC 应用 ({{ pocCheckedCount }}/{{ popCatApps.poc.length }})</span>
                          </div>
                          <el-checkbox-group v-model="popSupportedPoc" size="small" style="padding-left:24px">
                            <el-checkbox v-for="a in popCatApps.poc" :key="a.id" :label="a.name" :value="a.name" style="margin-right:4px" />
                          </el-checkbox-group>
                        </div>
                        <div v-if="popStatus === 'conditional'" style="margin-bottom:6px">
                          <div style="display:flex;align-items:center;gap:4px;margin-bottom:4px">
                            <el-checkbox v-model="popSpecialTender" size="small">全选</el-checkbox>
                            <span style="font-size:12px;font-weight:500;color:#e6a23c">招标应用</span>
                          </div>
                          <div style="padding-left:24px">
                            <el-checkbox v-model="popSpecialTender" size="small">特殊应用</el-checkbox>
                          </div>
                        </div>
                      </div>
                      <div style="margin-top:10px;text-align:right">
                        <el-button size="small" @click="popoverKey = ''">取消</el-button>
                        <el-button size="small" type="primary" @click="applyPopover">确定</el-button>
                      </div>
                    </div>
                  </el-popover>
                  <el-tooltip v-else :content="getCellTooltip(cat.id, column.feature.id)" placement="top" :disabled="!getCellTooltip(cat.id, column.feature.id)">
                    <ProbeSupportCell :class="{ 'catalog-preview-cell': column.feature.pending }" :status="_getStatus(`${cat.id}_${column.feature.id}`)" :apps="getCatAllApps(cat.id)" :excludes="_getExcludes(`${cat.id}_${column.feature.id}`)" :tender="_getTender(`${cat.id}_${column.feature.id}`)" :mode="showMode" />
                  </el-tooltip>
                </template>
              </el-table-column>
            </el-table-column>
            </template>
          </el-table>
        </div>
      </div>
    </el-card>

    <!-- Versions Dialog -->
    <el-dialog v-model="showVersions" title="模板版本历史" width="500px">
      <el-table :data="versions" border stripe size="small" max-height="400">
        <el-table-column prop="version_number" label="版本号" width="180" />
        <el-table-column prop="created_at" label="时间" width="200" />
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button size="small" type="warning" @click="rollback(row)">回滚</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!versions.length" description="暂无版本" />
    </el-dialog>

  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, nextTick } from 'vue'
import { featureCurrentName } from '../utils/featureNameStandard'
import { openFeatureNameReview } from '../utils/featureNameReviewHost'
import { useWorkspaceRefresh } from '../utils/useWorkspaceRefresh'
import { ElMessage } from 'element-plus'
import { getProbeCategories, getTemplateFeatureCatalog, getTemplateFeatures } from '../api/data'
import TemplateFeatureCatalogDialog from '../components/TemplateFeatureCatalogDialog.vue'
import { catalogFeatureLabel, projectTemplateCatalog, catalogCellSource } from '../utils/templateFeatureCatalog'
import api from '../api/index'
import ProbeManagementActions from '../components/ProbeManagementActions.vue'
import ProbeSupportCell from '../components/ProbeSupportCell.vue'
import TableColumnSettings from '../components/TableColumnSettings.vue'
import { buildTemplateMatrixColumns, templateMatrixSections, normalizeColumnLayout, loadColumnLayout, saveColumnLayout } from '../utils/tableColumnLayout'
import { expandCombinedName, parseProbeExcludes, formatProbeSupport, probeGroupColors } from '../utils/probeSupport'

const categories = ref([]); const features = ref([])
const tplMap = ref({}); const loading = ref(false)
const featureCatalog = ref(null), pendingMatrixCells = ref({}), pendingMatrixFeatureIds = ref(new Set()), catalogAdditionCount = ref(0), loadError = ref(''), catalogDialog = ref(null)
const editMode = ref(false); const pendingChanges = reactive({})
const categoryAppsMap = ref({})
const showMode = ref('auto')
const featureGroups = ref([])
const featureSearch = ref('')
const showRegular = ref(true)
const showPOC = ref(true)
const selectedGroupIds = ref([])
const settingsFeatureId = ref(null)
const settingsFeatures = computed(() => features.value.map(feature => ({
  id: feature.id,
  label: catalogFeatureLabel({ ...feature, name: featureCurrentName(feature.id, feature.name) })
})))
const editSettingsFeature = openAfterClose => {
  const id = settingsFeatureId.value
  openAfterClose(() => openFeatureNameReview(id, true))
}

const matrixTable = ref(null)
const tableWrap = ref(null)
const columnStorageKey = 'template-matrix-columns-v1'
const columnStorage = { getItem: key => localStorage.getItem(key), setItem: (key, value) => localStorage.setItem(key, value) }
const columnDefaults = computed(() => buildTemplateMatrixColumns(features.value.map(feature => ({ ...feature, name: featureCurrentName(feature.id, feature.name) }))))
const columnLayout = ref([])
// Only normalize once the complete catalog is available, never against search results.
watch(features, () => {
  columnLayout.value = loadColumnLayout(columnStorage, columnStorageKey, columnDefaults.value, message => ElMessage.warning(message))
}, { immediate: true })
const applyColumnLayout = columns => {
  columnLayout.value = normalizeColumnLayout(columnDefaults.value, columns)
  saveColumnLayout(columnStorage, columnStorageKey, columnLayout.value, message => ElMessage.warning(message))
  nextTick(() => matrixTable.value?.doLayout())
}
const resizeColumn = (width, _oldWidth, column) => {
  applyColumnLayout(columnLayout.value.map(item => item.key === column.columnKey ? { ...item, width: Math.max(30, width) } : item))
}
const scrollFeatures = direction => {
  const wrap = tableWrap.value?.querySelector('.el-scrollbar__wrap')
  if (wrap) matrixTable.value?.setScrollLeft(wrap.scrollLeft + direction * Math.max(100, wrap.clientWidth / 2))
}


const selectAllGroups = computed({
  get: () => selectedGroupIds.value.length === featureGroups.value.length,
  set: (val) => { selectedGroupIds.value = val ? featureGroups.value.map(g => g.id) : [] }
})
const groupIndeterminate = computed(() => {
  const n = selectedGroupIds.value.length
  return n > 0 && n < featureGroups.value.length
})

const searchMatchGroups = computed(() => {
  if (!featureSearch.value) return []
  const q = featureSearch.value.toLowerCase()
  const matched = new Set()
  for (const f of features.value) {
    if (catalogFeatureLabel({ ...f, name: featureCurrentName(f.id, f.name) }).toLowerCase().includes(q)) matched.add(f.group_id)
  }
  return [...matched]
})

function selectSearchResults() {
  const ids = new Set(selectedGroupIds.value)
  for (const gid of searchMatchGroups.value) ids.add(gid)
  selectedGroupIds.value = [...ids]
}

const filteredFeatures = computed(() => {
  let list = features.value.map(feature => ({ ...feature, name: featureCurrentName(feature.id, feature.name) }))
  if (selectedGroupIds.value.length) {
    const set = new Set(selectedGroupIds.value)
    list = list.filter(f => set.has(f.group_id))
  }
  if (featureSearch.value) {
    const q = featureSearch.value.toLowerCase()
    list = list.filter(f => catalogFeatureLabel({ ...f, name: featureCurrentName(f.id, f.name) }).toLowerCase().includes(q))
  }
  return list
})

function getGroupFeatures(groupId) {
  return filteredFeatures.value.filter(f => f.group_id === groupId)
}

const displayColumnLayout = computed(() => columnLayout.value.map(column => ({ ...column, label: column.key.startsWith('feature:') ? featureCurrentName(column.key.slice(8), column.label) : column.label })))
const matrixSections = computed(() => templateMatrixSections(displayColumnLayout.value, filteredFeatures.value, featureGroups.value, {
  showRegular: showRegular.value, showPOC: showPOC.value
}))
const visibleFeatureCount = computed(() => matrixSections.value.reduce((count, section) => count + (section.columns?.length || 0), 0))

// ---- group header coloring ----
const groupColorMap = computed(() => probeGroupColors(featureGroups.value))

function headerCellStyle({ column }) {
  const feat = features.value.find(f => `feature:${f.id}` === column.property)
  if (!feat) return {}
  const c = groupColorMap.value[feat.group_id]
  if (!c) return { fontWeight: 600, fontSize: '12px' }
  return { background: c.bg, fontWeight: 600, fontSize: '12px', borderBottom: `2px solid ${c.border}` }
}

// ---- helpers ----
function getCatAllApps(catId) {
  const apps = categoryAppsMap.value[catId]
  if (!apps) return []
  return [...(apps.regular || []), ...(apps.poc || [])].map(a => a.name)
}

function getExcludedList(catId, featId) {
  const key = `${catId}_${featId}`
  if (key in pendingExcludes && pendingExcludes[key]) {
    return _parseExcludes(pendingExcludes[key]).excludes
  }
  const t = templateCell(key)
  if (t?.default_excludes) {
    try { const raw = JSON.parse(t.default_excludes); return _parseExcludes(raw).excludes } catch { return [] }
  }
  return []
}

function getResolvedExcluded(catId, featId) {
  return getExcludedList(catId, featId).flatMap(n => expandCombinedName(n))
}

function getSupportedList(catId, featId) {
  const all = getCatAllApps(catId)
  if (!all.length) return []
  const excluded = new Set(getResolvedExcluded(catId, featId))
  return all.filter(n => !excluded.has(n))
}

// ---- cell display ----
let templateLoadRequest = 0
const loadData = async () => {
  const request = ++templateLoadRequest
  loading.value = true; loadError.value = ''
  try {
    const [catRes, catalog, drafts] = await Promise.all([
      getProbeCategories({ limit: 200 }), getTemplateFeatureCatalog(), api.get('/template-features/drafts')
    ])
    const nextCategories = catRes.items || []
    const projection = projectTemplateCatalog(catalog, drafts, nextCategories)
    const details = await Promise.all(nextCategories.map(async cat => {
      const [templates, apps] = await Promise.all([
        getTemplateFeatures(cat.id), api.get(`/probe-categories/${cat.id}/apps`)
      ])
      return { categoryId: cat.id, templates: templates || [], apps }
    }))
    const allTpl = {}; const allCatApps = {}
    for (const detail of details) {
      for (const t of detail.templates) allTpl[`${detail.categoryId}_${t.feature_id}`] = t
      allCatApps[detail.categoryId] = detail.apps
    }
    if (request !== templateLoadRequest) return false
    categories.value = nextCategories; features.value = projection.features
    featureGroups.value = projection.groups; featureCatalog.value = catalog
    pendingMatrixCells.value = projection.pendingCells; pendingMatrixFeatureIds.value = projection.pendingFeatureIds
    draftTotal.value = projection.draftTotal; catalogAdditionCount.value = projection.catalogAdditionsCount
    tplMap.value = allTpl; categoryAppsMap.value = allCatApps
    return true
  } catch (failure) {
    if (request === templateLoadRequest) {
      loadError.value = `功能库或模板数据加载失败，已保留当前矩阵。${failure?.message || '请重试'}`
    }
    return false
  } finally {
    if (request === templateLoadRequest) loading.value = false
  }
}

const templateCell = key => catalogCellSource(key, tplMap.value, pendingMatrixCells.value, pendingMatrixFeatureIds.value)

const getCellClass = (catId, featId) => {
  const key = `${catId}_${featId}`
  let status = templateCell(key)?.default_support
  if (key in pendingChanges) status = pendingChanges[key]
  const cls = status === 'supported' ? 'supported' : status === 'conditional' ? 'conditional' : 'unsupported'
  return `${cls}${pendingMatrixFeatureIds.value.has(featId) ? ' is-catalog-preview' : ''}${key in pendingChanges ? ' is-dirty' : ''}`
}

const getCellIcon = (catId, featId) => {
  const key = `${catId}_${featId}`
  if (key in pendingChanges) {
    if (pendingChanges[key] === 'supported') return '√'
    if (pendingChanges[key] === 'conditional') return '△'
    return ''
  }
  const t = templateCell(key)
  if (t?.default_support === 'supported') return '√'
  if (t?.default_support === 'conditional') return '△'
  return ''
}

const isAllApps = (catId, featId) => {
  const key = `${catId}_${featId}`
  if (key in pendingChanges) return pendingChanges[key] === 'supported'
  const t = templateCell(key)
  if (!t || t.default_support === 'unsupported') return false
  const excluded = getResolvedExcluded(catId, featId)
  return excluded.length === 0
}

function _getStatus(key) {
  if (key in pendingChanges) return pendingChanges[key]
  const t = templateCell(key)
  return t ? t.default_support : null
}

function _parseExcludes(value) { return parseProbeExcludes(value) }

function _getExcludes(key) {
  if (key in pendingExcludes) return _parseExcludes(pendingExcludes[key]).excludes
  const t = templateCell(key)
  if (t?.default_excludes) {
    try { const raw = JSON.parse(t.default_excludes); return _parseExcludes(raw).excludes } catch {}
  }
  return []
}

function _getTender(key) {
  if (key in pendingExcludes) return _parseExcludes(pendingExcludes[key]).tender
  const t = templateCell(key)
  if (t?.default_excludes) {
    try { const raw = JSON.parse(t.default_excludes); return _parseExcludes(raw).tender } catch {}
  }
  return []
}

const getCellDisplay = (catId, featId) => {
  const key = `${catId}_${featId}`
  return formatProbeSupport({ status: _getStatus(key), apps: getCatAllApps(catId), excludes: _getExcludes(key), tender: _getTender(key), mode: showMode.value })
}

const getCellTooltip = (catId, featId) => {
  const prefix = pendingMatrixFeatureIds.value.has(featId) ? '待提交预览，提交模板版本后生效。' : ''
  const all = getCatAllApps(catId)
  if (!all.length) return prefix
  const key = `${catId}_${featId}`
  const status = _getStatus(key)
  const excluded = _getExcludes(key)
  const tender = _getTender(key)
  const parts = []
  if (status === 'conditional' && tender.length) {
    const supported = all.filter(n => !new Set(excluded).has(n) && !tender.includes(n))
    if (supported.length) parts.push('支:' + supported.join(','))
    parts.push('招:' + tender.join(','))
    return [prefix, ...parts].filter(Boolean).join('\n')
  }
  if (!excluded.length) return prefix
  const supported = all.filter(n => !new Set(excluded).has(n))
  return [prefix, `支: ${supported.join(', ')}\n除: ${excluded.join(', ')}`].filter(Boolean).join('\n')
}

// ---- edit mode ----
const enterEditMode = () => { editMode.value = true; Object.keys(pendingChanges).forEach(k => delete pendingChanges[k]) }
const cancelEdit = () => {
  editMode.value = false
  Object.keys(pendingChanges).forEach(k => delete pendingChanges[k])
  Object.keys(pendingExcludes).forEach(k => delete pendingExcludes[k])
}
const pendingCount = computed(() => Object.keys(pendingChanges).length)

const openTemplateCatalog = () => {
  if (pendingCount.value > 0) { ElMessage.warning('请先保存草稿或取消当前单元格修改，再从功能库添加'); return false }
  if (loading.value || loadError.value || !featureCatalog.value) { ElMessage.warning('请先完成共用功能库读取'); return false }
  catalogDialog.value?.open()
  return true
}
const refreshCatalogPreview = async payload => {
  if (!await loadData()) throw new Error('矩阵读取失败，可重试刷新')
  if (selectedGroupIds.value.length && !selectedGroupIds.value.includes(payload.group_id)) {
    selectedGroupIds.value = [...selectedGroupIds.value, payload.group_id]
  }
  featureSearch.value = ''
}

const popoverKey = ref(''); const popStatus = ref('unsupported'); const popExcludes = ref([])
const popOldStatus = ref('')
const popSupportedReg = ref([])
const popSupportedPoc = ref([])
const popSpecialTender = ref(false)
const popCatApps = ref({ regular: [], poc: [] })
const popReplaceUnknown = ref(false)
const popUnknownExcludes = computed(() => {
  const names = [...popCatApps.value.regular, ...popCatApps.value.poc].map(app => app.name)
  return popExcludes.value.filter(name => !names.includes(name))
})
const pendingExcludes = reactive({})

const openPopover = (catId, featId) => {
  const key = `${catId}_${featId}`
  popoverKey.value = key
  popReplaceUnknown.value = false
  popCatApps.value = categoryAppsMap.value[catId] || { regular: [], poc: [] }
  // Record old values for diff
  popOldStatus.value = templateCell(key)?.default_support || 'unsupported'
  const cur = key in pendingChanges ? pendingChanges[key] : (templateCell(key)?.default_support || 'unsupported')
  popStatus.value = cur
  // Compute supported apps from excludes
  const apps = categoryAppsMap.value[catId]
  const allNames = [...(apps?.regular||[]).map(a => a.name), ...(apps?.poc||[]).map(a => a.name)]
  // Parse stored data: supports new format {excludes:[],tender:[]} or old flat array
  let ex = [], tender = []
  if (key in pendingExcludes) {
    const pe = pendingExcludes[key]
    if (pe && typeof pe === 'object' && !Array.isArray(pe)) {
      ex = pe.excludes || []; tender = pe.tender || []
    } else {
      ex = Array.isArray(pe) ? pe : []
    }
  } else if (templateCell(key)?.default_excludes) {
    try {
      const raw = JSON.parse(templateCell(key).default_excludes)
      if (raw && typeof raw === 'object' && !Array.isArray(raw)) {
        ex = raw.excludes || []; tender = raw.tender || []
      } else {
        ex = Array.isArray(raw) ? raw : []
      }
    } catch { ex = [] }
  }
  ex = ex.flatMap(expandCombinedName)
  tender = tender.flatMap(expandCombinedName)
  popSpecialTender.value = tender.includes('__特殊应用__') || false
  if (cur === 'unsupported' || !allNames.length) {
    popSupportedReg.value = []
    popSupportedPoc.value = []
  } else {
    const exSet = new Set(ex)
    const regNames = popCatApps.value.regular.map(a => a.name)
    const pocNames = popCatApps.value.poc.map(a => a.name)
    popSupportedReg.value = regNames.filter(n => !exSet.has(n) && !tender.includes(n))
    popSupportedPoc.value = pocNames.filter(n => !exSet.has(n) && !tender.includes(n))
  }
  popExcludes.value = (ex || []).filter(Boolean)
}

// Per-group computed
const regCheckedCount = computed(() => popCatApps.value.regular.filter(a => popSupportedReg.value.includes(a.name)).length)
const pocCheckedCount = computed(() => popCatApps.value.poc.filter(a => popSupportedPoc.value.includes(a.name)).length)
const regAllChecked = computed(() => popCatApps.value.regular.length > 0 && regCheckedCount.value === popCatApps.value.regular.length)
const pocAllChecked = computed(() => popCatApps.value.poc.length > 0 && pocCheckedCount.value === popCatApps.value.poc.length)
const regIndeterminate = computed(() => regCheckedCount.value > 0 && regCheckedCount.value < popCatApps.value.regular.length)
const pocIndeterminate = computed(() => pocCheckedCount.value > 0 && pocCheckedCount.value < popCatApps.value.poc.length)

function toggleRegAll(val) {
  const names = popCatApps.value.regular.map(a => a.name)
  const set = new Set(popSupportedReg.value)
  if (val) { names.forEach(n => set.add(n)) } else { names.forEach(n => set.delete(n)) }
  popSupportedReg.value = [...set]
}

function togglePocAll(val) {
  const names = popCatApps.value.poc.map(a => a.name)
  const set = new Set(popSupportedPoc.value)
  if (val) { names.forEach(n => set.add(n)) } else { names.forEach(n => set.delete(n)) }
  popSupportedPoc.value = [...set]
}

watch(popStatus, (val) => {
  const reg = popCatApps.value.regular.map(a => a.name)
  const poc = popCatApps.value.poc.map(a => a.name)
  if (val === 'unsupported' || (!reg.length && !poc.length)) {
    popSupportedReg.value = []
    popSupportedPoc.value = []
  } else if (val === 'conditional') {
    popSpecialTender.value = false
  } else {
    popSpecialTender.value = false
    const exSet = new Set(popExcludes.value || [])
    popSupportedReg.value = reg.filter(n => !exSet.has(n))
    popSupportedPoc.value = poc.filter(n => !exSet.has(n))
  }
})

const applyPopover = () => {
  const [catId, featId] = popoverKey.value.split('_').map(Number)
  const key = popoverKey.value
  pendingChanges[key] = popStatus.value
  // Compute excludes and tender
  const allNames = [...popCatApps.value.regular.map(a => a.name), ...popCatApps.value.poc.map(a => a.name)]
  const supportedSet = new Set([...(popSupportedReg.value || []), ...(popSupportedPoc.value || [])])
  const excludes = [...new Set([
    ...(popReplaceUnknown.value ? [] : popUnknownExcludes.value),
    ...allNames.filter(n => !supportedSet.has(n))
  ])]
  const tender = popSpecialTender.value ? ['__特殊应用__'] : []
  pendingExcludes[key] = { excludes: excludes.length ? excludes : [], tender }
  popoverKey.value = ''
}

const saveChanges = async () => {
  let count = 0
  try {
    for (const [key, val] of Object.entries(pendingChanges)) {
      const [catId, featId] = key.split('_').map(Number)
      const pe = pendingExcludes[key]
      const excludes = pe ? JSON.stringify(pe) : null
      await api.post('/template-features/save-draft', { category_id: catId, feature_id: featId, new_support: val || 'unsupported', excludes })
      count++
    }
    ElMessage.success(`已保存 ${count} 条草稿，请提交后生效`)
    editMode.value = false; Object.keys(pendingChanges).forEach(k => { delete pendingChanges[k]; delete pendingExcludes[k] })
    if (!await loadData()) ElMessage.warning('草稿已保存，刷新失败，可点击刷新重试')
  } catch (e) { ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message)); console.error(e) }
}

// ---- draft / version ----
const draftTotal = ref(0); const submitting = ref(false); const versions = ref([]); const showVersions = ref(false)
const submitDrafts = async () => {
  submitting.value = true
  try {
    await api.post('/template-features/submit'); ElMessage.success('提交成功')
    if (!await loadData()) ElMessage.warning('提交成功，刷新失败，可点击刷新重试')
  } catch (failure) { ElMessage.error('提交失败: ' + (failure.response?.data?.detail || failure.message)) }
  finally { submitting.value = false }
}
const discardDrafts = async () => {
  try {
    await api.post('/template-features/discard'); ElMessage.success('已废弃')
    if (!await loadData()) ElMessage.warning('已废弃草稿，刷新失败，可点击刷新重试')
  } catch { ElMessage.error('废弃失败') }
}
const loadVersions = async () => { try { versions.value = await api.get('/template-features/versions') || [] } catch { versions.value = [] } }
const openVersions = async () => { await loadVersions(); showVersions.value = true }
const rollback = async (row) => {
  try { await api.post(`/template-features/rollback/${row.id}`); ElMessage.success('回滚成功'); await loadData(); await loadVersions() } catch { ElMessage.error('回滚失败') }
}

const refreshData = () => loadData()
useWorkspaceRefresh(refreshData, { canRefresh: () => !editMode.value && !catalogDialog.value?.isOpen })
</script>

<style scoped>
.page { padding: 0; display: flex; flex-direction: column; flex: 1; min-height: 0; min-width: 0; overflow: hidden; }
.template-card { display: flex; flex-direction: column; flex: 1; min-height: 0; }
.template-card :deep(.el-card__body) { display: flex; flex-direction: column; flex: 1; min-height: 0; padding: 10px; }
.matrix-container { display: flex; flex-direction: column; flex: 1; min-height: 0; }
.toolbar-row { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; flex-shrink: 0; gap: 4px 8px; margin-bottom: 6px; }
.legend { display: flex; gap: 12px; font-size: 12px; }
.legend-item { display: flex; align-items: center; gap: 4px }
.dot { display: inline-block; width: 14px; height: 14px; border-radius: 3px }
.dot.supported { background: #dcfce7; border: 1px solid #22c55e }
.dot.unsupported { background: #f1f5f9; border: 1px solid #cbd5e1 }
.dot.pending { background: #fef3c7; border: 2px dashed #f59e0b }
.toolbar-right { display:flex; align-items:center; gap:8px; flex-wrap:wrap }
.filter-row { display:flex; align-items:center; gap:8px; padding:0 0 6px; flex-wrap:wrap; flex-shrink:0 }
.group-filter-compact { display:inline-flex; flex-wrap:wrap; gap:2px }
.group-filter-compact .el-checkbox { margin-right:0; white-space:nowrap }
.matrix-settings-options { display: grid; gap: 8px; padding-bottom: 10px; margin-bottom: 10px; border-bottom: 1px solid var(--el-border-color-lighter); }
.matrix-settings-row { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; font-size: 12px; }
.settings-feature-select { flex: 1 1 210px; min-width: 0; }
.table-wrap { flex: 1 1 0; min-height: 120px; min-width: 0; overflow: hidden; }
.matrix-scroll-tools { display: flex; justify-content: flex-end; align-items: center; gap: 6px; flex-shrink: 0; margin-bottom: 6px; font-size: 12px; color: var(--el-text-color-secondary); }
.matrix-scroll-tools .el-button + .el-button { margin-left: 0; }
.table-wrap :deep(.el-table__header .cell) { white-space: nowrap; }
.table-wrap :deep(.probe-support-cell), .cell-apps, .cat-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.table-wrap :deep(.probe-support-cell) { box-sizing: border-box; min-height: 28px; }
.table-wrap :deep(.el-scrollbar__bar.is-horizontal) { height: 10px; bottom: 1px; }
.table-wrap :deep(.el-scrollbar__wrap) { padding-bottom: 10px; box-sizing: border-box; }
.app-tag { max-width: 100%; }
.app-tag :deep(.el-tag__content) { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.tpl-cell { width: 100%; text-align: center; transition: background .1s; min-height: 28px; display: flex; align-items: center; justify-content: center }
.tpl-cell.supported { background: #dcfce7; color: #166534 }
.tpl-cell.conditional { background: #fef3c7; color: #92400e }
.tpl-cell.unsupported { background: #f1f5f9; color: #94a3b8 }
.tpl-cell.is-dirty { outline: 2px dashed #f59e0b; outline-offset: -2px }
.cell-apps { font-size: 11px; line-height: 1.3; padding: 2px 4px; max-width: 100%; box-sizing: border-box }
.cell-apps.is-all { font-weight: 700; font-size: 13px }
.draft-bar { display:flex; align-items:center; flex-wrap:wrap; flex-shrink:0; gap:6px; padding:6px 10px; margin-bottom:6px; background:#fef3c7; border-radius:4px; }
.cat-cell { line-height:1.4 }
.cat-name { font-weight:600; white-space:nowrap }
.cat-apps { display:flex; flex-wrap:wrap; gap:2px; max-height:80px; overflow-y:auto }
.app-tag { margin:0; font-size:10px }
.catalog-load-error { flex-shrink: 0; margin-bottom: 6px; }
.catalog-preview-badge, .catalog-preview-legend { color: #92400e; font-size: 11px; }
.catalog-preview-badge { margin-left: 4px; white-space: nowrap; }
.catalog-preview-cell, .tpl-cell.is-catalog-preview { outline: 1px dashed #d97706; outline-offset: -1px; }
.matrix-feature-header {
  display: flex;
  width: 100%;
  min-width: 0;
  height: 28px;
  align-items: center;
  justify-content: center;
}
.matrix-feature-label { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.matrix-feature-header :deep(.feature-name-mark), .catalog-preview-badge { flex-shrink: 0; }

</style>
