import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  coverageRequestPayload, coverageAssessment, coverageItems, coverageScopeNotice,
  createCoverageState, createCoverageWorkspace, coverageStatusLabel, coverageTraceBoundary,
  registeredPreviewUrl
} from '../src/utils/knowledgeReleaseCoverage.js'

const form = () => ({ query: '针增益', market: 'domestic', country: ' cn ', product_model_id: 9, software_version: ' 1.14.81 ', release_line: '', path: '/untrusted/path' })
const report = overrides => ({ checked_at: '2026-11-02T12:00:00Z', boundary: '仅已配置来源目录', message: '未发现已知缺口',
  scan_status: 'checked', completeness: 'no_known_gaps', scope: null,
  roots: [{ label: '发布记录', path: '/configured/release-notes', status: 'scanned' }],
  totals: { files: 1, registered: 1, ready: 1, gaps: 0, later: 0, unresolved: 0 }, items: [], ...overrides })
const deferred = () => { let resolve, reject; const promise = new Promise((yes,no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }

test('coverage uses only a complete query scope or an explicitly labelled global check', () => {
  assert.deepEqual(coverageRequestPayload(form()), { scope: { market: 'domestic', country: 'CN', product_model_id: 9, software_version: '1.14.81' } })
  assert.deepEqual(coverageRequestPayload({ ...form(), product_model_id: null }), { scope: null })
  assert.match(coverageScopeNotice(coverageRequestPayload({ ...form(), product_model_id: null })), /全部已配置来源.*不代表.*型号/)
  assert.match(coverageScopeNotice(coverageRequestPayload(form())), /1\.14\.81/)
})

test('coverage never declares all historical releases complete or hides unavailable roots', () => {
  assert.match(coverageAssessment(report()), /未发现已知缺口.*限已配置目录/)
  assert.match(coverageAssessment(report({ completeness: 'gaps_found' })), /缺口/)
  assert.match(coverageAssessment(report({ scan_status: 'partial', roots: [{ status: 'error' }] })), /未验证/)
  assert.match(coverageAssessment(null), /尚未检查/)
  assert.match(coverageTraceBoundary({ coverage: {} }), /已登记.*不能代表全部历史完整/)
})

test('gap filters retain unknown candidates but distinguish later and explicitly inapplicable sources', () => {
  const issue = [{ code: 'unregistered', reason: '未登记', action: '受控收纳后登记' }]
  const items = [
    { key: 'unknown', file_name: 'V系列1.14.81.pdf', range_status: 'unknown', applicability_status: 'unrecognized', issues: issue },
    { key: 'later', range_status: 'after_target', applicability_status: 'unrecognized', issues: issue },
    { key: 'other', range_status: 'within_target', applicability_status: 'not_applicable', issues: issue },
    { key: 'ready', range_status: 'within_target', applicability_status: 'applicable', issues: [] }
  ]
  assert.deepEqual(coverageItems(report({ items }), true).map(item => item.key), ['unknown'])
  assert.equal(coverageItems(report({ items }), false).length, 4)
  assert.equal(coverageItems(report({ items }), false, '1.14.81').length, 1)
  const many = Array.from({ length: 250 }, (_,i) => ({ key: String(i), issues: issue }))
  assert.equal(coverageItems(report({ items: many }), true).length, 250)
})

test('status labels keep unrecognized scope and unsupported formats explicit', () => {
  assert.match(coverageStatusLabel('applicability', 'unrecognized'), /未识别/)
  assert.match(coverageStatusLabel('extraction', 'unsupported'), /不支持/)
  assert.match(coverageStatusLabel('range', 'after_target'), /晚于目标/)
  assert.match(coverageStatusLabel('language', 'unknown'), /未识别/)
  assert.match(coverageStatusLabel('extraction', null), /未识别/)
})

test('previews are only registered document URLs, never source paths or arbitrary links', () => {
  assert.equal(registeredPreviewUrl({ document_ids: [92], preview_url: '/api/knowledge/documents/92/preview' }), '/api/knowledge/documents/92/preview')
  for (const preview_url of ['file:///private/a.pdf', 'https://external/a.pdf', '/api/knowledge/documents/93/preview']) {
    assert.equal(registeredPreviewUrl({ document_ids: [92], preview_url }), '')
  }
  assert.equal(registeredPreviewUrl({ document_ids: [], preview_url: '/api/knowledge/documents/92/preview' }), '')
})

test('a stale scan cannot replace a newer scope or clear its loading state', async () => {
  const first = deferred(), second = deferred(), requests = [], state = createCoverageState()
  const api = { checkReleaseCoverage: payload => { requests.push(payload); return requests.length === 1 ? first.promise : second.promise } }
  const workspace = createCoverageWorkspace(api, state)
  const old = workspace.check(form()); workspace.invalidate()
  const current = workspace.check({ ...form(), product_model_id: 30 })
  first.resolve(report({ message: 'old' })); await old
  assert.equal(state.report, null); assert.equal(state.loading, true)
  second.resolve(report({ message: 'new' })); await current
  assert.equal(state.report.message, 'new'); assert.equal(state.loading, false)
  assert.equal(requests[1].scope.product_model_id, 30)
})

test('coverage errors remain independent, preserve no outdated report, and can be retried', async () => {
  let fail = true; const state = createCoverageState()
  const workspace = createCoverageWorkspace({ checkReleaseCoverage: async () => {
    if (fail) throw { response: { data: { detail: '来源目录检查失败' } } }
    return report()
  } }, state)
  assert.equal(await workspace.check(form()), false)
  assert.match(state.error, /覆盖检查失败.*来源目录检查失败/)
  assert.equal(state.loading, false); assert.equal(state.report, null)
  fail = false; assert.equal(await workspace.check(form()), true)
  assert.equal(state.error, ''); assert.ok(state.report)
  workspace.invalidate(); assert.equal(state.report, null)
})

test('malformed responses and disposed requests cannot look like successful coverage', async () => {
  const state = createCoverageState()
  const malformed = createCoverageWorkspace({ checkReleaseCoverage: async () => ({}) }, state)
  assert.equal(await malformed.check(form()), false)
  assert.match(state.error, /返回.*不完整/)
  const pending = deferred(), waiting = createCoverageWorkspace({ checkReleaseCoverage: () => pending.promise }, state)
  const request = waiting.check(form()); waiting.dispose(); pending.resolve(report()); await request
  assert.equal(state.report, null); assert.equal(state.loading, false)
})

test('the history workspace exposes a compact scan with an independent result and retry', () => {
  const source = readFileSync(new URL('../src/components/KnowledgeReleaseHistoryWorkspace.vue', import.meta.url), 'utf8')
  const view = readFileSync(new URL('../src/components/KnowledgeReleaseCoverage.vue', import.meta.url), 'utf8')
  const trace = readFileSync(new URL('../src/components/KnowledgeHistoryTrace.vue', import.meta.url), 'utf8')
  assert.match(source, /检查资料覆盖/)
  assert.match(source, /<KnowledgeReleaseCoverage/)
  assert.match(source, /void runCoverage\(\)/)
  assert.match(view, /issues|item\.issues/)
  assert.match(view, /issue\.action/)
  assert.match(view, /source_locations/)
  assert.match(view, /checked_at/)
  assert.match(view, /只看缺口/)
  assert.match(trace, /coverageTraceBoundary/)
})
