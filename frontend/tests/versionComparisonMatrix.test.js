import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { VERSION_COMPARE_FIELDS, versionCellChanged, versionRowChanged, scopeVersionRows, filterVersionRows, versionExportPayload, reconcileVersionModelSelection } from '../src/utils/versionComparison.js'

const rows = [
  { key: 'unchanged', old_values: { 1: { final_config: 'S' } }, new_values: { 1: { final_config: 'S' } } },
  { key: 'changed', old_values: { 1: { final_config: 'S', current_config: 'O' } }, new_values: { 1: { final_config: 'O', current_config: 'O' } } },
  { key: 'removed', old_values: { 1: { current_config: 'X' } }, new_values: {} },
  { key: 'other-model', old_values: {}, new_values: { 2: { final_config: 'S' } } },
  { key: 'other-field', old_values: { 1: { rd_status: '未完成' } }, new_values: { 1: { rd_status: '已完成' } } }
]

test('version matrix filters selected models semantically before selected-field differences', () => {
  assert.deepEqual(scopeVersionRows(rows, [1]).map(row => row.key), ['unchanged', 'changed', 'removed', 'other-field'])
  assert.deepEqual(filterVersionRows(rows, [1], ['final_config'], true).map(row => row.key), ['changed'])
  assert.deepEqual(filterVersionRows(rows, [1], ['current_config'], true).map(row => row.key), ['removed'])
  assert.deepEqual(filterVersionRows(rows, [2], ['final_config'], false).map(row => row.key), ['other-model'])
  assert.deepEqual(filterVersionRows(rows, [], ['final_config'], false), [])
  assert.equal(versionRowChanged(rows[4], [1], VERSION_COMPARE_FIELDS.map(field => field.key)), true)
})

test('version matrix preserves null semantics and does not confuse missing values with zero', () => {
  assert.equal(versionCellChanged({ old_values: {}, new_values: { 1: { final_config: null } } }, 1, 'final_config'), false)
  assert.equal(versionCellChanged({ old_values: { 1: { final_config: 0 } }, new_values: {} }, 1, 'final_config'), true)
  assert.equal(scopeVersionRows([{ old_values: {}, new_values: { 1: { final_config: 0 } } }], [1]).length, 1)
})

test('export request captures exactly the visible model field and metadata scope', () => {
  const models = [2, 1], fields = ['current_config'], columns = ['zh_desc', 'ipn']
  const result = { version_1: { id: 5 }, version_2: { id: 8 } }
  const payload = versionExportPayload(result, models, fields, columns, true)
  models.push(9); fields.push('final_config'); columns.push('rd_name')
  assert.deepEqual(payload, { version_id_1: 5, version_id_2: 8, model_ids: [2, 1], compare_fields: ['current_config'], name_columns: ['zh_desc', 'ipn'], only_diff: true })
})

test('comparison component loads canonical historical choices and protects exports against changed scope', () => {
  const source = readFileSync(new URL('../src/components/VersionComparison.vue', import.meta.url), 'utf8')
  assert.match(source, /props\.result\?\.matrix_models/)
  assert.match(source, /key !== exportKey\(\) \|\| props\.result !== sourceResult/)
  assert.match(source, /v-model="fields" :min="1"/)
  assert.match(source, /v-model="nameColumns" :min="1"/)
  assert.match(source, /onBeforeUnmount\(\(\) => \{ alive = false; clearTimeout\(compareTimer\)/)
})


test('refreshing the same version pair preserves subsets and explicit clear while new pairs select all', () => {
  assert.deepEqual(reconcileVersionModelSelection([2], [1, 2, 3], [1, 2, 3, 4], true), [2])
  assert.deepEqual(reconcileVersionModelSelection([], [1, 2], [1, 2], true), [])
  assert.deepEqual(reconcileVersionModelSelection([1, 2], [1, 2], [1, 2, 3], true), [1, 2, 3])
  assert.deepEqual(reconcileVersionModelSelection([2], [1, 2], [1, 3], true), [])
  assert.deepEqual(reconcileVersionModelSelection([2], [1, 2], [1, 3], false), [1, 3])
})
