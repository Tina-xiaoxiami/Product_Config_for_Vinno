import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../src/views/Config.vue', import.meta.url), 'utf8')
const ref = value => ({ value })
const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds))

function deferred() {
  let resolve
  let reject
  const promise = new Promise((onResolve, onReject) => {
    resolve = onResolve
    reject = onReject
  })
  return { promise, resolve, reject }
}

function previewApp(previewImport) {
  const context = {
    pendingFiles: [],
    processTimer: null,
    previewRequest: 0,
    committedPreviewRequest: 0,
    previewFiles: ref([]),
    previewData: ref(null),
    previewDialogVisible: ref(false),
    previewImport,
    previewImportBatch: async data => ({ files: await Promise.all(data.getAll('files').map(file => { const form = new FormData(); form.append('file', file); return previewImport(form) })) }),
    ElMessage: { warning() {}, error() {} },
    console: { error() {} },
    FormData,
    setTimeout,
    clearTimeout
  }
  const code = source.slice(
    source.indexOf('const handleMultiFileUpload ='),
    source.indexOf('// 确认导入')
  )
  const handleMultiFileUpload = new Function(
    ...Object.keys(context),
    `${code}\nreturn handleMultiFileUpload`
  )(...Object.values(context))
  return { handleMultiFileUpload, ...context }
}

function importApp({ files, preview, importExcel, previewRequest = 1, committedPreviewRequest = 1 }) {
  const messages = []
  const context = {
    previewFiles: ref(files),
    previewData: ref(preview),
    previewRequest,
    committedPreviewRequest,
    importing: ref(false),
    importProgress: ref({ current: 0, total: 0 }),
    previewDialogVisible: ref(true),
    importExcel,
    ElMessage: {
      warning: message => messages.push(message),
      success: message => messages.push(message)
    },
    console: { error() {} },
    currentPage: ref(2),
    loadSeries: async () => {},
    loadModels: async () => {},
    loadEnumValues: async () => {},
    FormData
  }
  const code = source.slice(
    source.indexOf('const confirmImport ='),
    source.indexOf('// 导出Excel')
  )
  const confirmImport = new Function(
    ...Object.keys(context),
    `${code}\nreturn confirmImport`
  )(...Object.values(context))
  return { confirmImport, messages, ...context }
}

function exportApp(visibleRows) {
  let request
  const context = {
    selectedSeries: ref([10]),
    seriesList: ref([{ id: 10, name: 'V10' }]),
    filteredTableData: ref(visibleRows),
    allModelsMap: ref(new Map([[2, { id: 2, name: 'V10', seriesId: 10 }]])),
    selectedModels: ref([2]),
    draftFilters: ref(new Set()),
    showDiffOnly: ref(false),
    showRdIncomplete: ref(false),
    selectedCategories: ref(['Optional Features']),
    searchText: ref('needle'),
    visibleConfigFields: ref(['final_config']),
    draftChanges: ref(new Map()),
    deletedItemModelMap: ref(new Map()),
    draftDeleteValues: ref(new Map()),
    newItemModelMap: ref(new Map()),
    exportExcel: async (seriesId, params) => {
      request = { seriesId, params }
      return new Uint8Array([1])
    },
    mergeModelNames: names => names.join('-'),
    ElMessage: { warning() {}, info() {}, success() {}, error() {} },
    console: { error() {} },
    Blob,
    window: {
      URL: {
        createObjectURL: () => 'blob:test',
        revokeObjectURL() {}
      }
    },
    document: {
      createElement: () => ({ setAttribute() {}, click() {} }),
      body: { appendChild() {}, removeChild() {} }
    }
  }
  const code = source.slice(
    source.indexOf('const handleExport ='),
    source.indexOf('// 合并型号名称')
  )
  const handleExport = new Function(
    ...Object.keys(context),
    `${code}\nreturn handleExport`
  )(...Object.values(context))
  return { handleExport, getRequest: () => request }
}

const previewResponse = filename => ({
  filename,
  series: [],
  summary: { total_models: 1, total_items: 1, categories: ['Features'] },
  total_rows: 1
})

test('a slow upload preview cannot replace a newer preview and file set', async () => {
  const slow = deferred()
  let calls = 0
  const app = previewApp(() => ++calls === 1 ? slow.promise : Promise.resolve(previewResponse('B.xlsx')))
  const fileA = new File(['A'], 'A.xlsx')
  const fileB = new File(['B'], 'B.xlsx')

  app.handleMultiFileUpload({ file: fileA })
  await delay(120)
  app.handleMultiFileUpload({ file: fileB })
  await delay(120)
  assert.equal(app.previewData.value.files[0].filename, 'B.xlsx')

  slow.resolve(previewResponse('A.xlsx'))
  await delay(0)
  assert.equal(app.previewData.value.files[0].filename, 'B.xlsx')
  assert.deepEqual(app.previewFiles.value.map(file => file.name), ['B.xlsx'])
})

test('confirm import freezes the matched preview files for the whole queue', async () => {
  const firstImport = deferred()
  const imported = []
  const fileA = new File(['A'], 'A.xlsx')
  const fileB = new File(['B'], 'B.xlsx')
  const fileC = new File(['C'], 'C.xlsx')
  const preview = { files: [previewResponse('A.xlsx'), previewResponse('B.xlsx')] }
  const app = importApp({
    files: [fileA, fileB],
    preview,
    importExcel: formData => {
      imported.push(formData.get('file').name)
      return imported.length === 1 ? firstImport.promise : Promise.resolve({ message: 'ok' })
    }
  })

  const importing = app.confirmImport()
  await delay(0)
  app.previewFiles.value = [fileC]
  app.previewData.value = { files: [previewResponse('C.xlsx')] }
  firstImport.resolve({ message: 'ok' })
  await importing

  assert.deepEqual(imported, ['A.xlsx', 'B.xlsx'])
  assert.equal(app.previewDialogVisible.value, true)
})

test('confirm import rejects a file set that no longer matches the committed preview', async () => {
  let imports = 0
  const app = importApp({
    files: [new File(['B'], 'B.xlsx')],
    preview: { files: [previewResponse('A.xlsx')] },
    previewRequest: 2,
    committedPreviewRequest: 1,
    importExcel: async () => { imports++ }
  })

  await app.confirmImport()

  assert.equal(imports, 0)
  assert.equal(app.importing.value, false)
  assert.deepEqual(app.messages, ['预览已更新，请确认最新文件后再导入'])
})

test('export always sends the exact non-empty visible item id set', async () => {
  const app = exportApp([{ id: 3 }, { id: 7 }])

  await app.handleExport()

  assert.equal(app.getRequest().seriesId, 10)
  assert.equal(app.getRequest().params.item_ids, '3,7')
})


test('multiple-file preview requests one sequential batch and uses server final impact', async () => {
  let requestCount = 0
  const app = previewApp(async () => previewResponse('unused.xlsx'))
  // Instantiate the same controller with a batch-aware endpoint.
  const context = { ...app, previewImportBatch: async data => { requestCount++; return { files: data.getAll('files').map(file => previewResponse(file.name)), impact: { modified: 1, total_changes: 1 } } } }
  const code = source.slice(source.indexOf('const handleMultiFileUpload ='), source.indexOf('// 确认导入'))
  const upload = new Function(...Object.keys(context), `${code};return handleMultiFileUpload`)(...Object.values(context))
  upload({ file: new File(['A'], 'A.xlsx') }); upload({ file: new File(['B'], 'B.xlsx') })
  await delay(120)
  assert.equal(requestCount, 1)
  assert.equal(app.previewData.value.impact.modified, 1)
  assert.deepEqual(app.previewData.value.files.map(file => file.filename), ['A.xlsx', 'B.xlsx'])
})
