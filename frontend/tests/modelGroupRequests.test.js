import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolveGroupSeries } from '../src/utils/modelSelectionGroups.js'
const source = readFileSync(new URL('../src/views/Config.vue', import.meta.url), 'utf8')
const ref = value => ({ value })
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
function dataLoader(getConfigRows) {
 const context = {
  selectedSeries: ref([1]), selectedCategories: ref([]), searchText: ref(''),
  tableData: ref([{ id: 99, rd_name: 'old row' }]), originalData: ref([{ id: 99 }]), loading: ref(false),
  getConfigRows, ElMessage: { error() {}, warning() {} }, loadSeries: async () => {}, applyingModelGroup: ref(true)
 }
 const code = source.slice(source.indexOf('let dataLoadRequest ='), source.indexOf('// 检查字段是否被修改'))
 const { loadData } = new Function(...Object.keys(context), code + '\nreturn { loadData }')(...Object.values(context))
 return { ...context, loadData }
}
test('failed configuration request clears old rows and reports failure', async () => {
 const app = dataLoader(async () => { throw new Error('offline') })
 assert.equal(await app.loadData(), false)
 assert.deepEqual(app.tableData.value, [])
 assert.deepEqual(app.originalData.value, [])
 assert.equal(app.loading.value, false)
})
test('a delayed old request cannot replace a newer series table', async () => {
 const old = deferred(), latest = deferred()
 const app = dataLoader(({ series_id }) => series_id === 1 ? old.promise : latest.promise)
 const oldLoad = app.loadData()
 app.selectedSeries.value = [2]
 const newLoad = app.loadData()
 latest.resolve({ items: [{ id: 2, ipn: 'new', rd_name: 'new row', model_values: {} }] })
 assert.equal(await newLoad, true)
 old.resolve({ items: [{ id: 1, ipn: 'old', rd_name: 'old row', model_values: {} }] })
 assert.equal(await oldLoad, false)
 assert.equal(app.tableData.value[0].id, 2)
})
test('failed superseded group request preserves newer user series choice', async () => {
 const pending = deferred()
 const context = {
  applyingModelGroup: ref(false), resolveGroupSeries,
  seriesList: ref([{ id: 1, name: 'Original' }, { id: 2, name: 'Group' }, { id: 3, name: 'Latest' }]),
  selectedSeries: ref([1]), allModelsMap: ref(new Map()), currentPage: ref(4), modelFilterText: ref('query'),
  modelGroupsPopover: ref(null), loadModels: () => pending.promise,
  ElMessage: { warning() {} }, saveSeriesSelection() {}, saveModelOrder() {}
 }
 const code = source.slice(source.indexOf('const applyModelGroup ='), source.indexOf('const categoryOptions ='))
 const apply = new Function(...Object.keys(context), code + '\nreturn applyModelGroup')(...Object.values(context))
 const result = apply({ models: [{ seriesName: 'Group' }] })
 assert.equal(context.applyingModelGroup.value, true)
 context.selectedSeries.value = [3]
 pending.resolve(false)
 await result
 assert.deepEqual(context.selectedSeries.value, [3])
 assert.equal(context.applyingModelGroup.value, false)
})
test('stale draft failure cannot clear a newer series table', async () => {
 const oldDraft = deferred()
 let calls = 0
 const context = {
  selectedSeries: ref([1]), seriesList: ref([{ id: 1, name: 'A' }, { id: 2, name: 'B' }]),
  allModelsMap: ref(new Map()), selectedModels: ref([]), tempSelectedModels: ref([]),
  tableData: ref([]), originalData: ref([]), configReady: ref(true), showDiffOnly: ref(false), referenceModel: ref(null),
  getModels: async sid => ({ items: [{ id: sid, name: 'model' }] }),
  resolveGroupModels() {}, applySavedOrder() {},
  loadData: async () => { context.tableData.value = [{ id: context.selectedSeries.value[0] }]; return true },
  initDraft: () => ++calls === 1 ? oldDraft.promise : Promise.resolve(true),
  loadSeries: async () => {}, ElMessage: { error() {}, warning() {} }
 }
 const code = source.slice(source.indexOf('let modelLoadRequest ='), source.indexOf('// 加载配置数据'))
 const load = new Function(...Object.keys(context), code + '\nreturn loadModels')(...Object.values(context))
 const oldLoad = load()
 await new Promise(resolve => setImmediate(resolve))
 context.selectedSeries.value = [2]
 assert.equal(await load(), true)
 oldDraft.resolve(false)
 assert.equal(await oldLoad, false)
 assert.equal(context.tableData.value[0].id, 2)
})
test('filter requests are ignored while a group switch is loading', async () => {
 let calls = 0
 const context = { applyingModelGroup: ref(true), currentPage: ref(3), loadData: async () => { calls++ } }
 const code = source.slice(source.indexOf('const onFilterChange ='), source.indexOf('// 初始化草稿批次'))
 const change = new Function(...Object.keys(context), code + '\nreturn onFilterChange')(...Object.values(context))
 await change()
 assert.equal(calls, 0)
 assert.equal(context.currentPage.value, 3)
})
