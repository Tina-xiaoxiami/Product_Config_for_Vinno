import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { draftBaseline, draftWorkingValue, updateDraftStats } from '../src/utils/configDraftHelpers.js'

const source = readFileSync(new URL('../src/views/Config.vue', import.meta.url), 'utf8')
const ref = value => ({ value })

function deferred() {
  let resolve
  let reject
  const promise = new Promise((onResolve, onReject) => {
    resolve = onResolve
    reject = onReject
  })
  return { promise, resolve, reject }
}

function draftEditor({ createDraft, deleteDraftByKey, batchReady = true, change, rowValue = 'attempted' } = {}) {
  const row = { id: 1, model_values: { 2: { final_config: rowValue } } }
  const originalRow = { id: 1, model_values: { 2: { final_config: 'published' } } }
  const messages = []
  const draftChanges = ref(new Map(change ? [['1_2_final_config', change]] : []))
  const tableData = ref([row])
  const context = {
    reactive: value => value,
    selectedSeries: ref([10]),
    editingCell: ref(null),
    originalData: ref([originalRow]),
    originalDataMap: ref(new Map([[1, originalRow]])),
    isValueChanged: (oldValue, newValue) => oldValue !== newValue,
    draftWorkingValue,
    draftChanges,
    tableData,
    findSeriesIdByModelId: () => 10,
    draftBatchMap: ref(batchReady ? new Map([[10, 20]]) : new Map()),
    ElMessage: { error: message => messages.push(message) },
    console: { error() {} },
    deleteDraftByKey: deleteDraftByKey || (async () => {}),
    draftStats: { total: change ? 1 : 0, create: 0, update: change ? 1 : 0, delete: 0 },
    updateDraftStats,
    draftBaseline,
    createDraft: createDraft || (async () => ({ draft_id: 30 }))
  }
  const code = source.slice(
    source.indexOf('const finishEdit ='),
    source.indexOf('// 多文件上传处理')
  )
  const { finishEdit, removeDraftChange, handleCellChange, draftSaveFeedback, retryFailedCell, refreshSaveFeedback, undoLastCell } = new Function(
    ...Object.keys(context),
    `${code}\nreturn { finishEdit, removeDraftChange, handleCellChange, draftSaveFeedback, retryFailedCell, refreshSaveFeedback, undoLastCell }`
  )(...Object.values(context))
  return {
    finishEdit,
    draftSaveFeedback,
    retryFailedCell,
    refreshSaveFeedback,
    undoLastCell,
    removeDraftChange,
    handleCellChange,
    messages,
    row,
    tableData,
    draftChanges,
    originalDataMap: context.originalDataMap,
    draftBatchMap: context.draftBatchMap
  }
}

function draftLoadingController({ getModels, loadData, initDraft }) {
  const context = {
    selectedSeries: ref([10]),
    allModelsMap: ref(new Map()),
    selectedModels: ref([]),
    tempSelectedModels: ref([]),
    tableData: ref([]),
    originalData: ref([]),
    seriesList: ref([{ id: 10, name: 'V10' }, { id: 20, name: 'V20' }]),
    configReady: ref(true),
    getModels,
    loadData,
    initDraft,
    resolveGroupModels: () => null,
    applySavedOrder() {},
    showDiffOnly: ref(false),
    referenceModel: ref(null),
    ElMessage: { warning() {}, error() {} },
    console: { error() {} },
    loadSeries: async () => {}
  }
  const code = source.slice(
    source.indexOf('let modelLoadRequest ='),
    source.indexOf('// 加载配置数据')
  )
  const loadModels = new Function(
    ...Object.keys(context),
    `${code}\nreturn loadModels`
  )(...Object.values(context))
  return { loadModels, ...context }
}

function cellEditor({ ready = true, loading = false, applyingModelGroup = false } = {}) {
  const context = {
    configReady: ref(ready),
    loading: ref(loading),
    applyingModelGroup: ref(applyingModelGroup),
    submitDialogVisible: ref(false),
    batchSubmitDialog: { visible: false },
    editingCell: ref(null),
    nextTick: callback => callback(),
    editSelectRef: ref(null),
    setTimeout
  }
  const code = source.slice(
    source.indexOf('const startEdit ='),
    source.indexOf('// 结束编辑单元格')
  )
  const startEdit = new Function(
    ...Object.keys(context),
    `${code}\nreturn startEdit`
  )(...Object.values(context))
  return { startEdit, editingCell: context.editingCell }
}

function clearCellAction(handleCellChange) {
  const messages = []
  const context = {
    hideContextMenu() {},
    contextMenu: {
      row: { id: 1, model_values: { 2: { final_config: 'old' } } },
      modelId: 2,
      field: 'final_config'
    },
    handleCellChange,
    ElMessage: {
      success: message => messages.push(message),
      error() {}
    }
  }
  const code = source.slice(
    source.indexOf('// 处理清空单元格'),
    source.indexOf('// 处理复制整行配置')
  )
  const handleClearCell = new Function(
    ...Object.keys(context),
    `${code}\nreturn handleClearCell`
  )(...Object.values(context))
  return { handleClearCell, messages }
}

function dragFillAction(handleCellChange) {
  const messages = []
  const context = {
    dragSource: ref({ rowId: 9, modelId: 9, field: 'final_config', value: 'new' }),
    dragTargetCells: ref([{ rowId: 1, modelId: 2, field: 'final_config' }]),
    tableData: ref([{ id: 1, model_values: { 2: { final_config: 'old' } } }]),
    paginatedTableData: ref([{ id: 1, model_values: { 2: { final_config: 'old' } } }]),
    selectedModels: ref([2]), visibleConfigFields: ref(['final_config']),
    configReady: ref(true), loading: ref(false), applyingModelGroup: ref(false), reviewInteractionLocked: ref(false),
    captureDraftCellContext: (row, modelId, field) => ({ row, modelId, field }),
    isValueChanged: (oldValue, newValue) => oldValue !== newValue,
    handleCellChange,
    ElMessage: {
      success: message => messages.push(message),
      error() {}
    }
  }
  const code = source.slice(
    source.indexOf('const performDragFill = async'),
    source.indexOf('// 拖拽结束')
  )
  const performDragFill = new Function(
    ...Object.keys(context),
    `${code}\nreturn performDragFill`
  )(...Object.values(context))
  return { performDragFill, messages }
}

test('draft save reports failure after restoring the previous working value', async () => {
  const previous = { oldValue: 'published', newValue: 'working', changeType: 'update' }
  const app = draftEditor({
    change: previous,
    createDraft: async () => {
      const error = new Error('offline')
      error.response = { data: { detail: 'network unavailable' } }
      throw error
    }
  })

  assert.equal(await app.handleCellChange(app.row, 2, 'final_config', 'attempted', 'working'), false)
  assert.equal(app.row.model_values[2].final_config, 'working')
  assert.deepEqual(app.messages, ['保存失败: network unavailable'])
})

test('single-cell actions only announce success when the draft was saved', async () => {
  const failed = clearCellAction(async () => false)
  await failed.handleClearCell()
  assert.deepEqual(failed.messages, [])

  const saved = clearCellAction(async () => true)
  await saved.handleClearCell()
  assert.deepEqual(saved.messages, ['已清空'])
})

test('bulk actions report only successfully saved cells', async () => {
  const failed = dragFillAction(async () => false)
  await failed.performDragFill()
  assert.deepEqual(failed.messages, [])

  const saved = dragFillAction(async () => true)
  await saved.performDragFill()
  assert.deepEqual(saved.messages, ['已填充 1 个单元格'])
})

test('an older failed save cannot roll back a newer successful save', async () => {
  const first = deferred()
  const second = deferred()
  const requests = [first, second]
  const app = draftEditor({
    rowValue: 'new',
    change: { oldValue: 'published', newValue: 'working', changeType: 'update' },
    createDraft: () => requests.shift().promise
  })

  const olderSave = app.handleCellChange(app.row, 2, 'final_config', 'new', 'working')
  const newerSave = app.handleCellChange(app.row, 2, 'final_config', 'new', 'working')
  first.reject(new Error('older request failed'))
  assert.equal(await olderSave, false)
  second.resolve({ draft_id: 31 })
  assert.equal(await newerSave, true)

  assert.equal(app.row.model_values[2].final_config, 'new')
  assert.equal(app.draftChanges.value.get('1_2_final_config').newValue, 'new')
  assert.deepEqual(app.messages, [])
})

test('undo queued while the first save is pending deletes the saved draft', async () => {
  const saveRequest = deferred()
  let deleteCount = 0
  const app = draftEditor({
    createDraft: () => saveRequest.promise,
    deleteDraftByKey: async () => { deleteCount++ }
  })

  const save = app.finishEdit(app.row, 2, 'final_config', 'attempted')
  app.row.model_values[2].final_config = 'published'
  const undo = app.finishEdit(app.row, 2, 'final_config', 'published')
  saveRequest.resolve({ draft_id: 30 })
  await Promise.all([save, undo])

  assert.equal(deleteCount, 1)
  assert.equal(app.draftChanges.value.has('1_2_final_config'), false)
  assert.equal(app.row.model_values[2].final_config, 'published')
})

test('a failed undo cannot roll back a newer queued save', async () => {
  const deleteRequest = deferred()
  const saveRequest = deferred()
  const app = draftEditor({
    rowValue: 'new',
    change: { oldValue: 'published', newValue: 'working', changeType: 'update' },
    deleteDraftByKey: () => deleteRequest.promise,
    createDraft: () => saveRequest.promise
  })

  const undo = app.removeDraftChange(app.row, 2, 'final_config', '1_2_final_config')
  const save = app.handleCellChange(app.row, 2, 'final_config', 'new', 'working')
  deleteRequest.reject(new Error('delete failed'))
  await undo
  await Promise.resolve()
  saveRequest.resolve({ draft_id: 32 })
  assert.equal(await save, true)

  assert.equal(app.row.model_values[2].final_config, 'new')
  assert.equal(app.draftChanges.value.get('1_2_final_config').newValue, 'new')
  assert.deepEqual(app.messages, [])
})

test('a stale save failure does not modify a replacement row with recycled ids', async () => {
  const saveRequest = deferred()
  const app = draftEditor({ createDraft: () => saveRequest.promise })
  const save = app.handleCellChange(app.row, 2, 'final_config', 'attempted', 'published')
  const replacement = { id: 1, model_values: { 2: { final_config: 'replacement' } } }
  app.tableData.value = [replacement]

  saveRequest.reject(new Error('old scope failed'))
  assert.equal(await save, false)

  assert.equal(replacement.model_values[2].final_config, 'replacement')
})

test('a queued undo still deletes an old-scope save after the table is replaced', async () => {
  const saveRequest = deferred()
  let deleteCount = 0
  const app = draftEditor({
    createDraft: () => saveRequest.promise,
    deleteDraftByKey: async () => { deleteCount++ }
  })

  const save = app.finishEdit(app.row, 2, 'final_config', 'attempted')
  app.row.model_values[2].final_config = 'published'
  const undo = app.finishEdit(app.row, 2, 'final_config', 'published')
  const replacement = { id: 1, model_values: { 2: { final_config: 'replacement' } } }
  app.tableData.value = [replacement]
  app.draftBatchMap.value = new Map([[10, 21]])
  saveRequest.resolve({ draft_id: 30 })
  await Promise.all([save, undo])

  assert.equal(deleteCount, 1)
  assert.equal(replacement.model_values[2].final_config, 'replacement')
})

test('table refresh keeps requests for the same backend cell serialized', async () => {
  const first = deferred()
  let requestCount = 0
  let backendValue = 'published'
  const app = draftEditor({ createDraft: async payload => {
    requestCount++
    if (requestCount === 1) await first.promise
    backendValue = payload.new_value
    return { draft_id: 30 }
  } })
  const olderSave = app.handleCellChange(app.row, 2, 'final_config', 'older', 'published')
  await Promise.resolve()
  const replacement = { id: 1, model_values: { 2: { final_config: 'newer' } } }
  app.tableData.value = [replacement]
  const newerSave = app.handleCellChange(replacement, 2, 'final_config', 'newer', 'published')
  await Promise.resolve()
  assert.equal(requestCount, 1)
  first.resolve()
  await Promise.all([olderSave, newerSave])
  assert.equal(backendValue, 'newer')
  assert.equal(replacement.model_values[2].final_config, 'newer')
  assert.equal(app.draftChanges.value.get('1_2_final_config').newValue, 'newer')
})

test('failed replacement-row save restores the last successful same-scope value', async () => {
  const first = deferred()
  let requestCount = 0
  const app = draftEditor({ createDraft: async () => {
    if (++requestCount === 1) { await first.promise; return { draft_id: 30 } }
    throw new Error('latest failed')
  } })
  const olderSave = app.handleCellChange(app.row, 2, 'final_config', 'older', 'published')
  await Promise.resolve()
  const replacement = { id: 1, model_values: { 2: { final_config: 'newer' } } }
  app.tableData.value = [replacement]
  const newerSave = app.handleCellChange(replacement, 2, 'final_config', 'newer', 'published')
  first.resolve()
  assert.equal(await olderSave, true)
  assert.equal(await newerSave, false)
  assert.equal(replacement.model_values[2].final_config, 'older')
  assert.equal(app.draftChanges.value.get('1_2_final_config').newValue, 'older')
})


test('failed save after refresh and successful undo restores the published baseline', async () => {
  const deletion = deferred()
  const app = draftEditor({
    rowValue: 'working',
    change: { oldValue: 'published', newValue: 'working', changeType: 'update' },
    deleteDraftByKey: () => deletion.promise,
    createDraft: async () => { throw new Error('new save failed') }
  })
  const undo = app.removeDraftChange(app.row, 2, 'final_config', '1_2_final_config')
  await Promise.resolve()
  const replacement = { id: 1, model_values: { 2: { final_config: 'newer' } } }
  const replacementOriginal = { id: 1, model_values: { 2: { final_config: 'working' } } }
  app.tableData.value = [replacement]
  app.originalDataMap.value = new Map([[1, replacementOriginal]])
  const save = app.handleCellChange(replacement, 2, 'final_config', 'newer', 'working')
  deletion.resolve()
  assert.equal(await undo, true)
  assert.equal(await save, false)
  assert.equal(replacement.model_values[2].final_config, 'published')
  assert.equal(replacementOriginal.model_values[2].final_config, 'published')
  assert.equal(app.draftChanges.value.has('1_2_final_config'), false)
})

test('successful save reconciles the replacement row after a same-scope filter refresh', async () => {
  const saveRequest = deferred()
  const app = draftEditor({ createDraft: () => saveRequest.promise })
  const save = app.handleCellChange(app.row, 2, 'final_config', 'attempted', 'published')

  const replacement = { id: 1, model_values: { 2: { final_config: 'published' } } }
  app.tableData.value = [replacement]
  saveRequest.resolve({ draft_id: 33 })
  assert.equal(await save, true)

  assert.equal(replacement.model_values[2].final_config, 'attempted')
  assert.equal(app.draftChanges.value.get('1_2_final_config').newValue, 'attempted')
})

test('successful undo reconciles the replacement row after a same-scope filter refresh', async () => {
  const deleteRequest = deferred()
  const app = draftEditor({
    rowValue: 'working',
    change: { oldValue: 'published', newValue: 'working', changeType: 'update' },
    deleteDraftByKey: () => deleteRequest.promise
  })
  const undo = app.removeDraftChange(app.row, 2, 'final_config', '1_2_final_config')

  const replacement = { id: 1, model_values: { 2: { final_config: 'working' } } }
  app.tableData.value = [replacement]
  deleteRequest.resolve()
  assert.equal(await undo, true)

  assert.equal(replacement.model_values[2].final_config, 'published')
  assert.equal(app.draftChanges.value.has('1_2_final_config'), false)
})

test('same-scope reconciliation does not overwrite a newer queued edit', async () => {
  const first = deferred()
  const second = deferred()
  const requests = [first, second]
  const app = draftEditor({ createDraft: () => requests.shift().promise })
  const olderSave = app.handleCellChange(app.row, 2, 'final_config', 'older', 'published')
  const replacement = { id: 1, model_values: { 2: { final_config: 'newer' } } }
  app.tableData.value = [replacement]
  const newerSave = app.handleCellChange(replacement, 2, 'final_config', 'newer', 'published')

  first.resolve({ draft_id: 34 })
  assert.equal(await olderSave, true)
  assert.equal(replacement.model_values[2].final_config, 'newer')
  second.resolve({ draft_id: 35 })
  assert.equal(await newerSave, true)
  assert.equal(replacement.model_values[2].final_config, 'newer')
})

test('successful old-scope save does not modify a replacement row in a new draft batch', async () => {
  const saveRequest = deferred()
  const app = draftEditor({ createDraft: () => saveRequest.promise })
  const save = app.handleCellChange(app.row, 2, 'final_config', 'attempted', 'published')
  const replacement = { id: 1, model_values: { 2: { final_config: 'new-scope' } } }
  app.tableData.value = [replacement]
  app.draftBatchMap.value = new Map([[10, 21]])

  saveRequest.resolve({ draft_id: 36 })
  assert.equal(await save, true)
  assert.equal(replacement.model_values[2].final_config, 'new-scope')
  assert.equal(app.draftChanges.value.has('1_2_final_config'), false)
})

test('model loading keeps editing unready until draft initialization finishes', async () => {
  const draftRequest = deferred()
  const app = draftLoadingController({
    getModels: async () => ({ items: [{ id: 2, name: 'V10' }] }),
    loadData: async () => true,
    initDraft: () => draftRequest.promise
  })

  const load = app.loadModels()
  await Promise.resolve()
  await Promise.resolve()
  assert.equal(app.configReady.value, false)

  draftRequest.resolve(true)
  assert.equal(await load, true)
  assert.equal(app.configReady.value, true)
})

test('a stale series load cannot reopen editing while the latest draft initializes', async () => {
  const firstModels = deferred()
  const latestDraft = deferred()
  const app = draftLoadingController({
    getModels: seriesId => seriesId === 10
      ? firstModels.promise
      : Promise.resolve({ items: [{ id: 3, name: 'V20' }] }),
    loadData: async () => true,
    initDraft: () => latestDraft.promise
  })

  const staleLoad = app.loadModels()
  app.selectedSeries.value = [20]
  const latestLoad = app.loadModels()
  await Promise.resolve()
  await Promise.resolve()
  firstModels.resolve({ items: [{ id: 2, name: 'V10' }] })
  assert.equal(await staleLoad, false)
  assert.equal(app.configReady.value, false)

  latestDraft.resolve(true)
  assert.equal(await latestLoad, true)
  assert.equal(app.configReady.value, true)
})

test('cell editing is gated by aggregate configuration readiness', () => {
  const unready = cellEditor({ ready: false })
  unready.startEdit({ id: 1 }, 2, 'final_config')
  assert.equal(unready.editingCell.value, null)

  const loading = cellEditor({ ready: true, loading: true })
  loading.startEdit({ id: 1 }, 2, 'final_config')
  assert.equal(loading.editingCell.value, null)

  const ready = cellEditor()
  ready.startEdit({ id: 1 }, 2, 'final_config')
  assert.deepEqual(ready.editingCell.value, { rowId: 1, modelId: 2, field: 'final_config' })
})


test('failed undo exposes an undo retry rather than an unavailable save retry', async () => {
  let calls = 0
  const app = draftEditor({ change: { oldValue: 'published', newValue: 'working', changeType: 'update' }, deleteDraftByKey: async () => { if (++calls === 1) throw new Error('offline') } })
  assert.equal(await app.removeDraftChange(app.row, 2, 'final_config', '1_2_final_config'), false)
  assert.equal(app.draftSaveFeedback.failedCell.action, 'undo')
  await app.retryFailedCell()
  assert.equal(calls, 2)
  assert.equal(app.draftSaveFeedback.lastCell, null)
  assert.equal(app.draftChanges.value.has('1_2_final_config'), false)
})

for (const order of ['failure-first', 'success-first']) {
  test(`independent cell outcomes preserve failed retry and successful undo (${order})`, async () => {
    const failing = deferred(); const saving = deferred(); let retried = false
    const app = draftEditor({ createDraft: payload => payload.item_id === 1
      ? retried ? Promise.resolve({ draft_id: 41 }) : failing.promise
      : saving.promise })
    const secondRow = { id: 2, model_values: { 2: { final_config: 'second' } } }
    app.tableData.value.push(secondRow)
    app.originalDataMap.value.set(2, { id: 2, model_values: { 2: { final_config: 'published-second' } } })
    const first = app.handleCellChange(app.row, 2, 'final_config', 'first', 'published')
    const second = app.handleCellChange(secondRow, 2, 'final_config', 'second', 'published-second')
    if (order === 'failure-first') { failing.reject(new Error('offline')); await first; saving.resolve({ draft_id: 40 }); await second }
    else { saving.resolve({ draft_id: 40 }); await second; failing.reject(new Error('offline')); await first }
    assert.equal(app.draftSaveFeedback.failedCell?.row.id, 1)
    assert.equal(app.draftSaveFeedback.lastCell?.row.id, 2)
    assert.match(app.draftSaveFeedback.message, /失败/)
    retried = true; await app.retryFailedCell()
    assert.equal(app.draftSaveFeedback.failedCell, null)
    assert.equal(app.draftChanges.value.get('1_2_final_config').newValue, 'first')
    assert.equal(app.draftChanges.value.get('2_2_final_config').newValue, 'second')
  })
}


test('switching draft batches prunes unavailable retry and undo feedback before another save', async () => {
  let requestCount = 0
  const app = draftEditor({ createDraft: async () => { if (++requestCount === 1) throw new Error('offline'); return { draft_id: 40 } } })
  await app.handleCellChange(app.row, 2, 'final_config', 'failed-A')
  assert.equal(app.draftSaveFeedback.failedCell.row.id, 1)
  app.draftBatchMap.value = new Map([[10, 21]])
  app.refreshSaveFeedback()
  assert.equal(app.draftSaveFeedback.failedCell, null)
  assert.equal(app.draftSaveFeedback.message, '')
  await app.handleCellChange(app.row, 2, 'final_config', 'saved-B')
  assert.equal(app.draftSaveFeedback.failedCell, null)
  assert.equal(app.draftSaveFeedback.lastCell.batchId, 21)
  assert.equal(app.draftSaveFeedback.message, '草稿已保存')
  app.draftBatchMap.value = new Map([[10, 22]])
  app.refreshSaveFeedback()
  assert.equal(app.draftSaveFeedback.lastCell, null)
  assert.equal(app.draftSaveFeedback.successes.size, 0)
})

for (const success of [true, false]) {
  test(`late old-batch outcome cannot reintroduce saving feedback (${success ? 'success' : 'failure'})`, async () => {
    const request = deferred()
    const app = draftEditor({ createDraft: () => request.promise })
    const saving = app.handleCellChange(app.row, 2, 'final_config', 'old-batch')
    await Promise.resolve()
    assert.equal(app.draftSaveFeedback.pending, 1)
    app.draftBatchMap.value = new Map([[10, 21]])
    app.refreshSaveFeedback()
    assert.equal(app.draftSaveFeedback.pending, 0)
    if (success) request.resolve({ draft_id: 40 }); else request.reject(new Error('offline'))
    await saving
    assert.equal(app.draftSaveFeedback.failedCell, null)
    assert.equal(app.draftSaveFeedback.lastCell, null)
    assert.equal(app.draftSaveFeedback.message, '')
    assert.equal(app.draftSaveFeedback.pending, 0)
    assert.deepEqual(app.messages, [])
  })
}

test('same-batch row filtering preserves actionable failed-cell feedback', async () => {
  const app = draftEditor({ createDraft: async () => { throw new Error('offline') } })
  await app.handleCellChange(app.row, 2, 'final_config', 'failed')
  app.tableData.value = []
  app.refreshSaveFeedback()
  assert.equal(app.draftSaveFeedback.failedCell.row.id, 1)
  assert.match(app.draftSaveFeedback.message, /失败/)
})


test('late old-batch undo completion cannot show an undo result in the new batch', async () => {
  const deletion = deferred()
  const app = draftEditor({ deleteDraftByKey: () => deletion.promise })
  await app.handleCellChange(app.row, 2, 'final_config', 'saved')
  const undo = app.undoLastCell()
  await Promise.resolve()
  app.draftBatchMap.value = new Map([[10, 21]])
  app.refreshSaveFeedback()
  deletion.resolve()
  await undo
  assert.equal(app.draftSaveFeedback.message, '')
  assert.equal(app.draftSaveFeedback.pending, 0)
  assert.equal(app.draftSaveFeedback.lastCell, null)
})
