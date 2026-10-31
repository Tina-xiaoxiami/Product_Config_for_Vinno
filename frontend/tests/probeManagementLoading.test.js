import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { parse } from '@vue/compiler-dom'
const read = name => readFileSync(new URL(`../src/views/${name}.vue`, import.meta.url), 'utf8')
const ref = value => ({ value })
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
function probeLoader(getProbeModels) {
  const context = { loading: ref(false), categories: ref([]), modelMap: ref({}), selectedCategory: ref(null), getProbeCategories: async () => ({ items: [{ id: 1 }, { id: 2 }] }), getProbeModels, ElMessage: { error() {} } }
  const source = read('ProbeModelsView')
  const code = source.slice(source.indexOf('let dataLoadRequest ='), source.indexOf('const currentModels ='))
  return { ...context, ...new Function(...Object.keys(context), code + '\nreturn { loadData }')(...Object.values(context)) }
}
test('probe first load includes details and selects a category without an application catalog', async () => {
  const app = probeLoader(async params => {
    assert.equal(params.include_details, true)
    return { items: [{ id: 1, category_id: 1, application_count: 2, variant_items: [{ id: 9 }] }] }
  })
  await app.loadData()
  assert.equal(app.selectedCategory.value.id, 1)
  assert.equal(app.modelMap.value[1][0]._appCount, 2)
  assert.deepEqual(app.modelMap.value[1][0]._variants, [{ id: 9 }])
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
  const ast = parse(read('Layout').split('<script setup>')[0])
  const entries = []
  function visit(node, parents = []) {
    const index = node.props?.find(p => p.name === 'index')?.value?.content
    if (index) entries.push({ tag: node.tag, index, parents })
    for (const child of node.children || []) visit(child, node.tag === 'el-sub-menu' ? [...parents, index] : parents)
  }
  visit(ast)
  const entry = entries.find(m => m.index === '/template-features')
  assert.equal(entry.tag, 'el-menu-item')
  assert.deepEqual(entry.parents, ['/manage'])
  assert.equal(entries.some(m => ['/probe-app-management', '/probe-models', '/applications', '/feature-manage'].includes(m.index)), false)
})
test('switching probe categories uses loaded details without fetching again', async () => {
  let requests = 0
  const app = probeLoader(async () => { requests++; return { items: [{ id: 2, category_id: 2 }] } })
  await app.loadData()
  const source = read('ProbeModelsView')
  const code = source.slice(source.indexOf('const selectCategory ='), source.indexOf('// Category CRUD'))
  const selectCategory = new Function('selectedCategory', code + '\nreturn selectCategory')(app.selectedCategory)
  selectCategory({ id: 2 })
  assert.equal(app.selectedCategory.value.id, 2)
  assert.equal(requests, 1)
})
test('template categories start independent detail requests together and preserve data on failure', async () => {
  const pending = deferred(), calls = [], errors = []
  const previous = { old: true }
  const context = { loading: ref(false), categories: ref([]), features: ref([]), featureGroups: ref([]), tplMap: ref(previous), categoryAppsMap: ref(previous),
    getProbeCategories: async () => ({ items: [{ id: 1 }, { id: 2 }] }), getFeatures: async () => ({ items: [] }), getFeatureGroups: async () => ({ items: [] }),
    getTemplateFeatures: id => { calls.push(`template-${id}`); return pending.promise }, api: { get: url => { calls.push(url); return Promise.resolve({ regular: [], poc: [] }) } }, ElMessage: { error: message => errors.push(message) }
  }
  const source = read('TemplateFeatures'), code = source.slice(source.indexOf('let templateLoadRequest ='), source.indexOf('const getCellClass ='))
  const loadData = new Function(...Object.keys(context), code + '\nreturn loadData')(...Object.values(context))
  const work = loadData(); await new Promise(resolve => setImmediate(resolve))
  assert.equal(calls.length, 4)
  pending.resolve([{ feature_id: 9, default_support: 'supported' }]); await work
  assert.equal(context.tplMap.value['2_9'].default_support, 'supported')
  const goodMap = context.tplMap.value
  context.api.get = async () => { throw new Error('offline') }
  await loadData()
  assert.equal(context.tplMap.value, goodMap)
  assert.deepEqual(errors, ['加载失败'])
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
