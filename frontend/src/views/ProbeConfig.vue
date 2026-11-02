<template>
  <div class="probe-workspace" v-loading="busy">
    <el-card shadow="never">
      <template #header><div class="toolbar"><strong>探头配置 · 子系列共同总集</strong>
        <el-select :model-value="current?.id" placeholder="选择已有总集" @change="openWorkspace" style="width:220px" :disabled="busy">
          <el-option v-for="w in workspaces" :key="w.id" :value="w.id" :label="w.name + (w.has_draft ? ' · 草稿' : '')" />
        </el-select>
        <el-button size="small" @click="createVisible = true">新建共同总集</el-button>
        <SubseriesEditor ref="scopeEditor" button-label="管理子系列与组合" @saved="loadShared" />
        <el-button size="small" @click="$router.push('/probe-versions')">版本历史</el-button>
      </div></template>
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <el-empty v-if="!current" description="选择子系列或组合建立共同总集，再按各机型配置计算结果。原有数据保留为待核对初始草稿。" />
      <template v-else>
        <div class="toolbar scope-line"><span>{{ scopeLabel }}</span><el-tag size="small">{{ document.scope.model_ids.length }} 个机型</el-tag>
          <el-tag v-if="document.scope.excluded_model_ids?.length" size="small" type="info">已排除 {{ document.scope.excluded_model_ids.length }} 个停用机型</el-tag>
          <el-tag size="small" :type="current.has_draft || dirty ? 'warning' : 'success'">{{ dirty ? '未保存' : current.has_draft ? '待发布草稿' : '已发布' }}</el-tag>
          <el-button size="small" @click="scopeVisible = true">调整子系列范围</el-button>
          <el-button size="small" @click="refreshScope">重新核对共享范围</el-button>
          <el-button size="small" @click="reloadTemplateDefinitions">刷新模板定义</el-button>
        </div>
        <div class="toolbar">
          <el-button size="small" type="primary" :disabled="!dirty" @click="save">保存草稿</el-button>
          <el-button size="small" v-if="!current.has_draft" :disabled="dirty" @click="save">建立下一版草稿</el-button>
          <el-button size="small" :disabled="!current.has_draft && !dirty" @click="discard">废弃草稿</el-button>
          <el-button size="small" type="success" :disabled="dirty || !current.has_draft" @click="startPublish">发布预览</el-button>
          <el-button size="small" :disabled="dirty" @click="download">导出 Excel / 模板</el-button>
          <el-button size="small" :disabled="dirty" @click="fileInput.click()">导入 Excel 草稿</el-button>
          <input ref="fileInput" type="file" accept=".xlsx,.xls" hidden @change="importFile" />
        </div>
        <el-tabs v-model="tab"><el-tab-pane label="共同总集" name="total" /><el-tab-pane label="机型结果与差异" name="models" /><el-tab-pane label="待发布变更" name="changes" /></el-tabs>
        <template v-if="tab === 'changes'"><el-alert :title="diffLabel" type="info" :closable="false" /><p>共同总集修改不会清除已有机型差异。发布预览会列出各机型结果及主配置来源。</p>
          <pre class="changes">{{ JSON.stringify({ common: document.rows, modelDifferences: document.overrides }, null, 2) }}</pre>
        </template>
        <template v-else>
          <div class="toolbar" ref="tableToolbar">
            <el-input v-model="search" size="small" clearable placeholder="搜索探头 / IPN / 功能 / 说明" aria-label="搜索探头配置" style="width:280px" />
            <template v-if="tab === 'models'"><el-select v-model="resultModel" size="small" style="width:230px" placeholder="选择结果机型"><el-option v-for="m in memberModels" :key="m.id" :value="m.id" :label="m.series + ' / ' + m.name" /></el-select>
              <el-checkbox v-model="differencesOnly">仅显示机型差异</el-checkbox>
              <el-tag v-if="dirty" type="warning" size="small">结果为上次保存草稿；保存后重新计算</el-tag>
            </template>
            <el-button v-if="tab === 'total'" size="small" @click="newRow">添加探头物料</el-button>

          </div>
          <div ref="tableContainer" class="table-container">
            <ProbeConfigurationMatrix :key="tab + resultModel" :document="document" :catalog="catalog" :results="tab === 'models' ? modelMatrixResults : undefined" :model-view="tab === 'models'" :search="search" :differences-only="tab === 'models' && differencesOnly" :height="tableHeight" @edit-cell="editMatrixCell" @remove-probe="removeMatrixProbe" />
          </div>
        </template>
      </template>
    </el-card>

    <el-dialog v-model="createVisible" title="建立共同总集" width="620px" :before-close="closeCreate">
      <el-form label-position="top"><el-form-item label="总集名称"><el-input v-model="createName" /></el-form-item>
        <el-form-item label="子系列（可多选）"><el-select v-model="selectedGroups" multiple filterable style="width:100%"><el-option v-for="g in shared.groups" :key="g.name" :value="g.name" :label="g.name + ' · ' + g.model_ids.length + ' 个机型'" /></el-select></el-form-item>
        <div class="toolbar"><SubseriesCombinations :selection-key="selectionKey" @apply="addCombination" @edit="scopeEditor.open()" /><el-tag v-for="name in selectedCombinations" :key="name" closable @close="selectedCombinations = selectedCombinations.filter(n => n !== name)">{{ name }}</el-tag></div>
        <p>组合共享已有定义，机型自动去重。原有记录仅作为待核对草稿，发布后才成为正式基线。</p>
      </el-form>
      <template #footer><el-button @click="closeCreate()">取消</el-button><el-button type="primary" @click="create">建立并核对草稿</el-button></template>
    </el-dialog>
    <el-dialog v-model="scopeVisible" title="调整子系列范围" width="620px" :before-close="closeScope">
      <el-select v-model="scopeGroups" multiple filterable placeholder="选择子系列" style="width:100%"><el-option v-for="g in shared.groups" :key="g.name" :value="g.name" :label="g.name" /></el-select>
      <el-select v-model="scopeCombinations" multiple filterable placeholder="选择子系列组合" style="width:100%;margin-top:12px"><el-option v-for="g in shared.combinations" :key="g.name" :value="g.name" :label="g.name" /></el-select>
      <p>新增成员不会自动复制其他机型差异；移除机型的差异将在核对后从当前草稿移除，历史版本仍保留。</p>
      <template #footer><el-button @click="closeScope()">取消</el-button><el-button type="primary" @click="applyScope">核对并保存范围</el-button></template>
    </el-dialog>
    <el-dialog v-model="editing" :title="editIsNew ? '添加探头物料' : editIsModel ? '编辑机型特有差异' : '编辑共同总集'" width="620px" :before-close="closeEdit">
      <el-form label-position="top">
        <div v-if="editIsNew" class="toolbar"><el-select v-model="newProbe" filterable placeholder="探头 / IPN" style="width:300px"><el-option v-for="p in probeOptions" :key="p.key" :value="p.key" :label="p.label" /></el-select></div>
        <el-form-item v-else-if="editIsModel" label="应用到机型（仅当前总集成员）"><el-select v-model="editModels" multiple style="width:100%"><el-option v-for="m in memberModels" :key="m.id" :value="m.id" :label="m.series + ' / ' + m.name" /></el-select></el-form-item>
        <p v-if="matrixEditKeys.length > 1">此单元格合并展示 {{ matrixEditKeys.length }} 条相同物料记录，修改的字段会同步保存到这些记录。</p>
        <div v-if="!editIsNew" class="rule-grid"><div v-for="side in ['defined', 'current']" :key="side"><el-form-item :label="side === 'defined' ? '定义值支持状态' : '现状值支持状态'"><el-select placeholder="存在差异，请选择" @change="touchEdit(side + '_status')" v-model="editRule[side + '_status']" :disabled="side === 'defined' && !editIsModel"><el-option v-for="s in statuses" :key="s" :value="s" :label="probeStatusLabel(s)" /></el-select></el-form-item>
          <el-form-item label="排除应用"><el-select @change="touchEdit(side + '_excludes')" v-model="editRule[side + '_excludes']" :disabled="side === 'defined' && !editIsModel" multiple filterable allow-create default-first-option><el-option v-for="a in appOptions" :key="a" :value="a" :label="a" /></el-select></el-form-item><el-form-item label="招标应用"><el-select v-model="editRule[side + '_tender']" :disabled="side === 'defined' && !editIsModel" multiple filterable allow-create @change="touchEdit(side + '_tender')"><el-option v-for="a in appOptions" :key="a" :value="a" :label="a" /></el-select></el-form-item></div></div>
        <el-form-item v-if="!editIsNew" label="优先级"><el-select v-model="editRule.priority" @change="touchEdit('priority')" clearable @clear="editRule.priority = null"><el-option v-for="p in priorities" :key="p" :value="p" :label="p" /></el-select></el-form-item>
        <el-form-item v-if="!editIsNew" label="说明"><el-input v-model="editRule.notes" @input="touchEdit('notes')" type="textarea" :rows="3" /></el-form-item>
        <div v-if="editMixedFields.length" class="toolbar"><span>合并记录存在差异，仅同步明确修改的字段：</span><el-button v-for="field in editMixedFields.filter(f => !f.endsWith('_status') && (editIsModel || !f.startsWith('defined_')))" :key="field" size="small" @click="touchEdit(field)">{{ ({current_excludes:'现状排除应用',defined_excludes:'定义排除应用',current_tender:'现状招标应用',defined_tender:'定义招标应用',notes:'说明',priority:'优先级'})[field] }}：{{ editTouchedFields.includes(field) ? '已选择同步' : '同步当前选择' }}</el-button></div>
        <p v-if="editIsNew">全部功能定义将自动取自模板，现状保留待确认，可在矩阵中逐项录入。</p>
        <p v-else>{{ editModels.length ? '差异不会使主配置中不可用的探头或功能变为支持。' : '修改总集会保留各机型已经明确设置的差异。' }}</p>
      </el-form>
      <template #footer><el-button v-if="editIsModel" @click="restoreInheritance">恢复继承总集</el-button><el-button @click="closeEdit()">取消</el-button><el-button type="primary" @click="applyEdit">应用到待保存草稿</el-button></template>
    </el-dialog>
    <el-dialog v-model="publishVisible" title="发布探头配置" width="780px" :close-on-click-modal="!busy" :close-on-press-escape="!busy" :before-close="closePublish">
      <div class="toolbar"><el-input :disabled="busy" v-model="versionNumber" placeholder="业务版本号（留空按配置管理规则递增）" style="width:340px" /><el-button @click="preparePreview" :disabled="versionCheck.pending || !!versionCheck.error">重新核对发布预览</el-button></div>
      <el-input :disabled="busy" v-model="description" placeholder="发布说明" type="textarea" :rows="2" />
      <el-alert v-if="versionCheck.error" :title="versionCheck.error" type="error" :closable="false" />
      <template v-if="preview"><p>{{ previewSummary }}</p><p>将创建配置管理版本：{{ JSON.stringify(preview.version_numbers) }}</p>
        <el-select v-model="previewModel" style="width:280px" placeholder="核对机型"><el-option v-for="m in memberModels" :key="m.id" :value="m.id" :label="m.series + ' / ' + m.name" /></el-select>
        <ProbeDataTable :rows="previewResults" :columns="previewColumns" table-id="publish-preview" />
      </template>
      <template #footer><el-button :disabled="busy" @click="closePublish()">取消</el-button><el-button type="primary" :disabled="!preview || versionCheck.pending || !!versionCheck.error || busy" @click="publish">确认发布</el-button></template>
    </el-dialog>
    <el-dialog v-model="importVisible" title="Excel 导入差异预览" width="640px"><p>{{ JSON.stringify(imported?.diff) }}</p><p>导入只保存草稿，不直接修改已发布结果。共同总集及机型差异按工作表完整替换。</p><template #footer><el-button @click="importVisible = false">取消</el-button><el-button type="primary" @click="applyImport">核对并保存草稿</el-button></template></el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onActivated, onUnmounted, nextTick } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import SubseriesEditor from '../components/SubseriesEditor.vue'
import SubseriesCombinations from '../components/SubseriesCombinations.vue'
import ProbeDataTable from '../components/ProbeDataTable.vue'
import ProbeConfigurationMatrix from '../components/ProbeConfigurationMatrix.vue'
import { getSubseries, checkSubmissionVersion } from '../api/data'
import { useVersionPreflight } from '../utils/useVersionPreflight'
import { probeRuleKey, probeStatusLabel, applyProbeRule, removeProbeRule } from '../utils/probeWorkspace'
import * as api from '../api/probeWorkspace'
import { newProbeMaterialRows } from '../utils/probeMatrix'
const copy = value => JSON.parse(JSON.stringify(value))
const workspaces = ref([]), current = ref(null), document = ref(null), catalog = ref({ probes: [], variants: [], features: [], applications: {} }), shared = ref({ groups: [], combinations: [], catalog: [] })
const busy = ref(false), error = ref(''), saved = ref(''), results = ref([]), diff = ref({}), tab = ref('total'), search = ref(''), differencesOnly = ref(false), resultModel = ref(null)
const dirty = computed(() => document.value && JSON.stringify(document.value) !== saved.value)
const memberModels = computed(() => shared.value.catalog.filter(m => document.value?.scope.model_ids.includes(m.id)))
const scopeLabel = computed(() => [...document.value.scope.groups, ...document.value.scope.combinations].join(' + '))
const scopeEditor = ref(), createVisible = ref(false), createName = ref(''), selectedGroups = ref([]), selectedCombinations = ref([])
const selectionKey = computed(() => JSON.stringify([selectedGroups.value, selectedCombinations.value]))
const addCombination = selection => { selectedCombinations.value = [...new Set([...selectedCombinations.value, selection.name])] }
async function run(task) { if (busy.value) return; busy.value = true; error.value = ''; try { return await task() } catch (e) { error.value = e.response?.data?.detail || e.message; ElMessage.error(error.value) } finally { busy.value = false } }
async function loadShared() { shared.value = await getSubseries() }
async function refreshList() { workspaces.value = await api.listProbeWorkspaces() }
function assign(data) { current.value = data; document.value = copy(data.data); saved.value = JSON.stringify(data.data); document.value = copy(data.template_data || data.data); if (!document.value.scope.model_ids.includes(resultModel.value)) resultModel.value = document.value.scope.model_ids[0]; preview.value = null }
async function loadResults() { const data = await api.getProbeResults(current.value.id); results.value = data.results; diff.value = data.diff }
async function allowDiscardLocal() { if (!dirty.value) return true; try { await ElMessageBox.confirm('有未保存的编辑，确定放弃？', '未保存修改', { type: 'warning' }); return true } catch { return false } }
async function openWorkspace(id) { if (!await allowDiscardLocal()) return; await run(async () => { assign(await api.getProbeWorkspace(id)); await loadResults() }) }
async function create() { if (!await allowDiscardLocal()) return; await run(async () => { assign(await api.createProbeWorkspace({ name: createName.value, groups: selectedGroups.value, combinations: selectedCombinations.value })); createVisible.value = false; createName.value = ''; selectedGroups.value = []; selectedCombinations.value = []; await refreshList(); await loadResults() }) }
async function closeCreate(done) { if (createName.value || selectedGroups.value.length || selectedCombinations.value.length) { try { await ElMessageBox.confirm('确定放弃新总集的范围设置？', '未保存设置') } catch { return } } createVisible.value = false; createName.value = ''; selectedGroups.value = []; selectedCombinations.value = []; done?.() }
async function persist(refresh = false) { assign(await api.saveProbeDraft(current.value.id, { revision: current.value.revision, data: document.value, refresh_scope: refresh })); await refreshList(); await loadResults() }
async function save() { await run(async () => { await persist(); ElMessage.success('草稿已保存，尚未发布') }) }
async function discard() { try { await ElMessageBox.confirm('废弃整个总集的未发布草稿？已发布配置保持不变。', '废弃草稿', {type:'warning'}) } catch { return } await run(async () => { assign(await api.discardProbeDraft(current.value.id, current.value.revision)); await refreshList(); await loadResults() }) }
const scopeVisible = ref(false), scopeGroups = ref([]), scopeCombinations = ref([])
watch(scopeVisible, visible => { if (visible) { scopeGroups.value = [...document.value.scope.groups]; scopeCombinations.value = [...document.value.scope.combinations] } })
async function closeScope(done) { const changed = JSON.stringify([scopeGroups.value, scopeCombinations.value]) !== JSON.stringify([document.value.scope.groups, document.value.scope.combinations]); if (changed) { try { await ElMessageBox.confirm('放弃范围修改？', '未保存设置') } catch { return } } scopeVisible.value = false; done?.() }
async function applyScope() { await run(async () => { await loadShared(); const names = scopeGroups.value; const combinations = scopeCombinations.value; const groups = shared.value.groups.filter(g => names.includes(g.name)); const combo = shared.value.combinations.filter(g => combinations.includes(g.name)); const ids = new Set([...groups, ...combo].flatMap(g => g.model_ids)); const next = copy(document.value); next.scope.groups = [...names]; next.scope.combinations = [...combinations]; for (const mid of Object.keys(next.overrides)) if (!ids.has(Number(mid))) delete next.overrides[mid]; const data = await api.saveProbeDraft(current.value.id, { revision: current.value.revision, data: next, refresh_scope: true }); assign(data); scopeVisible.value = false; await refreshList(); await loadResults() }) }
async function reloadTemplateDefinitions() {
  if (!await allowDiscardLocal()) return
  await run(async () => { catalog.value = await api.getProbeCatalog(); assign(await api.getProbeWorkspace(current.value.id, true)); await loadResults() })
}
async function refreshScope() {
  if (!await allowDiscardLocal()) return
  await run(async () => {
    await loadShared()
    assign(await api.getProbeWorkspace(current.value.id))
    const scope = document.value.scope
    scopeGroups.value = [...scope.groups]
    scopeCombinations.value = [...scope.combinations]
    const selected = [...shared.value.groups.filter(g => scope.groups.includes(g.name)), ...shared.value.combinations.filter(g => scope.combinations.includes(g.name))]
    const ids = new Set(selected.flatMap(g => g.model_ids))
    for (const mid of Object.keys(document.value.overrides)) if (!ids.has(Number(mid))) delete document.value.overrides[mid]
    await persist(true)
  })
}
const priorities = ['标1', '标2', '标3', '新', '新(未优化)', '新(未发放)']
const editIsModel = ref(false), editOriginalRule = ref({}), matrixEditKeys = ref([]), editTouchedFields = ref([]), editMixedFields = ref([])
const statuses = ['supported', 'conditional', 'unsupported', 'pending'], editing = ref(false), editRule = ref({}), editKey = ref(''), editModels = ref([]), editIsNew = ref(false), newProbe = ref(''), editBaseline = ref('')
const probeOptions = computed(() => catalog.value.probes.flatMap(p => { const variants = catalog.value.variants.filter(v => v.probe_model_id === p.id); return (variants.length ? variants : [{ id: 0, ipn: '' }]).map(v => ({ key: `${p.id}:${v.id}`, label: `${p.name} ${v.ipn || ''}` })) }))
const appOptions = computed(() => [...new Set(Object.values(catalog.value.applications).flat())])
const editState = () => JSON.stringify([editRule.value, editModels.value, newProbe.value, editTouchedFields.value])
function touchEdit(field) { if (!editTouchedFields.value.includes(field)) editTouchedFields.value.push(field) }
function startEdit() { editTouchedFields.value = []; editMixedFields.value = []; editOriginalRule.value = copy(editRule.value); editing.value = true; editBaseline.value = editState() }
function newRow() { matrixEditKeys.value = []; editIsNew.value = true; editIsModel.value = false; editModels.value = []; newProbe.value = ''; editRule.value = { defined_status: 'pending', current_status: 'pending', defined_excludes: [], current_excludes: [], current_tender: [], defined_tender: [], notes: '', priority: null }; startEdit() }
function edit(row) { editIsNew.value = false; editIsModel.value = tab.value === 'models'; editKey.value = row.key; const common = document.value.rows.find(r => probeRuleKey(r) === row.key); editModels.value = tab.value === 'models' ? [row.model_id] : []; const rule = { ...common, ...(editModels.value.length ? document.value.overrides[row.model_id]?.[row.key] : {}) }; editRule.value = Object.fromEntries(['defined_status', 'current_status', 'defined_excludes', 'current_excludes', 'defined_tender', 'current_tender', 'notes', 'priority'].map(f => [f, copy(rule[f] ?? ((f.endsWith('excludes') || f.endsWith('tender')) ? [] : f === 'notes' ? '' : f === 'priority' ? null : 'pending'))])); startEdit() }
function editMatrixCell(cell) {
  if (tab.value === 'models' && (dirty.value || !cell.model_id)) { ElMessage.warning('请先保存草稿，再编辑机型差异'); return }
  matrixEditKeys.value = [...cell.keys]
  edit({ ...cell, key: cell.keys[0] })
  editMixedFields.value = Object.keys(editRule.value).filter(field => new Set(cell.records.map(row => JSON.stringify(row[field] ?? editRule.value[field]))).size > 1)
  for (const field of editMixedFields.value.filter(field => field.endsWith('_status'))) editRule.value[field] = null
  editOriginalRule.value = copy(editRule.value)
  editBaseline.value = editState()
}
async function removeMatrixProbe(row) {
  try { await ElMessageBox.confirm('从当前草稿总集中移除此探头物料的全部功能及机型差异？', '移除探头', {type:'warning'}) } catch { return }
  for (const cell of Object.values(row.cells)) for (const key of cell.keys) document.value = removeProbeRule(document.value, key)
}
async function closeEdit(done) { if (editState() !== editBaseline.value) { try { await ElMessageBox.confirm('放弃尚未应用的编辑？', '未保存修改') } catch { return } } editing.value = false; done?.() }
function applyEdit() { try { if (editIsNew.value) { if (!newProbe.value) throw new Error('请选择探头物料'); const rows = newProbeMaterialRows(newProbe.value, catalog.value); if (document.value.rows.some(r => r.probe_model_id === rows[0]?.probe_model_id && r.variant_id === rows[0]?.variant_id)) throw new Error('该探头物料已经存在'); document.value.rows.push(...rows) } else { if (tab.value === 'models' && !editModels.value.length) throw new Error('请至少选择一个目标机型'); const patch = Object.fromEntries(Object.entries(editRule.value).filter(([field, value]) => { if (value === null && field !== 'priority') return false; return editTouchedFields.value.includes(field) || JSON.stringify(value) !== JSON.stringify(editOriginalRule.value[field]) })); for (const key of (matrixEditKeys.value.length ? matrixEditKeys.value : [editKey.value])) document.value = applyProbeRule(document.value, key, patch, editModels.value) } editing.value = false } catch (e) { ElMessage.error(e.message) } }
async function restoreInheritance() {
  if (!editModels.value.length) { ElMessage.warning('请先选择目标机型'); return }
  try { await ElMessageBox.confirm('移除所选机型在此功能的特有差异，恢复继承共同总集？', '恢复继承') } catch { return }
  const next = copy(document.value)
  for (const mid of editModels.value) for (const key of matrixEditKeys.value) delete next.overrides[mid]?.[key]
  document.value = next
  editing.value = false
}
const modelMatrixResults = computed(() => results.value.filter(row => row.model_id === resultModel.value))
const diffLabel = computed(() => `相对已发布总集：新增 ${diff.value.added || 0}，修改 ${diff.value.modified || 0}，删除 ${diff.value.deleted || 0}；机型差异${diff.value.model_differences_changed ? '有变化' : '无变化'}${dirty.value ? '（先保存以更新统计）' : ''}`)
const tableContainer = ref(), tableToolbar = ref(), tableHeight = ref(400)
function measure() { if (tableContainer.value) tableHeight.value = Math.max(220, window.innerHeight - tableContainer.value.getBoundingClientRect().top - 70) }
watch([tab, current, error], async () => { await nextTick(); measure() })
const previewColumns = [['probe_name', '探头'], ['feature_name', '功能'], ['defined_status', '定义'], ['current_status', '现状'], ['current_reason', '依据']].map(([key, label]) => ({key, label, width:140, visible:true}))
const publishVisible = ref(false), versionNumber = ref(''), description = ref(''), preview = ref(null), previewModel = ref(null)
const versionCheck = useVersionPreflight(() => ({enabled:publishVisible.value, seriesIds:[...new Set(memberModels.value.map(m=>m.series_id))], versionNumber:versionNumber.value || undefined}), checkSubmissionVersion)
watch([versionNumber, description], () => { preview.value = null })
const previewResults = computed(() => (preview.value?.results || []).filter(r => r.model_id === previewModel.value))
const previewSummary = computed(() => `${preview.value.results.length} 条机型结果，${preview.value.results.filter(r => r.defined_status === 'pending' || r.current_status === 'pending').length} 条待确认。${JSON.stringify(preview.value.diff)}`)
function startPublish() { publishVisible.value = true; preview.value = null; previewModel.value = resultModel.value }
async function preparePreview() { await run(async () => { preview.value = await api.previewProbeRelease(current.value.id, {version_number:versionNumber.value || undefined, description:description.value}) }) }
function closePublish(done) { if (busy.value) return; publishVisible.value = false; preview.value = null; done?.() }
async function publish() { await run(async () => { await api.publishProbeRelease(current.value.id, {version_number:versionNumber.value || undefined, description:description.value, signature:preview.value.signature}); publishVisible.value = false; assign(await api.getProbeWorkspace(current.value.id)); await refreshList(); await loadResults(); ElMessage.success('已发布完整快照，并创建对应的配置管理版本') }) }
const fileInput = ref(), importVisible = ref(false), imported = ref(null)
async function importFile(event) { const file = event.target.files?.[0]; event.target.value = ''; if (!file) return; await run(async () => { imported.value = await api.previewProbeImport(current.value.id,file); importVisible.value = true }) }
async function applyImport() { await run(async () => { assign(await api.saveProbeDraft(current.value.id, {revision:imported.value.revision,data:imported.value.data})); importVisible.value = false; await refreshList(); await loadResults() }) }
async function download() { await run(async () => { const blob = await api.exportProbeWorkbook(current.value.id); const url = URL.createObjectURL(blob); const link = window.document.createElement('a'); link.href = url; link.download = `${current.value.name}.xlsx`; link.click(); URL.revokeObjectURL(url) }) }
function beforeUnload(event) { if (dirty.value || editing.value) { event.preventDefault(); event.returnValue = '' } }
async function leaveWorkspace() {
  if (busy.value || editing.value) return false
  const allowed = await allowDiscardLocal()
  if (allowed && dirty.value) document.value = JSON.parse(saved.value)
  return allowed
}
onBeforeRouteLeave(leaveWorkspace)
onMounted(async () => { window.addEventListener('resize',measure); window.addEventListener('beforeunload',beforeUnload); await run(async () => { await Promise.all([loadShared(),refreshList(),api.getProbeCatalog().then(c=>{catalog.value=c})]); if (workspaces.value.length) { assign(await api.getProbeWorkspace(workspaces.value[0].id)); await loadResults() } }); await nextTick(); measure() })
let firstActivation = true
onActivated(async () => {
  if (firstActivation) { firstActivation = false; return }
  if (busy.value || dirty.value || editing.value) return
  await run(async () => {
    await Promise.all([loadShared(), refreshList()])
    catalog.value = await api.getProbeCatalog()
    if (current.value) { assign(await api.getProbeWorkspace(current.value.id)); await loadResults() }
  })
})
onUnmounted(() => {window.removeEventListener('resize',measure);window.removeEventListener('beforeunload',beforeUnload)})
</script>
<style scoped>
.toolbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px}.toolbar .el-button+.el-button{margin-left:0}.scope-line{font-size:13px}.table-container{width:100%;overflow:hidden}.rule-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.rule-grid .el-select{width:100%}.changes{max-height:50vh;overflow:auto;font-size:12px}.probe-workspace :deep(.el-card__body){padding:12px}.probe-workspace p{font-size:13px;line-height:1.6;color:var(--el-text-color-secondary)}
</style>
