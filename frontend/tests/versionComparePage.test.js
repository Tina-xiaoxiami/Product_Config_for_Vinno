import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { reactive, watch, effectScope } from 'vue'
import { createVersionCompareState, createVersionCompareController, positiveQueryId } from '../src/utils/versionComparePage.js'
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }
function app(overrides = {}) {
  const state = reactive(createVersionCompareState()), scope = effectScope()
  let active = true
  const api = { getSeriesList: async () => ({ items: [{ id: 1 }, { id: 2 }] }), getVersions: async id => ({ items: [{ id: id * 10 + 1 }, { id: id * 10 + 2 }], total: 2 }), compareVersions: async data => data, ...overrides }
  const controller = createVersionCompareController(state, api, () => active)
  scope.run(() => watch(() => [state.version1, state.version2], controller.invalidateComparison, { flush: 'sync' }))
  return { state, ...controller, stop() { active = false; controller.deactivate(); scope.stop() } }
}
test('positive route IDs reject arrays, malformed strings and unsafe integers', () => {
  assert.equal(positiveQueryId('23'), 23)
  for (const value of [[], ['2'], '2x', '-1', '0', '1.2', '9007199254740992', undefined]) assert.equal(positiveQueryId(value), null)
})
test('history deep links select their series and neighboring version, with safe invalid fallbacks', async () => {
  const a = app(); await a.load({ series: '2', version: '22' })
  assert.equal(a.state.selectedSeries, 2); assert.equal(a.state.version1, 22); assert.equal(a.state.version2, 21)
  await a.compare(); assert.deepEqual(a.state.result, { version_id_1: 22, version_id_2: 21 })
  await a.load({ series: '999', version: '11' }); assert.equal(a.state.selectedSeries, 2); assert.equal(a.state.version1, 21)
  a.stop()
})
test('version catalogs load all server pages rather than just the history page', async () => {
  const calls = []
  const a = app({ getVersions: async (id, page) => { calls.push(page); return page.skip === 0 ? { items: Array.from({ length: 100 }, (_, i) => ({ id: i + 1 })), total: 101 } : { items: [{ id: 101 }], total: 101 } } })
  await a.load({ version: '101' }); assert.equal(a.state.versions.length, 101); assert.equal(a.state.version1, 101); assert.equal(a.state.version2, 100)
  assert.deepEqual(calls, [{ skip: 0, limit: 100 }, { skip: 100, limit: 100 }]); a.stop()
})
test('switching series ignores stale catalog successes and failures', async () => {
  const old = deferred(), a = app({ getVersions: id => id === 1 ? old.promise : Promise.resolve({ items: [{ id: 21 }, { id: 22 }], total: 2 }) })
  const pending = a.load({ series: '1' }); await Promise.resolve()
  await a.load({ series: '2' }); old.reject(new Error('old error')); await pending
  assert.equal(a.state.version1, 21); assert.equal(a.state.error, ''); a.stop()
})
test('same-version and single-version catalogs cannot issue comparisons', async () => {
  let calls = 0; const a = app({ getVersions: async () => ({ items: [{ id: 11 }], total: 1 }), compareVersions: async () => { calls++; return {} } })
  await a.load(); await a.compare(); assert.equal(a.state.version2, null); assert.equal(calls, 0)
  a.state.version2 = 11; await a.compare(); assert.equal(calls, 0); a.stop()
})
test('changing pairs away and back invalidates old results and latest failures clear prior content', async () => {
  const pending = deferred(); let calls = 0
  const a = app({ compareVersions: () => ++calls === 1 ? pending.promise : Promise.reject(new Error('offline')) })
  await a.load(); const old = a.compare(); a.state.version2 = null; a.state.version2 = 12
  pending.resolve({ stale: true }); await old; assert.equal(a.state.result, null)
  await a.compare(); assert.equal(a.state.error, '版本对比失败，请重试'); assert.equal(a.state.loading, false); a.stop()
})
test('leaving the cached page invalidates pending catalog and comparison requests', async () => {
  const pending = deferred(), a = app({ compareVersions: () => pending.promise })
  await a.load(); const old = a.compare(); a.stop(); pending.resolve({ stale: true }); await old
  assert.equal(a.state.result, null); assert.equal(a.state.loading, false)
  const catalog = deferred(), b = app({ getSeriesList: () => catalog.promise })
  const loading = b.load(); b.stop(); catalog.resolve({ items: [{ id: 2 }] }); await loading
  assert.deepEqual(b.state.series, [])
})
test('standalone route/nav reuse the existing matrix and unmount it on deactivation', () => {
  const page = readFileSync(new URL('../src/views/VersionCompare.vue', import.meta.url), 'utf8')
  const routes = readFileSync(new URL('../src/router/index.js', import.meta.url), 'utf8')
  const layout = readFileSync(new URL('../src/views/Layout.vue', import.meta.url), 'utf8')
  assert.match(routes, /path: 'version-compare'/); assert.match(layout, /index="\/version-compare"/)
  assert.match(page, /<VersionComparison v-if="active"/); assert.match(page, /onDeactivated\(deactivate\)/)
  assert.match(page, /route.name === 'VersionCompare'/)
})
