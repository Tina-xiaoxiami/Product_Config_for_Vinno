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
    configReady: ref(true), loading: ref(false), configLoadError: ref(''), applyingModelGroup: ref(false), reviewInteractionLocked: ref(false), rdCompleteSubmitting: ref(false),
    draftBatchMap: ref(new Map([[5, 'A']])), selectedModels: ref([10,20]), tableData: ref(rows), filteredTableData: ref([rows[0]]),
    applyToAllDialog: { visible:false, saving:false, row:null, request:0, targets:[], retryTargets:null, modelIds:[], result:null },
    pasteRowDialog: { visible:false, saving:false, targetRowId:null, request:0, targets:[], retryTargets:null, result:null, modelIds:[] },
    contextMenu: { row:rows[0], modelId:10, field:'final_config' }, copiedRowConfig: ref(null), hideContextMenu(){},
    // These tests start from an already-open, validated menu session.
    takeContextMenuTarget: () => {
      const { row,modelId,field } = context.contextMenu
      if (!row) return null
      const modelIds = [...context.selectedModels.value]
      const rowTargets = modelIds.flatMap(id => ['final_config','current_config','selection_config','rd_status'].map(targetField => ({
        row,modelId:id,field:targetField,oldValue:row.model_values[id][targetField],
        context:context.captureDraftCellContext(row,id,targetField)
      })))
      context.contextMenu.row = null
      return { row,modelId,field,modelIds,rowTargets,sourceValues:{...row.model_values[modelId]} }
    },
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

test('apply and paste retry do not write while configuration loading has failed', async () => {
  const apply=bulkApp(); apply.handleApplyToAllModels('field'); apply.configLoadError.value='配置数据加载失败'; await apply.confirmApplyToAll()
  assert.equal(apply.calls.length,0); assert.equal(apply.applyToAllDialog.visible,true); assert.equal(apply.applyToAllDialog.result,null)

  const paste=bulkApp(); paste.handleCopyRowConfig(); paste.pasteRowDialog.targetRowId=2; paste.configLoadError.value='配置数据加载失败'; await paste.confirmPasteRowConfig()
  assert.equal(paste.calls.length,0); assert.equal(paste.pasteRowDialog.visible,true); assert.equal(paste.pasteRowDialog.result,null)
})

test('shortcut dialogs disable confirmation while configuration is not ready, loading, or failed', () => {
  const applyDialog=source.slice(source.indexOf('<!-- 应用到所有机型确认对话框 -->'),source.indexOf('<!-- 粘贴整行配置对话框 -->'))
  const pasteDialog=source.slice(source.indexOf('<!-- 粘贴整行配置对话框 -->'),source.indexOf('<!-- 行差异查看对话框 -->'))
  assert.match(applyDialog,/:disabled="[^"]*!configReady[^"]*loading[^"]*configLoadError/)
  assert.match(pasteDialog,/:disabled="[^"]*!configReady[^"]*loading[^"]*configLoadError/)
})

test('shortcut saving stops before the next target when configuration starts loading', async () => {
  let app; const fields=[]
  app=bulkApp({handleCellChange:async(_row,_model,field)=>{fields.push(field);if(fields.length===1)app.loading.value=true;return true}})
  Object.assign(app.rows[0].model_values[10],{current_config:'COPY',selection_config:'Optional',rd_status:'已完成'})
  app.handleApplyToAllModels('row'); await app.confirmApplyToAll()
  assert.deepEqual(fields,['final_config'])
  assert.deepEqual(app.applyToAllDialog.result,{success:1,failed:0,unchanged:0,stale:1})
  assert.equal(app.applyToAllDialog.visible,true)
  assert.equal(app.messages.at(-1).type,'warning')
})

test('a load failure during the final save is reported as stale without losing the successful save count', async () => {
  const save=deferred(); const app=bulkApp({handleCellChange:()=>save.promise})
  app.handleApplyToAllModels('field'); const pending=app.confirmApplyToAll(); await Promise.resolve()
  app.configLoadError.value='配置数据加载失败'; save.resolve(true); await pending
  assert.deepEqual(app.applyToAllDialog.result,{success:1,failed:0,unchanged:1,stale:1})
  assert.equal(app.applyToAllDialog.visible,true)
  assert.equal(app.messages.at(-1).type,'warning')
})

test('a batch change during the final save is reported as stale without losing the successful save count', async () => {
  const save=deferred(); const app=bulkApp({handleCellChange:()=>save.promise})
  app.handleApplyToAllModels('field'); const pending=app.confirmApplyToAll(); await Promise.resolve()
  app.draftBatchMap.value=new Map([[5,'B']]); save.resolve(true); await pending
  assert.deepEqual(app.applyToAllDialog.result,{success:1,failed:0,unchanged:1,stale:1})
  assert.equal(app.applyToAllDialog.visible,true)
  assert.equal(app.messages.at(-1).type,'warning')
})

test('a successful reload may hide frozen targets without invalidating their save scope', async () => {
  let app; const fields=[]
  app=bulkApp({handleCellChange:async(_row,_model,field)=>{fields.push(field);if(fields.length===1)app.tableData.value=[app.rows[1]];return true}})
  Object.assign(app.rows[0].model_values[10],{current_config:'COPY',selection_config:'Optional',rd_status:'已完成'})
  app.handleApplyToAllModels('row'); await app.confirmApplyToAll()
  assert.deepEqual(fields,['final_config','current_config','selection_config','rd_status'])
  assert.deepEqual(app.applyToAllDialog.result,{success:4,failed:0,unchanged:0,stale:0})
  assert.equal(app.applyToAllDialog.visible,false)
})
