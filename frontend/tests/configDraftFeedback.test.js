import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { draftBaseline, draftWorkingValue, updateDraftStats } from '../src/utils/configDraftHelpers.js'

const source = readFileSync(new URL('../src/views/Config.vue', import.meta.url), 'utf8')
const ref = value => ({ value })

function draftEditor({ createDraft, batchReady = true, change } = {}) {
  const row = { id: 1, model_values: { 2: { final_config: 'attempted' } } }
  const messages = []
  const context = {
    originalDataMap: ref(new Map([[1, { id: 1, model_values: { 2: { final_config: 'published' } } }]])),
    draftWorkingValue,
    draftChanges: ref(new Map(change ? [['1_2_final_config', change]] : [])),
    tableData: ref([row]),
    findSeriesIdByModelId: () => 10,
    draftBatchMap: ref(batchReady ? new Map([[10, 20]]) : new Map()),
    ElMessage: { error: message => messages.push(message) },
    console: { error() {} },
    deleteDraftByKey: async () => {},
    draftStats: { total: change ? 1 : 0, create: 0, update: change ? 1 : 0, delete: 0 },
    updateDraftStats,
    draftBaseline,
    createDraft: createDraft || (async () => ({ draft_id: 30 }))
  }
  const code = source.slice(
    source.indexOf('const restoreWorkingCell ='),
    source.indexOf('// 多文件上传处理')
  )
  const { handleCellChange } = new Function(
    ...Object.keys(context),
    `${code}\nreturn { handleCellChange }`
  )(...Object.values(context))
  return { handleCellChange, messages, row }
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
