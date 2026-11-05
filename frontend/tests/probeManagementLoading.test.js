import test from 'node:test'
import { projectTemplateCatalog, catalogCellSource } from '../src/utils/templateFeatureCatalog.js'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { WORKSPACE_SECTIONS, workspaceForPath } from '../src/utils/workspaceNavigation.js'
import { groupProbeVariants } from '../src/utils/probeMatrix.js'
import { resolveProbeCategory, applicationEditorState, probeContextBlock } from '../src/utils/probeApplications.js'
const read = name => readFileSync(new URL(`../src/views/${name}.vue`, import.meta.url), 'utf8')
const ref = value => ({ value })
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
function probeLoader(getProbeModels) {
  const context = { loading: ref(false), categories: ref([]), modelMap: ref({}), selectedCategory: ref(null), getProbeCategories: async () => ({ items: [{ id: 1 }, { id: 2 }] }), getProbeModels, groupProbeVariants, resolveProbeCategory, ElMessage: { error() {} } }
  const source = read('ProbeModelsView')
  const code = source.slice(source.indexOf('let dataLoadRequest ='), source.indexOf('const currentModels ='))
  return { ...context, ...new Function(...Object.keys(context), 'let requestedCategoryId = null; ' + code + '\nreturn { loadData }')(...Object.values(context)) }
}
test('probe first load includes details and selects a category without an application catalog', async () => {
  const app = probeLoader(async params => {
    assert.equal(params.include_details, true)
    return { items: [{ id: 1, category_id: 1, application_count: 2, variant_items: [{ id: 9 }] }] }
  })
  await app.loadData()
  assert.equal(app.selectedCategory.value.id, 1)
  assert.equal(app.modelMap.value[1][0]._appCount, 2)
  assert.deepEqual(app.modelMap.value[1][0]._variants, [{ id: 9, history_ids: [9] }])
  assert.equal(app.loading.value, false)
})
test('late probe refresh cannot replace a newer successful refresh', async () => {
  const old = deferred(), latest = deferred(); let calls = 0
  const app = probeLoader(() => ++calls === 1 ? old.promise : latest.promise)
  const first = app.loadData(), second = app.loadData()
  latest.resolve({ items: [{ id: 2, category_id: 2 }] }); await second
  old.resolve({ items: [{ id: 1, category_id: 1 }] }); await first
  assert.equal(app.modelMap.value[2][0].id, 2)
  assert.equal(app.modelMap.value[1], undefined)
})
test('probe management has one basic-data sidebar entry without an expanded child menu', () => {
  const entry = WORKSPACE_SECTIONS.find(section => section.id === 'master-data')
  assert.equal(entry.menuId, '/manage')
  assert.equal(entry.tabs.filter(tab => tab.path === '/template-features').length, 1)
  assert.equal(entry.tabs.some(tab => ['/probe-app-management', '/probe-models', '/applications', '/feature-manage'].includes(tab.path)), false)
  assert.equal(workspaceForPath('/applications').activeTab, '/template-features')
})
test('switching probe categories uses loaded details without fetching again', async () => {
  let requests = 0
  const app = probeLoader(async () => { requests++; return { items: [{ id: 2, category_id: 2 }] } })
  await app.loadData()
  const source = read('ProbeModelsView')
  const code = source.slice(source.indexOf('const selectCategory ='), source.indexOf('watch(() => route.query.category_id'))
  const selectCategory = new Function('selectedCategory', 'metadataOpen', 'probeContextBlock', 'applicationState', 'ElMessage', code + '\nreturn selectCategory')(app.selectedCategory, () => false, probeContextBlock, ref(applicationEditorState()), { warning() {} })
  selectCategory({ id: 2 })
  assert.equal(app.selectedCategory.value.id, 2)
  assert.equal(requests, 1)
})
test('template categories start independent detail requests together and preserve data on failure', async () => {
  const pending = deferred(), calls = []
  const previous = { old: true }
  const context = { loading: ref(false), loadError: ref(''), categories: ref([]), features: ref([]), featureGroups: ref([]), tplMap: ref(previous), categoryAppsMap: ref(previous),
    featureCatalog: ref(null), pendingMatrixCells: ref({}), pendingMatrixFeatureIds: ref(new Set()), draftTotal: ref(0), catalogAdditionCount: ref(0), projectTemplateCatalog, catalogCellSource,
    getProbeCategories: async () => ({ items: [{ id: 1 }, { id: 2 }] }),
    getTemplateFeatureCatalog: async () => ({ total: 2, items: [{ id: 9, group_id: 1, probe_matrix_enabled: true }, { id: 10, group_id: 2, probe_matrix_enabled: false }],
      matrix_items: [{ id: 9, group_id: 1, probe_matrix_enabled: true }], groups: [{ id: 1, name: '探头功能' }, { id: 2, name: '配置功能（未分类）' }] }),
    getTemplateFeatures: id => { calls.push(`template-${id}`); return pending.promise }, api: { get: url => { calls.push(url); return Promise.resolve(url === '/template-features/drafts' ? { total: 0, drafts: [], catalog_additions: [] } : { regular: [], poc: [] }) } }
  }
  const source = read('TemplateFeatures'), code = source.slice(source.indexOf('let templateLoadRequest ='), source.indexOf('const getCellClass ='))
  const loadData = new Function(...Object.keys(context), code + '\nreturn loadData')(...Object.values(context))
  const work = loadData(); await new Promise(resolve => setImmediate(resolve))
  assert.equal(calls.filter(call => call !== '/template-features/drafts').length, 4)
  assert.equal(calls.filter(call => call === '/template-features/drafts').length, 1)
  pending.resolve([{ feature_id: 9, default_support: 'supported' }]); await work
  assert.equal(context.tplMap.value['2_9'].default_support, 'supported')
  assert.deepEqual(context.featureGroups.value, [{ id: 1, name: '探头功能' }])
  const goodMap = context.tplMap.value
  context.api.get = async () => { throw new Error('offline') }
  await loadData()
  assert.equal(context.tplMap.value, goodMap)
  assert.match(context.loadError.value, /加载失败.*保留当前矩阵/)
  assert.equal(context.loading.value, false)
})
test('feature groups and features load concurrently', async () => {
  const pending = deferred(); let featureStarted = false
  const context = { loading: ref(false), tableData: ref([]), getFeatureGroups: () => pending.promise, getFeatures: async () => { featureStarted = true; return { items: [{ id: 4, group_id: 1 }] } }, ElMessage: { error() {} } }
  const source = read('FeatureManage'), code = source.slice(source.indexOf('const loadData ='), source.indexOf('// Groups'))
  const loadData = new Function(...Object.keys(context), code + '\nreturn loadData')(...Object.values(context))
  const work = loadData()
  assert.equal(featureStarted, true)
  pending.resolve({ items: [{ id: 1 }] }); await work
  assert.equal(context.tableData.value[0].features[0].id, 4)
})
