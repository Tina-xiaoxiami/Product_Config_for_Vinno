import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'


const read = relativePath => readFileSync(new URL(relativePath, import.meta.url), 'utf8')


test('published review batches are shown as read-only in the review center', () => {
  const view = read('../src/views/RegistrationManage.vue')

  // 批次状态必须显示出来，否则用户点了才发现改不了
  assert.match(view, /const reviewBatchEditable = computed/)
  assert.match(view, /草稿 · 可审核修正/)
  assert.match(view, /已发布 · 不可修改/)

  // 已发布时不给编辑按钮，并说明要走修订
  assert.match(view, /已发布，需走修订/)
  assert.match(view, /正式版本不可修改；如需修订请更新源表后重新导入并发布新版本/)
})
