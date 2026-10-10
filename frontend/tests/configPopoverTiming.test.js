import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
const source=readFileSync(new URL('../src/views/Config.vue',import.meta.url),'utf8')
const ref=value=>({value})
function events(tag,context) {
  const handlers=new Map([...tag.matchAll(/@([\w:-]+)="([^"]+)"/g)].map(match=>[match[1],match[2]]))
  return name=>{
    if(!handlers.has(name))return
    const result=new Function(...Object.keys(context),`return (${handlers.get(name)})`)(...Object.values(context))
    if(typeof result==='function')result()
  }
}
function filterPopover(field) {
  const ctx={reactive:value=>value,selectedModels:ref([10]),visibleConfigFields:ref(['final_config','current_config','selection_config','rd_status']),currentPage:ref(3)}
  const code=source.slice(source.indexOf('const fieldFilters ='),source.indexOf('const tempSelectedModels ='))
  const methods=new Function(...Object.keys(ctx),`${code};return {fieldFilters,pendingFieldFilters,openFieldFilterPopover,applyFieldFilterPopover}`)(...Object.values(ctx))
  const tag=[...source.matchAll(/<el-popover\b[^>]*popper-class="field-filter-popover"[^>]*>/g)].map(match=>match[0]).find(tag=>tag.includes(`'${field}'`))
  assert.ok(tag,'field popover must exist')
  return {...methods,emit:events(tag,{...methods,modelId:10}),key:`${field}|10`}
}
for(const field of ['final_config','current_config','selection_config','rd_status']) {
  test(`${field}: a selection made during the opening transition is retained`,()=>{
    const app=filterPopover(field)
    app.emit('before-enter')
    app.pendingFieldFilters[app.key]=['X']
    app.emit('show');app.emit('after-enter')
    assert.deepEqual(app.pendingFieldFilters[app.key],['X'])
  })
  test(`${field}: a previous closing transition cannot commit the reopened draft`,()=>{
    const app=filterPopover(field)
    app.emit('before-enter');app.emit('show');app.emit('after-enter')
    app.pendingFieldFilters[app.key]=['O']
    app.emit('before-leave')
    app.emit('before-enter');app.emit('show');app.emit('after-enter')
    app.pendingFieldFilters[app.key]=['X']
    app.emit('hide');app.emit('after-leave')
    assert.deepEqual(app.fieldFilters[app.key],['O'])
    assert.deepEqual(app.pendingFieldFilters[app.key],['X'])
  })
}
function columnsPopover() {
  const visibleColumns={rd_name:true,v_code:false,en_desc:false},fixedColumns={rd_name:true,v_code:false,en_desc:false}
  const warnings=[];let saves=0,hides=0
  const ctx={visibleColumns,fixedColumns,tempVisibleColumns:{...visibleColumns},tempFixedColumns:{...fixedColumns},saveColumnSettings:()=>saves++,ElMessage:{warning:message=>warnings.push(message)},popoverRef:ref({hide:()=>hides++})}
  const code=source.slice(source.indexOf('const initTempColumns ='),source.indexOf('const resetTempColumns ='))
  const methods=new Function(...Object.keys(ctx),`${code};return {initTempColumns,applyTempColumns,applyTempColumnsAndClose}`)(...Object.values(ctx))
  const tag=source.match(/<el-popover\b[^>]*ref="popoverRef"[^>]*>/)[0]
  return {...ctx,...methods,emit:events(tag,methods),warnings,saves:()=>saves,hides:()=>hides}
}
test('column settings are committed on closing before a new panel resets temporary settings',()=>{
  const app=columnsPopover()
  app.emit('before-enter');app.tempVisibleColumns.v_code=true
  app.emit('before-leave');app.emit('before-enter')
  app.tempVisibleColumns.en_desc=true
  app.emit('hide');app.emit('after-leave')
  assert.equal(app.visibleColumns.v_code,true)
  assert.equal(app.visibleColumns.en_desc,false)
  assert.equal(app.tempVisibleColumns.en_desc,true)
})
test('closing column settings cannot persist a view with no visible fixed column',()=>{
  const app=columnsPopover()
  app.emit('before-enter');app.tempFixedColumns.rd_name=false
  app.emit('before-leave');app.emit('hide');app.emit('after-leave')
  assert.equal(app.fixedColumns.rd_name,true)
  assert.equal(app.saves(),0)
  assert.match(app.warnings[0],/至少.*固定/)
})
test('applying invalid column settings keeps the panel open and the old view intact',()=>{
  const app=columnsPopover();app.tempVisibleColumns.rd_name=false
  app.applyTempColumnsAndClose()
  assert.equal(app.hides(),0)
  assert.equal(app.visibleColumns.rd_name,true)
  assert.equal(app.saves(),0)
})
