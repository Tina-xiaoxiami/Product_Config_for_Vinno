<template>
  <div class="probe-config-page">
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>探头配置管理</span>
          <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap">
            <el-select v-model="selectedGroup" placeholder="分组" style="width:180px" @change="onGroupChange">
              <el-option v-for="g in groupOptions" :key="g" :label="g" :value="g" />
            </el-select>
            <el-select v-model="selectedSeriesIds" placeholder="系列" style="width:220px" multiple collapse-tags collapse-tags-tooltip @change="onSeriesChange" :disabled="!selectedGroup">
              <el-option v-for="s in filteredSeriesList" :key="s.id" :label="s.name" :value="s.id" />
            </el-select>
            <el-select v-model="selectedModelIds" placeholder="型号" style="width:260px" multiple collapse-tags collapse-tags-tooltip @change="onModelChange" :disabled="!selectedGroup">
              <el-option v-for="m in modelOptions" :key="m.id" :label="m.label" :value="m.id" />
            </el-select>
            <el-button size="small" type="primary" @click="refreshMatrix" :loading="loading" :disabled="!selectedModelIds.length">查询配置</el-button>
            <template v-if="selectedModelIds.length">
              <el-button size="small" @click="openLinkProbes">关联探头</el-button>
              <el-button size="small" v-if="matrixData" @click="showImportProduct = true">导入Excel</el-button>
              <el-button size="small" v-if="matrixData" @click="exportConfig">导出Excel</el-button>
            </template>
            <el-checkbox v-if="matrixData" v-model="showDetailMode">详细模式</el-checkbox>
            <template v-if="matrixData && showDetailMode">
              <el-radio-group v-model="detailShowMode" size="small">
                <el-radio value="auto">智能</el-radio>
                <el-radio value="supported">显示支持</el-radio>
                <el-radio value="excluded">显示排除</el-radio>
              </el-radio-group>
              <el-checkbox v-model="showMismatchOnly">仅显示不一致</el-checkbox>
            </template>
            <el-checkbox v-if="matrixData && !showDetailMode" v-model="showStatusMismatch">仅显示定义/现状不一致</el-checkbox>
          </div>
        </div>
      </template>

      <div v-if="!selectedGroup" class="empty-state">
        <el-empty description="请选择产品分组" />
      </div>
      <div v-else-if="!selectedSeriesIds.length" class="empty-state">
        <el-empty description="请选择产品系列" />
      </div>
      <div v-else-if="!matrixData && !loading" class="empty-state">
        <el-empty description="请选择型号并点击「查询配置」">
          <el-button type="primary" @click="refreshMatrix">查询配置</el-button>
        </el-empty>
      </div>
      <div v-else-if="matrixData && !filteredProbes.length && !loading" class="empty-state">
        <el-empty description="所选型号暂无探头关联，请先关联探头到产品型号">
          <el-button type="primary" @click="openLinkProbes">关联探头</el-button>
        </el-empty>
      </div>

      <div v-else v-loading="loading" class="matrix-container">
        <div v-if="draftTotal > 0" class="draft-bar">
          <span><strong>{{ draftTotal }}</strong> 条草稿待提交</span>
          <el-button size="small" type="primary" @click="handleSubmit" :loading="submitting">提交并创建版本</el-button>
          <el-button size="small" type="danger" @click="handleDiscard">废弃全部</el-button>
        </div>
        <div class="legend">
          <template v-if="!showDetailMode">
            <span class="legend-item"><span class="dot supported"></span> 支持（√）</span>
            <span class="legend-item"><span class="dot conditional"></span> 条件支持（△）</span>
            <span class="legend-item"><span class="dot unsupported"></span> 不支持</span>
            <span class="legend-item"><span class="status-mismatch-border"></span> 定义/现状不一致</span>
            <span class="legend-item"><span class="dot mixed"></span> 型号值冲突</span>
          </template>
          <template v-else>
            <span class="legend-item"><span class="dot supported"></span> 支持（ALL）</span>
            <span class="legend-item"><span class="dot conditional"></span> 条件（排除部分应用）</span>
            <span class="legend-item"><span class="dot unsupported"></span> 不支持（—）</span>
            <span class="legend-item"><span class="status-mismatch-border"></span> 定义/现状不一致</span>
          </template>
        </div>

        <el-table :data="filteredProbes" border stripe size="small" :max-height="600" style="width:100%" row-key="row_key">
          <el-table-column prop="category_name" label="类别" width="100" fixed />
          <el-table-column label="探头型号" width="220" fixed>
            <template #default="{ row: r }">
              <div style="display:flex;align-items:center;gap:4px">
                <div>
                  <div style="font-weight:500">{{ r.model_number }}{{ r.priority ? ' (' + r.priority + ')' : '' }}</div>
                  <div v-if="r.ipn" style="font-size:10px;color:#909399">IPN: {{ r.ipn }}{{ r.internal_model ? ' (' + r.internal_model + ')' : '' }}</div>
                </div>
                <el-dropdown trigger="click" size="small" @command="(cmd) => batchSetRow(r.id, cmd)">
                  <el-button size="small" text :icon="ArrowDown" style="padding:0 2px" />
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item command="supported">批量设为√</el-dropdown-item>
                      <el-dropdown-item command="unsupported">批量清空</el-dropdown-item>
                      <el-dropdown-item command="from_template">从模板恢复</el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </div>
            </template>
          </el-table-column>
          <el-table-column v-for="f in allFeatures" :key="f.id" :width="showDetailMode ? (featureWidths[f.id] || 64) : 64" align="center">
            <template #header>
              <div style="font-size:12px;line-height:1.3">
                <div>{{ f.name }}</div>
                <div style="font-size:10px;color:#909399" v-if="f.ipn">{{ f.ipn }}</div>
              </div>
            </template>
            <template #default="{ row: r }">
              <div class="config-cell" :class="cellClass(r.id, f.id)" @click="editCell(r.id, f.id)">
                <template v-if="showDetailMode">
                  <el-tooltip :content="getCellTooltip(r, f)" placement="top" :disabled="!getCellTooltip(r, f)" :show-after="300">
                    <div class="cell-apps" :class="{ 'is-all': isCellAll(r, f) }" style="font-size:11px;line-height:1.3;padding:2px 4px;word-break:break-all">
                      <div>{{ detailCellText(getConfig(r.id, f.id), r, 'defined') }}</div>
                      <div style="border-top:1px solid #ddd;margin:2px 0">{{ detailCellText(getConfig(r.id, f.id), r, 'current') }}</div>
                    </div>
                  </el-tooltip>
                </template>
                <template v-else>
                  <span class="defined">{{ statusIcon(getConfig(r.id, f.id)?.defined_status) }}</span>
                  <span class="divider">/</span>
                  <span class="current">{{ statusIcon(getConfig(r.id, f.id)?.current_status) }}</span>
                </template>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-card>

    <!-- Edit Dialog -->
    <el-dialog v-model="editDialog.visible" title="编辑支持状态" width="700px">
      <div v-if="editDialog.row" class="edit-dialog-content">
        <div style="display:flex;gap:12px;margin-bottom:12px">
          <el-tag>{{ editDialog.row.model_number }}</el-tag>
          <el-tag type="info">{{ editDialog.feature?.name }}</el-tag>
        </div>
        <div v-if="editDialog.hasMixed" style="margin-bottom:12px;padding:8px 12px;background:#fef3c7;border-radius:6px;font-size:12px">
          <strong style="color:#d46b08">不同型号值冲突，各型号当前值：</strong>
          <div v-for="(v, mid) in editDialog.perModel" :key="mid" style="margin-top:4px;color:#606266">
            {{ modelNameMap[mid] || mid }}: 定义={{ {supported:'√',conditional:'△',unsupported:'—'}[v.defined_status] }} / 现状={{ {supported:'√',conditional:'△',unsupported:'—'}[v.current_status] }}
          </div>
        </div>
        <!-- Status selectors -->
        <div style="display:flex;gap:24px;margin-bottom:12px">
          <div style="flex:1">
            <label style="display:block;margin-bottom:4px;font-weight:500">定义值</label>
            <el-select v-model="editDialog.definedStatus" style="width:100%" @change="onStatusChange">
              <el-option value="supported" label="支持 √" />
              <el-option value="conditional" label="条件 △" />
              <el-option value="unsupported" label="不支持" />
            </el-select>
          </div>
          <div style="flex:1">
            <label style="display:block;margin-bottom:4px;font-weight:500">现状值</label>
            <el-select v-model="editDialog.currentStatus" style="width:100%">
              <el-option value="supported" label="支持 √" />
              <el-option value="conditional" label="条件 △" />
              <el-option value="unsupported" label="不支持" />
            </el-select>
          </div>
        </div>
        <!-- Per-app configuration -->
        <div v-if="editDialog.definedStatus !== 'unsupported' || editDialog.currentStatus !== 'unsupported'" style="padding-top:12px;border-top:1px solid #ebeef5">
          <div style="font-weight:500;margin-bottom:8px;font-size:13px">
            应用配置 <span style="font-size:11px;color:#909399;font-weight:400">（勾选 = 支持，未勾选 = 排除）</span>
          </div>
          <el-tabs v-model="editDialog.appTab" size="small">
            <el-tab-pane label="定义值" name="defined">
              <div v-if="editDialog.definedStatus === 'unsupported'" style="color:#909399;padding:8px">不支持状态无需配置应用</div>
              <template v-else>
                <div v-if="editDialogApps.regular.length" style="margin-bottom:8px">
                  <div style="font-size:12px;font-weight:500;margin-bottom:4px">常规应用 ({{ editDialogApps.regular.length }})</div>
                  <el-checkbox-group v-model="editDialog.definedSupportedApps" size="small">
                    <el-checkbox v-for="a in editDialogApps.regular" :key="'dr-'+a.id" :label="a.name" :value="a.name" style="margin-right:4px" />
                  </el-checkbox-group>
                </div>
                <div v-if="editDialogApps.poc.length">
                  <div style="font-size:12px;font-weight:500;margin-bottom:4px">POC 应用 ({{ editDialogApps.poc.length }})</div>
                  <el-checkbox-group v-model="editDialog.definedSupportedApps" size="small">
                    <el-checkbox v-for="a in editDialogApps.poc" :key="'dp-'+a.id" :label="a.name" :value="a.name" style="margin-right:4px" />
                  </el-checkbox-group>
                </div>
              </template>
            </el-tab-pane>
            <el-tab-pane label="现状值" name="current">
              <div v-if="editDialog.currentStatus === 'unsupported'" style="color:#909399;padding:8px">不支持状态无需配置应用</div>
              <template v-else>
                <div v-if="editDialogApps.regular.length" style="margin-bottom:8px">
                  <div style="font-size:12px;font-weight:500;margin-bottom:4px">常规应用 ({{ editDialogApps.regular.length }})</div>
                  <el-checkbox-group v-model="editDialog.currentSupportedApps" size="small">
                    <el-checkbox v-for="a in editDialogApps.regular" :key="'cr-'+a.id" :label="a.name" :value="a.name" style="margin-right:4px" />
                  </el-checkbox-group>
                </div>
                <div v-if="editDialogApps.poc.length">
                  <div style="font-size:12px;font-weight:500;margin-bottom:4px">POC 应用 ({{ editDialogApps.poc.length }})</div>
                  <el-checkbox-group v-model="editDialog.currentSupportedApps" size="small">
                    <el-checkbox v-for="a in editDialogApps.poc" :key="'cp-'+a.id" :label="a.name" :value="a.name" style="margin-right:4px" />
                  </el-checkbox-group>
                </div>
              </template>
            </el-tab-pane>
          </el-tabs>
        </div>
        <div style="margin-top:12px;font-size:12px;color:#909399">
          将应用到 {{ selectedModelIds.length }} 个选中的产品型号
        </div>
      </div>
      <template #footer>
        <el-button @click="editDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="saveEdit" :loading="saving">保存</el-button>
      </template>
    </el-dialog>

    <!-- Link Probes Dialog -->
    <el-dialog v-model="linkDialog.visible" title="关联探头到产品型号" width="600px">
      <div style="margin-bottom:12px;font-size:13px;color:#606266">
        将为 <strong>{{ selectedModelIds.length }}</strong> 个选中的产品型号同时关联以下探头
      </div>
      <div v-loading="linkDialog.loading" style="max-height:400px;overflow-y:auto">
        <div v-for="cat in linkDialog.categories" :key="cat.id" style="margin-bottom:12px">
          <div style="font-weight:500;margin-bottom:4px;padding:4px 0;border-bottom:1px solid #ebeef5">
            <el-checkbox :indeterminate="isIndeterminate(cat)" :model-value="isCatAllChecked(cat)" @change="toggleCat(cat, $event)">
              {{ cat.name }}
            </el-checkbox>
          </div>
          <div style="padding-left:12px;display:flex;flex-wrap:wrap;gap:6px">
            <el-checkbox
              v-for="m in cat.models" :key="m.id"
              v-model="linkDialog.selectedIds"
              :label="m.id"
            >{{ m.model_number }}</el-checkbox>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="linkDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="saveLinkProbes" :loading="linkDialog.saving">确认关联</el-button>
      </template>
    </el-dialog>

    <!-- Import Dialog -->
    <el-dialog v-model="showImportProduct" title="导入产品 Excel" width="450px">
      <el-upload drag :auto-upload="false" :on-change="handleProductFile" accept=".xlsx,.xls">
        <el-icon class="el-icon--upload"><Upload /></el-icon>
        <div class="el-upload__text">拖拽文件或<em>点击上传</em></div>
      </el-upload>
      <p style="color:#909399;font-size:12px;margin-top:10px">选择产品探头配置 Excel 文件</p>
      <template #footer>
        <el-button @click="showImportProduct = false">取消</el-button>
        <el-button type="primary" @click="doImportProduct" :loading="importing">开始导入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowDown, Upload } from '@element-plus/icons-vue'
import { getSeriesList, getModels, getApplications, getSeriesMatrix, updateSeriesFeature, getSeriesDrafts, discardSeriesDrafts, submitSeriesDrafts, getSeriesProbeVersions, exportProbeConfig, batchSetStatus, batchFromTemplate, getAllProbesByCategory, setSeriesProbes, getModelGroups } from '../api/data'
import api from '../api/index'

// State
const seriesList = ref([])
const selectedGroup = ref('')
const groupOptions = ref([])
const groupData = ref(null)  // raw /model-groups response
const selectedSeriesIds = ref([])
const selectedModelIds = ref([])
const modelOptions = ref([])
const modelNameMap = reactive({})
const matrixData = ref(null)
const loading = ref(false)
const saving = ref(false)
const allApplications = ref([])
const showOnlyDiff = ref(false)
const showStatusMismatch = ref(false)
const showDetailMode = ref(false)
const detailShowMode = ref('auto')
const showMismatchOnly = ref(false)
const priorities = ['标1', '标2', '标3', '新', '新(未优化)', '新(未发放)']

// Group filtering
const groupModelIds = computed(() => {
  if (!selectedGroup.value || !groupData.value?.groups) return new Set()
  const models = groupData.value.groups[selectedGroup.value] || []
  return new Set(models.map(m => m.id))
})
const filteredSeriesList = computed(() => {
  if (!selectedGroup.value || !groupData.value?.groups) return seriesList.value
  const models = groupData.value.groups[selectedGroup.value] || []
  const seriesIds = new Set(models.map(m => m.series_id))
  return seriesList.value.filter(s => seriesIds.has(s.id))
})

// Link probes dialog
const linkDialog = reactive({
  visible: false, loading: false, saving: false, categories: [], selectedIds: []
})

const isIndeterminate = (cat) => {
  const catIds = cat.models.map(m => m.id)
  const selected = linkDialog.selectedIds.filter(id => catIds.includes(id))
  return selected.length > 0 && selected.length < catIds.length
}
const isCatAllChecked = (cat) => {
  const catIds = cat.models.map(m => m.id)
  return catIds.every(id => linkDialog.selectedIds.includes(id))
}
const toggleCat = (cat, checked) => {
  const catIds = cat.models.map(m => m.id)
  if (checked) {
    catIds.forEach(id => { if (!linkDialog.selectedIds.includes(id)) linkDialog.selectedIds.push(id) })
  } else {
    linkDialog.selectedIds = linkDialog.selectedIds.filter(id => !catIds.includes(id))
  }
}

const openLinkProbes = async () => {
  linkDialog.loading = true; linkDialog.visible = true
  try {
    linkDialog.categories = await getAllProbesByCategory()
    linkDialog.selectedIds = []
  } catch { ElMessage.error('加载探头列表失败') }
  finally { linkDialog.loading = false }
}

const saveLinkProbes = async () => {
  if (!linkDialog.selectedIds.length) return ElMessage.warning('请至少选择一个探头')
  linkDialog.saving = true
  try {
    await setSeriesProbes({
      model_ids: selectedModelIds.value,
      probe_model_ids: linkDialog.selectedIds
    })
    ElMessage.success('探头关联成功')
    linkDialog.visible = false
    await refreshMatrix()
  } catch (e) { ElMessage.error('关联失败: ' + (e.response?.data?.detail || e.message)) }
  finally { linkDialog.saving = false }
}

// Import
const showImportProduct = ref(false)
const importing = ref(false)
const productFile = ref(null)
const handleProductFile = (file) => { productFile.value = file.raw }

// Derived
const allFeatures = computed(() => matrixData.value?.features || [])
const probes = computed(() => matrixData.value?.probe_models || [])

// Per-feature column widths for detail mode: adaptive based on max cell text length
const featureWidths = computed(() => {
  const widths = {}
  if (!showDetailMode.value || !matrixData.value) return widths
  for (const f of allFeatures.value) {
    let maxLen = 0
    for (const p of probes.value) {
      const cfg = getConfig(p.id, f.id)
      const dText = detailCellText(cfg, p, 'defined')
      const cText = detailCellText(cfg, p, 'current')
      maxLen = Math.max(maxLen, dText.length, cText.length)
    }
    // ALL/— (3-4 chars) → ~48px; long text → up to 160px
    widths[f.id] = Math.max(48, Math.min(160, maxLen * 7.5 + 16))
  }
  return widths
})

const filteredProbes = computed(() => {
  let result = probes.value
  if (showDetailMode.value && showMismatchOnly.value) {
    result = result.filter(p => {
      for (const f of allFeatures.value) {
        const cfg = getConfig(p.id, f.id)
        if (!cfg) continue
        if (cfg.defined_status !== cfg.current_status) return true
        if (cfg.defined_status === 'mixed' || cfg.current_status === 'mixed') return true
        const defEx = cfg.defined_excludes || cfg.template_excludes || ''
        const curEx = cfg.current_excludes || cfg.template_excludes || ''
        if (defEx !== curEx) return true
      }
      return false
    })
  } else if (!showDetailMode.value && showStatusMismatch.value) {
    result = result.filter(p => {
      for (const f of allFeatures.value) {
        const cfg = getConfig(p.id, f.id)
        if (cfg && cfg.defined_status && cfg.current_status && cfg.defined_status !== cfg.current_status) return true
        if (cfg?.defined_status === 'mixed' || cfg?.current_status === 'mixed') return true
      }
      return false
    })
  }
  return result
})

const getConfig = (probeModelId, featureId) => {
  if (!matrixData.value?.configs) return null
  const pm = matrixData.value.configs[String(probeModelId)]
  if (!pm) return null
  return pm[String(featureId)] || null
}

const statusIcon = (status) => {
  if (status === 'supported') return '√'
  if (status === 'conditional') return '△'
  if (status === 'mixed') return '?'
  return '—'
}

// ---- Detailed mode helpers (mirrors TemplateFeatures.vue style) ----
function _parseExcludes(excludesVal) {
  if (!excludesVal) return { excludes: [], tender: [] }
  if (typeof excludesVal === 'object' && !Array.isArray(excludesVal)) {
    return { excludes: excludesVal.excludes || [], tender: excludesVal.tender || [] }
  }
  if (typeof excludesVal === 'string') {
    try {
      const parsed = JSON.parse(excludesVal)
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        return { excludes: parsed.excludes || [], tender: parsed.tender || [] }
      }
      return { excludes: Array.isArray(parsed) ? parsed : [], tender: [] }
    } catch { return { excludes: [], tender: [] } }
  }
  return { excludes: [], tender: [] }
}

// Get applications for a probe's category from matrixData
const getProbeCategoryApps = (probe) => {
  if (!matrixData.value?.applications) return { regular: [], poc: [] }
  return matrixData.value.applications[String(probe.category_id)] || { regular: [], poc: [] }
}

const isCellAll = (probe, feature) => {
  const cfg = getConfig(probe.id, feature.id)
  if (!cfg || cfg.defined_status === 'unsupported') return false
  if (cfg.defined_status === 'supported') return true
  if (cfg.defined_status === 'conditional') {
    const ex = cfg.defined_excludes || cfg.template_excludes
    const parsed = _parseExcludes(ex)
    return parsed.excludes.length === 0 && parsed.tender.length === 0
  }
  return false
}

// Cell tooltip for detailed mode
const getCellTooltip = (probe, feature) => {
  const cfg = getConfig(probe.id, feature.id)
  if (!cfg) return ''
  const all = getProbeCategoryApps(probe)
  const allNames = [...(all.regular || []).map(a => a.name), ...(all.poc || []).map(a => a.name)]
  if (!allNames.length) return ''
  const parts = []
  for (const side of ['defined', 'current']) {
    const status = side === 'defined' ? cfg.defined_status : cfg.current_status
    let exRaw = side === 'defined' ? cfg.defined_excludes : cfg.current_excludes
    if (!exRaw) exRaw = cfg.template_excludes
    const parsed = _parseExcludes(exRaw)
    const excludedSet = new Set(parsed.excludes)
    const tenderSet = new Set(parsed.tender)
    const supported = allNames.filter(n => !excludedSet.has(n) && !tenderSet.has(n))
    const label = side === 'defined' ? '定义' : '现状'
    if (status === 'unsupported') parts.push(`${label}: 不支持`)
    else if (status === 'supported') parts.push(`${label}: 全部支持`)
    else if (status === 'conditional') {
      let s = `${label}: `
      if (supported.length) s += '支:' + supported.join(',')
      if (parsed.tender.length) s += (supported.length ? ' | ' : '') + '招:' + parsed.tender.join(',')
      parts.push(s)
    }
  }
  return parts.join('\n')
}

const detailCellText = (cfg, probe, side) => {
  if (!cfg) return '—'
  const status = side === 'defined' ? cfg.defined_status : cfg.current_status
  // Use product-level excludes if set, otherwise fall back to template excludes
  let excludesRaw = side === 'defined' ? cfg.defined_excludes : cfg.current_excludes
  if (!excludesRaw) excludesRaw = cfg.template_excludes
  if (!status || status === 'unsupported') return '—'

  const apps = getProbeCategoryApps(probe)
  const allNames = [...(apps.regular || []).map(a => a.name), ...(apps.poc || []).map(a => a.name)]
  if (!allNames.length) return status === 'supported' ? 'ALL' : '△'

  const parsed = _parseExcludes(excludesRaw)
  const excludedSet = new Set(parsed.excludes)
  const supported = allNames.filter(n => !excludedSet.has(n) && !parsed.tender.includes(n))

  if (status === 'conditional' && parsed.tender.length) {
    const parts = []
    if (supported.length) parts.push('支:' + supported.join(','))
    parts.push('招:' + parsed.tender.join(','))
    return parts.join(' | ')
  }

  if (parsed.excludes.length === 0 && parsed.tender.length === 0) return 'ALL'

  if (detailShowMode.value === 'supported' || (detailShowMode.value === 'auto' && supported.length <= parsed.excludes.length)) {
    return supported.join(', ')
  }
  return '除: ' + parsed.excludes.join(', ')
}

// Edit dialog computed: apps for current probe category
const editDialogApps = computed(() => {
  if (!editDialog.row) return { regular: [], poc: [] }
  return getProbeCategoryApps(editDialog.row)
})

const cellClass = (probeId, featureId) => {
  const cfg = getConfig(probeId, featureId)
  const classes = []
  if (cfg?.defined_status === 'supported') classes.push('s-supported')
  else if (cfg?.defined_status === 'conditional') classes.push('s-conditional')
  else if (cfg?.defined_status === 'mixed') classes.push('s-mixed')
  if (cfg?.defined_status && cfg?.current_status && cfg.defined_status !== cfg.current_status) classes.push('status-mismatch')
  if (cfg?.is_overridden || (cfg?.template_support && cfg?.defined_status !== cfg?.template_support)) classes.push('overridden')
  return classes
}

// Series / Model / Group selection
const loadSeriesList = async () => {
  try { seriesList.value = (await getSeriesList({ limit: 200 })).items || [] } catch { seriesList.value = [] }
}

const loadGroupList = async () => {
  try { groupData.value = await getModelGroups() } catch { groupData.value = null }
}

const onGroupChange = async () => {
  if (!selectedGroup.value || !groupData.value?.groups) {
    selectedSeriesIds.value = []
    modelOptions.value = []
    selectedModelIds.value = []
    matrixData.value = null
    return
  }
  // Get group models and their series
  const models = groupData.value.groups[selectedGroup.value] || []
  if (!models.length) {
    selectedSeriesIds.value = []
    modelOptions.value = []
    selectedModelIds.value = []
    matrixData.value = null
    return
  }
  const seriesIds = [...new Set(models.map(m => m.series_id))]
  // Auto-select all series in this group
  selectedSeriesIds.value = seriesIds
  // Load models for all selected series, filtered by group
  await loadFilteredModels(seriesIds)
  if (selectedModelIds.value.length) {
    refreshMatrix()
  }
}

let _loadSeq = 0
const loadFilteredModels = async (seriesIds) => {
  const seq = ++_loadSeq
  const allowedModelIds = groupModelIds.value
  // Clear old model name map
  for (const key of Object.keys(modelNameMap)) {
    delete modelNameMap[key]
  }
  // Parallelize model loading across series
  const results = await Promise.allSettled(
    seriesIds.map(sid => getModels(sid, { limit: 500 }))
  )
  if (seq !== _loadSeq) return
  const all = []
  for (let i = 0; i < results.length; i++) {
    if (seq !== _loadSeq) return
    const result = results[i]
    const models = result.status === 'fulfilled' ? (result.value?.items || []) : []
    for (const m of models) {
      if (allowedModelIds.has(m.id)) {
        all.push({ id: m.id, label: m.name, series_id: seriesIds[i] })
        modelNameMap[m.id] = m.name
      }
    }
  }
  if (seq !== _loadSeq) return
  modelOptions.value = all
  selectedModelIds.value = all.map(m => m.id)
}

const onSeriesChange = async () => {
  if (!selectedSeriesIds.value.length) {
    modelOptions.value = []
    selectedModelIds.value = []
    matrixData.value = null
    return
  }
  await loadFilteredModels(selectedSeriesIds.value)
  if (selectedModelIds.value.length) {
    refreshMatrix()
  }
}

const onModelChange = () => { refreshMatrix() }

// Matrix loading (with concurrent guard)
let _refreshing = false
const refreshMatrix = async () => {
  if (!selectedSeriesIds.value.length || !selectedModelIds.value.length) return
  if (_refreshing) return
  _refreshing = true
  loading.value = true
  try {
    const raw = await getSeriesMatrix({
      series_ids: selectedSeriesIds.value.join(','),
      model_ids: selectedModelIds.value.join(',')
    })
    matrixData.value = raw
    // Store model name map
    ;(matrixData.value.product_models || []).forEach(m => { modelNameMap[m.id] = m.name })
  } catch (e) {
    matrixData.value = null
    console.error('[refreshMatrix] getSeriesMatrix:', e)
    ElMessage.error(e.response?.data?.detail || '矩阵加载失败: ' + (e.message || '网络错误'))
    _refreshing = false
    loading.value = false
    return
  }
  try { await loadDrafts() } catch (e) { console.error('[refreshMatrix] loadDrafts:', e) }
  try {
    const apps = await getApplications({ limit: 500 })
    allApplications.value = apps.items || []
  } catch (e) { console.error('[refreshMatrix] getApplications:', e) }
  _refreshing = false
  loading.value = false
}

// Draft management
const draftTotal = ref(0); const submitting = ref(false)
const loadDrafts = async () => {
  if (!selectedModelIds.value.length) return
  try { draftTotal.value = (await getSeriesDrafts(selectedModelIds.value)).total || 0 } catch { draftTotal.value = 0 }
}
const handleSubmit = async () => {
  submitting.value = true
  try {
    await submitSeriesDrafts({ series_ids: selectedSeriesIds.value, model_ids: selectedModelIds.value })
    ElMessage.success('提交成功')
    await refreshMatrix(); await loadDrafts()
  } catch (e) { ElMessage.error('提交失败: ' + (e.response?.data?.detail || e.message)) }
  finally { submitting.value = false }
}
const handleDiscard = async () => {
  try {
    await discardSeriesDrafts({ model_ids: selectedModelIds.value })
    ElMessage.success('已废弃'); await refreshMatrix(); await loadDrafts()
  } catch { ElMessage.error('废弃失败') }
}

// Batch operations
const batchSetRow = async (probeId, cmd) => {
  try {
    const mids = selectedModelIds.value
    if (cmd === 'from_template') {
      for (const mid of mids) { await batchFromTemplate(mid, { probe_model_id: probeId }) }
    } else {
      const status = cmd === 'supported' ? 'supported' : 'unsupported'
      for (const mid of mids) {
        await batchSetStatus(mid, { probe_model_id: probeId, defined_status: status, current_status: status })
      }
    }
    ElMessage.success('批量设置已保存'); await refreshMatrix(); await loadDrafts()
  } catch { ElMessage.error('操作失败') }
}

// Cell editing
const editDialog = reactive({
  visible: false, row: null, feature: null,
  definedStatus: 'unsupported', currentStatus: 'unsupported',
  definedSupportedApps: [], currentSupportedApps: [],
  appTab: 'defined',
  perModel: {}, hasMixed: false,
  priority: null, notes: ''
})

const editCell = (probeModelId, featureId) => {
  const cfg = getConfig(probeModelId, featureId)
  const probe = probes.value.find(p => p.id === probeModelId)
  const feat = allFeatures.value.find(f => f.id === featureId)
  editDialog.row = probe || { model_number: '' }
  editDialog.feature = feat || { name: '' }
  editDialog.definedStatus = cfg?.defined_status === 'mixed' ? 'unsupported' : (cfg?.defined_status || 'unsupported')
  editDialog.currentStatus = cfg?.current_status === 'mixed' ? 'unsupported' : (cfg?.current_status || 'unsupported')
  editDialog.perModel = cfg?.per_model || {}
  editDialog.hasMixed = cfg?.defined_status === 'mixed' || cfg?.current_status === 'mixed'
  // Compute supported apps from excludes
  const apps = getProbeCategoryApps(probe || {})
  const allNames = [...(apps.regular || []).map(a => a.name), ...(apps.poc || []).map(a => a.name)]
  const computeSupported = (excludesRaw) => {
    if (!excludesRaw) return allNames
    const p = _parseExcludes(excludesRaw)
    const es = new Set(p.excludes), ts = new Set(p.tender)
    return allNames.filter(n => !es.has(n) && !ts.has(n))
  }
  editDialog.definedSupportedApps = computeSupported(cfg?.defined_excludes || cfg?.template_excludes)
  editDialog.currentSupportedApps = computeSupported(cfg?.current_excludes || cfg?.template_excludes)
  editDialog.appTab = 'defined'
  editDialog.priority = cfg?.priority || null
  editDialog.notes = cfg?.notes || ''
  editDialog.visible = true
}

const onStatusChange = (val) => {
  if (val === 'supported') { editDialog.definedSupportedApps = [...getAllAppNames()] }
}

const getAllAppNames = () => {
  const apps = getProbeCategoryApps(editDialog.row || {})
  return [...(apps.regular || []).map(a => a.name), ...(apps.poc || []).map(a => a.name)]
}

const saveEdit = async () => {
  if (!editDialog.row) return
  saving.value = true
  try {
    const allApps = getProbeCategoryApps(editDialog.row)
    const allNames = [...(allApps.regular || []).map(a => a.name), ...(allApps.poc || []).map(a => a.name)]
    const computeExcludes = (supportedAppNames, status) => {
      if (status !== 'conditional') return null
      if (!allNames.length) return null
      const supported = new Set(supportedAppNames || [])
      const excludes = allNames.filter(n => !supported.has(n))
      if (!excludes.length) return null
      return JSON.stringify({ excludes, tender: [] })
    }
    await updateSeriesFeature({
      probe_model_id: editDialog.row.id,
      feature_id: editDialog.feature.id,
      defined_status: editDialog.definedStatus,
      current_status: editDialog.currentStatus,
      defined_excludes: computeExcludes(editDialog.definedSupportedApps, editDialog.definedStatus),
      current_excludes: computeExcludes(editDialog.currentSupportedApps, editDialog.currentStatus),
      priority: editDialog.priority,
      notes: editDialog.notes,
      target_model_ids: selectedModelIds.value
    })
    ElMessage.success(`已为 ${selectedModelIds.value.length} 个型号保存`)
    editDialog.visible = false
    await refreshMatrix(); await loadDrafts()
  } catch (e) { ElMessage.error(e.response?.data?.detail || '保存失败') }
  finally { saving.value = false }
}

// Import / Export
const doImportProduct = async () => {
  if (!productFile.value) return ElMessage.warning('请选择文件')
  importing.value = true
  try {
    const fd = new FormData(); fd.append('file', productFile.value)
    // Import for the first selected model
    fd.append('product_model_id', String(selectedModelIds.value[0]))
    const res = await api.post('/probes/import-product', fd)
    ElMessage.success(res.message); showImportProduct.value = false
    await refreshMatrix()
  } catch (e) { ElMessage.error('导入失败') } finally { importing.value = false }
}

const exportConfig = async () => {
  if (!selectedModelIds.value.length) return
  try {
    const blob = await exportProbeConfig(selectedModelIds.value[0])
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a'); a.href = url
    a.download = `探头配置_${Date.now()}.xlsx`
    document.body.appendChild(a); a.click(); document.body.removeChild(a)
    window.URL.revokeObjectURL(url)
  } catch { ElMessage.error('导出失败') }
}

onMounted(async () => {
  await Promise.all([loadSeriesList(), loadGroupList()])
  // Extract group names for dropdown options
  groupOptions.value = groupData.value?.groups ? Object.keys(groupData.value.groups) : []
})
</script>

<style scoped>
.page { padding: 0 } .card-header { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px }
.matrix-container { padding-top: 12px }
.empty-state { padding: 40px 0 }
.legend { display: flex; gap: 16px; font-size: 13px; margin-bottom: 12px; flex-wrap: wrap }
.legend-item { display: flex; align-items: center; gap: 4px }
.dot { display: inline-block; width: 14px; height: 14px; border-radius: 3px }
.dot.supported { background: #dcfce7; border: 1px solid #22c55e }
.dot.conditional { background: #fef3c7; border: 1px solid #f59e0b }
.dot.unsupported { background: #f1f5f9; border: 1px solid #cbd5e1 }
.dot.mixed { background: repeating-linear-gradient(45deg, #dcfce7, #dcfce7 3px, #f1f5f9 3px, #f1f5f9 6px); border: 1px solid #f59e0b }
.status-mismatch-border { width: 14px; height: 14px; border: 2px solid #ef4444; border-radius: 3px; background: transparent }
.draft-bar { display:flex; align-items:center; gap:12px; padding:8px 16px; background:#fef3c7; border-radius:6px; margin-bottom:12px }
.config-cell { width: 100%; min-height: 36px; display: flex; align-items: center; justify-content: center; gap: 2px; cursor: pointer; font-size: 12px; transition: background .1s }
.config-cell:hover { filter: brightness(0.95) }
.config-cell .defined { color: #1e40af; min-width: 12px; text-align: center }
.config-cell .current { color: #047857; min-width: 12px; text-align: center }
.config-cell .divider { color: #cbd5e1; font-size: 10px }
.config-cell.s-supported { background: #dcfce7 }
.config-cell.s-conditional { background: #fef3c7 }
.config-cell.s-mixed { background: repeating-linear-gradient(45deg, #fef3c7, #fef3c7 4px, #f1f5f9 4px, #f1f5f9 8px) }
.config-cell.status-mismatch { outline: 2px solid #ef4444; outline-offset: -2px }
.config-cell.overridden { box-shadow: inset 0 0 0 2px rgba(59,130,246,0.4) }
</style>
