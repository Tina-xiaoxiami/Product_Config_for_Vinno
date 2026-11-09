import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const versions = readFileSync(new URL('../src/views/Versions.vue', import.meta.url), 'utf8')
const models = readFileSync(new URL('../src/views/Models.vue', import.meta.url), 'utf8')
const ref = value => ({ value })

function versionSeriesLoader(getSeriesList) {
  const state = {
    getSeriesList, seriesList: ref([]), selectedSeries: ref(2), currentPage: ref(3),
    versions: ref([{ id: 1 }]), total: ref(1), versionLoadRequest: 0,
    console: { error() {} }, calls: [],
  }
  state.loadVersions = async () => state.calls.push([state.selectedSeries.value, state.currentPage.value])
  const code = versions.slice(versions.indexOf('const loadSeries ='), versions.indexOf('// 加载版本列表'))
  return { ...state, load: new Function(...Object.keys(state), `let seriesLoadRequest = 0; ${code}; return loadSeries`)(...Object.values(state)) }
}

test('returning to version history preserves existing series and page while refreshing names', async () => {
  const app = versionSeriesLoader(async () => ({ items: [{ id: 1, name: 'First' }, { id: 2, name: 'Renamed' }] }))
  await app.load()
  assert.equal(app.selectedSeries.value, 2)
  assert.equal(app.currentPage.value, 3)
  assert.equal(app.seriesList.value[1].name, 'Renamed')
  assert.deepEqual(app.calls, [[2, 3]])
  assert.match(versions, /useWorkspaceRefresh\(loadSeries, \{ canRefresh: \(\) => !editDialogVisible\.value \}\)/)
})

test('deleted selected series falls back to the first page; empty catalog clears stale history', async () => {
  let items = [{ id: 1, name: 'Remaining' }]
  const app = versionSeriesLoader(async () => ({ items }))
  await app.load()
  assert.deepEqual(app.calls, [[1, 1]])
  items = []
  await app.load()
  assert.equal(app.selectedSeries.value, null)
  assert.deepEqual(app.versions.value, [])
  assert.equal(app.total.value, 0)
})

test('late series responses cannot override a newer version workspace load', async () => {
  let resolve, count = 0
  const app = versionSeriesLoader(() => ++count === 1 ? new Promise(done => { resolve = done }) : Promise.resolve({ items: [{ id: 2, name: 'Current' }] }))
  const old = app.load()
  await app.load()
  resolve({ items: [{ id: 1, name: 'Stale' }] })
  await old
  assert.deepEqual(app.seriesList.value, [{ id: 2, name: 'Current' }])
  assert.deepEqual(app.calls, [[2, 3]])
})

test('returning to models refreshes shared series and ignores fetches completed after leaving', async () => {
  let resolve, pageActive = true, loads = 0
  const state = { getSeriesList: () => new Promise(done => { resolve = done }), seriesList: ref([{ id: 1 }]),
    loadData: async () => { loads++ }, console: { error() {} } }
  const code = models.slice(models.indexOf('let seriesLoadRequest ='), models.indexOf('let loadRequest ='))
  const load = new Function(...Object.keys(state), 'isActive', `${code.replace('!pageActive', '!isActive()')}; return loadSeries`)(...Object.values(state), () => pageActive)
  const pending = load()
  pageActive = false
  resolve({ items: [{ id: 2 }] })
  await pending
  assert.deepEqual(state.seriesList.value, [{ id: 1 }])
  assert.equal(loads, 0)
  assert.match(models, /onActivated\(\(\) => \{ pageActive = true; if \(initialized\) \{ loadSeries\(\)/)
})
