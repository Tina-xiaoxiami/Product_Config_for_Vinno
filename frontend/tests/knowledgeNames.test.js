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
