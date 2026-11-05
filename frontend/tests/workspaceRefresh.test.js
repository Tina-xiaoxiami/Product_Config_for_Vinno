import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../src/utils/useWorkspaceRefresh.js', import.meta.url), 'utf8')
  .replace(/^import .*$/gm, '').replace('export function', 'function')
function workspace(refresh, options) {
  const hooks = {}
  const ticks = []
  const use = new Function('onMounted', 'onActivated', 'nextTick', `${source}; return useWorkspaceRefresh`)(
    hook => { hooks.mount = hook }, hook => { hooks.activate = hook }, callback => ticks.push(callback)
  )
  use(refresh, options)
  hooks.finishMount = () => ticks.splice(0).forEach(callback => callback())
  return hooks
}

test('retained pages read their shared source once on mount and on each return', () => {
  let reads = 0
  const hooks = workspace(() => ++reads)
  hooks.mount(); hooks.activate()
  assert.equal(reads, 1)
  hooks.finishMount()
  hooks.activate(); hooks.activate()
  assert.equal(reads, 3)
})

test('returning to an unsaved editor preserves its draft and refreshes when safe', () => {
  let dirty = false, reads = 0
  const hooks = workspace(() => ++reads, { canRefresh: () => !dirty })
  hooks.mount(); hooks.activate()
  hooks.finishMount()
  dirty = true; hooks.activate()
  assert.equal(reads, 1)
  dirty = false; hooks.activate()
  assert.equal(reads, 2)
})

test('configuration refresh reads current series labels without restoring an older selection', async () => {
  const view = readFileSync(new URL('../src/views/Config.vue', import.meta.url), 'utf8')
  const block = view.slice(view.indexOf('let seriesLoadRequest ='), view.indexOf('// 全选系列'))
  let modelReads = 0, storageReads = 0
  const ref = value => ({ value })
  const context = {
    modelLoadRequest: 0, configReady: ref(true), configLoadError: ref(''),
    seriesList: ref([{ id: 2, name: 'Old' }]), selectedSeries: ref([2]),
    allModelsMap: ref(new Map()), selectedModels: ref([22]), tempSelectedModels: ref([22]), tableData: ref([]),
    getSeriesList: async () => ({ items: [{ id: 2, name: 'Renamed' }, { id: 3, name: 'Added' }] }),
    localStorage: { getItem: () => { storageReads++; return '{"selected_ids":[3]}' } }, SERIES_SELECTION_KEY: 'series',
    loadModels: async () => { modelReads++; return true }, ElMessage: { error() {} }
  }
  const load = new Function(...Object.keys(context), `${block};return loadSeries`)(...Object.values(context))
  assert.equal(await load({ restoreSelection: false }), true)
  assert.deepEqual(context.selectedSeries.value, [2])
  assert.deepEqual(context.selectedModels.value, [22])
  assert.equal(context.seriesList.value[0].name, 'Renamed')
  assert.equal(storageReads, 0)
  assert.equal(modelReads, 1)
})
