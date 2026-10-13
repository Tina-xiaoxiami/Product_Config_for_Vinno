import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { ref, watch, effectScope } from 'vue'

const compareSource = readFileSync(new URL('../src/views/Compare.vue', import.meta.url), 'utf8')
const versionSource = readFileSync(new URL('../src/views/Versions.vue', import.meta.url), 'utf8')
const deferred = () => {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const result = (id, models = [11, 12]) => ({ total: 1, diff_count: 1, items: [{ item_id: id, field_name: 'final_config', values: Object.fromEntries(models.map(model => [model, `item-${id}`])) }] })
const versionResult = id => ({ summary: { added: 0, modified: 1, deleted: 0 }, added: [], modified: [{ id }], deleted: [] })

function comparisonController({ compareConfigs = async () => result(1), getDraftList = async () => ({ items: [] }) } = {}) {
  const ticks = [], messages = [], payloads = []
  const context = {
    seriesLoading: ref(false), modelsLoading: ref(false), seriesLoadError: ref(''), modelLoadError: ref(''), comparisonError: ref(''),
    watch, selectedModels: ref([11, 12]), selectedSeries: ref([1]), compareFields: ref(['final_config']), showOnlyDiff: ref(true),
    allModelsMap: ref(new Map([[11, { seriesId: 1 }], [12, { seriesId: 1 }], [13, { seriesId: 1 }], [14, { seriesId: 1 }]])),
    loading: ref(false), compareResult: ref(null), currentPage: ref(1), referenceModel: ref(11),
    compareConfigs: payload => { payloads.push(payload); return compareConfigs(payload) },
    nextTick: callback => ticks.push(callback), compareTableRef: ref(null), originalValues: ref(new Map()),
    draftChanges: ref(new Map()), draftItemTypes: ref(new Map()), draftBatchMap: ref(new Map()), draftStats: ref({ total: 0, create: 0, update: 0, delete: 0 }),
    getCurrentDraftBatch: async seriesId => ({ exists: true, batch: { id: seriesId * 10 } }),
    getDraftList, createDraftBatch: async () => { throw new Error('Test must not create a server batch') }, loadEnumValues: async () => {},
    ElMessage: Object.fromEntries(['warning', 'error', 'success', 'info'].map(type => [type, message => messages.push({ type, message })])), console: { error() {} }
  }
  const start = compareSource.indexOf('// 执行对比')
  const pipeline = compareSource.slice(start, compareSource.indexOf('// 加载枚举值\nconst loadEnumValues', start))
  const lifecycleStart = compareSource.indexOf('// 对比条件生命周期')
  const lifecycle = lifecycleStart < 0 ? '' : compareSource.slice(lifecycleStart, compareSource.indexOf('// 对比条件生命周期结束', lifecycleStart))
  const scope = effectScope()
  const functions = scope.run(() => new Function(...Object.keys(context), `${pipeline}\n${lifecycle}\nreturn {handleCompare, autoCompare}`)(...Object.values(context)))
  return { ...context, ...functions, payloads, messages, flushTicks: () => { const queued = ticks.splice(0); queued.forEach(fn => fn()) }, stop: () => scope.stop() }
}

function versionController(compareVersions = async () => versionResult('one')) {
  const context = {
    watch, compareRequest: 0, selectedSeries: ref(1), compareDialogVisible: ref(true), compareVersion1: ref(1), compareVersion2: ref(2),
    selectedModels: ref([]), compareResult: ref(null), compareLoading: ref(false), activeTab: ref('modified'), compareVersions,
    versions: ref([{ id: 1 }, { id: 2 }, { id: 3 }]), versionOptions: ref([]),
    loadAllVersionOptions: async () => [{ id: 1 }, { id: 2 }, { id: 3 }],
    ElMessage: { warning() {}, error() {} }, console: { error() {} }
  }
  const start = versionSource.indexOf('const executeCompare =')
  const openStart = versionSource.indexOf('const openCompareDialog =')
  const pipeline = versionSource.slice(openStart, versionSource.indexOf('// 回滚版本', start))
  const lifecycleStart = versionSource.indexOf('// 版本对比条件生命周期')
  const lifecycle = lifecycleStart < 0 ? '' : versionSource.slice(lifecycleStart, versionSource.indexOf('// 版本对比条件生命周期结束', lifecycleStart))
  const scope = effectScope()
  const functions = scope.run(() => new Function(...Object.keys(context), `${pipeline}\n${lifecycle}\nreturn { executeCompare, openCompareDialog }`)(...Object.values(context)))
  return { ...context, ...functions, stop: () => scope.stop() }
}

test('manual and automatic comparison share latest-request protection', async () => {
  const slow = deferred(); let calls = 0
  const app = comparisonController({ compareConfigs: () => ++calls === 1 ? slow.promise : Promise.resolve(result(2, [13, 14])) })
  const old = app.handleCompare(); app.selectedModels.value = [13, 14]; await app.autoCompare()
  slow.resolve(result(1)); await old
  assert.equal(app.compareResult.value.items[0].item_id, 2)
  assert.equal(app.originalValues.value.has('1_11_final_config'), false)
  assert.deepEqual(app.payloads.map(payload => payload.model_ids), [[11, 12], [13, 14]])
  app.stop()
})
for (const condition of ['models', 'fields', 'series']) {
  test(`clearing ${condition} clears results and prevents an older response returning`, async () => {
    const slow = deferred(), app = comparisonController({ compareConfigs: () => slow.promise })
    app.compareResult.value = result(99)
    const old = app.autoCompare()
    if (condition === 'models') app.selectedModels.value = []
    if (condition === 'fields') app.compareFields.value = []
    if (condition === 'series') app.selectedSeries.value = []
    assert.equal(app.compareResult.value, null)
    slow.resolve(result(1)); await old
    assert.equal(app.compareResult.value, null)
    assert.equal(app.draftBatchMap.value.size, 0)
    assert.equal(app.loading.value, false)
    app.stop()
  })
}

test('a late draft stage cannot contaminate newer comparison rows or draft statistics', async () => {
  const drafts = deferred(); let compareCalls = 0, draftCalls = 0
  const app = comparisonController({
    compareConfigs: async () => result(++compareCalls, compareCalls === 1 ? [11, 12] : [13, 14]),
    getDraftList: () => ++draftCalls === 1 ? drafts.promise : Promise.resolve({ items: [{ id: 21, item_id: 2, model_id: 13, field_name: 'final_config', change_type: 'update', old_value: 'S', new_value: 'O' }] })
  })
  const old = app.autoCompare(); await new Promise(resolve => setImmediate(resolve))
  app.selectedModels.value = [13, 14]; await app.autoCompare()
  drafts.resolve({ items: [{ id: 11, item_id: 1, model_id: 11, field_name: 'final_config', change_type: 'update', old_value: 'S', new_value: 'O' }] }); await old
  assert.equal(app.compareResult.value.items[0].item_id, 2)
  assert.equal(app.draftChanges.value.has('1_11_final_config'), false)
  assert.equal(app.draftChanges.value.has('2_13_final_config'), true)
  assert.equal(app.draftStats.value.total, 1)
  app.stop()
})

test('latest automatic comparison failure removes the previously completed result', async () => {
  let calls = 0
  const app = comparisonController({ compareConfigs: async () => { if (++calls === 1) return result(1); throw new Error('offline') } })
  await app.autoCompare(); assert.equal(app.compareResult.value.items[0].item_id, 1)
  await app.autoCompare()
  assert.equal(app.compareResult.value, null); assert.equal(app.loading.value, false)
  assert.equal(app.originalValues.value.size, 0); assert.equal(app.draftChanges.value.size, 0)
  app.stop()
})

test('changing a completed comparison condition clears its result immediately', async () => {
  const app = comparisonController(); await app.autoCompare()
  app.compareFields.value = ['current_config']
  assert.equal(app.compareResult.value, null)
  app.stop()
})

for (const condition of ['version', 'models']) {
  test(`version comparison clears completed results when ${condition} selection changes`, async () => {
    const app = versionController(); await app.executeCompare()
    if (condition === 'version') app.compareVersion2.value = 3
    else app.selectedModels.value.push(8)
    assert.equal(app.compareResult.value, null)
    app.stop()
  })
}

test('a failed latest version comparison cannot show the previous version pair', async () => {
  let calls = 0
  const app = versionController(async () => { if (++calls === 1) return versionResult('old'); throw new Error('offline') })
  await app.executeCompare(); await app.executeCompare()
  assert.equal(app.compareResult.value, null); assert.equal(app.compareLoading.value, false)
  app.stop()
})

test('changing version conditions away and back still invalidates its pending response', async () => {
  const pending = deferred(), app = versionController(() => pending.promise)
  const old = app.executeCompare(); app.compareVersion2.value = 3; app.compareVersion2.value = 2
  pending.resolve(versionResult('stale')); await old
  assert.equal(app.compareResult.value, null); assert.equal(app.compareLoading.value, false)
  app.stop()
})

// Real synchronous watchers must not invalidate the dialog's own initialization.
test('opening version comparison still selects its preceding version with lifecycle watchers active', async () => {
  const app = versionController()
  await app.openCompareDialog({ id: 2 })
  assert.equal(app.compareVersion1.value, 2)
  assert.equal(app.compareVersion2.value, 3)
  await app.executeCompare()
  assert.equal(app.compareResult.value.modified[0].id, 'one')
  app.stop()
})
