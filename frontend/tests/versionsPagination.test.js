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

function versionCompareController(compareVersions) {
  const context = {
    compareRequest: 0,
    selectedSeries: ref(10),
    versions: ref([{ id: 1 }, { id: 2 }, { id: 3 }, { id: 4 }]),
    currentPage: ref(2),
    versionOptions: ref([]),
    versionOptionLoadRequest: 0,
    loadVersions() {},
    loadAllVersionOptions: async () => [{ id: 1 }, { id: 2 }, { id: 3 }, { id: 4 }],
    compareDialogVisible: ref(true),
    compareVersion1: ref(1),
    compareVersion2: ref(2),
    compareResult: ref(null),
    compareLoading: ref(false),
    selectedModels: ref([]),
    activeTab: ref('modified'),
    compareVersions,
    ElMessage: { warning() {}, error() {} },
    console: { error() {} }
  }
  const seriesCode = source.slice(
    source.indexOf('const handleSeriesChange ='),
    source.indexOf('const handlePageSizeChange =')
  )
  const openCode = source.slice(
    source.indexOf('const openCompareDialog ='),
    source.indexOf('// 执行版本对比')
  )
  const compareCode = source.slice(
    source.indexOf('const executeCompare ='),
    source.indexOf('// 回滚版本')
  )
  const functions = new Function(
    ...Object.keys(context),
    `${seriesCode}\n${openCode}\n${compareCode}\nreturn { handleSeriesChange, openCompareDialog, executeCompare }`
  )(...Object.values(context))
  return { ...functions, ...context }
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

test('latest version comparison wins with its captured series, versions, and model filter', async () => {
  const slow = deferred()
  const payloads = []
  const latestResult = { summary: {}, added: [{ id: 'latest' }], modified: [], deleted: [] }
  const staleResult = { summary: {}, added: [], modified: [{ id: 'stale' }], deleted: [] }
  const app = versionCompareController(payload => {
    payloads.push(payload)
    return payloads.length === 1 ? slow.promise : Promise.resolve(latestResult)
  })

  app.selectedModels.value = [7]
  const oldCompare = app.executeCompare()
  app.compareVersion1.value = 3
  app.compareVersion2.value = 4
  app.selectedModels.value = [8, 9]
  await app.executeCompare()
  slow.resolve(staleResult)
  await oldCompare

  assert.deepEqual(payloads, [
    { version_id_1: 1, version_id_2: 2, model_ids: [7] },
    { version_id_1: 3, version_id_2: 4, model_ids: [8, 9] }
  ])
  assert.equal(app.compareResult.value, latestResult)
  assert.equal(app.activeTab.value, 'added')
  assert.equal(app.compareLoading.value, false)
})

test('series changes and reopening the dialog invalidate an in-flight version comparison', async () => {
  const afterSeriesChange = deferred()
  const seriesApp = versionCompareController(() => afterSeriesChange.promise)
  const oldSeriesCompare = seriesApp.executeCompare()
  seriesApp.selectedSeries.value = 20
  seriesApp.handleSeriesChange()
  afterSeriesChange.resolve({ summary: {}, added: [], modified: [{ id: 'stale' }], deleted: [] })
  await oldSeriesCompare
  assert.equal(seriesApp.compareResult.value, null)
  assert.equal(seriesApp.compareLoading.value, false)

  const afterReopen = deferred()
  const dialogApp = versionCompareController(() => afterReopen.promise)
  const oldDialogCompare = dialogApp.executeCompare()
  await dialogApp.openCompareDialog({ id: 3 })
  afterReopen.resolve({ summary: {}, added: [], modified: [{ id: 'stale' }], deleted: [] })
  await oldDialogCompare
  assert.equal(dialogApp.compareResult.value, null)
  assert.equal(dialogApp.compareVersion1.value, 3)
  assert.equal(dialogApp.compareLoading.value, false)
})
