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
