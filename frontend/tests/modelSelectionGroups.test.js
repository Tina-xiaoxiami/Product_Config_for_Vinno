import test from 'node:test'
import assert from 'node:assert/strict'
import { buildModelSelectionGroup, resolveGroupSeries, resolveGroupModels, loadModelSelectionGroups, saveModelSelectionGroups } from '../src/utils/modelSelectionGroups.js'
const models = new Map([
 [10, { id: 10, name: '9E Super', seriesId: 1, seriesName: 'China' }],
 [20, { id: 20, name: '9E Pro', seriesId: 1, seriesName: 'China' }],
 [30, { id: 30, name: '9E Super', seriesId: 2, seriesName: 'Oversea' }]
])
const group = () => buildModelSelectionGroup(' 常用机型 ', [20, 10, 30, 20], models, 'group-1')
const memoryStorage = () => { const values = new Map(); return { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) } }
test('saves ordered unique selection and validates empty names and selections', () => {
 const saved = group(); assert.equal(saved.name, '常用机型'); assert.deepEqual(saved.models.map(m => m.id), [20, 10, 30])
 assert.throws(() => buildModelSelectionGroup(' ', [10], models, 'g')); assert.throws(() => buildModelSelectionGroup('empty', [], models, 'g'))
})
test('persists, renames, updates and deletes groups across reloads', () => {
 const storage = memoryStorage(), saved = [group()]; saveModelSelectionGroups(saved, storage); assert.deepEqual(loadModelSelectionGroups(storage), saved)
 saveModelSelectionGroups([{ ...saved[0], name: '新名称', models: [saved[0].models[0]] }], storage)
 assert.equal(loadModelSelectionGroups(storage)[0].name, '新名称'); assert.equal(loadModelSelectionGroups(storage)[0].models.length, 1)
 saveModelSelectionGroups([], storage); assert.deepEqual(loadModelSelectionGroups(storage), [])
})
test('recovers by series and model name after IDs change without selecting reused IDs', () => {
 const saved = group(); assert.deepEqual(resolveGroupSeries(saved, [{ id: 7, name: 'China' }, { id: 8, name: 'Oversea' }]), { ids: [7, 8], missing: 0 })
 const moved = new Map([[20, { id: 20, name: 'Wrong model', seriesName: 'China' }], [71, { id: 71, name: '9E Super', seriesName: 'China' }], [72, { id: 72, name: '9E Pro', seriesName: 'China' }], [81, { id: 81, name: '9E Super', seriesName: 'Oversea' }]])
 assert.deepEqual(resolveGroupModels(saved, moved), { ids: [72, 71, 81], missing: 0 })
})
test('reports missing or ambiguous models and retains surviving selection', () => {
 assert.deepEqual(resolveGroupModels(group(), new Map([[10, models.get(10)]])), { ids: [10], missing: 2 })
 assert.deepEqual(resolveGroupModels(group(), new Map([[10, models.get(10)], [11, { ...models.get(10), id: 11 }]])), { ids: [], missing: 3 })
 assert.deepEqual(resolveGroupSeries(group(), [{ id: 1, name: 'China' }]), { ids: [1], missing: 1 })
})
test('surfaces invalid storage and quota errors instead of pretending to save', () => {
 assert.throws(() => loadModelSelectionGroups({ getItem: () => 'broken' })); assert.throws(() => loadModelSelectionGroups({ getItem: () => '{"name":"wrong"}' }))
 assert.throws(() => saveModelSelectionGroups([group()], { setItem: () => { throw new Error('full') } }), /full/)
})
