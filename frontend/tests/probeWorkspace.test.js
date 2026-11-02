import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
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

// Exercise the real event handlers without starting a browser or replacing their
// business behavior with a second implementation in the test.
const viewSource = readFileSync(new URL('../src/views/ProbeConfig.vue', import.meta.url), 'utf8')
function handler(name, dependencies) {
  const start = viewSource.search(new RegExp(`(?:async )?function ${name}\\(`))
  assert.notEqual(start, -1, `Missing view handler ${name}`)
  const rest = viewSource.slice(start)
  const boundary = rest.search(/\n(?=(?:async )?function |const |onBeforeRouteLeave|onMounted|onUnmounted|watch\()/)
  assert.notEqual(boundary, -1, `Missing boundary after ${name}`)
  return new Function(...Object.keys(dependencies), `${rest.slice(0, boundary)}\nreturn ${name}`)(...Object.values(dependencies))
}
const ref = value => ({ value })
const copy = value => JSON.parse(JSON.stringify(value))

test('canceling new-workspace navigation preserves unsaved edits without creating data', async () => {
  let requests = 0
  const create = handler('create', {
    allowDiscardLocal: async () => false,
    run: async callback => callback(),
    api: { createProbeWorkspace: async () => { requests++; throw new Error('Unexpected creation') } },
  })
  await create()
  assert.equal(requests, 0)
})

test('refreshing shared scope discards local edits, reloads revision and removes departed model exceptions', async () => {
  const server = {
    id: 3, revision: 7,
    data: { scope: { groups: ['V6'], combinations: [] }, rows: [{ notes: 'saved' }],
      overrides: { '1': { row: { notes: 'keep' } }, '2': { row: { notes: 'departed' } } } },
  }
  const current = ref({ id: 3, revision: 6 })
  const document = ref({ ...copy(server.data), rows: [{ notes: 'unsaved' }] })
  const shared = ref({ groups: [{ name: 'V6', model_ids: [1] }], combinations: [] })
  let persisted
  const refresh = handler('refreshScope', {
    allowDiscardLocal: async () => true,
    run: async callback => callback(), loadShared: async () => {},
    api: { getProbeWorkspace: async id => { assert.equal(id, 3); return copy(server) } },
    current, document, shared, scopeGroups: ref([]), scopeCombinations: ref([]),
    assign: value => { current.value = value; document.value = copy(value.data) },
    persist: async refresh => { persisted = { refresh, revision: current.value.revision, document: copy(document.value) } },
  })
  await refresh()
  assert.equal(persisted.refresh, true)
  assert.equal(persisted.revision, 7)
  assert.equal(persisted.document.rows[0].notes, 'saved')
  assert.deepEqual(Object.keys(persisted.document.overrides), ['1'])
})

test('editing only a model note keeps inherited support sparse and follows later total changes', () => {
  const document = ref(fixture())
  const apply = handler('applyEdit', {
    editIsNew: ref(false), tab: ref('models'), editModels: ref([1]),
    editRule: ref({ current_status: 'supported', notes: 'model note' }),
    editOriginalRule: ref({ current_status: 'supported', notes: '' }),
    document, editKey: ref('5:6:7'), applyProbeRule, editing: ref(true),
    ElMessage: { error: error => assert.fail(error) },
  })
  apply()
  assert.deepEqual(document.value.overrides['1']['5:6:7'], { notes: 'model note' })
  const later = applyProbeRule(document.value, '5:6:7', { current_status: 'unsupported' }, [])
  const result = { ...later.rows[0], ...later.overrides['1']['5:6:7'] }
  assert.equal(result.current_status, 'unsupported')
  assert.equal(result.notes, 'model note')
})

test('an unchanged model edit does not create an empty exception or a fake draft', () => {
  const baseline = fixture()
  const result = applyProbeRule(baseline, '5:6:7', {}, [1])
  assert.deepEqual(result, baseline)
})

test('a model edit with no target cannot modify the shared total', () => {
  const baseline = fixture(), document = ref(copy(baseline)), messages = []
  const apply = handler('applyEdit', {
    editIsNew: ref(false), tab: ref('models'), editModels: ref([]),
    document, editing: ref(true), ElMessage: { error: message => messages.push(message) },
  })
  apply()
  assert.equal(messages.length, 1)
  assert.deepEqual(document.value, baseline)
})
