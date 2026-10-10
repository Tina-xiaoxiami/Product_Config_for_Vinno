import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
const source = readFileSync(new URL('../src/views/Config.vue', import.meta.url), 'utf8')
const ref = value => ({ value })
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
function batchApp(save) {
  const rows = [1, 2, 3].map(id => ({ id, model_values: { 10: { final_config: id === 2 ? 'new' : 'old' }, 20: { final_config: 'old' } } }))
  const messages = []
  const context = {
    batchEditForm: { scope: 'filtered', field: 'final_config', value: 'new' }, selectedRows: ref([rows[0]]), filteredTableData: ref(rows.slice(0, 2)), tableData: ref(rows), selectedModels: ref([10]),
    batchEditSubmitting: ref(false), batchEditDialogVisible: ref(true), batchEditResult: ref(null), batchEditTargets: ref(null),
    handleCellChange: save, captureDraftCellContext: (row, modelId, field) => ({ row, modelId, field }), isValueChanged: (a, b) => a !== b,
    ElMessage: { warning: m => messages.push(m), success: m => messages.push(m), error: m => messages.push(m) }, console,
  }
  const code = source.slice(source.indexOf('const confirmBatchEdit ='), source.indexOf('// 创建版本', source.indexOf('const confirmBatchEdit =')))
  return { ...new Function(...Object.keys(context), `${code};return { confirmBatchEdit }`)(...Object.values(context)), ...context, rows, messages }
}
test('batch filtered scope never writes a hidden row and skips unchanged values', async () => {
  const saved = []; const app = batchApp(async (row, model, field, value) => { saved.push([row.id, model, field, value]); return true })
  await app.confirmBatchEdit()
  assert.deepEqual(saved, [[1, 10, 'final_config', 'new']])
  assert.equal(app.rows[2].model_values[10].final_config, 'old')
  assert.deepEqual(app.batchEditResult.value, { success: 1, failed: 0, unchanged: 1, missing: 0 })
})
test('batch freezes models and field while saving and refuses a second click', async () => {
  const pending = deferred(); const saved = []; const app = batchApp(async (row, model, field, value) => { saved.push([row.id, model, field, value]); await pending.promise; return false })
  app.batchEditForm.scope = 'selected'; app.selectedRows.value = [app.rows[0], app.rows[2]]
  const first = app.confirmBatchEdit(); await Promise.resolve()
  app.selectedModels.value = [20]; app.batchEditForm.field = 'rd_status'; app.batchEditForm.value = 'other'
  const second = app.confirmBatchEdit(); pending.resolve(); await Promise.all([first, second])
  assert.deepEqual(saved, [[1, 10, 'final_config', 'new'], [3, 10, 'final_config', 'new']])
  assert.equal(app.batchEditResult.value.failed, 2)
})
test('publish review is backed by server preview and expected signatures for both paths', () => {
  const single = source.slice(source.indexOf('const handleSubmitDraft ='), source.indexOf('// 提交选中机型'))
  assert.match(single, /previewDraftSubmission/)
  assert.match(single, /expected_signature/)
  const batch = source.slice(source.indexOf('const handleOpenBatchSubmit ='), source.indexOf('// 计算表格高度'))
  assert.match(batch, /previewDraftSubmission/)
  assert.match(batch, /expected_signatures/)
  assert.doesNotMatch(single, /draftItems\.length/)
})
