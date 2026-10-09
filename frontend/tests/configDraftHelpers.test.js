import test from 'node:test'
import assert from 'node:assert/strict'
import { draftBaseline, draftWorkingValue, updateDraftStats } from '../src/utils/configDraftHelpers.js'

test('editing a restored draft keeps its original published value', () => {
  assert.equal(draftBaseline({ oldValue: 'X', newValue: 'O' }, 'O'), 'X')
  assert.equal(draftBaseline({ oldValue: null, newValue: 'O' }, 'O'), null)
  assert.equal(draftBaseline(undefined, 'X'), 'X')
})

test('removing or changing the type of a draft updates the correct counters', () => {
  const initial = { total: 2, create: 1, update: 1, delete: 0 }
  assert.deepEqual(updateDraftStats(initial, 'create', null), { total: 1, create: 0, update: 1, delete: 0 })
  assert.deepEqual(updateDraftStats(initial, 'update', 'create'), { total: 2, create: 2, update: 0, delete: 0 })
  assert.deepEqual(initial, { total: 2, create: 1, update: 1, delete: 0 })
})


test('failed edits or undo restore the previous working value, including an empty draft', () => {
  assert.equal(draftWorkingValue({ oldValue: 'X', newValue: 'O' }, 'X'), 'O')
  assert.equal(draftWorkingValue({ oldValue: 'X', newValue: null }, 'X'), null)
  assert.equal(draftWorkingValue(undefined, 'X'), 'X')
})
