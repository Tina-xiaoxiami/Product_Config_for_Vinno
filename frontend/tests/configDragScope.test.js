import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
const source = readFileSync(new URL('../src/views/Config.vue', import.meta.url), 'utf8')
const ref = value => ({ value })
function app() {
  const rows = [1, 2, 3].map(id => ({ id, model_values: { 10: { final_config: id === 1 ? 'X' : 'O' }, 20: { final_config: 'O' } } }))
  const saved = []
  const ctx = {
    tableData: ref(rows), paginatedTableData: ref([rows[0], rows[2]]), selectedModels: ref([10]), visibleConfigFields: ref(['final_config']),
    dragSource: ref({ rowId: 1, modelId: 10, field: 'final_config', value: 'X', row: rows[0] }), dragTargetCells: ref([]), isDragging: ref(true),
    configReady: ref(true), loading: ref(false), applyingModelGroup: ref(false), reviewInteractionLocked: ref(false),
    isValueChanged: (a, b) => a !== b, handleCellChange: async (row, modelId, field, value) => { saved.push([row.id, modelId, field, value]); return true },
    captureDraftCellContext: (row, modelId, field) => ({ row, modelId, field }),
    ElMessage: { success() {}, error() {} }, console,
  }
  const code = source.slice(source.indexOf('const handleDragStart ='), source.indexOf('const navigateToCell =', source.indexOf('const handleDragStart =')))
  return { ...ctx, ...new Function(...Object.keys(ctx), `${code};return { highlightDragTarget, performDragFill, handleDrop, handleDragStart }`)(...Object.values(ctx)), saved, rows }
}

test('drag fills only displayed rows and follows the displayed order', async () => {
  const a = app()
  a.highlightDragTarget(3, 10, 'final_config')
  assert.deepEqual(a.dragTargetCells.value.map(c => c.rowId), [1, 3])
  await a.performDragFill()
  assert.deepEqual(a.saved, [[3, 10, 'final_config', 'X']])
  assert.equal(a.rows[1].model_values[10].final_config, 'O')
})

test('drag execution rechecks current row, model and field visibility', async () => {
  const a = app()
  a.dragTargetCells.value = [{ rowId: 2, modelId: 10, field: 'final_config' }, { rowId: 3, modelId: 20, field: 'final_config' }, { rowId: 3, modelId: 10, field: 'rd_status' }]
  await a.performDragFill()
  assert.deepEqual(a.saved, [])
})

test('drag over a different field clears old targets and drop never fills them', async () => {
  const a = app()
  a.highlightDragTarget(3, 10, 'final_config')
  a.highlightDragTarget(3, 10, 'rd_status')
  assert.deepEqual(a.dragTargetCells.value, [])
  a.dragTargetCells.value = [{ rowId: 3, modelId: 10, field: 'final_config' }]
  await a.handleDrop({ preventDefault() {} }, a.rows[2], 10, 'rd_status')
  assert.deepEqual(a.saved, [])
  assert.equal(a.isDragging.value, false)
})

test('drag cannot start while draft loading or a review blocks editing', () => {
  const a = app()
  a.isDragging.value = false; a.dragSource.value = null; a.configReady.value = false
  let prevented = false
  a.handleDragStart({ preventDefault() { prevented = true }, dataTransfer: {} }, a.rows[0], 10, 'final_config')
  assert.equal(a.isDragging.value, false)
  assert.equal(prevented, true)
})
