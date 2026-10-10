import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../src/views/Versions.vue', import.meta.url), 'utf8')
const ref = value => ({ value })

function deferred() {
  let resolve
  let reject
  const promise = new Promise((onResolve, onReject) => {
    resolve = onResolve
    reject = onReject
  })
  return { promise, resolve, reject }
}

function versionLoader({ getVersions, getModels = async () => ({ items: [] }) }) {
  const context = {
    versionLoadRequest: 0,
    selectedSeries: ref(1),
    versions: ref([{ id: 99, version_number: 'old' }]),
    total: ref(42),
    currentPage: ref(1),
    pageSize: ref(20),
    modelList: ref([{ id: 99, name: 'old model' }]),
    versionOptions: ref([{ id: 99, version_number: 'old' }]),
    getVersions,
    getModels,
    ElMessage: { error() {} },
    console: { error() {} }
  }
  const code = source.slice(
    source.indexOf('const loadVersions ='),
    source.indexOf('const handleSeriesChange =')
  )
  const loadVersions = new Function(
    ...Object.keys(context),
    `${code}\nreturn loadVersions`
  )(...Object.values(context))
  return { loadVersions, ...context }
}

test('version history requests the selected server page and renders pagination', () => {
  assert.match(source, /getVersions\(selectedSeries\.value,\s*\{[\s\S]*?skip:\s*\(currentPage\.value - 1\) \* pageSize\.value,[\s\S]*?limit:\s*pageSize\.value/)
  assert.match(source, /total\.value\s*=\s*res\.total\s*\|\|\s*0/)
  assert.match(source, /<el-pagination[\s\S]*?v-model:current-page="currentPage"[\s\S]*?:total="total"/)
})

test('changing series resets version history to its first page', () => {
  assert.match(source, /const handleSeriesChange = \(\) => \{[\s\S]*?currentPage\.value = 1[\s\S]*?loadVersions\(\)/)
  assert.match(source, /@change="handleSeriesChange"/)
})

test('compare selectors load every version through bounded API pages', () => {
  assert.match(source, /const VERSION_OPTION_PAGE_SIZE = \d+/)
  assert.match(source, /const loadAllVersionOptions = async/)
  assert.match(source, /getVersions\(seriesId,\s*\{\s*skip,\s*limit:\s*VERSION_OPTION_PAGE_SIZE\s*\}\)/)
  assert.match(source, /while \(skip < total\)/)
  assert.match(source, /<el-option v-for="v in versionOptions"/)
})

test('a current version load failure clears the previous series total', async () => {
  const app = versionLoader({ getVersions: async () => { throw new Error('offline') } })

  await app.loadVersions()

  assert.deepEqual(app.versions.value, [])
  assert.deepEqual(app.modelList.value, [])
  assert.equal(app.total.value, 0)
})

test('a stale version response cannot replace the latest series page or total', async () => {
  const oldRequest = deferred()
  const app = versionLoader({
    getVersions: seriesId => seriesId === 1
      ? oldRequest.promise
      : Promise.resolve({ items: [{ id: 2, version_number: 'new' }], total: 1 }),
    getModels: async seriesId => ({ items: [{ id: seriesId, name: `model-${seriesId}` }] })
  })

  const oldLoad = app.loadVersions()
  app.selectedSeries.value = 2
  await app.loadVersions()
  oldRequest.resolve({ items: [{ id: 1, version_number: 'stale' }], total: 99 })
  await oldLoad

  assert.deepEqual(app.versions.value, [{ id: 2, version_number: 'new' }])
  assert.equal(app.total.value, 1)
  assert.deepEqual(app.modelList.value, [{ id: 2, name: 'model-2' }])
})
