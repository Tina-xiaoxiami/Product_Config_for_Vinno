import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
const source = readFileSync(new URL('../src/views/Config.vue', import.meta.url), 'utf8')
const ref = value => ({ value })
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
function app(createVersion, waitForDraftSaves = async () => {}) {
  const messages = [], requests = []
  const context = {
    selectedSeries: ref([10, 20]), seriesList: ref([{ id: 10, name: '国内' }, { id: 20, name: '海外' }]),
    versionDialogVisible: ref(false), versionSubmitting: ref(false), versionCreateScope: ref(null), versionResults: ref([]),
    versionForm: { version_number: '', version_name: '', description: '' },
    configReady: ref(true), loading: ref(false), applyingModelGroup: ref(false), reviewInteractionLocked: ref(false),
    waitForDraftSaves,
    createVersion: async payload => { requests.push(payload); return createVersion(payload) },
    ElMessage: Object.fromEntries(['success', 'warning', 'error', 'info'].map(type => [type, message => messages.push({ type, message })])),
    console: { error() {} }
  }
  const code = source.slice(source.indexOf('// 创建版本\nconst handleCreateVersion ='), source.indexOf('// 提交草稿\n// 切换草稿筛选'))
  return { ...context, ...new Function(...Object.keys(context), `${code}; return {handleCreateVersion, confirmCreateVersion}`)(...Object.values(context)), requests, messages }
}
test('repeat confirmation creates each series only once and keeps the form while pending', async () => {
  const pending = deferred(), a = app(() => pending.promise)
  a.handleCreateVersion(); a.versionForm.version_name = '基线'
  const first = a.confirmCreateVersion(); await Promise.resolve()
  assert.equal(a.versionSubmitting.value, true)
  await a.confirmCreateVersion(); a.handleCreateVersion()
  assert.equal(a.versionForm.version_name, '基线')
  pending.resolve({}); await first
  assert.deepEqual(a.requests.map(r => r.series_id), [10, 20])
  assert.equal(a.versionSubmitting.value, false)
})
test('dialog freezes series names and IDs before selection changes', async () => {
  const a = app(async () => ({})); a.handleCreateVersion()
  a.selectedSeries.value = [30]; a.seriesList.value = [{ id: 30, name: '新系列' }]
  await a.confirmCreateVersion()
  assert.deepEqual(a.requests.map(r => r.series_id), [10, 20])
  assert.deepEqual(a.versionResults.value.map(r => r.seriesName), ['国内', '海外'])
})
test('partial success stays visible and retries only failed series with the original form', async () => {
  let failed = true
  const a = app(async payload => { if (payload.series_id === 20 && failed) throw { response: { data: { detail: '连接失败' } } }; return {} })
  a.handleCreateVersion(); a.versionForm.version_number = '1.2'; await a.confirmCreateVersion()
  assert.equal(a.versionDialogVisible.value, true)
  assert.deepEqual(a.versionResults.value.map(r => [r.seriesId, r.success]), [[10, true], [20, false]])
  assert.match(a.versionResults.value[1].message, /连接失败/)
  a.versionForm.version_number = '9.9'; a.selectedSeries.value = [30]; failed = false
  await a.confirmCreateVersion()
  assert.deepEqual(a.requests.map(r => r.series_id), [10, 20, 20])
  assert.equal(a.requests[2].version_number, '1.2')
  assert.equal(a.versionDialogVisible.value, false)
})
test('all failures keep editable input and permit correcting it before retry', async () => {
  let fail = true
  const a = app(async () => { if (fail) throw { response: { data: { detail: '版本号已存在' } } }; return {} })
  a.handleCreateVersion(); a.versionForm.version_number = '1.2'; await a.confirmCreateVersion()
  assert.equal(a.versionDialogVisible.value, true)
  assert.equal(a.versionResults.value.length, 2)
  a.versionForm.version_number = '1.3'; fail = false; await a.confirmCreateVersion()
  assert.equal(a.requests[2].version_number, '1.3')
})
test('version creation waits for the existing save queue and freezes input before waiting', async () => {
  const saves = deferred(), a = app(async () => ({}), () => saves.promise)
  a.handleCreateVersion(); a.versionForm.description = '确认时说明'
  const pending = a.confirmCreateVersion(); await Promise.resolve()
  assert.equal(a.requests.length, 0)
  a.versionForm.description = '后来的说明'; saves.resolve(); await pending
  assert.equal(a.requests[0].description, '确认时说明')
})
test('unready page or no series cannot open a version creation dialog', () => {
  const a = app(async () => ({})); a.configReady.value = false; a.handleCreateVersion()
  assert.equal(a.versionDialogVisible.value, false)
  a.configReady.value = true; a.selectedSeries.value = []; a.handleCreateVersion()
  assert.equal(a.versionDialogVisible.value, false)
})
