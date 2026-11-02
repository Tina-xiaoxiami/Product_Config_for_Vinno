import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { knowledgeScopePayload, knowledgeScopeLabel, knowledgeScopeFingerprint } from '../src/utils/knowledgeQueryScope.js'

const source = readFileSync(new URL('../src/views/KnowledgeHub.vue', import.meta.url), 'utf8')
const scope = () => ({ country: 'CN', market: 'domestic', product_model_id: 901, software_version: '1.14.80' })

function setup() {
  const asks = [], queues = [], warnings = []
  const context = {
    qaScope: scope(), qaQuestion: { value: '功能如何操作？' }, qaQueueMode: { value: 'selected' },
    qaResult: { value: null }, qaAsking: { value: false }, qaStatus: { value: 'pending' },
    qaQuestions: { value: [] }, qaListLoading: { value: false },
    knowledgeScopePayload, knowledgeScopeFingerprint,
    askKnowledgeQuestion: payload => new Promise(resolve => asks.push({ payload, resolve })),
    getKnowledgeQuestions: params => new Promise(resolve => queues.push({ params, resolve })),
    ElMessage: { warning: text => warnings.push(text), error() {}, info() {} }
  }
  const start = source.indexOf('let qaAskRequestId = 0')
  const end = source.indexOf('\nconst qaReviewNotice', start)
  assert.ok(start > 0 && end > start, 'scoped query actions exist')
  const actions = new Function(...Object.keys(context), `${source.slice(start, end)}; return { askQuestion, loadQaQuestions, onQaScopeInput }`)(...Object.values(context))
  return { context, asks, queues, warnings, ...actions }
}

test('query scope never supplies a missing default and keeps history explicitly labelled', () => {
  assert.equal(knowledgeScopePayload({}), null)
  assert.equal(knowledgeScopePayload({ ...scope(), software_version: '' }), null)
  assert.deepEqual(knowledgeScopePayload({ ...scope(), country: ' cn ' }), scope())
  assert.match(knowledgeScopeLabel(null), /历史范围待核实/)
  assert.match(knowledgeScopeLabel({ ...scope(), model_name: 'VINNO 10' }), /VINNO 10/)
})

test('ask sends the selected scope and ignores a response after scope editing', async () => {
  const { context, asks, askQuestion, onQaScopeInput } = setup()
  const pending = askQuestion()
  assert.deepEqual(asks[0].payload, { question: '功能如何操作？', scope: scope() })
  context.qaScope.software_version = '1.14.81'
  onQaScopeInput()
  asks[0].resolve({ status: 'answered', answer: { answer_text: 'old scope' } })
  await pending
  assert.equal(context.qaResult.value, null)
  assert.equal(context.qaAsking.value, false)
})

test('incomplete scope makes no ask or queue request; history uses a separate explicit mode', async () => {
  const { context, asks, queues, warnings, askQuestion, loadQaQuestions } = setup()
  context.qaScope.country = ''
  await askQuestion()
  await loadQaQuestions()
  assert.equal(asks.length, 0)
  assert.equal(queues.length, 0)
  assert.ok(warnings.length)
  context.qaQueueMode.value = 'legacy'
  const loading = loadQaQuestions()
  assert.deepEqual(queues[0].params, { status: 'pending', limit: 100 })
  queues[0].resolve({ items: [{ id: 71, scope: null }] })
  await loading
  assert.equal(context.qaQuestions.value[0].id, 71)
})

test('the latest scoped queue owns rows and loading state', async () => {
  const { context, queues, loadQaQuestions } = setup()
  const first = loadQaQuestions()
  context.qaScope.product_model_id = 902
  const second = loadQaQuestions()
  assert.equal(queues[1].params.product_model_id, 902)
  queues[0].resolve({ items: [{ id: 1 }] })
  await first
  assert.equal(context.qaListLoading.value, true)
  queues[1].resolve({ items: [{ id: 2 }] })
  await second
  assert.deepEqual(context.qaQuestions.value, [{ id: 2 }])
  assert.equal(context.qaListLoading.value, false)
})
