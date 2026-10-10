import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
const source = readFileSync(new URL('../src/views/Config.vue', import.meta.url), 'utf8')
const ref = value => ({ value })
function deferred() { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
function bulkApp(overrides = {}) {
  const rows = [1, 2].map(id => ({ id, rd_name: `行${id}`, model_values: { 10: { final_config: 'X', current_config: '', selection_config: '', rd_status: '未完成' }, 20: { final_config: '●', current_config: '', selection_config: '', rd_status: '未完成' } } }))
  const calls = []; const confirmations = []; const messages = []
  const context = {
    configReady: ref(true), loading: ref(false), applyingModelGroup: ref(false), reviewInteractionLocked: ref(false), rdCompleteSubmitting: ref(false),
    draftBatchMap: ref(new Map([[5, 'A']])), selectedModels: ref([10,20]), tableData: ref(rows), filteredTableData: ref([rows[0]]),
    applyToAllDialog: { visible:false, saving:false, row:null, request:0, targets:[], retryTargets:null, modelIds:[], result:null },
    pasteRowDialog: { visible:false, saving:false, targetRowId:null, request:0, targets:[], retryTargets:null, result:null, modelIds:[] },
    contextMenu: { row:rows[0], modelId:10, field:'final_config' }, copiedRowConfig: ref(null), hideContextMenu(){},
    isValueChanged: (a,b) => a !== b,
    captureDraftCellContext: (row,modelId,field) => ({ row,modelId,field, seriesId:5, batchId: context.draftBatchMap.value.get(5) }),
    isDraftCellScopeCurrent: scope => context.draftBatchMap.value.get(5) === scope.batchId,
    handleCellChange: async (row,modelId,field,value,oldValue,scope) => { calls.push({ rowId:row.id, modelId,field,value,scope }); return true },
    ElMessage: Object.fromEntries(['info','warning','success','error'].map(type => [type, message => messages.push({ type,message })])),
    ElMessageBox: { confirm: async text => { confirmations.push(text) } }, console, ...overrides
  }
  const helperStart = source.indexOf('const buildShortcutTargets =')
  const applyStart = helperStart >= 0 ? helperStart : source.indexOf('const handleApplyToAllModels =')
  const apply = source.slice(applyStart,source.indexOf('// 当前值应用到该行所有字段'))
  const complete = source.slice(source.indexOf('const handleBatchCompleteRdStatus ='),source.indexOf('// 显示右键菜单'))
  const copy = source.slice(source.indexOf('const handleCopyRowConfig ='),source.indexOf('// 查看该行差异'))
  const paste = source.slice(source.indexOf('const confirmPasteRowConfig ='),source.indexOf('const fieldLabels ='))
  const methods = new Function(...Object.keys(context),`${apply}\n${complete}\n${copy}\n${paste};return {handleBatchCompleteRdStatus,handleApplyToAllModels,confirmApplyToAll,handleCopyRowConfig,confirmPasteRowConfig}`)(...Object.values(context))
  return {...context,...methods,rows,calls,confirmations,messages}
}
test('mark completed only changes current filtered rows, with exact confirmation counts', async () => {
  const app = bulkApp(); await app.handleBatchCompleteRdStatus()
  assert.deepEqual(app.calls.map(call => call.rowId),[1,1])
  assert.match(app.confirmations[0], /1.*行.*2.*机型.*2.*处/)
  assert.equal(app.rows[1].model_values[10].rd_status,'未完成')
})
test('mark completed freezes scope and blocks a second click while confirming', async () => {
  const confirmation = deferred(); let shown=0
  const app = bulkApp({ElMessageBox:{ confirm:()=>{shown++;return confirmation.promise} }})
  const first = app.handleBatchCompleteRdStatus(); app.selectedModels.value=[20]; app.filteredTableData.value=[app.rows[1]]
  const second = app.handleBatchCompleteRdStatus(); confirmation.resolve(); await Promise.all([first,second])
  assert.equal(shown,1); assert.deepEqual(app.calls.map(call=>[call.rowId,call.modelId]),[[1,10],[1,20]])
})
test('mark completed never writes to a new batch after the confirmation scope becomes stale', async () => {
  const confirmation=deferred(); const app=bulkApp({ElMessageBox:{confirm:()=>confirmation.promise}})
  const pending=app.handleBatchCompleteRdStatus(); app.draftBatchMap.value=new Map([[5,'B']]); confirmation.resolve(); await pending
  assert.equal(app.calls.length,0)
})
test('apply all freezes the reviewed model targets and leaves failures open for safe retry', async () => {
  let attempts=0; const app=bulkApp({handleCellChange:async (row,model,field,value)=>{ attempts++; if(attempts===1){row.model_values[model][field]='●';return false} return true }})
  app.handleApplyToAllModels('field'); app.selectedModels.value=[10]; await app.confirmApplyToAll()
  assert.equal(attempts,1); assert.equal(app.applyToAllDialog.visible,true); assert.equal(app.applyToAllDialog.result.failed,1)
  await app.confirmApplyToAll(); assert.equal(attempts,2); assert.equal(app.applyToAllDialog.visible,false)
})
test('apply all old completion cannot close a newer dialog and double confirm cannot cancel in-flight state', async () => {
  const save=deferred(); const app=bulkApp({handleCellChange:()=>save.promise})
  app.handleApplyToAllModels('field'); const pending=app.confirmApplyToAll(); await Promise.resolve()
  const second=app.confirmApplyToAll(); await Promise.resolve(); assert.equal(app.applyToAllDialog.visible,true)
  app.applyToAllDialog.request++; app.applyToAllDialog.visible=true; save.resolve(true); await Promise.all([pending,second])
  assert.equal(app.applyToAllDialog.visible,true)
})
test('paste completion preserves a newer clipboard and dialog', async () => {
  const save=deferred(); const app=bulkApp({handleCellChange:()=>save.promise})
  app.handleCopyRowConfig(); app.pasteRowDialog.targetRowId=2; const pending=app.confirmPasteRowConfig(); await Promise.resolve()
  const newer={sourceRowId:99,config:{10:{final_config:'NEW'}}}; app.copiedRowConfig.value=newer; app.pasteRowDialog.request++; app.pasteRowDialog.visible=true
  save.resolve(true); await pending
  assert.equal(app.copiedRowConfig.value,newer); assert.equal(app.pasteRowDialog.visible,true)
})
test('failed paste retains its target and copied configuration for retry', async () => {
  const app=bulkApp({handleCellChange:async()=>false}); app.rows[1].model_values[10].final_config='different'; app.handleCopyRowConfig(); app.pasteRowDialog.targetRowId=2; const copied=app.copiedRowConfig.value
  await app.confirmPasteRowConfig()
  assert.equal(app.pasteRowDialog.visible,true); assert.equal(app.copiedRowConfig.value,copied); assert.ok(app.pasteRowDialog.result.failed>0)
})


test('row apply uses the four reviewed source values, not later source edits', async () => {
  const app=bulkApp(); app.rows[0].model_values[10].current_config='source-current'
  app.handleApplyToAllModels('row'); app.rows[0].model_values[10].current_config='later-current'; await app.confirmApplyToAll()
  assert.equal(app.rows[0].model_values[20].current_config,'source-current')
})

test('paste retry sends only failed fields with the frozen source values', async () => {
  const calls=[]; let retry=false
  const app=bulkApp({handleCellChange:async(row,model,field,value,oldValue)=>{calls.push({model,field,value}); if(!retry && field==='final_config'){row.model_values[model][field]=oldValue;return false} return true}})
  app.rows[0].model_values[10].current_config='COPY'; app.rows[1].model_values[10].final_config='old'
  app.handleCopyRowConfig(); app.pasteRowDialog.targetRowId=2; await app.confirmPasteRowConfig()
  assert.equal(app.pasteRowDialog.result.success,1); assert.equal(app.pasteRowDialog.result.failed,1)
  app.rows[0].model_values[10].final_config='later source'; retry=true; await app.confirmPasteRowConfig()
  assert.deepEqual(calls.map(call=>[call.field,call.value]),[['final_config','X'],['current_config','COPY'],['final_config','X']])
  assert.equal(app.pasteRowDialog.visible,false)
})
