import test from 'node:test'
import assert from 'node:assert/strict'
import { MODEL_TABLE_COLUMNS, normalizeColumnLayout, moveLayoutColumn, loadColumnLayout, saveColumnLayout } from '../src/utils/tableColumnLayout.js'

test('removed technical columns never return; order, visibility, fixed and independent widths survive', () => {
  const columns = normalizeColumnLayout(MODEL_TABLE_COLUMNS, [{key:'id'}, {key:'status',visible:false,fixed:true,width:1200},{key:'name',width:12},{key:'status'},{key:'sort_order'}])
  assert.equal(columns[0].key,'status')
  assert.equal(columns[0].visible,false)
  assert.equal(columns[0].fixed,true)
  assert.equal(columns[0].width,1200)
  assert.equal(columns[1].width,30)
  assert.equal(columns.length,MODEL_TABLE_COLUMNS.length)
  assert.ok(!columns.some(column=>['id','sort_order'].includes(column.key)))
  assert.equal(columns.find(column=>column.key==='series_id').width,190)
})
test('reordering keeps each field state attached to stable key without mutating input', () => {
  const original = normalizeColumnLayout(MODEL_TABLE_COLUMNS)
  const moved = moveLayoutColumn(original,'status','name')
  assert.equal(moved[0].key,'status')
  assert.equal(original[0].key,'name')
  assert.deepEqual(moveLayoutColumn(moved,'missing','name'),moved)
  const hidden = normalizeColumnLayout(MODEL_TABLE_COLUMNS,original.map(column=>({...column,visible:false})))
  assert.equal(hidden.filter(column=>column.visible).length,1)
})
test('layout storage is isolated, roundtrips and tolerates corruption/unavailable storage with warning', () => {
  const data = new Map(), warnings=[]
  const storage={getItem:key=>data.get(key),setItem:(key,value)=>data.set(key,value)}
  const columns=moveLayoutColumn(MODEL_TABLE_COLUMNS,'status','name')
  assert.equal(saveColumnLayout(storage,'models',columns),true)
  assert.deepEqual(loadColumnLayout(storage,'models',MODEL_TABLE_COLUMNS),columns)
  assert.deepEqual(loadColumnLayout(storage,'other',MODEL_TABLE_COLUMNS),MODEL_TABLE_COLUMNS)
  data.set('models','bad json')
  assert.deepEqual(loadColumnLayout(storage,'models',MODEL_TABLE_COLUMNS,m=>warnings.push(m)),MODEL_TABLE_COLUMNS)
  assert.equal(warnings.length,1)
  assert.equal(saveColumnLayout({setItem(){throw Error('blocked')}},'models',columns,m=>warnings.push(m)),false)
  assert.equal(warnings.length,2)
})

import { readFileSync } from 'node:fs'
const component = readFileSync(new URL('../src/components/TableColumnSettings.vue', import.meta.url), 'utf8')
function settings(confirm = async () => {}) {
  const warnings = [], emitted = []
  const context = {
    ref: value => ({value}), computed: fn => ({get value(){return fn()}}),
    defineProps: () => ({modelValue: normalizeColumnLayout(MODEL_TABLE_COLUMNS), defaults: MODEL_TABLE_COLUMNS}),
    defineEmits: () => (...args) => emitted.push(args),
    ElMessage: {warning: message => warnings.push(message)},
    ElMessageBox: {confirm}, normalizeColumnLayout, moveLayoutColumn
  }
  const script = component.slice(component.indexOf('const props ='), component.indexOf('</script>'))
  const controller = new Function(...Object.keys(context), script + '; return {open, requestClose, apply, move, draft, visible}')(...Object.values(context))
  return {...controller, warnings, emitted}
}
test('declining dirty close preserves unapplied draft; applying saves width by column identity', async () => {
  const editor = settings(async () => {throw 'cancel'})
  editor.open()
  editor.draft.value[0].width = 1430
  editor.move(0,1)
  await editor.requestClose()
  assert.equal(editor.visible.value,true)
  assert.equal(editor.draft.value[1].key,'name')
  assert.equal(editor.draft.value[1].width,1430)
  editor.apply()
  assert.equal(editor.visible.value,false)
  assert.equal(editor.emitted[0][0],'update:modelValue')
  assert.equal(editor.emitted[0][1][1].width,1430)
  assert.match(component, /el-input-number[^>]*:min="30"/)
  assert.doesNotMatch(component, /el-input-number[^>]*:max=/)
})
test('last visible column cannot be hidden; confirmed cancel discards without emitting', async () => {
  const editor = settings()
  editor.open()
  editor.draft.value.forEach(column => {column.visible=false})
  editor.apply()
  assert.equal(editor.visible.value,true)
  assert.equal(editor.warnings.length,1)
  assert.equal(editor.emitted.length,0)
  await editor.requestClose()
  assert.equal(editor.visible.value,false)
  assert.equal(editor.emitted.length,0)
  editor.open()
  assert.ok(editor.draft.value.every(column=>column.visible))
})
