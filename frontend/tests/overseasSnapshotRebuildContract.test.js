import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'


const read = relativePath => readFileSync(new URL(relativePath, import.meta.url), 'utf8')


test('published overseas snapshot can be rebuilt into a draft without losing the live one', () => {
  const view = read('../src/views/RegistrationManage.vue')
  const api = read('../src/api/data.js')

  // 已发布快照冻结、原件没变时也能重开一版：入口挂在生效快照那一行
  assert.match(view, /基于此快照重建草稿/)
  assert.match(view, /const rebuildOverseasDraft = async/)
  assert.match(view, /rebuildOverseasRegistrationDraft\(active\.id\)/)
  assert.match(view, /overseasRebuildAvailable/)
  assert.match(view, /overseasRebuilding/)

  // 重建前要说清「旧快照在发布前继续生效」，不能让人以为查询会立刻变
  assert.match(view, /ElMessageBox\.confirm/)
  assert.match(view, /在发布前继续生效/)

  // 同一份原件已经挂着待发布草稿时不再重复重建
  assert.match(view, /source_document_id ===/)

  // 草稿与生效快照并存时，文案不能再断言「结果为空」
  assert.match(view, /当前查询仍使用已发布快照/)

  assert.match(
    api,
    /export const rebuildOverseasRegistrationDraft[\s\S]*rebuild-draft/
  )
})


test('an unwanted draft can be discarded from the same bar', () => {
  const view = read('../src/views/RegistrationManage.vue')
  const api = read('../src/api/data.js')

  assert.match(view, /放弃草稿/)
  assert.match(view, /const discardOverseasDraft = async/)
  assert.match(view, /discardOverseasRegistrationDraft\(draft\.id\)/)

  // 删的是草稿，必须说清删掉什么、且不可撤销
  assert.match(view, /ElMessageBox\.confirm/)
  assert.match(view, /审核条目/)
  assert.match(view, /不可撤销/)

  // 删完要刷新：快照、国家列表、关系都要回到已发布那一版
  assert.match(view, /await loadOverseasSnapshots\(\)[\s\S]{0,200}loadOverseasRelations/)

  assert.match(
    api,
    /export const discardOverseasRegistrationDraft[\s\S]*api\.delete\([\s\S]*overseas\/snapshots/
  )
})
