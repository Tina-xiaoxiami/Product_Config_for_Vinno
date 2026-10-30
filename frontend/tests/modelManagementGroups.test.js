import test from 'node:test'
import assert from 'node:assert/strict'
import { applySharedMemberships, buildManagementGroups, loadCompleteModelCatalog } from '../src/utils/modelManagementGroups.js'

test('hierarchy uses IDs and deduplicates overlaps; ungrouped remains visible', () => {
  const models = [{ id: 1, name: 'same' }, { id: 2, name: 'same' }, { id: 3 }]
  const data = { groups: [{ name: 'A', series: 'China', model_ids: [1, 1] }, { name: 'B', model_ids: [1, 2] }], combinations: [{ name: 'Pack', sub_series: ['A', 'B'] }, { name: 'Other', sub_series: ['A'] }] }
  const nodes = buildManagementGroups(models, data)
  assert.deepEqual(nodes.map(n => n.label), ['全部型号', 'Pack', 'Other', '未分组'])
  assert.deepEqual(nodes[1].ids, ['1', '2'])
  assert.deepEqual(nodes.at(-1).ids, ['3'])
  assert.notEqual(nodes[1].children[0].key, nodes[2].children[0].key)
  assert.deepEqual(buildManagementGroups([models[1]], data)[1].ids, ['2'])
})

test('refresh replaces memberships without changing source map or identity', () => {
  const original = new Map([[1, { id: 1, name: 'A', seriesId: 8, sub_series: ['old'] }], [2, { id: 2, sub_series: ['removed'] }]])
  const result = applySharedMemberships(original, [{ name: 'new', model_ids: ['1'] }])
  assert.deepEqual(result.get(1), { id: 1, name: 'A', seriesId: 8, sub_series: ['new'] })
  assert.deepEqual(result.get(2).sub_series, [])
  assert.deepEqual(original.get(1).sub_series, ['old'])
})

test('complete catalog loads all pages; rejects incomplete/duplicate/changing data, ignores stale response', async () => {
  const calls = []
  const result = await loadCompleteModelCatalog(async params => { calls.push(params); return { total: 3, items: params.skip === 0 ? [{ id: 1 }, { id: 2 }] : [{ id: 3 }] } })
  assert.equal(result.length, 3); assert.equal(calls[1].skip, 2)
  await assert.rejects(loadCompleteModelCatalog(async () => ({ total: 2, items: [{ id: 1 }] })))
  await assert.rejects(loadCompleteModelCatalog(async () => ({ total: 2, items: [] })))
  await assert.rejects(loadCompleteModelCatalog(async ({ skip }) => ({ total: skip ? 3 : 2, items: [{ id: skip + 1 }] })))
  await assert.rejects(loadCompleteModelCatalog(async () => { throw new Error('offline') }), /offline/)
  assert.equal(await loadCompleteModelCatalog(async () => ({ total: 1, items: [{ id: 1 }] }), () => false), null)
})

test('Config refresh rejects stale memberships without resetting selected models', async () => {
  const { readFileSync } = await import('node:fs')
  const source = readFileSync(new URL('../src/views/Config.vue', import.meta.url), 'utf8')
  const block = source.slice(source.indexOf('let modelTreeRequest = 0'), source.indexOf('// 根据 modelId'))
  const applyingModelGroup = { value: false }
  const requests = [], allModelsMap = { value: new Map([[1, { id: 1, sub_series: ['old'] }]]) }, combinations = { value: [] }
  const refresh = new Function('getSubseries', 'allModelsMap', 'modelSubseriesCombinations', 'applySharedMemberships', 'ElMessage', 'applyingModelGroup', block + ';return loadModelCombinations')(
    () => new Promise(resolve => requests.push(resolve)), allModelsMap, combinations, applySharedMemberships, { warning() {} }, applyingModelGroup)
  const first = refresh(), second = refresh()
  requests[1]({ combinations: [{ name: 'new' }], groups: [{ name: 'new', model_ids: [1] }] }); await second
  requests[0]({ combinations: [{ name: 'old' }], groups: [{ name: 'old', model_ids: [1] }] }); await first
  assert.deepEqual(allModelsMap.value.get(1).sub_series, ['new'])
  assert.equal(combinations.value[0].name, 'new')
  const previous = allModelsMap.value
  const busyRefresh = refresh(); applyingModelGroup.value = true
  requests[2]({ groups: [{ name: 'busy', model_ids: [1] }] }); await busyRefresh
  assert.equal(allModelsMap.value, previous)
  assert.doesNotMatch(block, /selectedModels\.value\s*=|loadData\(/)
  assert.match(source, /path: '\/models', query: \{ editSubseries: '1' \}/)
  assert.match(source, /onActivated\(\(\) => \{ if \(allModelsMap.value.size\) loadModelCombinations\(\)/)
})

test('editor query is consumed once and cannot open after leaving cached Models', async () => {
  const { createGroupEditorRequest } = await import('../src/utils/modelManagementGroups.js')
  let finish, active = true, opened = 0, consumed = 0
  const request = createGroupEditorRequest({ isRequested: () => true, isActive: () => active,
    consume: () => { consumed++; return new Promise(resolve => { finish = resolve }) }, nextTick: async () => {}, open: () => opened++ })
  const first = request.run(); await request.run()
  assert.equal(consumed, 1)
  active = false; request.invalidate(); finish(); await first
  assert.equal(opened, 0)
  active = true
  const second = request.run(); finish(); await second
  assert.equal(opened, 1)
})

test('model management loads every market and shows all children of cross-market combinations', async () => {
  const { readFileSync } = await import('node:fs')
  const source = readFileSync(new URL('../src/views/Models.vue', import.meta.url), 'utf8')
  assert.match(source, /getModels\(null, params\)/)
  assert.doesNotMatch(source, /v-model="selectedSeries"/)
  assert.match(source, /series_id: form.series_id/)
  const models = [{id:1,name:'VINNO 5',series_id:1},{id:2,name:'VINNO 5',series_id:2}]
  const nodes = buildManagementGroups(models, {groups:[{name:'国内',model_ids:[1]},{name:'海外',model_ids:[2]}],combinations:[{name:'国内海外',sub_series:['国内','海外']}]})
  assert.deepEqual(nodes[1].children.map(group => group.label), ['国内','海外'])
  assert.deepEqual(nodes[1].ids,['1','2'])
})
