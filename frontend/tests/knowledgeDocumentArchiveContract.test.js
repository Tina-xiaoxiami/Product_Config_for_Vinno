import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'


const read = relativePath => readFileSync(new URL(relativePath, import.meta.url), 'utf8')


test('knowledge documents can be retired from the hub without touching originals', () => {
  const view = read('../src/views/KnowledgeHub.vue')
  const api = read('../src/api/data.js')

  // 列表里给出「归档」入口，并二次确认
  assert.match(view, /archiveDocument\(document\)/)
  assert.match(view, /const archiveDocument = async/)
  assert.match(view, /ElMessageBox\.confirm/)

  // 确认文案必须说明原件文件不受影响
  assert.match(view, /原件文件不会被删除/)

  assert.match(api, /export const archiveKnowledgeDocument/)
  assert.match(api, /documents\/\$\{id\}\/archive/)
})
