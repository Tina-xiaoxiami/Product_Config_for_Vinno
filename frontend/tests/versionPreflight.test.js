import test from 'node:test'
import assert from 'node:assert/strict'
import { reactive, effectScope } from 'vue'
import { useVersionPreflight } from '../src/utils/useVersionPreflight.js'
const tick = () => new Promise(resolve => setTimeout(resolve, 10))
test('input and series changes block immediately and ignore stale responses', async () => {
  const input = reactive({ enabled: true, seriesIds: [1], versionNumber: 'old' })
  const calls = []; const scope = effectScope()
  const state = scope.run(() => useVersionPreflight(() => ({ ...input }), params => new Promise(resolve => calls.push({ params, resolve })), 0))
  assert.equal(state.pending, true); await tick()
  input.versionNumber = 'new'; assert.equal(state.pending, true); await tick()
  calls[1].resolve({ results: [{ series_id: 1, valid: true }] }); await tick()
  calls[0].resolve({ results: [{ series_id: 1, valid: false, message: '旧版本冲突' }] }); await tick()
  assert.equal(state.error, ''); assert.equal(state.pending, false)
  input.seriesIds = [2]; assert.equal(state.pending, true); await tick()
  calls[2].resolve({ results: [{ series_id: 2, valid: false, message: '系列2版本已存在' }] }); await tick()
  assert.match(state.error, /系列2/)
  input.enabled = false; assert.equal(state.error, ''); scope.stop()
})
test('connection failure or missing result blocks submission and allows recheck', async () => {
  const scope = effectScope(); let mode = 'error'
  const state = scope.run(() => useVersionPreflight(() => ({ enabled: true, seriesIds: [1], versionNumber: '' }), async () => {
    if (mode === 'error') throw new Error('offline')
    return { results: mode === 'missing' ? [] : [{ series_id: 1, valid: true }] }
  }, 0))
  await tick(); assert.match(state.error, /校验/)
  mode = 'missing'; state.recheck(); await tick(); assert.ok(state.error)
  mode = 'valid'; state.recheck(); await tick(); assert.equal(state.error, ''); scope.stop()
})
