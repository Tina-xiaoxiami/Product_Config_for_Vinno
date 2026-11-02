<template>
  <section class="history-workspace" data-testid="history-workspace">
    <div class="history-heading"><div><h3>历史Release Note追溯</h3><p>按明确适用的版本链检索新增、变化与限制，保留原文；未检索到不等于不支持。</p></div><el-button size="small" @click="openBindings">维护资料适用范围</el-button></div>
    <div class="history-controls">
      <el-input v-model="form.query" size="small" placeholder="主题，如：针增益调节" aria-label="历史追溯主题" @input="invalidateTrace" />
      <el-select v-model="form.market" size="small" placeholder="市场" aria-label="历史追溯市场" @change="form.product_model_id = null; invalidateTrace()"><el-option label="国内" value="domestic" /><el-option label="海外" value="overseas" /></el-select>
      <el-input v-model="form.country" size="small" maxlength="2" placeholder="国家代码，如CN" aria-label="历史追溯国家" @input="invalidateTrace" />
      <el-select v-model="form.product_model_id" size="small" filterable placeholder="完整机型" aria-label="历史追溯完整机型" @change="invalidateTrace"><el-option v-for="model in filteredModels(form.market)" :key="model.id" :label="`${model.name} · ${model.series_name}`" :value="model.id" /></el-select>
      <el-input v-model="form.software_version" size="small" placeholder="目标软件版本，如1.14.65" aria-label="历史追溯目标版本" @input="invalidateTrace" />
      <el-input v-model="form.release_line" size="small" placeholder="版本链（可选，留空分别展示）" aria-label="历史追溯版本链" @input="invalidateTrace" />
      <el-button size="small" :disabled="!currentScope" @click="useCurrentScope">使用问答查询范围</el-button><el-button size="small" type="primary" :loading="loading" @click="runTrace">追溯历史</el-button>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <KnowledgeHistoryTrace :trace="result" />
    <el-dialog v-model="bindingVisible" title="资料适用范围" width="min(940px, calc(100vw - 32px))" :before-close="closeBindings">
      <p>根据资料中的适用说明绑定机型与版本链；不同硬件平台分别命名。国家、市场不能仅按资料语言判断。</p>
      <el-alert v-if="bindingError" type="error" :title="bindingError" :closable="false" />
      <el-form label-position="top" :disabled="savingBinding" size="small">
        <div class="binding-grid">
          <el-form-item label="Release Note"><el-select v-model="bindingForm.document_ids" multiple filterable placeholder="选择资料与版本" aria-label="绑定发布资料"><el-option v-for="doc in documents" :key="doc.id" :value="doc.id" :label="`${doc.title} · ${doc.version || '版本待核实'}`" /></el-select></el-form-item>
          <el-form-item label="完整机型"><el-select v-model="bindingForm.product_model_ids" multiple filterable aria-label="绑定适用机型"><el-option v-for="model in filteredModels(bindingForm.market)" :key="model.id" :value="model.id" :label="`${model.name} · ${model.series_name}`" /></el-select></el-form-item>
          <el-form-item label="国家代码"><el-input v-model="bindingForm.country" maxlength="2" /></el-form-item>
          <el-form-item label="市场"><el-select v-model="bindingForm.market" @change="bindingForm.product_model_ids = []"><el-option label="国内" value="domestic" /><el-option label="海外" value="overseas" /></el-select></el-form-item>
          <el-form-item label="版本链名称"><el-input v-model="bindingForm.release_line" placeholder="按资料明确命名，如V6 VLucid+" /></el-form-item>
          <el-form-item label="本次核对人"><el-input v-model="bindingForm.confirmed_by" placeholder="实际核对人" /></el-form-item>
        </div>
        <el-form-item label="硬件平台及升级限制"><el-input v-model="bindingForm.conditions" type="textarea" :rows="2" placeholder="登记原文限制；有限制时不得留空以绕过判断" /></el-form-item>
        <el-form-item label="适用依据与位置"><el-input v-model="bindingForm.evidence_reference" type="textarea" :rows="2" placeholder="封面/适用范围章节、页码及核对说明" /></el-form-item>
      </el-form>
      <div class="binding-existing" v-loading="bindingsLoading"><strong>已登记的适用关系</strong><el-button size="small" link @click="retryBindings">刷新列表</el-button><ul><li v-for="row in bindings" :key="row.id"><span>{{ row.document_title || row.title || `资料${row.document_id}` }} · {{ row.model_name }} · {{ row.country }} · {{ row.release_line }}<small v-if="row.conditions">{{ row.conditions }}</small></span><el-button size="small" link type="danger" :disabled="savingBinding" @click="deactivateBinding(row)">停用</el-button></li></ul><p v-if="!bindings.length">暂无已确认关系。上方保存后可用于历史追溯。</p></div>
      <template #footer><el-button :disabled="savingBinding" @click="closeBindings()">关闭</el-button><el-button type="primary" :loading="savingBinding" @click="saveBindings">保存适用关系</el-button></template>
    </el-dialog>
  </section>
</template>
<script setup>
import { reactive, ref } from 'vue'
import { ElMessageBox, ElMessage } from 'element-plus'
import KnowledgeHistoryTrace from './KnowledgeHistoryTrace.vue'
import { historyTracePayload } from '../utils/knowledgeReleaseHistory'
import { traceReleaseHistory, getReleaseHistoryDocuments, getReleaseHistoryBindings, saveReleaseHistoryBindings, deactivateReleaseHistoryBinding } from '../api/knowledgeReleaseHistory'
const props = defineProps({ models: { type: Array, default: () => [] }, currentScope: { type: Object, default: null }, query: { type: String, default: '' } })
const form = reactive({ query: '', country: '', market: '', product_model_id: null, software_version: '', release_line: '' })
const result = ref(null), loading = ref(false), error = ref('')
let traceRequestId = 0
const invalidateTrace = () => { traceRequestId += 1; result.value = null; loading.value = false; error.value = '' }
const runTrace = async () => {
  const payload = historyTracePayload(form)
  if (!payload) { error.value = '请填写主题、国家、市场、完整机型和目标软件版本'; return }
  const requestId = ++traceRequestId
  const fingerprint = JSON.stringify(payload)
  result.value = null; error.value = ''; loading.value = true
  try { const data = await traceReleaseHistory(payload); if (requestId === traceRequestId && fingerprint === JSON.stringify(historyTracePayload(form))) result.value = data }
  catch (failure) { if (requestId === traceRequestId) error.value = failure?.response?.data?.detail || '历史追溯失败，请重试' }
  finally { if (requestId === traceRequestId) loading.value = false }
}
const useCurrentScope = () => { if (props.currentScope) { Object.assign(form, props.currentScope, { query: props.query || form.query }); invalidateTrace() } }
const filteredModels = market => props.models.filter(model => !market || model.series_name?.endsWith(market === 'domestic' ? '-China' : '-Oversea'))
const bindingVisible = ref(false), documents = ref([]), bindings = ref([]), bindingError = ref(''), bindingsLoading = ref(false), savingBinding = ref(false), bindingBaseline = ref('')
const emptyBinding = () => ({ document_ids: [], product_model_ids: [], country: '', market: '', release_line: '', conditions: '', evidence_reference: '', confirmed_by: '' })
const bindingForm = reactive(emptyBinding())
let bindingSession = 0
const refreshBindings = async session => { const data = await getReleaseHistoryBindings({}); if (session === bindingSession) bindings.value = data.items || [] }
const loadAllDocuments = async session => {
  const items = []
  let total = 0
  do {
    const page = await getReleaseHistoryDocuments({ skip: items.length, limit: 200 })
    if (session !== bindingSession) return
    const rows = page.items || []
    total = page.total || 0
    if (!rows.length && items.length < total) throw new Error('资料分页结果不完整，请重试')
    items.push(...rows)
  } while (items.length < total)
  documents.value = items
}
const openBindings = async () => {
  const session = ++bindingSession
  Object.assign(bindingForm, emptyBinding()); bindingBaseline.value = JSON.stringify(bindingForm)
  bindingVisible.value = true; bindingError.value = ''; documents.value = []; bindings.value = []; bindingsLoading.value = true
  try { await Promise.all([loadAllDocuments(session), refreshBindings(session)]) }
  catch (failure) { if (session === bindingSession) bindingError.value = failure?.response?.data?.detail || '资料与适用关系加载失败' }
  finally { if (session === bindingSession) bindingsLoading.value = false }
}
const retryBindings = async () => {
  const session = bindingSession; bindingsLoading.value = true; bindingError.value = ''
  try { await refreshBindings(session) }
  catch { if (session === bindingSession) bindingError.value = '列表刷新失败，请重试；已保存的数据不受影响' }
  finally { if (session === bindingSession) bindingsLoading.value = false }
}
const closeBindings = async done => {
  if (savingBinding.value) return
  if (JSON.stringify(bindingForm) !== bindingBaseline.value) {
    try { await ElMessageBox.confirm('资料适用范围尚未保存，是否放弃修改？', '未保存的修改', { confirmButtonText: '放弃修改', cancelButtonText: '继续编辑', type: 'warning' }) } catch { return }
  }
  bindingSession += 1; bindingVisible.value = false
  if (typeof done === 'function') done()
}
const saveBindings = async () => {
  if (savingBinding.value) return
  if (!bindingForm.document_ids.length || !bindingForm.product_model_ids.length || !bindingForm.country.trim() || !bindingForm.market || !bindingForm.release_line.trim() || !bindingForm.evidence_reference.trim() || !bindingForm.confirmed_by.trim()) { bindingError.value = '请补齐资料、机型、国家市场、版本链、适用依据和实际核对人'; return }
  savingBinding.value = true; bindingError.value = ''
  const session = bindingSession
  try {
    await saveReleaseHistoryBindings({ ...JSON.parse(JSON.stringify(bindingForm)), country: bindingForm.country.trim().toUpperCase() })
    if (session !== bindingSession) return
    bindingBaseline.value = JSON.stringify(bindingForm); invalidateTrace(); ElMessage.success('适用关系已保存，请重新追溯')
    try { await refreshBindings(session) }
    catch { if (session === bindingSession) bindingError.value = '适用关系已保存，列表刷新失败，请点击刷新列表重试' }
  } catch (failure) { if (session === bindingSession) bindingError.value = failure?.response?.data?.detail || '保存失败，输入已保留' }
  finally { if (session === bindingSession) savingBinding.value = false }
}
const deactivateBinding = async row => {
  if (savingBinding.value) return
  try { await ElMessageBox.confirm('停用后，该关系不再参与历史支持判断，记录仍保留。', '停用适用关系', { type: 'warning' }) } catch { return }
  const session = bindingSession; savingBinding.value = true; bindingError.value = ''
  try {
    await deactivateReleaseHistoryBinding(row.id, row.revision)
    if (session !== bindingSession) return
    invalidateTrace()
    try { await refreshBindings(session) }
    catch { if (session === bindingSession) bindingError.value = '适用关系已停用，列表刷新失败，请点击刷新列表重试' }
  }
  catch (failure) { if (session === bindingSession) bindingError.value = failure?.response?.data?.detail || '停用失败' }
  finally { if (session === bindingSession) savingBinding.value = false }
}
</script>
<style scoped>
.history-heading { display: flex; justify-content: space-between; align-items: center; gap: 12px; }.history-heading h3 { margin: 0; }.history-heading p { color: var(--el-text-color-secondary); }.history-controls { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; }.history-controls .el-input,.history-controls .el-select { width: 190px; }.binding-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 8px 14px; }.binding-grid .el-select { width: 100%; }.binding-existing { max-height: 230px; overflow: auto; }.binding-existing ul { padding: 0; list-style: none; }.binding-existing li { display: flex; justify-content: space-between; gap: 10px; border-top: 1px solid var(--el-border-color-lighter); padding: 8px 0; }.binding-existing small { display: block; color: var(--el-text-color-secondary); }@media(max-width:650px) { .binding-grid { grid-template-columns: 1fr; } }
</style>
