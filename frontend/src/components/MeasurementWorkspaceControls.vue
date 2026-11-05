<template>
  <div class="workspace-controls">
    <div class="workspace-selection">
    <span class="workspace-caption">测量库版本</span>
    <el-select :model-value="snapshot?.id || 0" aria-label="测量库版本" size="small" class="workspace-version" :disabled="locked" @change="selectVersion">
      <el-option :value="0" :label="`当前工作区 · ${latestVersion}${workspace.has_draft ? ' · 有草稿' : ''}`" />
      <el-option v-for="version in workspace.versions" :key="version.id" :value="version.id" :label="`${version.version_number} · ${version.created_at || ''}`" />
    </el-select>
    <el-tag v-if="snapshot" size="small" type="info">历史快照 · 只读</el-tag>
    </div>
    <div class="workspace-action-buttons">
    <el-dropdown trigger="click" :disabled="locked" @command="manage"><el-button size="small" :disabled="locked">管理 ▾</el-button><template #dropdown><el-dropdown-menu><el-dropdown-item command="batches">来源批次</el-dropdown-item><template v-if="!snapshot"><el-dropdown-item command="new">新增项目 / 关系</el-dropdown-item><el-dropdown-item command="applications">应用字典</el-dropdown-item><el-dropdown-item command="modes">模式字典</el-dropdown-item><el-dropdown-item command="sync">同步核对资料</el-dropdown-item></template></el-dropdown-menu></template></el-dropdown>
    <template v-if="!snapshot">
      <el-button size="small" :type="workspace.has_draft ? 'warning' : 'default'" :disabled="locked" @click="openDialog('drafts')">草稿 ({{ workspace.changes?.length || 0 }})</el-button>
      <el-button size="small" type="primary" :disabled="locked || !workspace.has_draft || syncPending" @click="openDialog('publish')">发布版本</el-button>
    </template>
    <el-button size="small" :disabled="locked" @click="openDialog('history')">版本历史 / 对比</el-button>
    </div>
    <span v-if="snapshot?.description" class="workspace-note">{{ snapshot.description }}</span>
  </div>
  <el-dialog :model-value="!!dialog" :title="dialogTitle" width="min(1080px, calc(100vw - 32px))" top="5vh" append-to-body destroy-on-close :before-close="requestClose" :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy">
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="workspace-alert" />
    <template v-if="['rename', 'assign', 'new'].includes(dialog)">
      <el-alert v-if="dialog === 'rename'" :title="`修改将应用到全库所有相同类型与 Id 的 ${affectedCount} 条记录，包含当前筛选以外的记录；各关系的应用与模式保持独立。`" type="warning" :closable="false" show-icon class="workspace-alert" />
      <el-alert v-if="dialog === 'assign'" title="仅修改当前这一条来源关系的应用与模式，不推断其他关系；人工关联不会自动完成资料核对。" type="info" :closable="false" class="workspace-alert" />
      <el-form label-width="120px" size="small" :disabled="busy" @submit.prevent>
        <template v-if="dialog === 'new'"><el-form-item label="记录类型"><el-select v-model="form.kind" aria-label="新增记录类型"><el-option value="measurement" label="测量项" /><el-option value="calculation" label="计算项" /></el-select></el-form-item><el-form-item label="Id" required><el-input v-model="form.item_id" aria-label="新增 Id" maxlength="255" /></el-form-item></template>
        <p v-else class="identity-line">{{ kindLabel(target.kind) }} · {{ target.item_id }} · {{ target.source_sheet ? `${target.source_sheet} 第 ${target.source_row} 行` : '手工新增关系' }}</p>
        <template v-if="dialog !== 'assign'"><el-form-item label="中文 UI 名称"><el-input v-model="form.cn_name" aria-label="中文 UI 名称" maxlength="1000" :disabled="duplicateIdentity && form.allow_existing_id" /></el-form-item><el-form-item label="英文 Description"><el-input v-model="form.description" aria-label="英文 Description" maxlength="4000" :disabled="duplicateIdentity && form.allow_existing_id" /></el-form-item><p class="workspace-hint">英文 UI 使用 Description；留空时显示 Id。</p></template>
        <template v-if="dialog !== 'rename'"><el-form-item label="应用"><el-select v-model="form.categories" multiple filterable aria-label="编辑应用"><el-option v-for="item in workspace.data.applications" :key="item.code" :value="item.code" :label="`${item.name} (${item.code})`" /></el-select></el-form-item><el-form-item label="关联模式"><el-select v-model="form.modes" multiple filterable aria-label="编辑关联模式"><el-option v-for="item in workspace.data.modes" :key="item.code" :value="item.code" :label="`${item.name} (${item.code})`" /></el-select></el-form-item></template>
        <template v-if="dialog === 'new'"><el-form-item label="计算分组"><el-input v-model="form.group" aria-label="新增计算分组" /></el-form-item><el-form-item label="单位"><el-input v-model="form.unit" aria-label="新增单位" /></el-form-item><el-form-item label="原始启用值"><el-input v-model="form.enabled_raw" aria-label="新增启用值" /></el-form-item><el-form-item v-if="duplicateIdentity" label="同 Id 关系"><el-checkbox v-model="form.allow_existing_id" aria-label="允许同 Id 新关系">明确新增同类型、同 Id 的独立关系（沿用现有名称）</el-checkbox></el-form-item><el-alert v-if="duplicateIdentity" type="warning" :closable="false" title="该类型与 Id 已存在。需明确勾选新增关系；现有名称将自动沿用，不合并来源行。" /></template>
      </el-form>
    </template>
    <template v-if="dialog === 'batches'">
      <p class="workspace-hint">来源批次来自导入的原始表格；每个批次分别维护测量库草稿和版本。</p>
      <el-form label-width="90px" size="small" @submit.prevent><el-form-item label="来源批次"><el-select v-model="selectedBatch" aria-label="来源批次" :disabled="syncPending" class="batch-select"><el-option v-for="batch in batches" :key="batch.id" :value="batch.id" :label="`${batch.version} · ${batch.source_file} · #${batch.id}`" /></el-select></el-form-item></el-form>
      <el-alert v-if="syncPending" type="warning" :closable="false" title="请先完成核对资料同步，再切换来源批次。" />
    </template>
    <template v-if="dialog === 'dictionary'">
      <p class="workspace-hint">代码为稳定标识，已有代码不可修改；显示名称可编辑。拖动排序手柄调整显示顺序，操作立即保存到草稿；聚焦手柄后也可使用 Alt + ↑ / ↓。Common 始终表示常规分类，改名不会改变语义。</p>
      <div @dragover="dictionaryDragOver" @drop="dropDictionary">
        <ProbeDataTable :rows="workspace.data[dimension]" :columns="dictionaryColumns" :table-id="`measurement-dictionary-${dimension}`" :actions-width="120"><template #actions="{ row }"><span class="dictionary-drag" :class="{ 'is-drop-target': dragTarget === row.code }" :data-dictionary-code="row.code" :draggable="!busy && !syncPending" tabindex="0" :aria-label="`拖动排序 ${row.name}`" title="拖动调整顺序；也可按 Alt + ↑ / ↓" @dragstart="startDictionaryDrag($event, row.code)" @dragend="clearDictionaryDrag" @keydown.alt.up.prevent="moveDictionaryByKeyboard(row.code, -1)" @keydown.alt.down.prevent="moveDictionaryByKeyboard(row.code, 1)">⠿</span><el-button size="small" link :disabled="busy" @click="editDictionary(row)">编辑名称</el-button></template></ProbeDataTable>
      </div>
      <el-form inline size="small" :disabled="busy" class="dictionary-form" @submit.prevent><el-form-item label="代码"><el-input v-model="form.code" aria-label="字典代码" :disabled="dictionaryExisting" /></el-form-item><el-form-item label="显示名称"><el-input v-model="form.name" aria-label="字典显示名称" /></el-form-item><el-button size="small" :disabled="busy" @click="newDictionary">新增代码</el-button></el-form>
    </template>
    <template v-if="dialog === 'drafts'">
      <p class="workspace-hint">以下为整个测量库的草稿变更，包含当前搜索、筛选和分页以外的项目。撤销恢复发布基线中的原始值。</p>
      <div class="draft-filters"><el-tag v-for="option in draftOptions" :key="option.value" :type="getDraftTagType(option.value)" effect="plain" tabindex="0" role="button" @click="toggleDraftFilter(option.value)" @keydown.enter.prevent="toggleDraftFilter(option.value)" @keydown.space.prevent="toggleDraftFilter(option.value)">{{ option.label }}</el-tag></div>
      <MeasurementWorkspaceChanges :changes="filteredChanges" :before-document="workspace.published_data" :after-document="workspace.data" table-id="measurement-workspace-drafts" undo :busy="busy" @undo="undo" />
    </template>
    <template v-if="dialog === 'publish'">
      <p class="workspace-hint">预览完整草稿后才能发布。发布保存不可变快照，并清空草稿；后续修改进入下一份草稿。</p>
      <el-form inline size="small" :disabled="busy" @submit.prevent><el-form-item label="新版本号" required><el-input v-model="form.version_number" aria-label="发布版本号" maxlength="100" /></el-form-item><el-form-item label="版本说明"><el-input v-model="form.description" aria-label="发布版本说明" maxlength="4000" class="version-description" /></el-form-item><el-button size="small" :disabled="busy || !form.version_number.trim() || syncPending" @click="previewPublish">生成发布预览</el-button></el-form>
      <template v-if="preview"><el-alert :title="`待发布 ${preview.version_number} · ${preview.change_count} 项全库变更 · 修订 ${preview.revision}`" type="warning" :closable="false" class="workspace-alert" /><MeasurementWorkspaceChanges :changes="preview.changes" :before-document="workspace.published_data" :after-document="workspace.data" table-id="measurement-publish-preview" /></template>
    </template>
    <template v-if="dialog === 'history'">
      <ProbeDataTable :rows="workspace.versions" :columns="versionColumns" table-id="measurement-version-history" :page-size="10" :actions-width="180"><template #actions="{ row }"><el-button size="small" link :disabled="busy" @click="selectVersion(row.id)">查看快照</el-button><el-button size="small" link type="warning" :disabled="busy || syncPending" @click="restore(row)">恢复为草稿</el-button></template></ProbeDataTable>
      <div class="compare-controls"><el-select v-model="fromVersion" :disabled="busy" aria-label="对比起始版本" size="small"><el-option v-for="version in workspace.versions" :key="version.id" :value="version.id" :label="version.version_number" /></el-select><span>→</span><el-select v-model="toVersion" :disabled="busy" aria-label="对比目标版本" size="small"><el-option v-for="version in workspace.versions" :key="version.id" :value="version.id" :label="version.version_number" /></el-select><el-button size="small" :disabled="busy || !fromVersion || !toVersion || fromVersion === toVersion" @click="compareVersions">对比版本</el-button></div>
      <MeasurementWorkspaceChanges v-if="comparison" :changes="comparison.changes" :before-document="comparisonDocuments.before" :after-document="comparisonDocuments.after" table-id="measurement-version-compare" />
    </template>
    <template #footer>
      <el-button size="small" :disabled="busy" @click="requestClose()">关闭</el-button>
      <el-button v-if="dialog === 'batches'" size="small" type="primary" :disabled="syncPending || !selectedBatch || selectedBatch === workspace.batch_id" @click="selectBatch">切换批次</el-button>
      <el-button v-if="['rename', 'assign', 'new', 'dictionary'].includes(dialog)" size="small" type="primary" :loading="busy" :disabled="!dirty || syncPending" @click="saveEdit">保存到草稿</el-button>
      <el-button v-if="dialog === 'drafts'" size="small" type="danger" plain :disabled="busy || !workspace.has_draft || syncPending" @click="discard">放弃全部草稿</el-button>
      <el-button v-if="dialog === 'publish'" size="small" type="primary" :loading="busy" :disabled="!preview?.signature || syncPending" @click="publish">确认发布 {{ preview?.version_number || '' }}</el-button>
    </template>
  </el-dialog>
</template>
<script setup>
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api/index'
import ProbeDataTable from './ProbeDataTable.vue'
import MeasurementWorkspaceChanges from './MeasurementWorkspaceChanges.vue'
import { identityRows, reorderDictionaryCodes } from '../utils/measurementWorkspace'
import { useDraftFilter } from '../utils/useDraftFilter'
const props = defineProps({ workspace: { type: Object, required: true }, snapshot: Object, batches: { type: Array, default: () => [] }, syncPending: Boolean })
const emit = defineEmits(['updated', 'snapshot', 'locked', 'sync-evidence', 'select-batch'])
const dialog = ref(''), busy = ref(false), error = ref(''), target = ref(null), dimension = ref('applications'), dictionaryExisting = ref(false)
const selectedBatch = ref(null)
const dragCode = ref(null), dragTarget = ref(null)
const form = reactive({}), baseline = ref(''), preview = ref(null), comparison = ref(null), fromVersion = ref(null), toVersion = ref(null)
const comparisonDocuments = reactive({ before: null, after: null })
let session = 0, prompting = false
const latestVersion = computed(() => props.workspace.versions?.find(version => version.id === props.workspace.latest_version_id)?.version_number || '')
const locked = computed(() => busy.value || !!dialog.value)
watch(locked, value => emit('locked', value), { immediate: true })
watch(() => props.workspace.id, () => { session++; busy.value = false; dialog.value = ''; preview.value = null; comparison.value = null })
watch(() => [props.workspace.revision, JSON.stringify(form)], () => { preview.value = null })
const dirty = computed(() => JSON.stringify(form) !== baseline.value)
const affectedCount = computed(() => target.value ? identityRows(props.workspace.data, target.value).length : 0)
const duplicateIdentity = computed(() => dialog.value === 'new' && identityRows(props.workspace.data, form).length > 0)
watch(() => [form.allow_existing_id, form.kind, form.item_id], () => {
  if (dialog.value !== 'new') return
  if (duplicateIdentity.value && form.allow_existing_id) { const row = identityRows(props.workspace.data, form)[0]; form.cn_name = row.cn_name; form.description = row.description }
  else form.allow_existing_id = false
})
const kindLabel = value => value === 'measurement' ? '测量项' : '计算项'
const dialogTitle = computed(() => ({ rename: '编辑同类型同 Id 的全库名称', assign: '编辑当前关系的应用与模式', new: '新增测量库项目 / 关系', dictionary: dimension.value === 'applications' ? '管理应用字典' : '管理模式字典', drafts: '测量库草稿', publish: '预览并发布测量库版本', history: '版本历史与对比', batches: '来源批次' })[dialog.value] || '')
const dictionaryColumns = [{ key: 'code', label: '稳定代码', width: 220, fixed: true, visible: true }, { key: 'name', label: '显示名称', width: 300, visible: true }]
const versionColumns = [{ key: 'version_number', label: '版本号', width: 180, fixed: true, visible: true }, { key: 'description', label: '版本说明', width: 400, visible: true }, { key: 'created_at', label: '发布时间', width: 190, visible: true }]
const { getDraftTagType, toggleDraftFilter, clearDraftFilter, filterByDraftMode } = useDraftFilter()
const draftOptions = [{ value: 'all', label: '全部草稿' }, { value: 'create', label: '新增' }, { value: 'update', label: '修改' }, { value: 'delete', label: '移除' }]
const filteredChanges = computed(() => filterByDraftMode(props.workspace.changes || [], change => new Set([change.change_type])))
function replaceForm(values) { for (const key of Object.keys(form)) delete form[key]; Object.assign(form, values); baseline.value = JSON.stringify(form) }
function openDialog(value) {
  if (locked.value) return
  session++; error.value = ''; preview.value = null; comparison.value = null; clearDraftFilter()
  replaceForm(value === 'publish' ? { version_number: '', description: '' } : {})
  fromVersion.value = props.workspace.versions?.at(-1)?.id || null; toVersion.value = props.workspace.latest_version_id
  dialog.value = value
}
function manage(value) {
  if (value === 'batches') { selectedBatch.value = props.workspace.batch_id; openDialog('batches'); return }
  if (value === 'sync') { emit('sync-evidence'); return }
  if (props.syncPending) return
  openDialog(value === 'new' ? 'new' : 'dictionary')
  if (value === 'new') replaceForm({ kind: 'measurement', item_id: '', cn_name: '', description: '', categories: [], modes: [], group: '', unit: '', enabled_raw: '', allow_existing_id: false })
  else { dimension.value = value; newDictionary() }
}
async function selectBatch() {
  if (props.syncPending || !selectedBatch.value || selectedBatch.value === props.workspace.batch_id) return
  const batch = selectedBatch.value
  if (await requestClose()) { await nextTick(); emit('select-batch', batch) }
}
function dictionaryCodeAtEvent(event) { return event.target.closest('tr')?.querySelector('[data-dictionary-code]')?.dataset.dictionaryCode }
function startDictionaryDrag(event, code) {
  if (busy.value || props.syncPending) { event.preventDefault(); return }
  dragCode.value = code
  event.dataTransfer.effectAllowed = 'move'
  event.dataTransfer.setData('text/plain', code)
}
function clearDictionaryDrag() { dragCode.value = null; dragTarget.value = null }
function dictionaryDragOver(event) {
  if (!dragCode.value) return
  const target = dictionaryCodeAtEvent(event)
  if (target) { event.preventDefault(); event.dataTransfer.dropEffect = 'move'; dragTarget.value = target }
}
function dropDictionary(event) {
  if (!dragCode.value) return
  const from = dragCode.value, to = dictionaryCodeAtEvent(event)
  clearDictionaryDrag()
  if (!to) return
  event.preventDefault()
  moveDictionary(from, to)
}
function moveDictionaryByKeyboard(code, direction) {
  const entries = props.workspace.data[dimension.value]
  const target = entries[entries.findIndex(item => item.code === code) + direction]
  if (target) moveDictionary(code, target.code)
}
async function moveDictionary(from, to) {
  if (busy.value || props.syncPending || from === to) return
  if (dirty.value && !await confirmAbandon()) return
  const entries = props.workspace.data[dimension.value]
  if (!entries.some(item => item.code === from) || !entries.some(item => item.code === to)) return
  const codes = reorderDictionaryCodes(entries, from, to)
  const result = await mutate('edit', { operation: 'reorder_dictionary', dimension: dimension.value, codes })
  if (result) { replaceForm({ code: '', name: '' }); dictionaryExisting.value = false; ElMessage.success('顺序已保存到测量库草稿') }
}
async function newDictionary() { if (dirty.value && !await confirmAbandon()) return; dictionaryExisting.value = false; replaceForm({ code: '', name: '' }) }
async function editDictionary(row) {
  if (dirty.value && !await confirmAbandon()) return
  dictionaryExisting.value = true; replaceForm({ code: row.code, name: row.name })
}
function openRename(row) { if (props.snapshot || props.syncPending || locked.value) return; openDialog('rename'); target.value = row; replaceForm({ cn_name: row.cn_name || '', description: row.description || '' }) }
function openAssignment(row) { if (props.snapshot || props.syncPending || locked.value) return; openDialog('assign'); target.value = row; replaceForm({ categories: [...row.categories], modes: [...row.mode] }) }
async function confirmAbandon() {
  if (busy.value || prompting) return false
  if (!dirty.value || !['rename', 'assign', 'new', 'dictionary', 'publish'].includes(dialog.value)) return true
  const current = session; prompting = true
  try { await ElMessageBox.confirm('本次输入尚未保存，确定放弃？', '未保存的测量库编辑', { type: 'warning', confirmButtonText: '放弃输入', cancelButtonText: '继续编辑' }); return current === session && !busy.value }
  catch { return false } finally { prompting = false }
}
async function requestClose(done) { if (!await confirmAbandon()) return false; session++; dialog.value = ''; preview.value = null; if (typeof done === 'function') done(); return true }
onBeforeRouteLeave(async () => !dialog.value || await requestClose())
async function run(task) {
  if (busy.value) return null
  const current = session, workspaceId = props.workspace.id
  busy.value = true; error.value = ''
  try { const result = await task(workspaceId); return current === session && workspaceId === props.workspace.id ? result : null }
  catch (failure) {
    if (current === session) {
      error.value = typeof failure.response?.data?.detail === 'string' ? failure.response.data.detail : '操作失败，请检查输入后重试'; preview.value = null
      if (failure.response?.status === 409) {
        try { const latest = await api.get(`/measurement-workspace/${workspaceId}`); if (current === session) emit('updated', latest) } catch { /* Keep the visible failure and unsaved input for retry. */ }
      }
    }
    return null
  } finally { if (current === session) busy.value = false }
}
async function mutate(endpoint, payload = {}) {
  if (props.syncPending) { error.value = '人工核对资料尚未同步，请先重试同步。'; return null }
  const result = await run(id => api.post(`/measurement-workspace/${id}/${endpoint}`, { revision: props.workspace.revision, ...payload }))
  if (result) emit('updated', result)
  return result
}
async function saveEdit() {
  let payload
  if (dialog.value === 'rename') payload = { operation: 'rename_item', record_key: target.value.record_key, cn_name: form.cn_name, description: form.description }
  else if (dialog.value === 'assign') payload = { operation: 'assign_item', record_key: target.value.record_key, categories: [...form.categories], modes: [...form.modes] }
  else if (dialog.value === 'new') {
    if (!form.item_id.trim()) { error.value = '请填写 Id'; return }
    if (duplicateIdentity.value && !form.allow_existing_id) { error.value = '同类型与 Id 已存在；请明确勾选新增关系。'; return }
    payload = { operation: 'add_item', ...form, item_id: form.item_id.trim() }
  } else {
    if (!form.code.trim() || !form.name.trim()) { error.value = '请填写代码与显示名称'; return }
    payload = { operation: 'upsert_dictionary', dimension: dimension.value, code: form.code.trim(), name: form.name.trim() }
  }
  const result = await mutate('edit', payload)
  if (result) { baseline.value = JSON.stringify(form); if (dialog.value === 'dictionary') newDictionary(); else await requestClose(); ElMessage.success('已保存到测量库草稿') }
}
async function undo(changeKey) { await mutate('undo', { change_key: changeKey }) }
async function discard() {
  try { await ElMessageBox.confirm('确定放弃整个测量库的全部草稿？所有未发布修改将恢复到当前发布版本。', '放弃全部草稿', { type: 'warning', confirmButtonText: '放弃全部', cancelButtonText: '保留草稿' }) } catch { return }
  await mutate('discard')
}
async function previewPublish() {
  const result = await run(id => api.post(`/measurement-workspace/${id}/preview`, { revision: props.workspace.revision, version_number: form.version_number.trim(), description: form.description }))
  if (result) preview.value = result
}
async function publish() {
  if (!preview.value?.signature || preview.value.revision !== props.workspace.revision) return
  const result = await mutate('publish', { version_number: form.version_number.trim(), description: form.description, signature: preview.value.signature })
  if (result) { baseline.value = JSON.stringify(form); await requestClose(); ElMessage.success('测量库版本已发布') }
}
async function selectVersion(value) {
  if (dialog.value && !await requestClose()) return
  if (!value) { emit('snapshot', null); return }
  const result = await run(id => api.get(`/measurement-workspace/${id}/versions/${value}`))
  if (result) emit('snapshot', result)
}
async function compareVersions() {
  const from = fromVersion.value, to = toVersion.value
  const result = await run(id => api.get(`/measurement-workspace/${id}/compare`, { params: { from_version_id: from, to_version_id: to } }))
  if (result) {
    const documents = await run(async id => Promise.all([
      api.get(`/measurement-workspace/${id}/versions/${from}`),
      api.get(`/measurement-workspace/${id}/versions/${to}`)
    ]))
    if (documents) { comparisonDocuments.before = documents[0].data; comparisonDocuments.after = documents[1].data; comparison.value = result }
  }
}
async function restore(version) {
  try { await ElMessageBox.confirm(`将 ${version.version_number} 恢复为新的草稿？当前未发布草稿将被替换，发布基线保持不变。`, '恢复历史为草稿', { type: 'warning', confirmButtonText: '恢复为草稿', cancelButtonText: '取消' }) } catch { return }
  const result = await mutate(`restore/${version.id}`)
  if (result) { emit('snapshot', null); ElMessage.success('历史版本已恢复到草稿，请检查后发布') }
}
onBeforeUnmount(() => { session++ })
defineExpose({ openRename, openAssignment, requestClose })
</script>
<style scoped>
.batch-select{width:min(700px,100%)}
.dictionary-drag{display:inline-block;cursor:grab;color:var(--el-text-color-secondary);padding:4px 8px;touch-action:none}.dictionary-drag:active{cursor:grabbing}.dictionary-drag.is-drop-target{color:var(--el-color-primary);box-shadow:inset 0 2px var(--el-color-primary)}.dictionary-drag[draggable="false"]{cursor:not-allowed;opacity:.5}
.workspace-controls,.compare-controls,.draft-filters,.workspace-selection,.workspace-action-buttons{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.workspace-controls{margin-top:8px;padding:8px 10px;border:1px solid var(--el-border-color-light);border-radius:8px;background:var(--el-fill-color-lighter);flex-shrink:0;justify-content:space-between}.workspace-selection{flex:0 1 360px;min-width:0;max-width:100%;flex-wrap:nowrap}.workspace-action-buttons{max-width:100%;min-width:0}.workspace-caption{white-space:nowrap}.workspace-controls .el-button+.el-button{margin-left:0}.workspace-version{flex:1;min-width:0;width:300px}.workspace-caption,.workspace-note,.workspace-hint,.identity-line{font-size:12px;color:var(--el-text-color-secondary);line-height:1.7}.workspace-alert{margin-bottom:12px}.workspace-hint{margin:8px 0}.identity-line{margin-left:120px}.el-form :deep(.el-select){min-width:260px}.dictionary-form{margin-top:16px}.compare-controls{margin-top:16px}.compare-controls .el-select{width:210px}.draft-filters{margin:10px 0}.draft-filters .el-tag{cursor:pointer}.version-description{width:340px;max-width:100%}
</style>
