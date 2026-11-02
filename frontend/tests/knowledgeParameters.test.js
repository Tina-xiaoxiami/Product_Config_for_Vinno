import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { formatParameterValues, filterParameterRows, parameterTopicPayload, parameterSpecPayload, createParameterEditor, createLatestParameterRequest, parameterStatusLabel } from '../src/utils/knowledgeParameters.js'

const topic = { fields: [{ key: 'capacity', label: '容量', unit: 'mAh', type: 'number' }, { key: 'energy', label: '能量', unit: 'Wh', type: 'number' }] }
test('parameters preserve zero, explicit units and unprovided values without guessing or conversion', () => {
  assert.equal(formatParameterValues(topic, { capacity: 0 }), '容量：0 mAh；能量：未填写')
  assert.equal(formatParameterValues(topic, { capacity: 6700, energy: 96.48 }), '容量：6700 mAh；能量：96.48 Wh')
  assert.deepEqual(parameterTopicPayload({ name: ' 电池 ', question: ' 电池容量？ ', aliases: '电池多大？\n\n', fields: topic.fields }).aliases, ['电池多大？'])
  const payload = parameterSpecPayload({ id: 9, revision: 3, name: ' 规格A ', ipn: ' 123 ', values: { capacity: '0', energy: '96.48' }, evidence_reference: ' 原始规格书 ', confirmed_by: ' 张三 ', is_active: true }, topic)
  assert.equal(payload.expected_revision, 3)
  assert.equal(payload.values.capacity, '0')
  assert.equal(payload.confirmed_by, '张三')
})
test('filters apply to the full preview before pagination and distinguish unlimited from no selected statuses', () => {
  const rows = [{ model_name: 'A', status: 'matched', matches: [{ ipn: '123', name: '规格甲' }] }, { model_name: 'B', status: 'missing', issues: ['缺参数'] }]
  assert.equal(filterParameterRows(rows, '', null).length, 2)
  assert.equal(filterParameterRows(rows, '', []).length, 0)
  assert.equal(filterParameterRows(rows, '123', ['matched']).length, 1)
  assert.equal(filterParameterRows(rows, '缺参数', ['missing']).length, 1)
})
test('an outdated preview request cannot replace a newly selected snapshot or clear its loading indicator', async () => {
  const requests = [], events = []
  const latest = createLatestParameterRequest()
  const run = value => latest.run(() => new Promise(resolve => requests.push(resolve)), { start: () => events.push('start'+value), success: result => events.push(result), finish: () => events.push('end'+value) })
  const first = run(1), second = run(2)
  requests[0]('old')
  await first
  assert.deepEqual(events, ['start1', 'start2'])
  requests[1]('current')
  await second
  assert.deepEqual(events, ['start1', 'start2', 'current', 'end2'])
})
test('failed saves retain the editor, source values and expected revision; rejected discard retains drafts', async () => {
  const state = {}
  const editor = createParameterEditor({ state, save: async () => { throw { response: { data: { detail: '版本已变化，请重新加载' } } } }, confirmDiscard: async () => { throw new Error('continue') } })
  editor.open('spec', { id: 9, revision: 3, name: '规格A' })
  state.form.name = '未保存'
  await editor.submit()
  assert.equal(state.visible, true)
  assert.equal(state.form.name, '未保存')
  assert.equal(state.form.revision, 3)
  assert.equal(state.saving, false)
  assert.match(state.error, /版本已变化/)
  await editor.close()
  assert.equal(state.visible, true)
})
test('successful saves close only their own session and emit the saved item', async () => {
  const state = {}, saved = [], resolve = []
  const editor = createParameterEditor({ state, save: () => new Promise(done => resolve.push(done)), onSaved: item => saved.push(item), confirmDiscard: async () => {} })
  editor.open('topic', { name: 'first' })
  const first = editor.submit()
  editor.open('topic', { name: 'second' })
  resolve[0]({ id: 1 })
  await first
  assert.equal(state.visible, true)
  assert.equal(state.form.name, 'second')
  assert.deepEqual(saved, [])
  const second = editor.submit()
  resolve[1]({ id: 2 })
  await second
  assert.equal(state.visible, false)
  assert.deepEqual(saved, [{ id: 2 }])
})
test('workspace uses shared table controls, protected dialogs and snapshot model options', () => {
  const source = readFileSync(new URL('../src/components/KnowledgeParameterWorkspace.vue', import.meta.url), 'utf8')
  assert.match(source, /TableColumnSettings/)
  assert.match(source, /header-dragend/)
  assert.match(source, /data-table-id="knowledge-parameter-preview"/)
  assert.match(source, /getParameterSnapshot/)
  assert.match(source, /:before-close="closeEditor"/)
  assert.match(source, /未保存/)
  assert.doesNotMatch(source, /6700|96\.48|1001036/)
})


test('actual preview missing-spec and needs-review outcomes are readable', () => {
  assert.equal(parameterStatusLabel('missing_spec'), '未匹配规格')
  assert.equal(parameterStatusLabel('needs_review'), '需核对')
})

test('changing selection invalidates obsolete errors and save-in-progress cannot be dismissed', async () => {
  const latest = createLatestParameterRequest(), events = []
  let reject
  const pending = latest.run(() => new Promise((_resolve, fail) => { reject = fail }), { error: () => events.push('error'), finish: () => events.push('finished') })
  latest.invalidate()
  reject(new Error('obsolete'))
  await pending
  assert.deepEqual(events, [])
  const state = {}, responses = []
  const editor = createParameterEditor({ state, save: () => new Promise(resolve => responses.push(resolve)), confirmDiscard: async () => {} })
  editor.open('spec', { name: '规格A' })
  const saving = editor.submit()
  await editor.close()
  assert.equal(state.visible, true)
  responses[0]({ id: 1 })
  await saving
})

test('topic creation only requires business field labels and units, not internal identifiers', () => {
  const payload = parameterTopicPayload({ name:'电池',question:'容量？',aliases:'',fields:[{key:'',label:'容量',unit:'mAh',type:'number'},{key:'',label:'能量',unit:'Wh',type:'number'}] })
  assert.ok(payload.fields.every(field => /^[a-z][a-z0-9_]*$/.test(field.key)))
  assert.equal(new Set(payload.fields.map(field => field.key)).size,2)
})
