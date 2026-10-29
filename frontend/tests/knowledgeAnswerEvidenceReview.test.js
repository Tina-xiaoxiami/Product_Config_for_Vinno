import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const view = readFileSync(new URL('../src/views/KnowledgeHub.vue', import.meta.url), 'utf8')
const start = view.indexOf('const qaReviewNotice =')
const end = view.indexOf('\nconst addCitation', start)

function setup() {
  const context = {
    answerForm: {value:{}}, answerDialogVisible:{value:false}, answerCandidates:{value:[]}, candidateLoading:{value:false},
    getKnowledgeQuestionCandidates: async () => ({items:[]}), ElMessage:{error() {}}
  }
  const actions = new Function(...Object.keys(context), `${view.slice(start,end)}; return {qaReviewNotice, openAnswerDialog}`)(...Object.values(context))
  return {context,...actions}
}

test('changed evidence has specific visible warnings and retains earlier answer and citations', async () => {
  const {context, qaReviewNotice, openAnswerDialog} = setup()
  assert.match(qaReviewNotice('source_changed'), /原文已变化/)
  assert.match(qaReviewNotice('scope_changed'), /适用范围已变化/)
  assert.match(qaReviewNotice('evidence_changed'), /原文和适用范围均已变化/)
  assert.equal(qaReviewNotice('published'), '')
  await openAnswerDialog({id:1, question_text:'问题', answer:{version:2, review_status:'evidence_changed', answer_text:'旧答案', change_note:'以前的说明', citations:[{document_id:4,source_ref:'第 5 页',excerpt:'旧原文'}]}})
  assert.equal(context.answerForm.value.review_status, 'evidence_changed')
  assert.equal(context.answerForm.value.answer_text, '旧答案')
  assert.deepEqual(context.answerForm.value.citations, [{document_id:4,source_ref:'第 5 页',excerpt:'旧原文'}])
  assert.equal(context.answerForm.value.previous_change_note, '以前的说明')
  assert.equal(context.answerForm.value.change_note, '')
  assert.equal(context.answerDialogVisible.value, true)
  assert.match(view, /data-testid="knowledge-answer-evidence-review"/)
  assert.match(view, /qaReviewNotice\(answerForm\.review_status\)/)
})

test('release version review reason is shown for pending entries and carried into edit context', () => {
  const source = readFileSync(new URL('../src/views/FeatureRelease.vue', import.meta.url), 'utf8')
  const start = source.indexOf('const editVersion = (row) => {')
  const end = source.indexOf('\nconst submitEdit', start)
  const editForm = {}, editEvidenceReason = {value:''}, editBaseline = {value:null}, editDialogVisible = {value:false}
  const edit = new Function('editForm','editEvidenceReason','editBaseline','editDialogVisible','releaseVersionPayload', `${source.slice(start,end)}; return editVersion`)(editForm, editEvidenceReason, editBaseline, editDialogVisible, form => ({...form}))
  edit({id:4, software_version:'1.14.80', review_status:'pending', evidence_review_reason:'引用原文已变化，请重新确认'})
  assert.equal(editEvidenceReason.value, '引用原文已变化，请重新确认')
  assert.equal(editDialogVisible.value, true)
  edit({id:5, software_version:'1.14.81', review_status:'confirmed'})
  assert.equal(editEvidenceReason.value, '')
  assert.equal((source.match(/row\.review_status === 'pending' && row\.evidence_review_reason/g) || []).length, 2)
  assert.match(source, /v-if="editEvidenceReason"/)
})
