import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { ref, computed, watch, effectScope } from 'vue'

const source = readFileSync(new URL('../src/views/Config.vue', import.meta.url), 'utf8')
const fields = ['final_config', 'current_config', 'selection_config', 'rd_status']

function editor() {
  const row = { id: 1, model_values: { 2: { final_config: 'published' } } }
  const other = { id: 9, model_values: { 2: { final_config: 'published' } } }
  const ticks = [], timers = new Map(), saves = [], undos = []
  let timerId = 0
  const context = {
    ref, watch, configReady: ref(true), loading: ref(false), applyingModelGroup: ref(false),
    reviewInteractionLocked: ref(false), submitDialogVisible: ref(false), batchSubmitDialog: { visible: false },
    editingCell: ref(null), editSelectRef: ref(null), currentPage: ref(1), pageSize: ref(20),
    selectedModels: ref([2]), visibleConfigFields: ref(fields), tableData: ref([row, other]),
    draftBatchMap: ref(new Map([[10, 20]])), originalData: ref([row, other]), draftChanges: ref(new Map()),
    nextTick: callback => ticks.push(callback),
    setTimeout: callback => { timers.set(++timerId, callback); return timerId }, clearTimeout: id => timers.delete(id),
    captureDraftCellContext: (target, modelId, field, key) => ({ row: target, modelId, field, key, seriesId: 10, batchId: context.draftBatchMap.value.get(10), originalRow: { model_values: { 2: { final_config: 'published' } } } }),
    isDraftCellScopeCurrent: captured => captured.batchId === context.draftBatchMap.value.get(10),
    isDraftCellContextCurrent: captured => context.tableData.value.includes(captured.row) && captured.batchId === context.draftBatchMap.value.get(10),
    draftBaseline: (change, fallback) => change ? change.oldValue : fallback,
    isValueChanged: (a, b) => a !== b, hasPendingDraftCellOperation: () => false,
    removeDraftChange: async (...args) => undos.push(args), handleCellChange: async (...args) => saves.push(args)
  }
  context.paginatedTableData = computed(() => context.currentPage.value === 1 ? context.tableData.value : [])
  const from = source.includes('let editSessionSequence =') ? source.indexOf('let editSessionSequence =') : source.indexOf('const startEdit =')
  const code = source.slice(from, source.indexOf('const draftSaveFeedback ='))
  const lifecycleFrom = source.indexOf('// 编辑会话范围清理')
  const lifecycle = lifecycleFrom < 0 ? '' : source.slice(lifecycleFrom, source.indexOf('// 编辑会话范围清理结束', lifecycleFrom))
  const scope = effectScope()
  const app = scope.run(() => new Function(...Object.keys(context), `${code}\n${lifecycle}\nreturn {startEdit, finishEdit, cancelEditSession: typeof cancelEditSession === 'function' ? cancelEditSession : () => {}, ...{}}`)(...Object.values(context)))
  return { ...context, ...app, row: context.tableData.value[0], other: context.tableData.value[1], saves, undos, ticks, timers, flushTicks: () => ticks.splice(0).forEach(fn => fn()), flushTimers: () => { const callbacks = [...timers.values()]; timers.clear(); callbacks.forEach(fn => fn()) }, stop: () => scope.stop() }
}
const begin = (app, row = app.row) => { app.startEdit(row, 2, 'final_config'); return app.editingCell.value }

test('old blur cannot write or close another cell session', async () => {
  const app = editor(), first = begin(app), next = begin(app, app.other)
  await app.finishEdit(app.row, 2, 'final_config', 'O', first)
  assert.equal(app.saves.length, 0)
  assert.equal(app.editingCell.value, next)
})
test('same-cell reopened session rejects callback from its prior editor', async () => {
  const app = editor(), first = begin(app)
  app.cancelEditSession(); const next = begin(app)
  await app.finishEdit(app.row, 2, 'final_config', 'O', first)
  assert.equal(app.saves.length, 0)
  assert.equal(app.editingCell.value, next)
})
test('batch switch and replaced row reject original edit context', async () => {
  const app = editor(), session = begin(app)
  app.draftBatchMap.value.set(10, 30)
  await app.finishEdit(app.row, 2, 'final_config', 'O', session)
  assert.equal(app.saves.length, 0)
  const current = begin(app)
  app.tableData.value = [{ ...app.row }]
  await app.finishEdit(app.row, 2, 'final_config', 'O', current)
  assert.equal(app.saves.length, 0)
})
test('change plus blur submit once with the captured draft scope', async () => {
  const app = editor(), session = begin(app)
  await app.finishEdit(app.row, 2, 'final_config', 'O', session)
  await app.finishEdit(app.row, 2, 'final_config', 'O', session)
  assert.equal(app.saves.length, 1)
  assert.equal(app.saves[0][5].batchId, 20)
  assert.equal(app.row.model_values[2].final_config, 'O')
})
test('reverting to baseline carries the original context into undo', async () => {
  const app = editor(); app.draftChanges.value.set('1_2_final_config', { oldValue: 'published' })
  const session = begin(app)
  await app.finishEdit(app.row, 2, 'final_config', 'published', session)
  assert.equal(app.undos.length, 1)
  assert.equal(app.undos[0][4].batchId, 20)
})
test('editor selection stays local until its session is committed', () => {
  const app = editor(), session = begin(app)
  session.value = 'O'
  assert.equal(app.row.model_values[2].final_config, 'published')
  for (const field of fields) {
    assert.ok(source.includes(`@change="finishEdit(row, modelId, '${field}', session.value, session)"`))
    assert.ok(source.includes(`@blur="finishEdit(row, modelId, '${field}', session.value, session)"`))
  }
  assert.equal((source.match(/v-model="session.value"/g) || []).length, 4)
})
test('rapid editor transitions focus and open only the current select', () => {
  const app = editor(); let focused = 0, toggled = 0
  begin(app); begin(app, app.other)
  app.editSelectRef.value = { expanded: false, focus: () => focused++, toggleMenu: () => toggled++ }
  app.flushTicks(); app.flushTimers()
  assert.equal(focused, 1); assert.equal(toggled, 1)
})
test('same editor click does not schedule another open or close an expanded menu', () => {
  const app = editor(); let toggled = 0
  const first = begin(app); begin(app)
  app.editSelectRef.value = { expanded: true, focus() {}, toggleMenu: () => toggled++ }
  app.flushTicks(); app.flushTimers()
  assert.equal(app.editingCell.value, first); assert.equal(toggled, 0)
})
test('delayed opening rejects a select ref replaced after focus', () => {
  const app = editor(); let toggled = 0
  begin(app)
  app.editSelectRef.value = { expanded: false, focus() {}, toggleMenu: () => toggled++ }
  app.flushTicks(); app.editSelectRef.value = { expanded: false, focus() {}, toggleMenu: () => toggled++ }
  app.flushTimers(); assert.equal(toggled, 0)
})
for (const transition of ['page', 'model', 'field', 'batch']) {
  test(`${transition} transition cancels session and its pending dropdown timer`, () => {
    const app = editor(); let toggled = 0
    begin(app); app.editSelectRef.value = { expanded: false, focus() {}, toggleMenu: () => toggled++ }; app.flushTicks()
    if (transition === 'page') app.currentPage.value = 2
    if (transition === 'model') app.selectedModels.value = []
    if (transition === 'field') app.visibleConfigFields.value = []
    if (transition === 'batch') app.draftBatchMap.value.set(10, 30)
    app.flushTimers()
    assert.equal(app.editingCell.value, null); assert.equal(toggled, 0)
    app.stop()
  })
}
test('unmount explicitly cancels editor work', () => {
  const hook = source.slice(source.indexOf('onUnmounted(() =>'), source.indexOf('watch([selectedSeries'))
  assert.match(hook, /cancelEditSession\(\)/)
})
