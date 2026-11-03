<template>
  <el-dialog v-model="visible" title="计算项补充资料人工核对" width="min(1100px, calc(100vw - 32px))" top="4vh" append-to-body destroy-on-close :before-close="requestClose" :show-close="!busy" :close-on-click-modal="!busy" :close-on-press-escape="!busy">
    <div v-loading="loading" class="enrichment-review" aria-label="计算项补充资料审核">
      <p class="review-identity"><strong>{{ detail?.item_id || row?.item_id }}</strong><span>批次 {{ detail?.batch_id || row?.batch_id }} · 当前状态 {{ loading ? '读取中' : reviewStatusLabel(detail?.enrichment?.status) }}</span></p>
      <el-alert type="info" :closable="false" title="参考公式与依赖说明来自公开资料，需人工核对；相关输入模式仅表示资料上下文，不代表设备已提供相应功能。" />
      <el-alert v-if="error" :title="error" type="error" :closable="false" class="review-alert" />
      <el-alert v-if="staleSource" type="warning" :closable="false" class="review-alert" title="原始资料已变化，当前候选不能用于审核。请等待候选资料更新后重新读取。" />
      <el-button v-if="conflict || staleSource" class="review-alert" :disabled="busy" @click="reloadLatest">重新读取最新资料</el-button>
      <template v-if="detail?.enrichment?.candidate">
        <div class="review-comparison">
          <section aria-label="原始导入字段与出处"><h3>原始导入字段与出处</h3><el-descriptions v-for="(original, index) in detail.raw_rows?.length ? detail.raw_rows : [row]" :key="index" :column="1" border size="small" class="original-fields"><el-descriptions-item v-for="field in originalFields(original)" :key="field.label" :label="field.label">{{ field.value }}</el-descriptions-item></el-descriptions></section>
          <section aria-label="本次待核对候选"><h3>本次待核对候选 · 修订 {{ detail.enrichment.candidate.revision }}</h3><ReadonlyPayload :payload="detail.enrichment.candidate.payload" /></section>
        </div>
        <details v-if="detail.enrichment.confirmed_payload" class="review-details"><summary>查看已确认内容{{ detail.enrichment.has_pending_update ? '（另有新候选待核对）' : '' }}</summary><ReadonlyPayload :payload="detail.enrichment.confirmed_payload" /></details>
        <el-form label-position="top" :disabled="reviewBlocked" class="review-form">
          <div class="review-grid">
            <el-form-item label="人工核对后的应用分类" required><el-select v-model="form.payload.categories" multiple aria-label="人工核对分类"><el-option v-for="value in REVIEW_CATEGORIES" :key="value" :label="reviewCategoryLabel(value)" :value="value" /></el-select></el-form-item>
            <el-form-item label="相关输入模式（待核对）"><el-select v-model="form.payload.modes" multiple aria-label="人工核对模式"><el-option v-for="value in REVIEW_MODES" :key="value" :label="value" :value="value" /></el-select></el-form-item>
          </div>
          <el-form-item label="参考公式与依赖说明"><el-input v-model="form.payload.formula_reference" type="textarea" :rows="3" aria-label="参考公式与依赖说明" /></el-form-item>
          <div class="section-heading"><h3>术语与候选关联</h3><el-button size="small" :disabled="busy" @click="addTerm">添加术语</el-button></div>
          <p class="review-hint">仅选择本批次已存在的测量或计算 ID；“分类上下文”不作为数值依赖，其他候选关联仍需逐项核对。搜索匹配项最多显示 80 个，已选项始终保留。</p>
          <section v-for="(term, index) in form.payload.input_terms" :key="index" class="review-card">
            <div class="term-heading"><el-input v-model="term.term" :aria-label="`输入术语 ${index + 1}`" placeholder="输入术语" /><el-button size="small" :disabled="busy" @click="form.payload.input_terms.splice(index, 1)">移除术语</el-button></div>
            <el-select v-model="term.relation_kind" :aria-label="`关联类型 ${index + 1}`"><el-option v-for="option in REVIEW_RELATIONS" :key="option.value" :value="option.value" :label="option.label" /></el-select>
            <p v-if="term.relation_kind === 'context'" class="review-hint">此处 ID 仅用于说明分类或检查上下文，不作为数值依赖。</p>
            <el-select :model-value="term.possible_dependencies.map(dependencyKey)" multiple filterable remote :remote-method="query => dependencyQueries[index] = query" :reserve-keyword="false" :aria-label="`候选依赖 ${index + 1}`" :placeholder="term.relation_kind === 'context' ? '搜索上下文 ID' : '搜索本批次精确 ID'" @update:model-value="keys => updateDependencies(term, keys)">
              <el-option v-for="option in termOptions(term, index)" :key="option.key" :value="option.key" :label="option.label" />
            </el-select>
            <el-input v-model="term.uncertainty" type="textarea" :rows="1" :aria-label="`依赖不确定性 ${index + 1}`" placeholder="依赖关联的不确定性" />
          </section>
          <div class="section-heading"><h3>公开来源</h3><el-button size="small" :disabled="busy" @click="addSource">添加来源</el-button></div>
          <section v-for="(source, index) in form.payload.sources" :key="index" class="review-card">
            <div class="source-heading"><strong>来源 {{ index + 1 }}</strong><a v-if="safeSourceUrl(source.url)" :href="safeSourceUrl(source.url)" target="_blank" rel="noopener noreferrer">打开来源</a><el-button size="small" :disabled="busy" @click="form.payload.sources.splice(index, 1)">移除来源</el-button></div>
            <div class="review-grid"><el-form-item label="来源标题"><el-input v-model="source.title" :aria-label="`来源标题 ${index + 1}`" /></el-form-item><el-form-item label="HTTP(S)链接"><el-input v-model="source.url" :aria-label="`来源链接 ${index + 1}`" /></el-form-item></div>
            <div class="review-grid"><el-form-item label="发布机构（可选）"><el-input v-model="source.publisher" :aria-label="`发布机构 ${index + 1}`" /></el-form-item><el-form-item label="页码或章节定位"><el-input v-model="source.locator" :aria-label="`来源定位 ${index + 1}`" /></el-form-item></div>
            <el-form-item label="支持哪些建议（每行一条）"><el-input :model-value="(source.supports || []).join('\n')" type="textarea" :rows="2" :aria-label="`来源支持内容 ${index + 1}`" @update:model-value="value => source.supports = lines(value)" /></el-form-item>
          </section>
          <el-form-item label="保留的不确定性（每行一条）"><el-input :model-value="form.payload.uncertainties.join('\n')" type="textarea" :rows="3" aria-label="保留的不确定性" @update:model-value="value => form.payload.uncertainties = lines(value)" /></el-form-item>
          <div class="review-grid">
            <el-form-item label="研究状态"><el-select v-model="form.payload.research_status" aria-label="研究状态"><el-option label="候选建议（仍需人工确认）" value="proposed" /><el-option label="待补依据（不可直接确认）" value="unresolved" /></el-select></el-form-item>
            <el-form-item label="本次核对人" required><el-input v-model="form.confirmed_by" maxlength="100" placeholder="填写实际姓名或工作标识" aria-label="本次核对人" /></el-form-item>
          </div>
          <el-form-item label="核对说明（拒绝、暂缓、撤销或补齐待补依据项时必填）"><el-input v-model="form.note" type="textarea" :rows="2" maxlength="4000" placeholder="记录修改原因、核对依据或后续待办" aria-label="核对说明" /></el-form-item>
        </el-form>
        <details class="review-details"><summary>只读审核历史（{{ detail.history?.length || 0 }}）</summary><section v-for="(entry, index) in detail.history || []" :key="entry.id || index" class="review-card"><strong>{{ actionLabel(entry.action) }}</strong> · {{ entry.actor || entry.confirmed_by }} · {{ entry.created_at || entry.reviewed_at }}<p>{{ entry.note }}</p><details v-if="entry.confirmed_payload"><summary>查看当时确认内容</summary><ReadonlyPayload :payload="entry.confirmed_payload" /></details></section><p v-if="!detail.history?.length">尚无审核记录。</p></details>
      </template>
      <p v-else-if="!loading && !error">当前项目没有可核对的候选补充资料。</p>
    </div>
    <template #footer><div class="review-actions"><el-button :disabled="busy" @click="requestClose()">关闭</el-button><template v-if="detail?.enrichment?.candidate"><el-button :disabled="reviewBlocked" @click="save('defer')">暂缓</el-button><el-button :disabled="reviewBlocked" type="danger" plain @click="save('reject')">拒绝</el-button><el-button v-if="detail.enrichment.confirmed_payload" :disabled="reviewBlocked" type="warning" plain @click="save('revoke')">撤销确认</el-button><el-button type="primary" :disabled="reviewBlocked" :loading="saving" @click="save('confirm')">确认人工核对结果</el-button></template></div></template>
  </el-dialog>
</template>

<script setup>
import { computed, h, onBeforeUnmount, reactive, ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { ElMessage, ElMessageBox, ElTag } from 'element-plus'
import api from '../api/index'
import { REVIEW_CATEGORIES, REVIEW_MODES, REVIEW_RELATIONS, reviewCategoryLabel, reviewStatusLabel, dependencyKey, parseDependencyKey, dependencyOptions, visibleDependencyOptions, safeSourceUrl, cloneReviewPayload, reviewSnapshot, validateReviewForm, buildReviewRequest } from '../utils/measurementEnrichmentReview'

const props = defineProps({ records: { type: Array, default: () => [] } })
const emit = defineEmits(['saved'])
const visible = ref(false), loading = ref(false), saving = ref(false), row = ref(null), detail = ref(null), error = ref(''), conflict = ref(false), baseline = ref(''), lastReviewer = ref('')
const form = reactive({ payload: {}, confirmed_by: '', note: '' })
const dependencyQueries = reactive({})
const busy = computed(() => loading.value || saving.value)
const staleSource = computed(() => detail.value?.enrichment?.status === 'stale_source')
const reviewBlocked = computed(() => busy.value || staleSource.value)
const dirty = computed(() => reviewSnapshot(form) !== baseline.value)
const allDependencies = computed(() => dependencyOptions(props.records, detail.value?.batch_id))
let sessionId = 0, closePrompt = false
const lines = value => value.split('\n').map(line => line.trim()).filter(Boolean)
const actionLabel = action => ({ confirm: '确认', reject: '拒绝', defer: '暂缓', revoke: '撤销确认' })[action] || action

const readableValue = value => Array.isArray(value) ? value.length ? value.join('、') : '（空白）' : value === '' || value == null ? '（空白）' : String(value)
function originalFields(original) {
  return [
    ['项目 ID', original?.item_id], ['中文名称', original?.cn_name], ['英文名称', original?.en_name],
    ['模式', original?.mode], ['原始分类', original?.categories?.map(reviewCategoryLabel)], ['分组', original?.group],
    ['单位', original?.unit], ['启用状态', { enabled: '已启用', disabled: '未启用', unknown: '待核对' }[original?.enabled] || original?.enabled_raw],
    ['来源文件', original?.source_file], ['来源工作表', original?.source_sheet], ['来源行号', original?.source_row]
  ].map(([label, value]) => ({ label, value: readableValue(value) }))
}
function ReadonlyPayload({ payload }) {
  const value = payload || {}
  const field = (label, content) => h('div', { class: 'summary-field' }, [h('strong', `${label}：`), content])
  const tags = (values, label) => (values || []).length ? h('span', { class: 'summary-tags' }, values.map(entry => h(ElTag, { size: 'small', type: 'info', key: entry }, () => label(entry)))) : '未提出建议'
  const inputs = (value.input_terms || []).map(term => {
    const relation = term.relation_kind || 'input'
    const label = REVIEW_RELATIONS.find(option => option.value === relation)?.label || '待核对关联'
    const names = (term.possible_dependencies || []).map(dependency => `${dependency.kind === 'calculation' ? '计算' : '测量'} ${dependency.item_id}`).join('、') || '尚未关联具体项目'
    return h('li', [h('strong', `${term.term} · ${label}`), h('p', names), relation === 'context' ? h('p', { class: 'review-hint' }, '仅作分类上下文，不作为数值依赖。') : null, term.uncertainty ? h('p', { class: 'review-hint' }, term.uncertainty) : null])
  })
  const sources = (value.sources || []).map(source => {
    const url = safeSourceUrl(source.url)
    return h('li', [url ? h('a', { href: url, target: '_blank', rel: 'noopener noreferrer' }, source.title || '查看来源') : h('span', source.title || '来源信息待补'), h('p', [source.publisher, source.locator].filter(Boolean).join(' · ')), ...(source.supports || []).map(support => h('p', support))])
  })
  return h('div', { class: 'readonly-summary' }, [
    field('应用分类', tags(value.categories, reviewCategoryLabel)), field('相关输入模式（待核对）', tags(value.modes, mode => mode)),
    field('研究状态', reviewStatusLabel(value.research_status)), field('参考公式与依赖说明', h('p', { class: 'summary-formula' }, value.formula_reference || '尚无参考说明')),
    field('术语与候选关联', inputs.length ? h('ul', inputs) : '尚无术语关联'),
    field('保留的不确定性', value.uncertainties?.length ? h('ul', value.uncertainties.map(uncertainty => h('li', uncertainty))) : '未另行登记，仍需人工核对'),
    field('公开来源', sources.length ? h('ul', sources) : '尚未补充来源')
  ])
}
ReadonlyPayload.props = { payload: { type: Object, default: () => ({}) } }

function termOptions(term, index) {
  const selected = term.possible_dependencies.map(dependencyKey)
  const options = [...allDependencies.value]
  const known = new Set(options.map(option => option.key))
  for (const dependency of term.possible_dependencies) {
    const key = dependencyKey(dependency)
    if (!known.has(key)) {
      known.add(key)
      options.push({ key, label: `${dependency.kind} · ${dependency.item_id}（本批次未找到，需核对）` })
    }
  }
  return visibleDependencyOptions(options, dependencyQueries[index] || '', selected)
}
function updateDependencies(term, keys) { term.possible_dependencies = keys.map(parseDependencyKey).filter(Boolean) }
function addTerm() { form.payload.input_terms.push({ term: '', relation_kind: 'unresolved', possible_dependencies: [], uncertainty: '' }) }
function addSource() { form.payload.sources.push({ url: '', title: '', publisher: '', locator: '', supports: [] }) }

async function discardAllowed() {
  if (busy.value || closePrompt) return false
  if (!dirty.value) return true
  const session = sessionId
  closePrompt = true
  try {
    await ElMessageBox.confirm('核对内容尚未保存，是否放弃本次修改？', '未保存的人工核对', { confirmButtonText: '放弃修改', cancelButtonText: '继续核对', type: 'warning' })
    return session === sessionId && !busy.value
  } catch { return false }
  finally { closePrompt = false }
}
async function requestClose(done) {
  const session = sessionId
  if (!await discardAllowed() || session !== sessionId || busy.value) return false
  sessionId += 1
  visible.value = false
  if (typeof done === 'function') done()
  return true
}
async function loadDetail(candidateId) {
  const session = ++sessionId
  loading.value = true
  error.value = ''
  try {
    const result = await api.get(`/measurements/enrichment/${encodeURIComponent(candidateId)}`)
    if (session !== sessionId) return
    detail.value = result
    form.payload = cloneReviewPayload(result)
    form.note = ''
    Object.keys(dependencyQueries).forEach(key => delete dependencyQueries[key])
    baseline.value = reviewSnapshot(form)
    conflict.value = false
  } catch (failure) {
    if (session === sessionId) error.value = errorText(failure, '读取失败，请稍后重试')
  } finally { if (session === sessionId) loading.value = false }
}
async function open(value) {
  if (busy.value || closePrompt) return false
  if (visible.value && !await discardAllowed()) return false
  row.value = JSON.parse(JSON.stringify(value))
  detail.value = null
  form.payload = {}
  form.note = ''
  form.confirmed_by = lastReviewer.value
  baseline.value = reviewSnapshot(form)
  conflict.value = false
  visible.value = true
  const id = value?.enrichment?.candidate?.id
  if (id == null) { error.value = '当前行没有可核对的候选资料'; return false }
  await loadDetail(id)
  return true
}
async function reloadLatest() {
  const session = sessionId
  if (!await discardAllowed() || session !== sessionId || busy.value) return
  const id = detail.value?.enrichment?.candidate?.id || row.value?.enrichment?.candidate?.id
  if (id != null) await loadDetail(id)
}
function errorText(failure, fallback) {
  const message = failure?.response?.data?.detail
  return typeof message === 'string' ? message : fallback
}
async function save(action) {
  if (reviewBlocked.value || !detail.value?.enrichment?.candidate) return
  const invalid = validateReviewForm(form, action, detail.value)
  if (invalid) { error.value = invalid; return }
  const session = sessionId
  const current = detail.value
  const request = buildReviewRequest(current, form, action)
  saving.value = true
  error.value = ''
  try {
    const result = await api.post(`/measurements/enrichment/${encodeURIComponent(current.enrichment.candidate.id)}/review`, request)
    if (session !== sessionId) return
    lastReviewer.value = request.confirmed_by
    baseline.value = reviewSnapshot(form)
    visible.value = false
    sessionId += 1
    saving.value = false
    emit('saved', result)
    ElMessage.success(`已保存${actionLabel(action)}记录`)
  } catch (failure) {
    if (session !== sessionId) return
    conflict.value = failure?.response?.status === 409
    error.value = conflict.value ? '资料或审核记录已变化，输入已保留。请先复制需要保留的修改，再重新读取最新资料核对。' : errorText(failure, '保存失败，输入已保留，请重试')
  } finally { if (session === sessionId) saving.value = false }
}
onBeforeRouteLeave(async () => !visible.value || await requestClose())
onBeforeUnmount(() => { sessionId += 1 })
defineExpose({ open })
</script>

<style scoped>
.enrichment-review { min-height: 120px; max-height: calc(90vh - 165px); overflow: auto; padding-right: 6px; color: #334155; }
.review-identity, .section-heading, .term-heading, .source-heading, .review-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.review-identity { margin-top: 0; }
.review-identity span, .review-hint { font-size: 12px; color: #64748b; }
.review-alert, .review-details { margin-top: 10px; }
.review-comparison, .review-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.review-comparison { margin: 12px 0; }
.review-comparison section { min-width: 0; }
h3 { font-size: 14px; margin: 10px 0; }
.summary-formula { white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; line-height: 1.5; max-height: 200px; overflow: auto; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 10px; }
.review-form { margin-top: 12px; }
.review-card { border: 1px solid #e2e8f0; border-radius: 6px; padding: 10px; margin: 8px 0; }
.review-card .el-select, .review-card > .el-textarea { width: 100%; margin-top: 8px; }
.term-heading .el-input { flex: 1 1 240px; }
.section-heading h3 { margin-right: auto; }
.source-heading { margin-bottom: 8px; }
.source-heading .el-button { margin-left: auto; }
.review-actions { justify-content: flex-end; }
.review-actions .el-button { margin-left: 0; }
.review-form :deep(.el-form-item) { margin-bottom: 12px; }
.review-form :deep(.el-select), .review-form :deep(.el-input) { min-height: 32px; width: 100%; }
.review-form :deep(.el-input__wrapper), .review-form :deep(.el-select__wrapper) { min-height: 32px; box-sizing: border-box; }
.review-card a, .readonly-summary :deep(a) { color: #2563eb; }
.original-fields { margin-bottom: 10px; overflow-wrap: anywhere; }
.readonly-summary { overflow-wrap: anywhere; font-size: 13px; line-height: 1.6; }
.readonly-summary :deep(.summary-field) { margin-bottom: 8px; }
.readonly-summary :deep(.summary-tags) { display: inline-flex; gap: 5px; flex-wrap: wrap; }
.readonly-summary :deep(p) { margin: 4px 0; white-space: pre-wrap; }
.readonly-summary :deep(ul) { padding-left: 20px; margin: 5px 0; }
.readonly-summary :deep(li) { margin-bottom: 6px; }
summary { cursor: pointer; }
@media (max-width: 700px) { .review-comparison, .review-grid { grid-template-columns: 1fr; } }
</style>
