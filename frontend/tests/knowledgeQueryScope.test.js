import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { knowledgeScopePayload, knowledgeScopeLabel, knowledgeScopeFingerprint } from '../src/utils/knowledgeQueryScope.js'

const source = readFileSync(new URL('../src/views/KnowledgeHub.vue', import.meta.url), 'utf8')
const scope = () => ({ market: 'domestic', product_model_id: 901, software_version: '1.14.80' })

function setup() {
  const asks = [], queues = [], warnings = []
  const context = {
    qaScope: scope(), qaQuestion: { value: '功能如何操作？' }, qaQueueMode: { value: 'selected' },
    qaResult: { value: null }, qaAsking: { value: false }, qaStatus: { value: 'pending' },
    qaQuestions: { value: [] }, qaListLoading: { value: false },
    qaTotal: { value: 0 }, qaPage: { value: 1 }, qaPageSize: { value: 100 }, qaSearch: { value: '' }, qaEvidenceFilter: { value: 'all' },
    nextTick: fn => fn(), updateQaTableHeight() {},
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

test('query scope ignores country while preserving historical provenance in labels', () => {
  assert.deepEqual(knowledgeScopePayload(scope()), scope())
  assert.deepEqual(knowledgeScopePayload({ ...scope(), country: 'DE' }), scope())
  assert.equal(knowledgeScopeFingerprint({ ...scope(), country: 'DE' }), knowledgeScopeFingerprint(scope()))
  assert.doesNotMatch(knowledgeScopeLabel(scope()), /undefined|null/)
  assert.match(knowledgeScopeLabel({ ...scope(), country: 'CN' }), /CN/)
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
  context.qaScope.software_version = ''
  await askQuestion()
  await loadQaQuestions()
  assert.equal(asks.length, 0)
  assert.equal(queues.length, 0)
  assert.ok(warnings.length)
  context.qaQueueMode.value = 'legacy'
  const loading = loadQaQuestions()
  assert.deepEqual(queues[0].params, { status: 'pending', workflow: 'unanswered', limit: 100, skip: 0 })
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

test('saving an earlier-scope answer cannot replace the current-scope result', async () => {
  let finish
  const current = { status: 'answered', answer: { answer_text: 'current scope' } }
  const context = {
    answerForm: { value: { question_id: 1, scope: scope(), draft_revision: 5, answer_text: 'edited', change_note: 'test', alias_text: '', citations: [] } },
    answerSaving: { value: false }, answerDialogVisible: { value: true },
    qaScope: scope(), qaStatus: { value: 'answered' }, qaResult: { value: null },
    answerDirty: { value: false }, knowledgeScopePayload, knowledgeScopeFingerprint,
    answerDialogSessionId: 1,
    publishKnowledgeAnswer: () => new Promise(resolve => { finish = resolve }),
    loadQaQuestions: async () => {}, ElMessage: { warning() {}, error() {}, success() {} }
  }
  const start = source.indexOf('const saveAnswer =')
  const end = source.indexOf('\nconst showHistory', start)
  const save = new Function(...Object.keys(context), `${source.slice(start, end)}; return publishSavedAnswer`)(...Object.values(context))
  const pending = save()
  context.qaScope.software_version = '1.14.81'
  context.qaResult.value = current
  finish({ id: 1, question_text: 'original question', answer: { answer_text: 'old scope save' } })
  await pending
  assert.equal(context.qaResult.value, current)
})

test('candidate response from an earlier answer dialog cannot cross into the next scope', async () => {
  const requests = []
  const context = {
    computed: () => null, ref: value => ({ value }), answerSaving: { value: false }, answerForm: { value: {} }, answerDialogVisible: { value: false },
    answerCandidates: { value: [] }, candidateLoading: { value: false },
    getKnowledgeQuestionCandidates: id => new Promise(resolve => requests.push({ id, resolve })),
    ElMessage: { error() {} }
  }
  const start = source.indexOf('const qaReviewNotice =')
  const end = source.indexOf('\nconst addCitation', start)
  const open = new Function(...Object.keys(context), `${source.slice(start, end)}; return openAnswerDialog`)(...Object.values(context))
  const first = open({ id: 1, scope: scope(), question_text: 'a' })
  const second = open({ id: 2, scope: { ...scope(), software_version: '1.14.81' }, question_text: 'b' })
  requests[0].resolve({ items: [{ document_id: 11 }] })
  await first
  assert.deepEqual(context.answerCandidates.value, [])
  assert.equal(context.candidateLoading.value, true)
  requests[1].resolve({ items: [{ document_id: 22 }] })
  await second
  assert.deepEqual(context.answerCandidates.value, [{ document_id: 22 }])
})

test('an earlier save cannot close or reset a newer answer editor', async () => {
  let finish
  const context = {
    answerForm: { value: { question_id: 1, scope: scope(), draft_revision: 5, answer_text: 'A', change_note: 'test', alias_text: '', citations: [] } },
    answerSaving: { value: false }, answerDialogVisible: { value: true },
    qaScope: scope(), qaStatus: { value: 'answered' }, qaResult: { value: null },
    answerDirty: { value: false }, knowledgeScopePayload, knowledgeScopeFingerprint,
    publishKnowledgeAnswer: () => new Promise(resolve => { finish = resolve }),
    loadQaQuestions: async () => {}, ElMessage: { warning() {}, error() {}, success() {} }
  }
  const start = source.indexOf('const saveAnswer =')
  const end = source.indexOf('\nconst showHistory', start)
  const actions = new Function(...Object.keys(context), `let answerDialogSessionId = 1; ${source.slice(start, end)}; return { publishSavedAnswer, nextSession: () => { answerDialogSessionId += 1 } }`)(...Object.values(context))
  const first = actions.publishSavedAnswer()
  actions.nextSession()
  context.answerForm.value = { question_id: 2, scope: { ...scope(), software_version: '1.14.81' }, answer_text: 'unsaved B' }
  context.answerSaving.value = true
  finish({ id: 1, question_text: 'A', answer: {} })
  await first
  assert.equal(context.answerDialogVisible.value, true)
  assert.equal(context.answerSaving.value, true)
  assert.equal(context.answerForm.value.answer_text, 'unsaved B')
})
