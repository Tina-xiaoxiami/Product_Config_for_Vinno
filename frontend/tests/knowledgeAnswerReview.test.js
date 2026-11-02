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
