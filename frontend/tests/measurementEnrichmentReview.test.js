import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dependencyKey, parseDependencyKey, dependencyOptions, visibleDependencyOptions, safeSourceUrl, cloneReviewPayload, reviewSnapshot, validateReviewForm, buildReviewRequest } from '../src/utils/measurementEnrichmentReview.js'

const candidatePayload = { categories: ['ABD'], modes: ['VShear'], input_terms: [], formula_reference: 'Q3 − Q1', sources: [{ title: 'Guideline', url: 'https://example.org/guideline', locator: 'p. 3', supports: ['IQR'] }], uncertainties: ['待核'], research_status: 'proposed', mapping_basis: 'public_standard', vendor_extra: { preserve: true } }
const detail = { batch_id: 7, enrichment: { candidate: { id: 42, fingerprint: 'candidate-fp', payload: candidatePayload }, source_fingerprint: 'source-fp', review_revision: 3, confirmed_payload: null } }
const form = () => ({ payload: cloneReviewPayload(detail), confirmed_by: ' Reviewer ', note: '' })

test('dependency identities preserve punctuation, kind, delimiters and same-batch scope', () => {
  const id = "E'|A/B(1)"
  assert.deepEqual(parseDependencyKey(dependencyKey({ kind: 'measurement', item_id: id })), { kind: 'measurement', item_id: id })
  assert.equal(parseDependencyKey('measurement|Distance'), null)
  assert.equal(parseDependencyKey('["unsafe","Distance"]'), null)
  assert.equal(parseDependencyKey('["measurement",42]'), null)
  const records = [{ batch_id: 7, kind: 'measurement', item_id: id }, { batch_id: 7, kind: 'measurement', item_id: id }, { batch_id: 7, kind: 'calculation', item_id: id }, { batch_id: 8, kind: 'measurement', item_id: 'Foreign' }]
  assert.equal(dependencyOptions(records, 7).length, 2)
  const options = Array.from({ length: 200 }, (_, i) => ({ key: String(i), label: `Item ${i}` }))
  assert.equal(visibleDependencyOptions(options, '', ['199']).length, 81)
  assert.ok(visibleDependencyOptions(options, 'Item 198', ['199']).some(option => option.key === '198'))
  assert.ok(visibleDependencyOptions(options, 'no match', ['199']).some(option => option.key === '199'))
})

test('only absolute http(s) source links are navigable', () => {
  for (const url of ['javascript:alert(1)', 'data:text/html,x', '//example.org', '/relative', 'file:///tmp/a', 'https://user:secret@example.org', 'https://example.org\n.evil']) assert.equal(safeSourceUrl(url), '')
  assert.equal(safeSourceUrl(' https://example.org/a?q=1 '), 'https://example.org/a?q=1')
  assert.equal(safeSourceUrl('http://example.org'), 'http://example.org/')
})

test('payload editing is isolated and preserves fields not exposed by the form', () => {
  const edited = form()
  edited.payload.categories.push('Common')
  edited.payload.vendor_extra.preserve = false
  assert.deepEqual(candidatePayload.categories, ['ABD'])
  assert.equal(candidatePayload.vendor_extra.preserve, true)
  assert.equal(cloneReviewPayload(detail).vendor_extra.preserve, true)
  assert.equal(reviewSnapshot({ b: 1, a: 2 }), reviewSnapshot({ a: 2, b: 1 }))
  assert.notEqual(reviewSnapshot(form()), reviewSnapshot(edited))
})

test('review validation requires human identity and reasons, and gates confirmation evidence', () => {
  assert.equal(validateReviewForm(form(), 'confirm', detail), '')
  for (const action of ['reject', 'defer', 'revoke']) assert.match(validateReviewForm(form(), action, detail), /说明|理由/)
  assert.match(validateReviewForm({ ...form(), confirmed_by: ' ' }, 'confirm', detail), /核对人/)
  const missing = form(); missing.payload.categories = []; assert.match(validateReviewForm(missing, 'confirm', detail), /分类/)
  const invalidMode = form(); invalidMode.payload.modes = ['unknown']; assert.match(validateReviewForm(invalidMode, 'confirm', detail), /模式/)
  const unsafe = form(); unsafe.payload.sources[0].url = 'javascript:x'; assert.match(validateReviewForm(unsafe, 'confirm', detail), /来源/)
  const unresolved = form(); unresolved.payload.research_status = 'unresolved'; assert.match(validateReviewForm(unresolved, 'confirm', detail), /待补依据|研究状态/)
  const originalUnresolved = structuredClone(detail); originalUnresolved.enrichment.candidate.payload.research_status = 'unresolved'
  assert.match(validateReviewForm(form(), 'confirm', originalUnresolved), /说明/)
  assert.equal(validateReviewForm({ ...form(), note: '补充依据后已核对' }, 'confirm', originalUnresolved), '')
})

test('review requests bind all optimistic concurrency fields to fetched detail and preserve payload', () => {
  const request = buildReviewRequest(detail, form(), 'confirm')
  assert.deepEqual(request, { action: 'confirm', expected_candidate_fingerprint: 'candidate-fp', expected_source_fingerprint: 'source-fp', expected_review_revision: 3, confirmed_by: 'Reviewer', note: '', confirmed_payload: cloneReviewPayload(detail) })
  request.confirmed_payload.vendor_extra.preserve = false
  assert.equal(candidatePayload.vendor_extra.preserve, true)
  assert.equal(Object.hasOwn(buildReviewRequest(detail, { ...form(), note: '待核' }, 'defer'), 'confirmed_payload'), false)
})

test('dialog protects edits, stale requests and external links while avoiding executable formula rendering', () => {
  const source = readFileSync(new URL('../src/components/MeasurementEnrichmentReviewDialog.vue', import.meta.url), 'utf8')
  assert.match(source, /:before-close="requestClose"/)
  assert.match(source, /session !== sessionId/)
  assert.match(source, /expected|buildReviewRequest/)
  assert.match(source, /safeSourceUrl/)
  assert.match(source, /noopener noreferrer/)
  assert.match(source, /onBeforeRouteLeave/)
  assert.doesNotMatch(source, /v-html|eval\(|new Function/)
})
