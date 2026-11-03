import test from 'node:test'
import assert from 'node:assert/strict'
import { filterMeasurements, measurementOptions, measurementCounts, measurementFacets, projectMeasurementRow } from '../src/utils/measurementLibrary.js'

const rows = [
  { kind: 'measurement', item_id: 'Distance', en_name: 'Distance', cn_name: '距离', mode: 'Tissue', categories: ['Common'] },
  { kind: 'measurement', item_id: 'Distance', en_name: 'Distance D', cn_name: '距离', mode: 'Doppler', categories: ['Common'] },
  { kind: 'measurement', item_id: 'Bladder', en_name: 'Bladder Vol.', cn_name: '膀胱容积', mode: 'Tissue', categories: ['ABD', 'GYN'] },
  { kind: 'measurement', item_id: 'Unclassified', en_name: 'Unclassified', cn_name: '', mode: 'URM', categories: [] },
  { kind: 'calculation', item_id: 'Volume', en_name: 'Volume', cn_name: '', group: '2D', categories: [], enabled: 'disabled', unit: 'ml' }
]

test('searches UI names and Id, ranks exact names first and preserves symbols', () => {
  assert.equal(filterMeasurements(rows, { q: '  distance  ' })[0].en_name, 'Distance')
  assert.equal(filterMeasurements(rows, { q: '膀胱' })[0].item_id, 'Bladder')
  assert.equal(filterMeasurements(rows, { q: 'bladder vol.' })[0].item_id, 'Bladder')
  assert.equal(filterMeasurements(rows, { q: 'not-there' }).length, 0)
  assert.equal(filterMeasurements([{ ...rows[0], item_id: "E'", en_name: "E'" }], { q: 'E' })[0].match, 'partial')
})

test('combines scopes with AND, multiple categories with OR, and keeps disabled entries', () => {
  assert.equal(filterMeasurements(rows, { scope: 'common', mode: ['Doppler'] }).length, 1)
  assert.equal(filterMeasurements(rows, { scope: 'application', category: ['GYN', 'VAS'] }).length, 1)
  assert.equal(filterMeasurements(rows, { scope: 'unclassified' }).length, 2)
  assert.equal(filterMeasurements(rows, { kind: 'calculation', group: ['2D'], enabled: ['disabled'] }).length, 1)
  assert.equal(filterMeasurements(rows, { category: [] }).length, 0)
  assert.equal(filterMeasurements(rows, { category: [''] }).length, 2)
})

test('options and counts use all records and distinguish IDs from mode relations', () => {
  assert.deepEqual(measurementOptions(rows, 'categories'), ['', 'ABD', 'Common', 'GYN'])
  assert.deepEqual(measurementCounts(rows), { rows: 5, measurements: 3, calculations: 1, common: 2, application: 1, unclassified: 2 })
})

test('sidebar facets count each relation once, intersect other dimensions and retain zero options', () => {
  const source = [...rows, { kind: 'calculation', item_id: 'Multi', mode: ['Tissue', 'Tissue', 'Doppler'], categories: ['ABD', 'GYN', 'GYN'] }]
  const snapshot = structuredClone(source)
  const facets = measurementFacets(source, { scope: 'application', category: ['ABD', 'GYN'], mode: ['Doppler'] })
  assert.deepEqual(facets.categories, [{ value: 'ABD', count: 1 }, { value: 'GYN', count: 1 }])
  assert.deepEqual(facets.modes, [{ value: '', count: 0 }, { value: 'Doppler', count: 1 }, { value: 'Tissue', count: 2 }, { value: 'URM', count: 0 }])
  assert.deepEqual(facets.scopes, { all: 2, common: 1, application: 1, unclassified: 0 })
  assert.equal(filterMeasurements(source, { category: ['ABD', 'GYN'], mode: ['Tissue', 'Doppler'] }).length, 2)
  assert.deepEqual(source, snapshot)
})

test('sidebar facets retain selected values after suggestions disappear and handle blank modes', () => {
  const facets = measurementFacets(rows, { q: 'no-result', mode: ['VShear'], category: ['CARD'] })
  assert.ok(facets.modes.some(option => option.value === 'VShear' && option.count === 0))
  assert.ok(facets.categories.some(option => option.value === 'CARD' && option.count === 0))
  assert.ok(facets.modes.every(option => option.count === 0))
  assert.equal(measurementFacets(rows, { kind: 'calculation' }).modes.find(option => option.value === '').count, 1)
})

const proposal = { categories: ['CARD'], modes: ['Tissue', 'Doppler'], input_terms: [], sources: [], uncertainties: [], research_status: 'proposed' }
const enriched = () => ({ ...rows[4], enrichment: { status: 'pending', candidate: { id: 1, payload: structuredClone(proposal) }, confirmed_payload: null } })

test('calculations without classification remain searchable under unclassified', () => {
  assert.deepEqual(filterMeasurements(rows, { scope: 'unclassified', kind: 'calculation' }).map(row => row.item_id), ['Volume'])
  assert.equal(filterMeasurements(rows, { scope: 'common', kind: 'calculation' }).length, 0)
})

test('pending classification and multiple modes are an explicit reversible view, never source mutation', () => {
  const source = enriched(), snapshot = structuredClone(source)
  const projected = projectMeasurementRow(source, true)
  assert.deepEqual(projected.categories, ['CARD'])
  assert.deepEqual(projected.mode, ['Tissue', 'Doppler'])
  assert.equal(projected.classification_basis, '待核对建议')
  assert.equal(filterMeasurements([projected], { scope: 'application', kind: 'calculation', mode: ['Doppler'] }).length, 1)
  assert.deepEqual(measurementOptions([projected], 'mode'), ['Doppler', 'Tissue'])
  assert.equal(projectMeasurementRow(source, false).mode, '')
  assert.deepEqual(projectMeasurementRow(source, false).categories, [])
  assert.deepEqual(source, snapshot)
})

test('confirmed corrections take precedence over a newer pending proposal', () => {
  const source = enriched()
  source.enrichment.confirmed_payload = { ...proposal, categories: ['VAS'], modes: ['Doppler'] }
  source.enrichment.has_pending_update = true
  for (const includePending of [true, false]) {
    const row = projectMeasurementRow(source, includePending)
    assert.deepEqual(row.categories, ['VAS'])
    assert.deepEqual(row.mode, ['Doppler'])
    assert.equal(row.classification_basis, '已核对补充')
    assert.match(row.enrichment_status, /已核对/)
  }
})

test('rejected and stale-source suggestions never enter classification filters', () => {
  for (const status of ['rejected', 'stale_source']) {
    const source = enriched(); source.enrichment.status = status
    const row = projectMeasurementRow(source, true)
    assert.deepEqual(row.categories, [])
    assert.equal(filterMeasurements([row], { scope: 'application' }).length, 0)
  }
})

test('a calculation is never classified by a similar ID or group name alone', () => {
  const row = projectMeasurementRow({ ...rows[4], item_id: 'Distance', group: 'Tissue' }, true)
  assert.deepEqual(row.categories, [])
  assert.equal(filterMeasurements([row], { scope: 'common' }).length, 0)
})
