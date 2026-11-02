import test from 'node:test'
import assert from 'node:assert/strict'
import { filterMeasurements, measurementOptions, measurementCounts } from '../src/utils/measurementLibrary.js'

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
  assert.equal(filterMeasurements(rows, { scope: 'unclassified' }).length, 1)
  assert.equal(filterMeasurements(rows, { kind: 'calculation', group: ['2D'], enabled: ['disabled'] }).length, 1)
  assert.equal(filterMeasurements(rows, { category: [] }).length, 0)
  assert.equal(filterMeasurements(rows, { category: [''] }).length, 2)
})

test('options and counts use all records and distinguish IDs from mode relations', () => {
  assert.deepEqual(measurementOptions(rows, 'categories'), ['', 'ABD', 'Common', 'GYN'])
  assert.deepEqual(measurementCounts(rows), { rows: 5, measurements: 3, calculations: 1, common: 2, application: 1, unclassified: 1 })
})
