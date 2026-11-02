import test from 'node:test'
import assert from 'node:assert/strict'
import { applyProbeRule, removeProbeRule, probeRuleKey, probeStatusLabel } from '../src/utils/probeWorkspace.js'

const fixture = () => ({ scope: { model_ids: [1, 2] }, rows: [{ probe_model_id: 5, variant_id: 6, feature_id: 7, current_status: 'supported' }], overrides: { '2': { '5:6:7': { current_status: 'unsupported' } } } })
test('common edits retain each model exception and do not mutate the baseline', () => {
  const original = fixture()
  const changed = applyProbeRule(original, '5:6:7', { current_status: 'conditional' }, [])
  assert.equal(changed.rows[0].current_status, 'conditional')
  assert.equal(changed.overrides['2']['5:6:7'].current_status, 'unsupported')
  assert.equal(original.rows[0].current_status, 'supported')
})
test('explicit model differences target only deduplicated selected models', () => {
  const changed = applyProbeRule(fixture(), '5:6:7', { current_excludes: ['心脏'] }, [2, 2])
  assert.deepEqual(changed.overrides['2']['5:6:7'].current_excludes, ['心脏'])
  assert.equal(changed.overrides['1'], undefined)
  assert.throws(() => applyProbeRule(fixture(), '5:6:7', {}, [99]))
})
test('removing a total entry removes its exceptions without leaving orphan differences', () => {
  const removed = removeProbeRule(fixture(), '5:6:7')
  assert.equal(removed.rows.length, 0)
  assert.equal(removed.overrides['2']['5:6:7'], undefined)
  assert.equal(probeRuleKey(fixture().rows[0]), '5:6:7')
  assert.equal(probeStatusLabel('pending'), '待确认')
  assert.equal(probeStatusLabel('not_applicable'), '不适用')
})
