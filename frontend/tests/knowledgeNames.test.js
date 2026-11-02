import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { questionDisplayText, answerDisplayText, featureDisplayName } from '../src/utils/knowledgeNames.js'

test('reading uses current IPN descriptions while keeping stored business text intact', () => {
  const item = { question_text: '胸膜自动识别是选配吗？', display_question_text: '胸膜自动测量是选配吗？',
    answer: { answer_text: '胸膜自动识别(IPN 6000317)为选配', display_answer_text: '胸膜自动测量(IPN 6000317)为选配' } }
  assert.equal(questionDisplayText(item), '胸膜自动测量是选配吗？')
  assert.equal(answerDisplayText(item.answer), '胸膜自动测量(IPN 6000317)为选配')
  assert.equal(item.answer.answer_text, '胸膜自动识别(IPN 6000317)为选配')
  assert.equal(questionDisplayText({ question: '原询问' }), '原询问')
  assert.equal(questionDisplayText({ question: '旧名', display_question: '当前名' }), '当前名')
  assert.equal(questionDisplayText(null), '')
  assert.equal(answerDisplayText(null), '')
})

test('feature display follows the server-resolved primary IPN and has legacy fallbacks', () => {
  assert.equal(featureDisplayName({ display_cn_name: '粘弹性成像', primary_cn_name: '粘性成像', legacy_name: '旧名' }), '粘弹性成像')
  assert.equal(featureDisplayName({ primary_cn_name: '原中文主名' }), '原中文主名')
  assert.equal(featureDisplayName({ legacy_name: '原名称' }), '原名称')
  assert.equal(featureDisplayName(null), '')
})

test('all current knowledge reading paths use shared name projections and revisions retain source text', () => {
  const view = readFileSync(new URL('../src/views/KnowledgeHub.vue', import.meta.url), 'utf8')
  const review = readFileSync(new URL('../src/components/KnowledgeAnswerReviewDialog.vue', import.meta.url), 'utf8')
  assert.match(view, /questionDisplayText\(row\)/)
  assert.match(view, /answerDisplayText\(qaResult.answer\)/)
  assert.match(view, /answerDisplayText\(row.answer\)/)
  assert.match(view, /featureDisplayName\(feature\)/)
  assert.match(review, /questionDisplayText\(question\)/)
  assert.match(review, /answerDisplayText\(question.answer\)/)
  assert.match(review, /查看保存原文/)
  assert.match(view, /revision.answer_text/)
  assert.match(view, /answer_text: question.answer\?\.answer_text/)
})

test('answer editor shows the current question label while editing saved text without implicit changes', async () => {
  const view = readFileSync(new URL('../src/views/KnowledgeHub.vue', import.meta.url), 'utf8')
  const context = { answerSaving: { value: false }, answerForm: { value: {} }, answerDialogVisible: { value: false },
    answerCandidates: { value: [] }, candidateLoading: { value: false },
    getKnowledgeQuestionCandidates: async () => ({ items: [] }), ElMessage: { error() {} } }
  const start = view.indexOf('const qaReviewNotice =')
  const end = view.indexOf('\nconst addCitation', start)
  const open = new Function(...Object.keys(context), `${view.slice(start, end)}; return openAnswerDialog`)(...Object.values(context))
  await open({ id: 26, question_text: '胸膜自动识别？', display_question_text: '胸膜自动测量？',
    answer: { answer_text: '胸膜自动识别(IPN 6000317)', display_answer_text: '胸膜自动测量(IPN 6000317)' } })
  assert.equal(questionDisplayText(context.answerForm.value), '胸膜自动测量？')
  assert.equal(context.answerForm.value.answer_text, '胸膜自动识别(IPN 6000317)')
  assert.match(view, /questionDisplayText\(answerForm\)/)
})


test('publishing refreshes the result label without submitting display text as source', async () => {
  const view = readFileSync(new URL('../src/views/KnowledgeHub.vue', import.meta.url), 'utf8')
  const scope = { country: 'CN', market: 'domestic', product_model_id: 1, software_version: '1.14.80' }
  let payload
  const context = {
    answerForm: { value: { question_id: 1, scope, answer_text: '保存原文', change_note: '说明', alias_text: '', citations: [] } },
    answerSaving: { value: false }, answerDialogVisible: { value: true }, qaScope: scope, qaStatus: { value: 'answered' }, qaResult: { value: null },
    parseQuestionAliases: () => [], knowledgeScopePayload: x => x, knowledgeScopeFingerprint: JSON.stringify,
    publishKnowledgeAnswer: async (_id, data) => { payload = data; return { id: 1, scope, question_text: '旧问题', display_question_text: '当前名称问题', answer: { answer_text: '保存原文', display_answer_text: '阅读显示' } } },
    loadQaQuestions: async () => {}, ElMessage: { warning() {}, error() {}, success() {} }
  }
  const start = view.indexOf('const saveAnswer =')
  const end = view.indexOf('\nconst showHistory', start)
  const save = new Function(...Object.keys(context), `const answerDialogSessionId = 1; ${view.slice(start, end)}; return saveAnswer`)(...Object.values(context))
  await save()
  assert.equal(questionDisplayText(context.qaResult.value), '当前名称问题')
  assert.equal(answerDisplayText(context.qaResult.value.answer), '阅读显示')
  assert.equal(payload.answer_text, '保存原文')
})
