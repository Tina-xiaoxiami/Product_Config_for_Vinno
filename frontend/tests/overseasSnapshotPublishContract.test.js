import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'


const read = relativePath => readFileSync(new URL(relativePath, import.meta.url), 'utf8')


test('overseas query surfaces an unpublished draft snapshot and lets it be published', () => {
  const view = read('../src/views/RegistrationManage.vue')
  const api = read('../src/api/data.js')

  // 关系查询只认生效快照，界面必须把草稿显式暴露出来
  assert.match(view, /overseasDraftSnapshot/)
  assert.match(view, /overseasActiveSnapshot/)
  assert.match(view, /loadOverseasSnapshots/)
  assert.match(view, /发布此快照/)
  assert.match(view, /const publishOverseasDraft = async/)

  // 发布要留发布人
  assert.match(view, /ElMessageBox\.prompt/)
  assert.match(view, /publishOverseasRegistrationSnapshot\(draft\.id, confirmedBy\)/)

  // 初始化时一并拉快照状态
  assert.match(view, /loadOverseasSnapshots\(\),/)

  assert.match(api, /export const getOverseasRegistrationSnapshots/)
  assert.match(api, /registrations\/overseas\/snapshots'\)/)
})
