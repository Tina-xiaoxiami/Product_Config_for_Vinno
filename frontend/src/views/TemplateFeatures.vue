<template>
  <div class="page">
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>模板配置管理</span>
          <div style="display:flex;gap:12px">
            <template v-if="editMode">
              <el-tag type="warning">编辑中 — {{ pendingCount }} 项修改</el-tag>
              <el-button size="small" type="primary" @click="saveChanges" :disabled="pendingCount === 0">保存草稿</el-button>
              <el-button size="small" @click="cancelEdit">取消</el-button>
            </template>
            <template v-else>
              <el-button size="small" type="primary" @click="enterEditMode">编辑模式</el-button>
              <el-button size="small" @click="refreshData">刷新</el-button>
              <el-button size="small" @click="openVersions">版本历史</el-button>
            </template>
          </div>
          <!-- Draft bar -->
          <div v-if="draftTotal > 0 && !editMode" class="draft-bar" style="margin-top:12px">
            <span><strong>{{ draftTotal }}</strong> 条草稿待提交</span>
            <el-button size="small" type="primary" @click="submitDrafts" :loading="submitting">提交并创建版本</el-button>
            <el-button size="small" type="danger" @click="discardDrafts">废弃全部</el-button>
          </div>
        </div>
      </template>

      <div class="matrix-container" v-loading="loading">
        <div class="toolbar-row">
          <div class="legend">
            <span class="legend-item"><span class="dot supported"></span> 支持</span>
            <span class="legend-item"><span class="dot unsupported"></span> 不支持</span>
            <span v-if="editMode" class="legend-item"><span class="dot pending"></span> 待保存</span>
          </div>
          <div class="toolbar-right">
            <el-switch v-model="showRegular" size="small" active-text="常规" inactive-text="常规" style="margin-right:4px" />
            <el-switch v-model="showPOC" size="small" active-text="POC" inactive-text="POC" style="margin-right:4px" />
            <div class="view-toggle" v-if="!editMode">
              <el-radio-group v-model="showMode" size="small">
                <el-radio value="auto">智能</el-radio>
                <el-radio value="supported">显示支持</el-radio>
                <el-radio value="excluded">显示排除</el-radio>
              </el-radio-group>
            </div>
          </div>
        </div>
        <div class="filter-row">
          <el-input v-model="featureSearch" placeholder="搜索功能名称" size="small" clearable style="width:160px" />
          <el-checkbox v-model="selectAllGroups" :indeterminate="groupIndeterminate" size="small">全选</el-checkbox>
          <el-checkbox-group v-model="selectedGroupIds" size="small" class="group-filter-compact">
            <el-checkbox v-for="g in featureGroups" :key="g.id" :label="g.id" :value="g.id" size="small">{{ g.name }}</el-checkbox>
          </el-checkbox-group>
          <el-button v-if="featureSearch && searchMatchGroups.length && searchMatchGroups.length !== selectedGroupIds.length" size="small" text type="primary" @click="selectSearchResults">选中搜索结果</el-button>
        </div>

        <div class="table-wrap">
          <el-table :data="categories" border stripe size="small" :max-height="600" style="width:100%" :header-cell-style="headerCellStyle">
            <el-table-column label="探头类别" width="120" fixed>
              <template #default="{ row: cat }">
                <div class="cat-name">{{ cat.name }}</div>
              </template>
            </el-table-column>
            <el-table-column v-if="showRegular" label="常规应用" width="140" fixed>
              <template #default="{ row: cat }">
                <div v-if="categoryAppsMap[cat.id]" class="cat-apps">
                  <el-tag v-for="a in (categoryAppsMap[cat.id]?.regular||[])" :key="a.id" size="small" class="app-tag">{{ a.name }}</el-tag>
                </div>
              </template>
            </el-table-column>
            <el-table-column v-if="showPOC" label="POC 应用" width="140" fixed>
              <template #default="{ row: cat }">
                <div v-if="categoryAppsMap[cat.id]" class="cat-apps">
                  <el-tag v-for="a in (categoryAppsMap[cat.id]?.poc||[])" :key="'poc-'+a.id" size="small" type="warning" class="app-tag">{{ a.name }}</el-tag>
                </div>
              </template>
            </el-table-column>
            <el-table-column v-for="g in visibleGroups" :key="g.id" :label="g.name" align="center">
              <el-table-column v-for="f in getGroupFeatures(g.id)" :key="f.id" :label="f.name" min-width="72" align="center">
                <template #default="{ row: cat }">
                  <el-popover
                    v-if="editMode"
                    trigger="click"
                    :visible="popoverKey === `${cat.id}_${f.id}`"
                    placement="bottom"
                    :width="260"
                    @hide="popoverKey = ''"
                  >
                    <template #reference>
                      <div
                        class="tpl-cell"
                        :class="getCellClass(cat.id, f.id)"
                        @click="openPopover(cat.id, f.id)"
                        style="cursor:pointer"
                      ><div class="cell-apps" :class="{ 'is-all': isAllApps(cat.id, f.id) }">{{ getCellDisplay(cat.id, f.id) }}</div></div>
                    </template>
                    <div>
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
                  <el-tooltip v-else :content="getCellTooltip(cat.id, f.id)" placement="top" :disabled="!getCellTooltip(cat.id, f.id)">
                    <div class="tpl-cell" :class="getCellClass(cat.id, f.id)">
                      <div class="cell-apps" :class="{ 'is-all': isAllApps(cat.id, f.id) }">{{ getCellDisplay(cat.id, f.id) }}</div>
                    </div>
                  </el-tooltip>
                </template>
              </el-table-column>
            </el-table-column>
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
import { ref, reactive, computed, watch, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getProbeCategories, getFeatures, getFeatureGroups, getTemplateFeatures } from '../api/data'
import api from '../api/index'

const categories = ref([]); const features = ref([])
const tplMap = ref({}); const loading = ref(false)
const editMode = ref(false); const pendingChanges = reactive({})
const categoryAppsMap = ref({})
const showMode = ref('auto')
const featureGroups = ref([])
const featureSearch = ref('')
const showRegular = ref(true)
const showPOC = ref(true)
const selectedGroupIds = ref([])

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
    if (f.name.toLowerCase().includes(q)) matched.add(f.group_id)
  }
  return [...matched]
})

function selectSearchResults() {
  const ids = new Set(selectedGroupIds.value)
  for (const gid of searchMatchGroups.value) ids.add(gid)
  selectedGroupIds.value = [...ids]
}

const filteredFeatures = computed(() => {
  let list = features.value
  if (selectedGroupIds.value.length) {
    const set = new Set(selectedGroupIds.value)
    list = list.filter(f => set.has(f.group_id))
  }
  if (featureSearch.value) {
    const q = featureSearch.value.toLowerCase()
    list = list.filter(f => f.name.toLowerCase().includes(q))
  }
  return list
})

function getGroupFeatures(groupId) {
  return filteredFeatures.value.filter(f => f.group_id === groupId)
}

const visibleGroups = computed(() => {
  const ids = [...new Set(filteredFeatures.value.map(f => f.group_id))]
  return ids.map(id => {
    const g = featureGroups.value.find(g => g.id === id)
    return { id, name: g ? g.name : '' }
  })
})

// ---- group header coloring ----
const groupColorMap = computed(() => {
  const colors = ['#e3f2fd', '#e8f5e9', '#fff8e1', '#fce4ec', '#ede7f6', '#e0f2f1', '#fff3e0', '#e8eaf6', '#fbe9e7', '#f3e5f5']
  const borderColors = ['#1976d2', '#388e3c', '#f57f17', '#c62828', '#5e35b1', '#00796b', '#e65100', '#3949ab', '#d84315', '#7b1fa2']
  const map = {}
  featureGroups.value.forEach((g, i) => {
    map[g.id] = { bg: colors[i % colors.length], border: borderColors[i % borderColors.length] }
  })
  return map
})

function headerCellStyle({ column }) {
  // Match feature columns by label
  const feat = features.value.find(f => f.name === column.label)
  if (!feat) return {}
  const c = groupColorMap.value[feat.group_id]
  if (!c) return { fontWeight: 600, fontSize: '12px' }
  return { background: c.bg, fontWeight: 600, fontSize: '12px', borderBottom: `2px solid ${c.border}` }
}

// ---- helpers ----
function expandCombinedName(name) {
  const parts = name.split(/[\\/]/)
  if (parts.length <= 1) return [name]
  const last = parts[parts.length - 1].trim()
  const suffix = last.length > 1 ? last.slice(1) : ''
  const result = []
  for (let i = 0; i < parts.length - 1; i++) {
    const p = parts[i].trim()
    if (p) result.push(p + suffix)
  }
  if (last) result.push(last)
  return result
}

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
  const t = tplMap.value[key]
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
const loadData = async () => {
  loading.value = true
  try {
    const [catRes, featRes, grpRes] = await Promise.all([getProbeCategories({ limit: 200 }), getFeatures({ limit: 500 }), getFeatureGroups()])
    categories.value = catRes.items || []; features.value = featRes.items || []
    featureGroups.value = grpRes.items || []
    const allTpl = {}; const allCatApps = {}
    for (const cat of categories.value) {
      try {
        for (const t of (await getTemplateFeatures(cat.id)) || []) { allTpl[`${cat.id}_${t.feature_id}`] = t }
        allCatApps[cat.id] = await api.get(`/probe-categories/${cat.id}/apps`)
      } catch {}
    }
    tplMap.value = allTpl; categoryAppsMap.value = allCatApps
  } catch { ElMessage.error('加载失败') } finally { loading.value = false }
}

const getCellClass = (catId, featId) => {
  const key = `${catId}_${featId}`
  let status = tplMap.value[key]?.default_support
  if (key in pendingChanges) status = pendingChanges[key]
  const cls = status === 'supported' ? 'supported' : status === 'conditional' ? 'conditional' : 'unsupported'
  return key in pendingChanges ? cls + ' is-dirty' : cls
}

const getCellIcon = (catId, featId) => {
  const key = `${catId}_${featId}`
  if (key in pendingChanges) {
    if (pendingChanges[key] === 'supported') return '√'
    if (pendingChanges[key] === 'conditional') return '△'
    return ''
  }
  const t = tplMap.value[key]
  if (t?.default_support === 'supported') return '√'
  if (t?.default_support === 'conditional') return '△'
  return ''
}

const isAllApps = (catId, featId) => {
  const key = `${catId}_${featId}`
  if (key in pendingChanges) return pendingChanges[key] === 'supported'
  const t = tplMap.value[key]
  if (!t || t.default_support === 'unsupported') return false
  const excluded = getResolvedExcluded(catId, featId)
  return excluded.length === 0
}

function _getStatus(key) {
  if (key in pendingChanges) return pendingChanges[key]
  const t = tplMap.value[key]
  return t ? t.default_support : null
}

function _parseExcludes(excludesVal) {
  if (!excludesVal) return { excludes: [], tender: [] }
  if (typeof excludesVal === 'object' && !Array.isArray(excludesVal)) {
    return { excludes: excludesVal.excludes || [], tender: excludesVal.tender || [] }
  }
  const arr = Array.isArray(excludesVal) ? excludesVal : []
  return { excludes: arr, tender: [] }
}

function _getExcludes(key) {
  if (key in pendingExcludes) return _parseExcludes(pendingExcludes[key]).excludes
  const t = tplMap.value[key]
  if (t?.default_excludes) {
    try { const raw = JSON.parse(t.default_excludes); return _parseExcludes(raw).excludes } catch {}
  }
  return []
}

function _getTender(key) {
  if (key in pendingExcludes) return _parseExcludes(pendingExcludes[key]).tender
  const t = tplMap.value[key]
  if (t?.default_excludes) {
    try { const raw = JSON.parse(t.default_excludes); return _parseExcludes(raw).tender } catch {}
  }
  return []
}

const getCellDisplay = (catId, featId) => {
  const key = `${catId}_${featId}`
  const status = _getStatus(key)
  if (!status || status === 'unsupported') return '—'

  const all = getCatAllApps(catId)
  if (!all.length) return status === 'supported' ? 'ALL' : '△'

  const excluded = _getExcludes(key).flatMap(n => expandCombinedName(n))
  const tender = _getTender(key).flatMap(n => expandCombinedName(n))
  const excludedSet = new Set(excluded)
  const supported = all.filter(n => !excludedSet.has(n) && !tender.includes(n))

  if (status === 'conditional' && tender.length) {
    const parts = []
    if (supported.length) parts.push('支:' + supported.join(','))
    parts.push('招:' + tender.join(','))
    return parts.join(' | ')
  }

  if (excluded.length === 0 && tender.length === 0) return 'ALL'

  if (showMode.value === 'supported' || (showMode.value === 'auto' && supported.length <= excluded.length)) {
    return supported.join(', ')
  }
  return '除: ' + excluded.join(', ')
}

const getCellTooltip = (catId, featId) => {
  const all = getCatAllApps(catId)
  if (!all.length) return ''
  const key = `${catId}_${featId}`
  const status = _getStatus(key)
  const excluded = _getExcludes(key)
  const tender = _getTender(key)
  const parts = []
  if (status === 'conditional' && tender.length) {
    const supported = all.filter(n => !new Set(excluded).has(n) && !tender.includes(n))
    if (supported.length) parts.push('支:' + supported.join(','))
    parts.push('招:' + tender.join(','))
    return parts.join('\n')
  }
  if (!excluded.length) return ''
  const supported = all.filter(n => !new Set(excluded).has(n))
  return `支: ${supported.join(', ')}\n除: ${excluded.join(', ')}`
}

// ---- edit mode ----
const enterEditMode = () => { editMode.value = true; Object.keys(pendingChanges).forEach(k => delete pendingChanges[k]) }
const cancelEdit = () => {
  editMode.value = false
  Object.keys(pendingChanges).forEach(k => delete pendingChanges[k])
  Object.keys(pendingExcludes).forEach(k => delete pendingExcludes[k])
}
const pendingCount = computed(() => Object.keys(pendingChanges).length)

const popoverKey = ref(''); const popStatus = ref('unsupported'); const popExcludes = ref([])
const popOldStatus = ref('')
const popSupportedReg = ref([])
const popSupportedPoc = ref([])
const popSpecialTender = ref(false)
const popCatApps = ref({ regular: [], poc: [] })
const pendingExcludes = reactive({})

const openPopover = (catId, featId) => {
  const key = `${catId}_${featId}`
  popoverKey.value = key
  // Record old values for diff
  popOldStatus.value = tplMap.value[key]?.default_support || 'unsupported'
  const cur = key in pendingChanges ? pendingChanges[key] : (tplMap.value[key]?.default_support || 'unsupported')
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
  } else if (tplMap.value[key]?.default_excludes) {
    try {
      const raw = JSON.parse(tplMap.value[key].default_excludes)
      if (raw && typeof raw === 'object' && !Array.isArray(raw)) {
        ex = raw.excludes || []; tender = raw.tender || []
      } else {
        ex = Array.isArray(raw) ? raw : []
      }
    } catch { ex = [] }
  }
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
  // Sync apps for this category
  popCatApps.value = categoryAppsMap.value[catId] || { regular: [], poc: [] }
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
  const excludes = allNames.filter(n => !supportedSet.has(n))
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
    await loadData(); await loadDrafts()
  } catch (e) { ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message)); console.error(e) }
}

// ---- draft / version ----
const draftTotal = ref(0); const submitting = ref(false); const versions = ref([]); const showVersions = ref(false)
const loadDrafts = async () => { try { const r = await api.get('/template-features/drafts'); draftTotal.value = r.total || 0 } catch { draftTotal.value = 0 } }
const submitDrafts = async () => { submitting.value = true; try { await api.post('/template-features/submit'); ElMessage.success('提交成功'); await loadData(); await loadDrafts() } catch(e) { ElMessage.error('提交失败: ' + (e.response?.data?.detail || e.message)); console.error(e) } finally { submitting.value = false } }
const discardDrafts = async () => { try { await api.post('/template-features/discard'); ElMessage.success('已废弃'); await loadData(); await loadDrafts() } catch { ElMessage.error('废弃失败') } }
const loadVersions = async () => { try { versions.value = await api.get('/template-features/versions') || [] } catch { versions.value = [] } }
const openVersions = async () => { await loadVersions(); showVersions.value = true }
const rollback = async (row) => {
  try { await api.post(`/template-features/rollback/${row.id}`); ElMessage.success('回滚成功'); await loadData(); await loadVersions() } catch { ElMessage.error('回滚失败') }
}

onMounted(async () => { await loadData(); await loadDrafts() })
</script>

<style scoped>
.page { padding: 0 } .card-header { display: flex; justify-content: space-between; align-items: center }
.matrix-container { padding-top: 12px }
.toolbar-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px }
.legend { display: flex; gap: 16px; font-size: 13px }
.legend-item { display: flex; align-items: center; gap: 4px }
.dot { display: inline-block; width: 14px; height: 14px; border-radius: 3px }
.dot.supported { background: #dcfce7; border: 1px solid #22c55e }
.dot.unsupported { background: #f1f5f9; border: 1px solid #cbd5e1 }
.dot.pending { background: #fef3c7; border: 2px dashed #f59e0b }
.toolbar-right { display:flex; align-items:center; gap:12px; flex-wrap:wrap }
.filter-row { display:flex; align-items:center; gap:8px; padding:6px 0 10px; flex-wrap:wrap }
.group-filter-compact { display:inline-flex; flex-wrap:wrap; gap:2px }
.group-filter-compact .el-checkbox { margin-right:0; white-space:nowrap }
.view-toggle { flex-shrink: 0 }
.table-wrap { overflow-x: auto }
.tpl-cell { width: 100%; text-align: center; transition: background .1s; min-height: 28px; display: flex; align-items: center; justify-content: center }
.tpl-cell.supported { background: #dcfce7; color: #166534 }
.tpl-cell.conditional { background: #fef3c7; color: #92400e }
.tpl-cell.unsupported { background: #f1f5f9; color: #94a3b8 }
.tpl-cell.is-dirty { outline: 2px dashed #f59e0b; outline-offset: -2px }
.cell-apps { font-size: 11px; line-height: 1.3; padding: 2px 4px; word-break: break-all }
.cell-apps.is-all { font-weight: 700; font-size: 13px }
.draft-bar { display:flex; align-items:center; gap:12px; padding:8px 16px; background:#fef3c7; border-radius:6px }
.cat-cell { line-height:1.4 }
.cat-name { font-weight:600; white-space:nowrap }
.cat-apps { display:flex; flex-wrap:wrap; gap:2px; max-height:80px; overflow-y:auto }
.app-tag { margin:0; font-size:10px }
</style>
