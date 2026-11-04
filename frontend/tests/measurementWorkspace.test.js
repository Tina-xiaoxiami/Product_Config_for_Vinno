import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import { projectManagedMeasurement, dictionaryLabel, identityRows, formatManagedChange, workspaceChangeRows, normalizeMeasurementModes, sourceEvidenceHasDrift } from '../src/utils/measurementWorkspace.js'
import { filterMeasurements } from '../src/utils/measurementLibrary.js'
const document = {
  applications: [{ code: 'Common', name: '常规项目' }, { code: 'CARD', name: '心脏' }],
  modes: [{ code: 'Tissue', name: '二维组织' }, { code: 'Doppler', name: '频谱' }],
  entries: [
    { record_key: 'source:1', kind: 'measurement', item_id: 'X', cn_name: '原名一' },
    { record_key: 'source:2', kind: 'measurement', item_id: 'X', cn_name: '原名二' },
    { record_key: 'source:3', kind: 'calculation', item_id: 'X', cn_name: '另一类型' }
  ]
}
const managed = origin => ({ record_key: 'source:7', kind: 'calculation', item_id: 'Index', cn_name: '已编辑名称', description: 'Edited UI', en_name: 'Edited UI', assignment_origin: origin, categories: ['CARD'], mode: ['Doppler'], official_categories: ['Common'], official_mode: ['Tissue'], enrichment: { status: 'pending', candidate: { payload: { categories: ['Wrong'], modes: ['Wrong'] } } } })
test('managed projection preserves edited names, manual assignments and frozen evidence with pending disabled', () => {
  const row = managed('manual'), before = structuredClone(row)
  assert.deepEqual(projectManagedMeasurement(row, false), row)
  assert.deepEqual(row, before)
  assert.equal(projectManagedMeasurement(row, true).cn_name, '已编辑名称')
})
test('only suggestion assignments revert to official fields when pending is hidden', () => {
  const row = managed('suggestion'), projected = projectManagedMeasurement(row, false)
  assert.deepEqual(projected.categories, ['Common'])
  assert.deepEqual(projected.mode, ['Tissue'])
  assert.equal(projected.en_name, 'Edited UI')
  assert.equal(projected.enrichment.status, 'pending')
  assert.deepEqual(projectManagedMeasurement(managed('confirmed'), false).categories, ['CARD'])
  assert.deepEqual(projectManagedMeasurement(managed('source'), false).categories, ['CARD'])
})
test('display dictionary names do not change stable codes or Common scope filtering', () => {
  assert.equal(dictionaryLabel(document, 'applications', 'Common'), '常规项目')
  assert.equal(dictionaryLabel(document, 'applications', 'New'), 'New')
  assert.equal(dictionaryLabel(document, 'modes', ''), '(空白)')
  const row = projectManagedMeasurement(managed('suggestion'), false)
  assert.equal(filterMeasurements([row], { scope: 'common', category: ['Common'], mode: ['Tissue'] }).length, 1)
  assert.equal(filterMeasurements([row], { category: ['常规项目'] }).length, 0)
})
test('name editor identifies all same-kind Id relationships without merging different kinds', () => {
  assert.deepEqual(identityRows(document, document.entries[0]).map(row => row.record_key), ['source:1', 'source:2'])
  assert.equal(identityRows(document, document.entries[2]).length, 1)
})
test('name diff preserves distinct old names and displays affected relationship counts without internal keys', () => {
  const output = formatManagedChange({ field: 'names' }, [...document.entries.slice(0, 2), document.entries[0]], document)
  assert.match(output, /原名一/); assert.match(output, /原名二/); assert.match(output, /适用 2 条关系/)
  assert.doesNotMatch(output, /source:/)
})
test('assignment and added-record diffs resolve labels and omit internal keys', () => {
  const row = managed('manual')
  const output = formatManagedChange({ field: 'assignments' }, row, document)
  assert.match(output, /心脏/); assert.match(output, /频谱/); assert.doesNotMatch(output, /source:/)
  const record = formatManagedChange({ field: 'record' }, row, document)
  assert.match(record, /Index/); assert.match(record, /已编辑名称/); assert.match(record, /Edited UI/)
  assert.match(record, /心脏/)
})
test('dictionary and evidence diffs summarize display edits and frozen research status', () => {
  assert.equal(formatManagedChange({ entity: 'dictionary', field: 'applications' }, { code: 'CARD', name: '心脏' }, document), 'CARD · 心脏')
  const output = formatManagedChange({ field: 'evidence' }, { enrichment: { status: 'pending', candidate: { revision: 4 }, history: [{ actor: 'A' }] }, official_categories: ['Common'], official_mode: ['Tissue'] }, document)
  assert.match(output, /待核对/); assert.match(output, /候选修订：4/); assert.match(output, /审核记录：1 条/)
  assert.match(output, /常规项目/)
})
test('shared draft normalization retains create/update/delete and exact empty values', () => {
  const changes = workspaceChangeRows([{ key: 'opaque', change_type: 'delete', field: 'record', before: { cn_name: '' }, after: null }])
  assert.equal(changes[0].type_label, '移除'); assert.equal(changes[0].after_label, '(空白)')
  assert.equal(formatManagedChange({ field: 'record' }, null, document), '(空白)')
})
test('workspace publication requires signed preview and stale revisions invalidate it', () => {
  const controls = fs.readFileSync(new URL('../src/components/MeasurementWorkspaceControls.vue', import.meta.url), 'utf8')
  assert.match(controls, /signature: preview\.value\.signature/)
  assert.match(controls, /preview\.value\.revision !== props\.workspace\.revision/)
  assert.match(controls, /props\.workspace\.revision, JSON\.stringify\(form\)/)
  assert.match(controls, /useDraftFilter/)
  assert.match(controls, /before-document="workspace\.published_data"/)
})
test('history stays frozen and source review sync has an explicit visible retry path', () => {
  const page = fs.readFileSync(new URL('../src/views/MeasurementLibrary.vue', import.meta.url), 'utf8')
  assert.match(page, /MeasurementEnrichmentReviewDialog v-if="!snapshot"/)
  assert.match(page, /projectManagedMeasurement\(row, includePending\.value\)/)
  assert.match(page, /expected_sha256: result\.batch\.sha256/)
  assert.match(page, /重试同步核对资料/)
  assert.match(page, /sync-evidence`, \{ revision: latest\.revision \}/)
  assert.match(page, /MeasurementFrozenEvidence :enrichment="detail\.enrichment"/)
})

test('async source fallback normalizes scalar and blank modes without changing source values', () => {
  const source = { mode: 'Tissue', cn_name: '名称' }
  const normalized = normalizeMeasurementModes(source)
  assert.deepEqual(normalized.mode.map(value => value), ['Tissue'])
  assert.equal(source.mode, 'Tissue')
  assert.deepEqual(normalizeMeasurementModes({ mode: '' }).mode, [])
  assert.deepEqual(normalizeMeasurementModes({ mode: ['Tissue', 'Doppler'] }).mode, ['Tissue', 'Doppler'])
})
test('source evidence drift survives a fresh load and ignores managed names/manual associations/frozen histories', () => {
  const source = { id: 7, enrichment: { status: 'pending', review_revision: 0, source_fingerprint: 'source', candidate: { revision: 1, fingerprint: 'candidate' } } }
  const frozen = { entries: [{ ...managed('manual'), source_entry_id: 7, enrichment: { ...structuredClone(source.enrichment), history: [{ actor: 'A' }], candidate_history: [] } }] }
  assert.equal(sourceEvidenceHasDrift([source], frozen), false)
  const newerReview = structuredClone(source); newerReview.enrichment.review_revision = 1
  assert.equal(sourceEvidenceHasDrift([newerReview], frozen), true)
  const newerCandidate = structuredClone(source); newerCandidate.enrichment.candidate.fingerprint = 'new'
  assert.equal(sourceEvidenceHasDrift([newerCandidate], frozen), true)
  const changedStatus = structuredClone(source); changedStatus.enrichment.status = 'confirmed'
  assert.equal(sourceEvidenceHasDrift([changedStatus], frozen), true)
  const changedSource = structuredClone(source); changedSource.enrichment.source_fingerprint = 'updated'
  assert.equal(sourceEvidenceHasDrift([changedSource], frozen), true)
  assert.equal(sourceEvidenceHasDrift([], frozen), true)
  assert.equal(sourceEvidenceHasDrift([], { entries: [{ source_entry_id: null, enrichment: source.enrichment }] }), false)
  assert.equal(sourceEvidenceHasDrift([{ id: 1 }], { entries: [{ source_entry_id: 1, enrichment: null }] }), false)
})
test('page derives pending sync on load and row menu bounds fixed action width', () => {
  const page = fs.readFileSync(new URL('../src/views/MeasurementLibrary.vue', import.meta.url), 'utf8')
  assert.match(page, /evidenceSyncPending\.value = sourceEvidenceHasDrift\(result\.entries, managed\.data\)/)
  assert.match(page, /normalizeMeasurementModes\(projectMeasurementRow\(row, includePending\.value\)\)/)
  assert.match(page, /:actions-width="160"/)
  assert.match(page, /aria-label="编辑"/)
  assert.match(page, /el-dropdown-item command="rename">编辑名称/)
  assert.match(page, /el-dropdown-item command="assign">编辑关联/)
})
