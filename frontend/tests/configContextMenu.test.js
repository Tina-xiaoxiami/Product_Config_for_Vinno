import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { ref, reactive, watch, effectScope } from 'vue'

const source=readFileSync(new URL('../src/views/Config.vue',import.meta.url),'utf8')
function eventSurface() {
  const listeners=new Map()
  return {
    listeners,
    addEventListener(name,handler){if(!listeners.has(name))listeners.set(name,new Set());listeners.get(name).add(handler)},
    removeEventListener(name,handler){listeners.get(name)?.delete(handler);if(!listeners.get(name)?.size)listeners.delete(name)},
    dispatch(name,event={}){for(const handler of [...(listeners.get(name)||[])])handler(event)}
  }
}
function menuApp({width=1280,height=577,menuWidth=220,menuHeight=397}={}) {
  const window=Object.assign(eventSurface(),{innerWidth:width,innerHeight:height}), document=eventSurface()
  const rows=[1,2,3].map(id=>({id,rd_name:`row-${id}`,model_values:{10:{final_config:`S-${id}`,current_config:`C-${id}`,selection_config:'O',rd_status:'未完成'},20:{final_config:'O',current_config:'',selection_config:'',rd_status:'未完成'}}}))
  const ticks=[],timers=new Map(),calls=[],messages=[]
  let timer=0,measurements=0
  const inside={menuChild:true}
  const menuElement={getBoundingClientRect:()=>{measurements++;return{width:menuWidth,height:menuHeight}},contains:target=>target===menuElement||target===inside}
  const ctx={
    window,document,watch,contextMenu:reactive({visible:false,x:0,y:0,row:null,modelId:null,field:null,scope:null,request:0,positioned:false}),contextMenuRef:ref(menuElement),
    configReady:ref(true),loading:ref(false),applyingModelGroup:ref(false),reviewInteractionLocked:ref(false),
    currentPage:ref(1),pageSize:ref(100),selectedModels:ref([10,20]),visibleConfigFields:ref(['final_config','current_config','selection_config','rd_status']),selectedSeries:ref([5]),
    tableData:ref(rows),paginatedTableData:ref(rows.slice(0,2)),draftBatchMap:ref(new Map([[5,'A']])),
    selectedCells:ref([]),copiedCell:ref(null),copiedRowConfig:ref(null),cancelEditSession(){},
    applyToAllDialog:reactive({visible:false,saving:false,request:0,targets:[],modelIds:[]}),pasteRowDialog:reactive({visible:false,saving:false,request:0}),rowDiffDialog:reactive({visible:false,row:null}),
    isValueChanged:(a,b)=>a!==b,
    captureDraftCellContext:(row,modelId,field,key)=>({row,modelId,field,key,seriesId:5,batchId:ctx.draftBatchMap.value.get(5)}),
    isDraftCellScopeCurrent:context=>ctx.draftBatchMap.value.get(5)===context.batchId,
    isDraftCellContextCurrent:context=>ctx.tableData.value.includes(context.row)&&ctx.draftBatchMap.value.get(5)===context.batchId,
    handleCellChange:async(...args)=>{calls.push(args);return true},
    ElMessage:Object.fromEntries(['success','warning','error','info'].map(type=>[type,message=>messages.push({type,message})])),console:{error(){}},
    nextTick:callback=>ticks.push(callback),setTimeout:callback=>{timers.set(++timer,callback);return timer},clearTimeout:id=>timers.delete(id)
  }
  const menu=source.slice(source.indexOf('// 显示右键菜单'),source.indexOf('// 处理应用到所有机型'))
  const actions=source.slice(source.indexOf('const buildShortcutTargets ='),source.indexOf('// 获取行差异对比数据'))
  const clipboard=source.slice(source.indexOf('// 复制单元格\nconst copyCell'),source.indexOf('onMounted(() =>'))
  const lifeStart=source.indexOf('// 右键菜单范围清理')
  const lifecycle=lifeStart<0?'':source.slice(lifeStart,source.indexOf('// 右键菜单范围清理结束',lifeStart))
  const scope=effectScope()
  const methods=scope.run(()=>new Function(...Object.keys(ctx),`${menu}\n${actions}\n${clipboard}\n${lifecycle}\nreturn {showContextMenu,hideContextMenu,handleCopyCell,handlePasteCell,handleClearCell,handleCopyRowConfig,handleViewRowDiff,handleApplyToAllModels,handleApplyValueToAllFields,pasteToSelectedCells}`)(...Object.values(ctx)))
  return {...ctx,...methods,calls,messages,inside,menuElement,get measurements(){return measurements},
    get rows(){return ctx.tableData.value},open(row=ctx.tableData.value[0],model=10,field='final_config',x=1268,y=565){return methods.showContextMenu({clientX:x,clientY:y},row,model,field)},
    flush(){ticks.splice(0).forEach(fn=>fn());const callbacks=[...timers.values()];timers.clear();callbacks.forEach(fn=>fn())},stop:()=>scope.stop()}
}

test('bottom-right menu uses the measured nine-item height and stays within the viewport',()=>{
  const app=menuApp();app.open();app.flush()
  assert.equal(app.measurements,1)
  assert.ok(app.contextMenu.y+397<=577)
  assert.ok(app.contextMenu.x+220<=1280)
  assert.ok(app.contextMenu.x>=0&&app.contextMenu.y>=0)
  app.stop()
})
test('small viewports clamp nonnegative coordinates and allow the constrained menu to scroll',()=>{
  const app=menuApp({width:120,height:100,menuWidth:104,menuHeight:84});app.open(undefined,10,'final_config',119,99);app.flush()
  assert.ok(app.contextMenu.x>=0&&app.contextMenu.y>=0)
  assert.ok(app.contextMenu.x+104<=120&&app.contextMenu.y+84<=100)
  const css=source.slice(source.indexOf('.context-menu {'),source.indexOf('.context-menu .menu-item {'))
  assert.match(css,/max-height:/);assert.match(css,/max-width:/);assert.match(css,/overflow-y:\s*auto/)
  app.stop()
})
for(const event of ['escape','scroll','outside','resize']) {
  test(`${event} closes the menu, removes targets and unregisters its listeners`,()=>{
    const app=menuApp();app.open();app.flush()
    if(event==='escape')app.document.dispatch('keydown',{key:'Escape',preventDefault(){}})
    if(event==='scroll')app.window.dispatch('scroll',{target:{}})
    if(event==='outside')app.document.dispatch('pointerdown',{target:{}})
    if(event==='resize')app.window.dispatch('resize')
    assert.equal(app.contextMenu.visible,false);assert.equal(app.contextMenu.row,null)
    assert.equal(app.document.listeners.size,0);assert.equal(app.window.listeners.size,0)
    app.stop()
  })
}
test('scrolling or pointing within a tall menu keeps it open',()=>{
  const app=menuApp();app.open();app.flush()
  app.window.dispatch('scroll',{target:app.menuElement});app.document.dispatch('pointerdown',{target:app.inside})
  assert.equal(app.contextMenu.visible,true)
  app.stop()
})
test('hiding before queued measurement cannot attach leaked listeners or reopen the menu',()=>{
  const app=menuApp();app.open();app.hideContextMenu();app.flush()
  assert.equal(app.contextMenu.visible,false);assert.equal(app.document.listeners.size,0);assert.equal(app.window.listeners.size,0)
  assert.equal(app.measurements,0)
  app.stop()
})
test('rapid reopen measures and positions only the latest menu session',()=>{
  const app=menuApp();app.open(undefined,10,'final_config',20,20);app.open(app.rows[1],10,'final_config',80,60);app.flush()
  assert.equal(app.measurements,1);assert.equal(app.contextMenu.row,app.rows[1]);assert.equal(app.contextMenu.x,80);assert.equal(app.contextMenu.y,60)
  app.stop()
})
for(const transition of ['page','filter','row','model','field','batch','loading']) {
  test(`${transition} transition closes the menu and makes a stale clear action inert`,async()=>{
    const app=menuApp(),row=app.rows[0];app.open();app.flush()
    if(transition==='page')app.currentPage.value=2
    if(transition==='filter')app.paginatedTableData.value=[]
    if(transition==='row'){app.tableData.value=app.rows.map(item=>({...item}));app.paginatedTableData.value=app.rows.slice(0,2)}
    if(transition==='model')app.selectedModels.value=[20]
    if(transition==='field')app.visibleConfigFields.value=['current_config']
    if(transition==='batch')app.draftBatchMap.value.set(5,'B')
    if(transition==='loading')app.loading.value=true
    assert.equal(app.contextMenu.visible,false)
    await app.handleClearCell();assert.equal(app.calls.length,0);assert.equal(row.model_values[10].final_config,'S-1')
    app.stop()
  })
}
test('a menu cannot open for an off-page row or while editing is blocked',()=>{
  const app=menuApp();app.open(app.rows[2]);assert.equal(app.contextMenu.visible,false)
  app.loading.value=true;app.open();assert.equal(app.contextMenu.visible,false)
  app.stop()
})
test('clear and paste keep the captured batch context after consuming their menu target',async()=>{
  const app=menuApp();app.open();await app.handleClearCell()
  assert.equal(app.calls[0][5]?.batchId,'A');assert.equal(app.contextMenu.row,null)
  app.copiedCell.value={value:'PASTED',row:app.rows[1],modelId:10,field:'final_config'}
  app.open();await app.handlePasteCell()
  assert.equal(app.calls[1][5]?.batchId,'A');assert.equal(app.rows[0].model_values[10].final_config,'PASTED')
  app.stop()
})
test('copy, row copy, row view and apply shortcuts reject a reloaded source row',async()=>{
  for(const action of ['handleCopyCell','handleCopyRowConfig','handleViewRowDiff','handleApplyToAllModels','handleApplyValueToAllFields']){
    const app=menuApp();app.open();app.tableData.value=[];app.paginatedTableData.value=[]
    await app[action]('field')
    assert.equal(app.calls.length,0);assert.equal(app.copiedCell.value,null);assert.equal(app.copiedRowConfig.value,null)
    assert.equal(app.rowDiffDialog.visible,false);assert.equal(app.applyToAllDialog.visible,false)
    app.stop()
  }
})
test('selected-cell paste freezes and validates visible row, model, field and batch targets',async()=>{
  const app=menuApp();app.selectedModels.value=[10];app.visibleConfigFields.value=['final_config']
  app.copiedCell.value={value:'PASTED',row:app.rows[0],modelId:10,field:'final_config'}
  app.selectedCells.value=[{rowId:2,modelId:10,field:'final_config'},{rowId:3,modelId:10,field:'final_config'},{rowId:2,modelId:20,field:'final_config'},{rowId:2,modelId:10,field:'current_config'}]
  app.open();await app.pasteToSelectedCells()
  assert.deepEqual(app.calls.map(call=>[call[0].id,call[1],call[2]]),[[2,10,'final_config']])
  assert.equal(app.calls[0][5]?.batchId,'A');assert.equal(app.contextMenu.row,null)
  app.stop()
})
test('all-fields shortcut binds every cell write to the captured source scope',async()=>{
  const app=menuApp();app.open();await app.handleApplyValueToAllFields()
  assert.equal(app.calls.length,3)
  assert.ok(app.calls.every(call=>call[5]?.batchId==='A'))
  app.stop()
})
test('menu labels describe reachable actions and unmount closes its events',()=>{
  const template=source.slice(source.indexOf('<!-- 右键菜单'),source.indexOf('<!-- 应用到所有机型确认'))
  assert.doesNotMatch(template,/Ctrl\+[CV]/);assert.match(template,/应用到已选机型/)
  const hook=source.slice(source.indexOf('onUnmounted(() =>'),source.indexOf('// 编辑会话范围清理'))
  assert.match(hook,/hideContextMenu\(\)/)
})
