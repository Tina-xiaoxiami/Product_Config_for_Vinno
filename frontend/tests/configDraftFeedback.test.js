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
  const { finishEdit, removeDraftChange, handleCellChange } = new Function(
    ...Object.keys(context),
    `${code}\nreturn { finishEdit, removeDraftChange, handleCellChange }`
  )(...Object.values(context))
  return { finishEdit, removeDraftChange, handleCellChange, messages, row, tableData, draftChanges }
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
