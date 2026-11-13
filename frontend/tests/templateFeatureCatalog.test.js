import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import {
  catalogFeatureLabel, catalogCandidates, catalogSelectionPayload, projectTemplateCatalog,
  catalogCellSource, createTemplateCatalogEditorState, createTemplateCatalogEditor
} from '../src/utils/templateFeatureCatalog.js'

const categories = [{ id: 1, name: '凸阵' }, { id: 2, name: '线阵' }]
const catalog = () => ({ total: 3, groups: [{ id: 10, name: '基础功能' }, { id: 20, name: '血流' }],
  items: [
    { id: 1, name: '梯形成像', primary_en_name: 'TView', ipn: '6000017', group_id: 10, probe_matrix_enabled: true, pending: false },
    { id: 2, name: '高灵敏度血流', primary_en_name: 'VFlow', ipn: '6000168', group_id: 10, probe_matrix_enabled: false, pending: true, pending_group_id: 20 },
    { id: 3, name: '弹性成像', primary_en_name: 'Elastography', ipn: '6000200', group_id: 10, probe_matrix_enabled: false, pending: false }
  ], matrix_items: [
    { id: 1, name: '梯形成像', group_id: 10, probe_matrix_enabled: true, pending: false },
    { id: 2, name: '高灵敏度血流', group_id: 20, original_group_id: 10, probe_matrix_enabled: false, pending: true }
  ] })
const drafts = () => ({ total: 1, drafts: [{ category_id: 1, feature_id: 2, new_support: 'supported', new_excludes: '["心脏"]' }],
  catalog_additions: [{ feature_id: 2, group_id: 20, category_ids: [1] }], catalog_additions_count: 1 })
const form = () => ({ feature_id: 3, group_id: 20, category_ids: [1] })
const deferred = () => { let resolve; const promise = new Promise(yes => { resolve = yes }); return { promise, resolve } }

test('the shared catalog searches current bilingual names and IPN without enabling every identity', () => {
  const source = catalog()
  assert.match(catalogFeatureLabel(source.items[2]), /弹性成像.*Elastography.*6000200/)
  assert.equal(catalogCandidates(source, '6000200')[0].id, 3)
  assert.equal(catalogCandidates(source, 'elasto')[0].id, 3)
  assert.equal(catalogCandidates(source, '高灵敏度')[0].id, 2)
  assert.equal(catalogCandidates(source, '').length, 3)
  const projection = projectTemplateCatalog(source, drafts(), categories)
  assert.deepEqual(projection.features.map(row => row.id), [1, 2])
  assert.equal(source.items[2].probe_matrix_enabled, false)
})

test('selection requires a new identity, an existing shared classification and explicit probe categories', () => {
  assert.deepEqual(catalogSelectionPayload({ ...form(), category_ids: [1, 1] }, catalog(), categories), form())
  for (const feature_id of [1, 2]) assert.throws(() => catalogSelectionPayload({ ...form(), feature_id }, catalog(), categories), /已加入|待提交|重复/)
  assert.throws(() => catalogSelectionPayload({ ...form(), feature_id: null }, catalog(), categories), /功能/)
  assert.throws(() => catalogSelectionPayload({ ...form(), group_id: 99 }, catalog(), categories), /分类/)
  assert.throws(() => catalogSelectionPayload({ ...form(), category_ids: [] }, catalog(), categories), /至少.*探头类别/)
  assert.throws(() => catalogSelectionPayload({ ...form(), category_ids: [99] }, catalog(), categories), /探头类别/)
})

test('server membership drafts preview independently of live template cells and local unsaved edits', () => {
  const projection = projectTemplateCatalog(catalog(), drafts(), categories)
  const live = { '1_1': { default_support: 'conditional' }, '2_2': { default_support: 'supported', default_excludes: '["旧排除"]' } }
  assert.equal(catalogCellSource('1_1', live, projection.pendingCells, projection.pendingFeatureIds).default_support, 'conditional')
  assert.deepEqual(catalogCellSource('1_2', live, projection.pendingCells, projection.pendingFeatureIds), { default_support: 'supported', default_excludes: '["心脏"]' })
  assert.deepEqual(catalogCellSource('2_2', live, projection.pendingCells, projection.pendingFeatureIds), { default_support: 'unsupported', default_excludes: null })
  assert.equal(projection.features[1].group_id, 20)
  assert.equal(projection.catalogAdditionsCount, 1)
  assert.equal(projection.draftTotal, 1)
  assert.equal(live['2_2'].default_support, 'supported')
  assert.throws(() => projectTemplateCatalog({ ...catalog(), matrix_items: [] }, drafts(), categories), /不一致|不完整/)
})

test('new selections start with no supported category and switching features does not reuse earlier choices', () => {
  const state = createTemplateCatalogEditorState()
  const editor = createTemplateCatalogEditor({ state, getContext: () => ({ catalog: catalog(), categories }), save: async () => {}, refresh: async () => {}, confirmDiscard: async () => {} })
  assert.equal(editor.open(), true)
  assert.deepEqual(state.form.category_ids, [])
  editor.chooseFeature(3)
  assert.equal(state.form.group_id, 10)
  assert.deepEqual(state.form.category_ids, [])
  state.form.category_ids = [1]
  editor.chooseFeature(null)
  assert.deepEqual(state.form.category_ids, [])
  assert.equal(state.form.group_id, null)
})

test('failed saves retain classification and probe selection and closing a dirty draft requires confirmation', async () => {
  let confirmed = 0; const state = createTemplateCatalogEditorState()
  const editor = createTemplateCatalogEditor({ state, getContext: () => ({ catalog: catalog(), categories }),
    save: async () => { throw { response: { data: { detail: '该功能已存在待提交草稿' } } } }, refresh: async () => {},
    confirmDiscard: async () => { confirmed++; throw new Error('继续编辑') } })
  editor.open(); Object.assign(state.form, form())
  assert.equal(await editor.submit(), false)
  assert.deepEqual(state.form, form())
  assert.match(state.error, /已存在待提交草稿/)
  assert.equal(state.saved, false)
  assert.equal(await editor.close(), false)
  assert.equal(confirmed, 1); assert.equal(state.visible, true)
})

test('a committed membership draft with refresh failure is saved, remains visible and never resubmits', async () => {
  let writes = 0, refreshes = 0, shouldFail = true
  const state = createTemplateCatalogEditorState()
  const editor = createTemplateCatalogEditor({ state, getContext: () => ({ catalog: catalog(), categories }),
    save: async payload => { writes++; assert.deepEqual(payload, form()); return { feature_id: 3 } },
    refresh: async () => { refreshes++; if (shouldFail) throw new Error('读取超时') }, confirmDiscard: async () => {} })
  editor.open(); Object.assign(state.form, form())
  assert.equal(await editor.submit(), true)
  assert.equal(state.saved, true); assert.equal(state.visible, true)
  assert.match(state.refreshError, /已保存.*刷新失败/)
  assert.deepEqual(state.form, form())
  assert.equal(await editor.submit(), false); assert.equal(writes, 1)
  shouldFail = false
  assert.equal(await editor.retryRefresh(), true)
  assert.equal(state.visible, false); assert.equal(writes, 1); assert.equal(refreshes, 2)
})

test('saving blocks duplicate actions and closing, and late completion after disposal has no UI effects', async () => {
  const pending = deferred(); let refreshes = 0
  const state = createTemplateCatalogEditorState()
  const editor = createTemplateCatalogEditor({ state, getContext: () => ({ catalog: catalog(), categories }), save: () => pending.promise,
    refresh: async () => { refreshes++ }, confirmDiscard: async () => {} })
  editor.open(); Object.assign(state.form, form())
  const work = editor.submit()
  assert.equal(state.saving, true)
  assert.equal(await editor.close(), false)
  assert.equal(await editor.submit(), false)
  editor.dispose(); pending.resolve({ feature_id: 3 }); await work
  assert.equal(state.visible, false); assert.equal(refreshes, 0)
})

test('leaving during the post-save refresh cannot announce an old dialog as a new success', async () => {
  const pending = deferred(), state = createTemplateCatalogEditorState()
  const view = readFileSync(new URL('../src/views/TemplateFeatures.vue', import.meta.url), 'utf8')
  const start = view.indexOf('const refreshCatalogPreview ='), end = view.indexOf('\nconst popoverKey', start)
  let messages = 0
  const context = { selectedGroupIds: { value: [10] }, featureSearch: { value: '旧功能' },
    loadData: () => pending.promise, ElMessage: { success() { messages++ } } }
  const refresh = new Function(...Object.keys(context), `${view.slice(start, end)};return refreshCatalogPreview`)(...Object.values(context))
  const editor = createTemplateCatalogEditor({ state, getContext: () => ({ catalog: catalog(), categories }), save: async () => ({}),
    refresh, confirmDiscard: async () => {} })
  editor.open(); Object.assign(state.form, form())
  const work = editor.submit()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(state.saved, true)
  editor.dispose(); pending.resolve(true)
  assert.equal(await work, false)
  assert.equal(state.visible, false)
  assert.equal(messages, 0)
})

test('new classifications and a previous search cannot hide a successfully staged preview', async () => {
  const view = readFileSync(new URL('../src/views/TemplateFeatures.vue', import.meta.url), 'utf8')
  const start = view.indexOf('const refreshCatalogPreview ='), end = view.indexOf('\nconst popoverKey', start)
  let loads = 0, messages = 0, available = true
  const context = { selectedGroupIds: { value: [10] }, featureSearch: { value: '旧功能' },
    loadData: async () => { loads++; return available }, ElMessage: { success() { messages++ } } }
  const refresh = new Function(...Object.keys(context), `${view.slice(start, end)};return refreshCatalogPreview`)(...Object.values(context))
  await refresh({ feature_id: 3, group_id: 20 })
  assert.deepEqual(context.selectedGroupIds.value, [10, 20])
  assert.equal(context.featureSearch.value, '')
  assert.equal(loads, 1); assert.equal(messages, 0)
  available = false; context.featureSearch.value = '保留本次筛选'
  await assert.rejects(refresh({ group_id: 30 }), /读取失败/)
  assert.deepEqual(context.selectedGroupIds.value, [10, 20])
  assert.equal(context.featureSearch.value, '保留本次筛选')
})

test('the template toolbar keeps local unsaved edits before opening the shared catalog selector', () => {
  const view = readFileSync(new URL('../src/views/TemplateFeatures.vue', import.meta.url), 'utf8')
  const start = view.indexOf('const openTemplateCatalog =')
  const end = view.indexOf('\nconst refreshCatalogPreview =', start)
  assert.ok(start >= 0 && end > start, '功能库入口必须先检查本地未保存修改')
  let opens = 0, warnings = 0
  const context = { pendingCount: { value: 1 }, saving: { value: false }, popoverKey: { value: '' }, loading: { value: false }, loadError: { value: '' }, featureCatalog: { value: catalog() },
    catalogDialog: { value: { open() { opens++ } } }, ElMessage: { warning() { warnings++ } } }
  const open = new Function(...Object.keys(context), `${view.slice(start, end)};return openTemplateCatalog`)(...Object.values(context))
  assert.equal(open(), false); assert.equal(opens, 0); assert.equal(warnings, 1)
  context.pendingCount.value = 0
  assert.equal(open(), true); assert.equal(opens, 1)
})

test('the selector stages shared identities, classifies them and previews without a second feature library', () => {
  const view = readFileSync(new URL('../src/views/TemplateFeatures.vue', import.meta.url), 'utf8')
  const dialog = readFileSync(new URL('../src/components/TemplateFeatureCatalogDialog.vue', import.meta.url), 'utf8')
  const api = readFileSync(new URL('../src/api/data.js', import.meta.url), 'utf8')
  assert.match(view, /从功能库添加/)
  assert.match(view, /待提交预览/)
  assert.match(view, /getTemplateFeatureCatalog/)
  assert.doesNotMatch(view, /getFeatures\(|getFeatureGroups\(/)
  assert.match(dialog, /功能分类（共用）/)
  assert.match(dialog, /至少选择一个探头类别/)
  assert.match(dialog, /probe_matrix_enabled.*pending|pending.*probe_matrix_enabled/)
  assert.match(dialog, /已保存|refreshError/)
  assert.doesNotMatch(dialog, /v-html|43121|白皮书正文/)
  assert.match(api, /getTemplateFeatureCatalog = .*api\.get\('\/template-features\/catalog'/)
  assert.match(api, /saveTemplateCatalogDraft = .*api\.post\('\/template-features\/catalog-draft'/)
})
