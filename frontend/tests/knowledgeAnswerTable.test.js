import test from 'node:test'
import assert from 'node:assert/strict'
import { answerBlocks } from '../src/utils/knowledgeAnswerTable.js'

test('plain answers preserve lines and a pipe without a table divider', () => {
  const text = '实测 52 分钟。\n\n条件 A | B\n<em>原文</em>'
  assert.deepEqual(answerBlocks(text), [{ type: 'text', text }])
})

test('structured answers keep prose, cells, blank values and escaped pipes', () => {
  assert.deepEqual(answerBlocks('实测时长\n\n| 模式 | 时长 |\n| --- | :---: |\n| A\\|B | 52 分钟 |\n| C | |\n\n测试条件'), [
    { type: 'text', text: '实测时长' },
    { type: 'table', columns: ['模式', '时长'], rows: [['A|B', '52 分钟'], ['C', '']] },
    { type: 'text', text: '测试条件' },
  ])
})

test('malformed table remains visible as text', () => {
  const text = '| 模式 | 时长 |\n| --- | --- |\n| A | 52 | 额外值 |'
  assert.deepEqual(answerBlocks(text), [{ type: 'text', text }])
})
