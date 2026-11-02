import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { answerReviewPayload, answerReviewError, answerReviewLabel, QA_COLUMNS } from '../src/utils/knowledgeAnswerReview.js'

const question = { id: 7, answer: { version: 1 }, evidence_review: { fingerprint: 'source-v1', review_revision: 0, status: 'needs_review' } }
const form = () => ({ action: 'record_reference', country: '', market: '', product_model_ids: [], software_version: '',
  version_applicability: 'unknown', evidence_reference: 'Existing 2026-09-03 confirmation', note: '', confirmed_by: 'Reviewer' })

test('recording a reference does not invent query scope or a reviewer identity', () => {
  assert.equal(answerReviewError(form()), '')
  const payload = answerReviewPayload(question, form())
  assert.equal(payload.expected_answer_version, 1)
  assert.equal(payload.expected_fingerprint, 'source-v1')
  assert.equal(payload.expected_review_revision, 0)
  assert.equal(payload.country, null)
  assert.equal(payload.software_version, null)
  assert.deepEqual(payload.product_model_ids, [])
  assert.match(answerReviewError({ ...form(), confirmed_by: '' }), /核对人/)
})

test('confirming query scopes requires a specific complete scope while defer requires a reason', () => {
  assert.match(answerReviewError({ ...form(), action: 'confirm_scope' }), /范围|版本/)
  assert.match(answerReviewError({ ...form(), action: 'defer' }), /理由/)
  assert.equal(answerReviewError({ ...form(), action: 'defer', note: 'Need historical certificate' }), '')
  assert.equal(answerReviewError({ ...form(), action: 'confirm_scope', country: 'CN', market: 'domestic',
    product_model_ids: [1, 2], software_version: '1.14.80', version_applicability: 'specific' }), '')
})

test('confirming a query scope needs no country and cannot carry over a historical country filter', () => {
  const review = { ...form(), action: 'confirm_scope', market: 'domestic', product_model_ids: [901],
    software_version: '1.14.80', version_applicability: 'specific' }
  assert.equal(answerReviewError(review), '')
  assert.equal(answerReviewPayload(question, { ...review, country: 'CN' }).country, null)
  assert.equal(answerReviewPayload(question, { ...review, action: 'record_reference', country: 'CN' }).country, 'CN')
})

test('answer review status and stable table columns preserve full-answer access', () => {
  assert.match(answerReviewLabel(question), /待核对/)
  assert.match(answerReviewLabel({ evidence_review: { status: 'reviewed' } }), /已核对/)
  assert.ok(QA_COLUMNS.some(column => column.key === 'answer'))
  assert.equal(new Set(QA_COLUMNS.map(column => column.key)).size, QA_COLUMNS.length)
  const source = readFileSync(new URL('../src/views/KnowledgeHub.vue', import.meta.url), 'utf8')
  assert.match(source, /data-testid="qa-answer-preview"/)
  assert.match(source, /data-testid="qa-answer-full"/)
  assert.match(source, /data-testid="qa-needs-review"/)
  assert.match(source, /KnowledgeAnswerReviewDialog/)
})

test('review dialog protects drafts and treats saving records separately from publishing scope answers', () => {
  const source = readFileSync(new URL('../src/components/KnowledgeAnswerReviewDialog.vue', import.meta.url), 'utf8')
  assert.match(source, /:before-close="requestClose"/)
  assert.match(source, /未保存/)
  assert.match(source, /仅补确认记录/)
  assert.match(source, /确认范围并用于查询/)
  assert.match(source, /answer_text/)
  assert.match(source, /change_note/)
})

function dialogActions(submit, confirm = async () => {}) {
  const source = readFileSync(new URL('../src/components/KnowledgeAnswerReviewDialog.vue', import.meta.url), 'utf8')
  const form = {}, events = []
  const context = {
    form, visible: { value: false }, saving: { value: false }, question: { value: null },
    error: { value: '' }, baseline: { value: '' }, lastReviewer: { value: '' }, props: { currentScope: null },
    dirty: { get value() { return JSON.stringify(form) !== context.baseline.value } },
    ElMessageBox: { confirm }, ElMessage: { success() {} }, emit: (...event) => events.push(event),
    answerReviewError, answerReviewPayload, reviewKnowledgeAnswer: submit
  }
  const start = source.indexOf('const open = value =>')
  const end = source.indexOf('\nconst openCitation', start)
  const actions = new Function(...Object.keys(context), `let sessionId = 0; ${source.slice(start, end)}; return { open, save, requestClose, useCurrentScope }`)(...Object.values(context))
  actions.open({ ...question, answer: { version: 1, answer_text: 'Original full answer', change_note: 'Existing owner confirmation' }, evidence_review: { ...question.evidence_review, available: true } })
  return { ...actions, context, events }
}

test('using the current query scope preserves an optional source country in a reference review', () => {
  const editor = dialogActions(async () => ({}))
  editor.context.form.country = 'DE'
  editor.context.props.currentScope = { market: 'overseas', product_model_id: 901, software_version: '1.51.90' }
  editor.useCurrentScope()
  assert.equal(editor.context.form.country, 'DE')
  assert.equal(editor.context.form.market, 'overseas')
  assert.deepEqual(editor.context.form.product_model_ids, [901])
})

test('failed review submission retains text, actor and the open editor', async () => {
  const editor = dialogActions(async () => { throw { response: { data: { detail: 'Answer changed, reload before confirming' } } } })
  editor.context.form.confirmed_by = 'Current reviewer'
  editor.context.form.note = 'Unsaved exception'
  await editor.save()
  assert.equal(editor.context.visible.value, true)
  assert.equal(editor.context.form.note, 'Unsaved exception')
  assert.equal(editor.context.form.confirmed_by, 'Current reviewer')
  assert.match(editor.context.error.value, /Answer changed/)
  assert.equal(editor.context.saving.value, false)
  assert.equal(editor.events.length, 0)
})

test('declining draft discard keeps review input, and success emits the saved record', async () => {
  const editor = dialogActions(async (_id, payload) => ({ id: question.id, evidence_review: { status: 'reviewed' }, reviewer: payload.confirmed_by }), async () => { throw new Error('continue editing') })
  editor.context.form.confirmed_by = 'Current reviewer'
  await editor.requestClose()
  assert.equal(editor.context.visible.value, true)
  assert.equal(editor.context.form.confirmed_by, 'Current reviewer')
  await editor.save()
  assert.equal(editor.context.visible.value, false)
  assert.equal(editor.events[0][0], 'saved')
  assert.equal(editor.events[0][1].reviewer, 'Current reviewer')
})

function queueActions() {
  const source = readFileSync(new URL('../src/views/KnowledgeHub.vue', import.meta.url), 'utf8')
  const calls = []
  const context = { qaPage: { value: 2 }, qaQueueMode: { value: 'legacy' }, qaEvidenceFilter: { value: 'needs_review' },
    qaStatus: { value: 'answered' }, qaSearch: { value: '' },
    loadQaQuestions: async () => calls.push({ page: context.qaPage.value, filter: context.qaEvidenceFilter.value }),
    loadQaReviewCount: async () => {} }
  const start = source.indexOf('const onAnswerReviewSaved =')
  const end = source.indexOf('const updateQaTableHeight =', start)
  const actions = new Function(...Object.keys(context), `${source.slice(start, end)}; return { onAnswerReviewSaved, onQaQueueModeChange }`)(...Object.values(context))
  return { ...actions, context, calls, source }
}

test('saving a review restarts pagination before reloading a shrinking queue', async () => {
  const queue = queueActions()
  await queue.onAnswerReviewSaved()
  assert.equal(queue.calls[0].page, 1)
})

test('leaving review queue clears its status filter and hides the review-only funnel', () => {
  const queue = queueActions()
  queue.onQaQueueModeChange()
  assert.equal(queue.context.qaEvidenceFilter.value, 'all')
  assert.equal(queue.calls[0].page, 1)
  assert.match(queue.source, /<el-popover v-if="qaQueueMode === 'review'"/)
})


test('invalidated answers never claim document-backed review status', () => {
  assert.equal(answerReviewLabel({ answer: { review_status: 'source_changed' }, evidence_review: { status: 'not_required' } }), '依据已变化')
  assert.equal(answerReviewLabel({ answer: { review_status: 'published', citations: [] } }), '核对状态未知')
})
