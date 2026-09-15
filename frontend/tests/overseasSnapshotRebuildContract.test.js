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
