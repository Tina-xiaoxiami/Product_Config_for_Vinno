import test from 'node:test'
import assert from 'node:assert/strict'
import { filterProbeRows, selectVisibleFilterValues } from '../src/utils/probeTableFilters.js'

test('table filters distinguish unrestricted, no values, blank, N/A, zero and false', () => {
  const rows = [null, '', 'N/A', 0, false].map(value => ({ value }))
  assert.equal(filterProbeRows(rows, { value: null }).length, 5)
  assert.equal(filterProbeRows(rows, { value: [] }).length, 0)
  assert.equal(filterProbeRows(rows, { value: [''] }).length, 2)
  assert.deepEqual(filterProbeRows(rows, { value: ['0', 'false'] }).map(row => row.value), [0, false])
})
test('values in one column use OR while different columns use AND', () => {
  const rows = [{ probe: 'A', status: 'yes' }, { probe: 'B', status: 'no' }, { probe: 'C', status: 'yes' }]
  assert.deepEqual(filterProbeRows(rows, { probe: ['A', 'B'], status: ['yes'] }), [rows[0]])
})
test('search select and clear preserve choices outside the visible candidates', () => {
  assert.deepEqual(selectVisibleFilterValues(['A', 'C'], ['A', 'B'], false), ['C'])
  assert.deepEqual(selectVisibleFilterValues(['C'], ['A', 'B'], true), ['C', 'A', 'B'])
})
