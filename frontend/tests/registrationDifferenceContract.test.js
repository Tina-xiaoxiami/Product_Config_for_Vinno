import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'


const read = relativePath => readFileSync(new URL(relativePath, import.meta.url), 'utf8')


test('difference summary lays out six models per row in a single block', () => {
  const view = read('../src/views/RegistrationManage.vue')

  // 一行一个块、每块 6 个机型：行标签（型号/差异）只出现一次
  assert.match(view, /const DIFFERENCE_MODELS_PER_ROW = 6/)
  assert.match(view, /index \+= DIFFERENCE_MODELS_PER_ROW/)
  assert.match(view, /\.difference-original-grid \{ display: grid; grid-template-columns: 1fr; gap: 12px; \}/)
  assert.doesNotMatch(view, /grid-template-columns: repeat\(2, minmax\(0, 1fr\)\); gap: 12px; \}/)

  // 行标签保持不变；标题不再声称"按原表格式"——原始资料只是核对用的证据，
  // 各系列差异读数都来自原表里的数据表，个别系列多附一张截图不代表展示格式
  assert.match(view, /<th scope="row">型号<\/th>/)
  assert.match(view, /<th scope="row">差异<\/th>/)
  assert.match(view, /<span>不适用\/未注册探头差异<\/span>/)
  assert.doesNotMatch(view, /按原表格式/)
  assert.match(view, /查看差异表/)
  assert.match(view, /探头全适用/)
  assert.match(view, /不适用/)
})
