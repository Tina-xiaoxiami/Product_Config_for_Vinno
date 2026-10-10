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

function publishApp(overrides = {}) {
  const messages = []; const requests = []
  const review = id => ({ batch_id: id, series_name: `系列 ${id}`, total_items: 2, total_changes: 3, total_models: 1, signature: `signature-${id}`, remaining_changes: 1,
    models: [{ id: 10, name: '机型' }], fields: ['final_config'], drafts: [{ item_id: 1, model_id: 10, field_name: 'final_config' }, { item_id: 2, model_id: 10, field_name: 'final_config' }, { item_id: 1, model_id: 20, field_name: 'final_config' }] })
  const context = {
    submitSubmitting: ref(false), submitPreviewLoading: ref(false), submitPreviewError: ref(''), submitPreviews: ref([]), submitResults: ref([]), submitDialogVisible: ref(false), submitScope: ref(null), submitPreviewRequest: 0,
    submitForm: { version_number: '', description: '', item_ids: null, model_ids: null },
    batchSubmitDialog: { visible: false, loading: false, error: '', selectedBatchIds: [], availableBatches: [], scope: null }, batchSubmitSubmitting: ref(false), batchSubmitPreviewRequest: 0, batchSubmitResultDialog: { visible: false, results: [] },
    draftBatchMap: ref(new Map([[100, 200], [101, 201]])), selectedSeries: ref([100, 101]), paginatedTableData: ref([{ id: 1 }]), selectedModels: ref([10]), visibleConfigFields: ref(['final_config']), draftCellOperations: new Map(),
    previewDraftSubmission: async id => review(id), submitDraftBatch: async (id, params) => { requests.push({ id, params }); return { changes: 3 } },
    getCurrentDraftBatch: async id => ({ exists: true, batch: { id: id + 100 } }), batchSubmitDrafts: async params => { requests.push({ params }); return { submitted_count: 2, results: params.batch_ids.map(id => ({ batch_id: id, success: true })) } },
    loadData: async () => true, initDraft: async () => true, ElMessage: { info: m => messages.push(m), success: m => messages.push(m), warning: m => messages.push(m), error: m => messages.push(m) }, ...overrides
  }
  const single = source.slice(source.indexOf('const fieldLabels ='), source.indexOf('// 提交选中机型'))
  const batch = source.slice(source.indexOf('const handleOpenBatchSubmit ='), source.indexOf('// 计算表格高度'))
  const methods = new Function(...Object.keys(context), `${single}\n${batch};return { handleSubmitDraft, refreshSubmitPreview, confirmSubmitDraft, handleOpenBatchSubmit, confirmBatchSubmit, describeSubmission }`)(...Object.values(context))
  return { ...context, ...methods, requests, messages, review }
}
test('publish preview identifies hidden rows and models and freezes chosen item scope', async () => {
  const app = publishApp(); const ids = new Set([1]); await app.handleSubmitDraft(ids)
  ids.add(99); app.draftBatchMap.value = new Map([[999, 999]])
  assert.equal(app.submitPreviews.value[0].hidden_changes, 2)
  await app.confirmSubmitDraft()
  assert.deepEqual(app.requests.map(request => request.id), [200, 201])
  assert.deepEqual(app.requests[0].params.item_ids, [1])
  assert.equal(app.requests[0].params.expected_signature, 'signature-200')
})
test('pending or failed publish preview cannot submit anything', async () => {
  const pending = deferred(); const app = publishApp({ previewDraftSubmission: () => pending.promise })
  const open = app.handleSubmitDraft(); await Promise.resolve(); await app.confirmSubmitDraft(); assert.equal(app.requests.length, 0)
  pending.resolve({ total_changes: 0, drafts: [] }); await open
  await app.confirmSubmitDraft(); assert.equal(app.requests.length, 0)
  const failed = publishApp({ previewDraftSubmission: async () => { throw new Error('offline') } })
  await failed.handleSubmitDraft(); await failed.confirmSubmitDraft(); assert.equal(failed.requests.length, 0); assert.match(failed.submitPreviewError.value, /无法核验/)
})
test('publish freezes text and signatures and ignores a second confirmation', async () => {
  const pending = deferred(); const requests = []
  const app = publishApp({ submitDraftBatch: async (id, params) => { requests.push({ id, params }); await pending.promise; return {} } })
  await app.handleSubmitDraft(); app.submitForm.version_number = 'V1'
  const first = app.confirmSubmitDraft(); app.submitForm.version_number = 'V2'; await app.confirmSubmitDraft(); pending.resolve(); await first
  assert.equal(requests.length, 2); assert.equal(requests[1].params.version_number, 'V1')
})
test('partial publication reports each outcome and requires a fresh preview before retry', async () => {
  const app = publishApp({ submitDraftBatch: async id => { if (id === 201) { const error = new Error('stale'); error.response = { data: { detail: '草稿已变化' } }; throw error } return {} } })
  await app.handleSubmitDraft(); await app.confirmSubmitDraft()
  assert.equal(app.submitDialogVisible.value, true)
  assert.deepEqual(app.submitResults.value.map(result => result.success), [true, false])
  assert.match(app.submitResults.value[1].message, /草稿已变化/)
  assert.match(app.submitPreviewError.value, /刷新范围/)
})
test('batch publication sends only reviewed series and their signatures', async () => {
  const app = publishApp(); await app.handleOpenBatchSubmit(); app.batchSubmitDialog.selectedBatchIds = [201]
  await app.confirmBatchSubmit()
  assert.deepEqual(app.requests[0].params.batch_ids, [201])
  assert.deepEqual(app.requests[0].params.expected_signatures, { 201: 'signature-201' })
})

test('reset columns uses the same defaults as first use', () => {
  const defaultCode = source.slice(source.indexOf('const defaultVisibleColumns ='), source.indexOf('// 从 localStorage 加载设置'))
  const defaults = new Function(`${defaultCode};return { defaultVisibleColumns, defaultFixedColumns }`)()
  const tempVisibleColumns = {}; const tempFixedColumns = {}
  const resetCode = source.slice(source.indexOf('const resetTempColumns ='), source.indexOf('// 清除所有选择'))
  const reset = new Function('tempVisibleColumns', 'tempFixedColumns', 'defaultVisibleColumns', 'defaultFixedColumns', `${resetCode};return resetTempColumns`)(tempVisibleColumns, tempFixedColumns, defaults.defaultVisibleColumns, defaults.defaultFixedColumns)
  reset()
  assert.deepEqual(tempVisibleColumns, defaults.defaultVisibleColumns)
  assert.deepEqual(tempFixedColumns, defaults.defaultFixedColumns)
})

test('row-wide publish review displays configuration values rather than item name', () => {
  const match = source.match(/const formatSubmissionValue = [\s\S]*?(?=const captureVisibleSubmissionScope =)/)
  assert.ok(match, 'publish preview needs a row-wide configuration value renderer')
  const fieldLabels = { final_config: '最终配置', current_config: '当前配置', selection_config: '选型类别', rd_status: '研发状态' }
  const format = new Function('fieldLabels', `${match[0]};return formatSubmissionValue`)(fieldLabels)
  const create = { field_name: null, new_value: 'S1-8CMV【启用】', old_values: {}, new_values: { final_config: 'X', current_config: '●', selection_config: '标准', rd_status: '已完成' } }
  assert.equal(format(create, 'new'), '最终配置：X；当前配置：●；选型类别：标准；研发状态：已完成')
  assert.equal(format(create, 'old'), '最终配置：-；当前配置：-；选型类别：-；研发状态：-')
  assert.equal(format({ field_name: 'final_config', old_value: '●', new_value: 'X' }, 'new'), 'X')
})

test('large import impact groups every affected model by series without hiding cross-series effects', () => {
  const match = source.match(/const groupImportImpactModels = [\s\S]*?(?=const impactModelGroups =)/)
  assert.ok(match, 'affected model preview needs grouped compact scope')
  const groupModels = new Function(`${match[0]};return groupImportImpactModels`)()
  const models = Array.from({ length: 101 }, (_, index) => ({ model_id: index + 1, model_name: `机型 ${index + 1}`, series_name: `系列 ${index % 6 + 1}` }))
  const groups = groupModels(models)
  assert.equal(groups.length, 6)
  assert.equal(groups.reduce((count, group) => count + group.models.length, 0), 101)
  assert.equal(groups.find(group => group.seriesName === '系列 6').models.length, 16)
  assert.deepEqual(groups.flatMap(group => group.models).map(model => model.model_id).sort((a, b) => a - b), models.map(model => model.model_id))
  assert.deepEqual(groupModels([]), [])
})

test('import shared field labels use readable business names', () => {
  const code = source.match(/const fieldLabels = \{[^\n]+/)[0]
  const labels = new Function(`${code};return fieldLabels`)()
  assert.deepEqual(['row_index', 'zh_desc', 'rd_name', 'v_code', 'ipn', 'en_desc', 'category'].map(field => labels[field]), ['排序位置', '中文描述', '研发名称', 'V代码', 'IPN号', '英文描述', '分类'])
})
