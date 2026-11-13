import test from 'node:test'
import assert from 'node:assert/strict'
import { createFeatureDetailWorkspace } from '../src/utils/knowledgeFeatureDetail.js'

const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
test('changing feature or scope clears evidence and prevents stale response restoration', async () => {
  const pending = deferred(), state = {}
  const workspace = createFeatureDetailWorkspace({ load: () => pending.promise }, state)
  const first = workspace.load(1, { market: 'domestic' }, 10)
  assert.equal(state.loading, true)
  workspace.invalidate()
  pending.resolve({ feature: { id: 1 } })
  await first
  assert.equal(state.result, null)
  assert.equal(state.loading, false)
})
test('detail preserves explicit configuration version and reports failed reload', async () => {
  const state = {}, calls = []
  let fail = false
  const workspace = createFeatureDetailWorkspace({ load: async (...args) => {
    calls.push(args)
    if (fail) throw new Error('读取失败')
    return { feature: { id: 2 } }
  } }, state)
  await workspace.load(2, { software_version: '1.51.90' }, 8)
  assert.deepEqual(calls[0], [2, { scope: { software_version: '1.51.90' }, configuration_version_id: 8 }])
  assert.equal(state.result.feature.id, 2)
  fail = true
  await workspace.load(2, {}, null)
  assert.equal(state.result, null)
  assert.match(state.error, /读取失败/)
  assert.equal(state.loading, false)
})

test('feature detail lives in knowledge hub and reuses citation and history views', async () => {
  const { readFile } = await import('node:fs/promises')
  const source = await readFile(new URL('../src/components/KnowledgeFeatureDetail.vue', import.meta.url), 'utf8')
  const hub = await readFile(new URL('../src/views/KnowledgeHub.vue', import.meta.url), 'utf8')
  assert.match(source, /KnowledgeHistoryTrace/)
  assert.match(source, /emit\('citation', citation\)/)
  assert.match(source, /关联版本/)
  assert.match(source, /候选原文/)
  assert.match(hub, /name="feature-detail"/)
  assert.match(hub, /@citation="openCitation"/)
})
