import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import {
  libraryMaintenanceUrl, libraryConnectionLabel, libraryFeatureStatus, libraryRelationLabel,
  descriptionScopeLabel, descriptionParagraphs, createFeatureLibraryState, createFeatureLibraryList,
  createFeatureLibraryDialogState, createFeatureLibraryDialog
} from '../src/utils/featureWhitepaperLibrary.js'

const source = overrides => ({ available: true, library_url: 'http://127.0.0.1:8123/#/features', revision: 'library-v2', feature_count: 153, message: '', ...overrides })
const feature = (id = 8, overrides = {}) => ({ feature_id: id, cn_name: `功能${id}`, en_name: 'Feature', status: 'linked',
  ipns: [{ ipn: '6000034', relation_type: 'primary' }], matches: [], ...overrides })
const report = (items = [feature()], overrides = {}) => ({ source: source(), summary: { configured: 171, linked: 120, ambiguous: 2, unlinked: 46, no_ipn: 3 }, items, ...overrides })
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }

test('maintenance links accept only the provided live loopback library route', () => {
  assert.equal(libraryMaintenanceUrl(source()), 'http://127.0.0.1:8123/#/features')
  assert.equal(libraryMaintenanceUrl(source({ library_url: 'http://localhost:9234/#/features' })), 'http://localhost:9234/#/features')
  assert.equal(libraryMaintenanceUrl(source({ library_url: 'http://[::1]:9234/#/features' })), 'http://[::1]:9234/#/features')
  for (const library_url of ['https://example.com/#/features', 'javascript:alert(1)', 'file:///private/library', 'http://127.0.0.1.evil:8123/#/features',
    'http://user:secret@localhost:8123/#/features', 'http://localhost:8123/#/features/uuid', 'http://localhost:8123/admin#/features']) {
    assert.equal(libraryMaintenanceUrl(source({ library_url })), '')
  }
  assert.equal(libraryMaintenanceUrl(source({ available: false })), '')
  assert.equal(libraryMaintenanceUrl(null), '')
})

test('connection counts distinguish native identities from whitepaper content and never imply a sync', () => {
  assert.match(libraryConnectionLabel(report()), /已关联.*120.*171/)
  assert.doesNotMatch(libraryConnectionLabel(report()), /同步成功|缺少51/)
  assert.match(libraryConnectionLabel(null, true), /读取/)
  assert.match(libraryConnectionLabel(null, false, 'offline'), /未连接/)
  assert.match(libraryConnectionLabel(report([], { source: source({ available: false }) })), /未连接/)
  assert.match(libraryFeatureStatus('ambiguous'), /多个|多候选|歧义/)
  assert.match(libraryFeatureStatus('no_ipn'), /IPN/)
  assert.match(libraryRelationLabel('primary'), /主/)
  assert.match(libraryRelationLabel('related'), /相关/)
  assert.match(libraryRelationLabel('version_variant'), /版本/)
})

test('description rendering preserves target scope, raw paragraphs and empty bodies', () => {
  const inherited = { scope: 'R&V10 series', language: 'zh', body: ['<b>原段落</b>', '', '第二段'], source: { kind: 'master', series: null, version: null } }
  assert.match(descriptionScopeLabel(inherited), /R&V10 series.*中文/)
  assert.match(descriptionScopeLabel({ scope: 'master', language: 'en' }), /通用.*英文/)
  assert.deepEqual(descriptionParagraphs(inherited), ['<b>原段落</b>', '第二段'])
  assert.deepEqual(inherited.body, ['<b>原段落</b>', '', '第二段'])
  assert.deepEqual(descriptionParagraphs({ body: [] }), [])
  assert.deepEqual(descriptionParagraphs({ body: [' ', null, {}] }), [])
})

test('one list request reports offline independently of local data and supports retry', async () => {
  let fail = true; const requests = [], localFeatures = [{ id: 8, name: '本地功能' }]
  const state = createFeatureLibraryState()
  const controller = createFeatureLibraryList(async params => {
    requests.push(params)
    if (fail) throw { response: { data: { detail: '白皮书服务未启动' } } }
    return report()
  }, state)
  assert.equal(await controller.refresh(), false)
  assert.match(state.error, /白皮书服务未启动/)
  assert.equal(state.report, null)
  assert.deepEqual(localFeatures, [{ id: 8, name: '本地功能' }])
  fail = false
  assert.equal(await controller.refresh(), true)
  assert.equal(state.report.source.revision, 'library-v2')
  assert.deepEqual(requests, [{}, {}])
  assert.equal(state.loading, false)
})

test('list refresh and disposal reject stale responses and malformed bridge content', async () => {
  const first = deferred(), second = deferred(); let count = 0
  const state = createFeatureLibraryState()
  const controller = createFeatureLibraryList(() => ++count === 1 ? first.promise : second.promise, state)
  const old = controller.refresh(), current = controller.refresh()
  first.resolve(report([], { source: source({ revision: 'old' }) })); await old
  assert.equal(state.report, null); assert.equal(state.loading, true)
  second.resolve(report()); await current
  assert.equal(state.report.source.revision, 'library-v2')
  controller.dispose()
  assert.equal(await controller.refresh(), false)
  const invalid = createFeatureLibraryState()
  assert.equal(await createFeatureLibraryList(async () => ({ source: {} }), invalid).refresh(), false)
  assert.match(invalid.error, /不完整|无效/)
})

test('each dialog open reads current data and preserves all IPN candidates and relationships', async () => {
  const requests = [], state = createFeatureLibraryDialogState()
  const matches = [{ id: 'uuid-a', name: '穿刺增强', matched_ipns: [{ ipn: '6000034', relation_type: 'primary' }], descriptions: [] },
    { id: 'uuid-b', name: '另一功能', matched_ipns: [{ ipn: '6000034', relation_type: 'version_variant' }], descriptions: [] }]
  const controller = createFeatureLibraryDialog(async params => { requests.push(params); return report([feature(8, { status: 'ambiguous', matches })]) }, state)
  await controller.open({ id: 8, name: '本地主名称' })
  assert.equal(state.item.matches.length, 2)
  assert.equal(state.item.status, 'ambiguous')
  assert.equal(state.item.matches[1].matched_ipns[0].relation_type, 'version_variant')
  controller.close()
  await controller.open({ id: 8, name: '新主名称' })
  assert.deepEqual(requests, [{ feature_id: 8 }, { feature_id: 8 }])
  assert.equal(state.title, '新主名称')
})

test('switching features and closing a pending dialog cannot display an older result', async () => {
  const first = deferred(), second = deferred(); let count = 0
  const state = createFeatureLibraryDialogState()
  const controller = createFeatureLibraryDialog(() => ++count === 1 ? first.promise : second.promise, state)
  const old = controller.open({ id: 8, name: '旧功能' }), current = controller.open({ id: 9, name: '新功能' })
  first.resolve(report([feature(8)])); await old
  assert.equal(state.featureId, 9); assert.equal(state.item, null); assert.equal(state.loading, true)
  controller.close()
  second.resolve(report([feature(9)])); await current
  assert.equal(state.visible, false); assert.equal(state.item, null); assert.equal(state.loading, false)
})

test('dialog failures, source outages and mismatched feature responses remain explicit and retryable', async () => {
  const state = createFeatureLibraryDialogState(); let response = report([feature(8)], { source: source({ available: false, message: '白皮书库暂未连接' }) })
  const controller = createFeatureLibraryDialog(async () => response, state)
  assert.equal(await controller.open({ id: 8, name: '本地功能' }), false)
  assert.match(state.error, /未连接/)
  assert.equal(state.visible, true)
  response = report([feature(9)])
  assert.equal(await controller.reload(), false)
  assert.match(state.error, /当前功能|不一致|未返回/)
  response = report([feature(8)])
  assert.equal(await controller.reload(), true)
  assert.equal(state.item.feature_id, 8)
})

test('the feature workspace exposes one shared source and read-only candidate descriptions', () => {
  const view = readFileSync(new URL('../src/views/FeatureManage.vue', import.meta.url), 'utf8')
  const dialog = readFileSync(new URL('../src/components/FeatureWhitepaperLibraryDialog.vue', import.meta.url), 'utf8')
  const api = readFileSync(new URL('../src/api/data.js', import.meta.url), 'utf8')
  assert.match(view, /白皮书功能库/)
  assert.match(view, /白皮书描述/)
  assert.match(view, /FeatureWhitepaperLibraryDialog/)
  assert.match(view, /loadWhitepaperLibrary\(\)/)
  assert.match(view, /名称.*IPN.*配置管理.*描述.*白皮书/)
  assert.match(dialog, /v-for="match in/)
  assert.match(dialog, /matched_ipns/)
  assert.match(dialog, /正文待补全/)
  assert.match(dialog, /descriptionScopeLabel/)
  assert.match(dialog, /\{\{ paragraph \}\}/)
  assert.doesNotMatch(dialog, /v-html|matches\[0\]|43121/)
  assert.match(api, /getFeatureWhitepaperLibrary = .*api\.get\('\/features\/whitepaper-library'/)
})
