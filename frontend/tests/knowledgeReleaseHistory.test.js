import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { historyTracePayload, historyAssessmentLabel } from '../src/utils/knowledgeReleaseHistory.js'

const form = () => ({ query: '针增益调节', country: 'CN', market: 'domestic', product_model_id: 9, software_version: '1.14.65', release_line: '' })
test('history requests require complete scope and never invent a release branch', () => {
  assert.equal(historyTracePayload({ ...form(), product_model_id: null }), null)
  assert.equal(historyTracePayload({ ...form(), query: '' }), null)
  assert.deepEqual(historyTracePayload(form()), { query: '针增益调节', scope: { country: 'CN', market: 'domestic', product_model_id: 9, software_version: '1.14.65' } })
  assert.match(historyAssessmentLabel('no_record'), /未检索到/)
  assert.match(historyAssessmentLabel('scope_unconfirmed'), /范围/)
})

function traceActions() {
  const source = readFileSync(new URL('../src/components/KnowledgeReleaseHistoryWorkspace.vue', import.meta.url), 'utf8')
  const requests = []
  const context = { form: form(), result: { value: null }, loading: { value: false }, error: { value: '' }, historyTracePayload,
    coverageWorkspace: { invalidate() {} }, runCoverage: async () => false, onBeforeUnmount() {},
    traceReleaseHistory: () => new Promise(resolve => requests.push(resolve)) }
  const start = source.indexOf('const invalidateTrace =')
  const end = source.indexOf('\nconst useCurrentScope', start)
  const actions = new Function(...Object.keys(context), `let traceRequestId = 0; ${source.slice(start,end)}; return { runTrace, invalidateTrace }`)(...Object.values(context))
  return { ...actions, context, requests }
}

test('an earlier trace cannot overwrite a later model selection or its loading state', async () => {
  const state = traceActions()
  const first = state.runTrace()
  state.context.form.product_model_id = 20
  state.invalidateTrace()
  const second = state.runTrace()
  state.requests[0]({ assessment: 'evidence_found', events: [{ document_id: 1 }] })
  await first
  assert.equal(state.context.result.value, null)
  assert.equal(state.context.loading.value, true)
  state.requests[1]({ assessment: 'no_record', events: [] })
  await second
  assert.equal(state.context.result.value.assessment, 'no_record')
})

test('the existing hub exposes both operations and separates unresolved sources from applied evidence', () => {
  const hub = readFileSync(new URL('../src/views/KnowledgeHub.vue', import.meta.url), 'utf8')
  const trace = readFileSync(new URL('../src/components/KnowledgeHistoryTrace.vue', import.meta.url), 'utf8')
  assert.match(hub, /label="历史版本追溯"/)
  assert.match(hub, /label="参数型答案"/)
  assert.match(hub, /qaResult.history_trace/)
  assert.match(trace, /unresolved_documents/)
  assert.match(trace, /未确认适用范围/)
  assert.match(trace, /preview_url/)
})

test('hardware constraints remain visible even when separate from a keyword match', () => {
  const view = readFileSync(new URL('../src/components/KnowledgeHistoryTrace.vue', import.meta.url), 'utf8')
  assert.match(view, /chain.detected_conditions/)
  assert.match(view, /doc.detected_conditions/)
})

test('a failed applicability save retains the draft and the reviewer identity', async () => {
  const source = readFileSync(new URL('../src/components/KnowledgeReleaseHistoryWorkspace.vue', import.meta.url), 'utf8')
  const form = { document_ids: [1], product_model_ids: [9], country: 'CN', market: 'domestic', release_line: 'V6 POC', conditions: '仅新硬件', evidence_reference: '第3页', confirmed_by: '当前用户' }
  const context = { bindingForm: form, savingBinding: { value: false }, bindingError: { value: '' }, bindingBaseline: { value: 'original' },
    saveReleaseHistoryBindings: async () => { throw { response: { data: { detail: '文件已变化' } } } }, invalidateTrace() {}, refreshBindings: async () => {}, ElMessage: { success() {} } }
  const start = source.indexOf('const saveBindings ='), end = source.indexOf('\nconst deactivateBinding',start)
  const save = new Function(...Object.keys(context), `const bindingSession = 1; ${source.slice(start,end)}; return saveBindings`)(...Object.values(context))
  await save()
  assert.equal(context.bindingForm.confirmed_by, '当前用户')
  assert.equal(context.bindingForm.conditions, '仅新硬件')
  assert.match(context.bindingError.value, /文件已变化/)
  assert.equal(context.bindingBaseline.value, 'original')
  assert.equal(context.savingBinding.value, false)
})

test('all registered release documents are selectable beyond the first page', async () => {
  const source = readFileSync(new URL('../src/components/KnowledgeReleaseHistoryWorkspace.vue', import.meta.url), 'utf8')
  const context = { bindingForm: {}, emptyBinding: () => ({}), bindingBaseline: { value: '' }, bindingVisible: { value: false }, bindingError: { value: '' }, documents: { value: [] }, bindings: { value: [] }, bindingsLoading: { value: false },
    getReleaseHistoryBindings: async () => ({ items: [] }), getReleaseHistoryDocuments: async params => ({ items: Array.from({ length: params.skip ? 1 : 200 }, (_,i) => ({ id: (params.skip || 0) + i + 1 })), total: 201 }) }
  const start = source.indexOf('const refreshBindings ='), end = source.indexOf('\nconst closeBindings',start)
  const open = new Function(...Object.keys(context), `let bindingSession = 0; ${source.slice(start,end)}; return openBindings`)(...Object.values(context))
  await open()
  assert.equal(context.documents.value.length, 201)
  assert.equal(context.documents.value[200].id, 201)
})

test('a refresh failure after a committed save is reported as saved and can be retried', async () => {
  const source = readFileSync(new URL('../src/components/KnowledgeReleaseHistoryWorkspace.vue', import.meta.url), 'utf8')
  let saved = 0
  const context = { bindingForm: { document_ids:[1],product_model_ids:[9],country:'CN',market:'domestic',release_line:'V6',conditions:'',evidence_reference:'封面',confirmed_by:'用户' }, savingBinding:{value:false},bindingError:{value:''},bindingBaseline:{value:'original'},
    saveReleaseHistoryBindings: async () => { saved += 1 }, invalidateTrace() {}, refreshBindings: async () => { throw new Error('offline') }, ElMessage:{ success() {} } }
  const start = source.indexOf('const saveBindings ='), end = source.indexOf('\nconst deactivateBinding',start)
  const save = new Function(...Object.keys(context), `const bindingSession = 1; ${source.slice(start,end)}; return saveBindings`)(...Object.values(context))
  await save()
  assert.equal(saved, 1)
  assert.match(context.bindingError.value, /已保存.*刷新/)
  assert.doesNotMatch(context.bindingError.value, /保存失败/)
})

test('a refresh failure after committed deactivation is never reported as deactivation failure', async () => {
  const source = readFileSync(new URL('../src/components/KnowledgeReleaseHistoryWorkspace.vue', import.meta.url), 'utf8')
  let committed = false
  const context = { savingBinding:{value:false},bindingError:{value:''},ElMessageBox:{confirm:async()=>{}},
    deactivateReleaseHistoryBinding:async()=>{committed=true},invalidateTrace(){},refreshBindings:async()=>{throw new Error('offline')} }
  const start = source.indexOf('const deactivateBinding ='), end = source.indexOf('\n</script>',start)
  const deactivate = new Function(...Object.keys(context), `const bindingSession = 1; ${source.slice(start,end)}; return deactivateBinding`)(...Object.values(context))
  await deactivate({id:1,revision:1})
  assert.equal(committed,true)
  assert.match(context.bindingError.value,/已停用.*刷新/)
  assert.doesNotMatch(context.bindingError.value,/停用失败/)
})

test('history accepts country-free query context without inventing a source country', () => {
  const payload = historyTracePayload({ ...form(), country: '' })
  assert.ok(payload)
  assert.equal(Object.hasOwn(payload.scope,'country'), false)
  assert.equal(historyTracePayload(form()).scope.country,'CN')
})
