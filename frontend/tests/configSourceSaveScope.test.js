import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { ref, reactive } from 'vue'
import { draftBaseline, draftWorkingValue, updateDraftStats } from '../src/utils/configDraftHelpers.js'
const source=readFileSync(new URL('../src/views/Config.vue',import.meta.url),'utf8')
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no});return{promise,resolve,reject}}
function app() {
  const rows=[1,2].map(id=>({id,rd_name:`r${id}`,model_values:{10:{final_config:'X',current_config:'O',selection_config:'O',rd_status:'未完成'},20:{final_config:'O',current_config:'O',selection_config:'O',rd_status:'未完成'}}}))
  const original=structuredClone(rows),writes=[],messages=[],ticks=[]
  let pending=null,pendingKey=null
  const events={addEventListener(){},removeEventListener(){}}
  const ctx={
    document:events,window:{...events,innerWidth:1280,innerHeight:577},nextTick:fn=>ticks.push(fn),
    contextMenu:reactive({visible:false,row:null,scope:null,request:0}),contextMenuRef:ref({getBoundingClientRect:()=>({width:220,height:397}),contains:()=>false}),
    tableData:ref(rows),paginatedTableData:ref(rows),currentPage:ref(1),pageSize:ref(100),selectedModels:ref([10,20]),selectedSeries:ref([5]),visibleConfigFields:ref(['final_config','current_config','selection_config','rd_status']),
    configReady:ref(true),loading:ref(false),applyingModelGroup:ref(false),reviewInteractionLocked:ref(false),cancelEditSession(){},
    originalDataMap:ref(new Map(original.map(row=>[row.id,row]))),draftChanges:ref(new Map()),draftBatchMap:ref(new Map([[5,'A']])),draftStats:{total:0,create:0,update:0,delete:0},
    draftBaseline,draftWorkingValue,updateDraftStats,findSeriesIdByModelId:()=>5,
    draftSaveFeedback:{sequence:0,failures:new Map(),successes:new Map()},refreshSaveFeedback(){},isFeedbackCellScopeCurrent:cell=>ctx.draftBatchMap.value.get(5)===cell.batchId&&ctx.tableData.value.includes(cell.row),
    createDraft:async params=>{writes.push(params);return pending&&pendingKey===`${params.item_id}_${params.model_id}_${params.field_name}`?pending.promise:{draft_id:123}},deleteDraftByKey:async()=>{},
    selectedCells:ref([]),copiedCell:ref(null),copiedRowConfig:ref(null),
    applyToAllDialog:reactive({visible:false,saving:false,request:0,targets:[]}),pasteRowDialog:reactive({visible:false,saving:false,request:0}),rowDiffDialog:reactive({visible:false,row:null}),
    dragSource:ref(null),dragTargetCells:ref([]),isDragging:ref(false),isValueChanged:(a,b)=>a!==b,
    ElMessage:Object.fromEntries(['info','warning','success','error'].map(type=>[type,message=>messages.push({type,message})])),console:{error(){}}
  }
  const cell=source.slice(source.indexOf('const draftCellOperations ='),source.indexOf('// 多文件上传处理'))
  const menu=source.slice(source.indexOf('// 显示右键菜单'),source.indexOf('// 处理应用到所有机型'))
  const actions=source.slice(source.indexOf('const buildShortcutTargets ='),source.indexOf('// 获取行差异对比数据'))
  const clipboard=source.slice(source.indexOf('// 复制单元格\nconst copyCell'),source.indexOf('onMounted(() =>'))
  const drag=source.slice(source.indexOf('const handleDragStart ='),source.indexOf('const navigateToCell =',source.indexOf('const handleDragStart =')))
  const methods=new Function(...Object.keys(ctx),`${cell}\n${menu}\n${actions}\n${clipboard}\n${drag}\nreturn{showContextMenu,hideContextMenu,handleCopyCell,handleCopyRowConfig,handleApplyToAllModels,handleApplyValueToAllFields,confirmApplyToAll,handleCellChange,handleDragStart,performDragFill,highlightDragTarget,handleDrop,hasPendingDraftCellOperation}`)(...Object.values(ctx))
  return{...ctx,...methods,writes,messages,get rows(){return ctx.tableData.value},
    open(row=ctx.tableData.value[0]){return methods.showContextMenu({clientX:100,clientY:100},row,10,'final_config')},
    flush(){ticks.splice(0).forEach(fn=>fn())},
    save(row=ctx.tableData.value[0],modelId=10,field='final_config'){
      pending=deferred();pendingKey=`${row.id}_${modelId}_${field}`;const wait=pending;row.model_values[modelId][field]='optimistic'
      const promise=methods.handleCellChange(row,modelId,field,'optimistic','X');return{...wait,promise}
    },
    drag(row=ctx.tableData.value[0]){let prevented=false;methods.handleDragStart({preventDefault(){prevented=true},dataTransfer:{}},row,10,'final_config');return prevented}
  }
}
for(const action of ['handleCopyCell','handleCopyRowConfig','handleApplyToAllModels','handleApplyValueToAllFields']) {
  test(`source save pending prevents menu ${action} from copying or propagating optimistic values`,async()=>{
    const a=app(),saving=a.save();await Promise.resolve()
    const opened=a.open();a.flush();await a[action]('field')
    const visible=a.contextMenu.visible,copied=a.copiedCell.value,rowCopied=a.copiedRowConfig.value,dialog=a.applyToAllDialog.visible,writes=a.writes.length
    saving.resolve({draft_id:1});await saving.promise
    assert.equal(opened,false);assert.equal(visible,false);assert.equal(copied,null);assert.equal(rowCopied,null);assert.equal(dialog,false);assert.equal(writes,1)
    assert.ok(a.messages.some(message=>/正在保存/.test(message.message)))
  })
}
test('menu consumption rechecks a new pending operation in any selected model and row field',async()=>{
  const a=app();a.open();a.flush();const saving=a.save(a.rows[0],20,'current_config');await Promise.resolve()
  a.handleCopyCell();const copied=a.copiedCell.value
  saving.reject(Error('offline'));await saving.promise
  assert.equal(copied,null);assert.equal(a.contextMenu.visible,false)
})
for(const success of [true,false]) {
  test(`after source ${success?'success':'failure'}, menu reopens with the settled value`,async()=>{
    const a=app(),saving=a.save();a.open();a.flush()
    if(success)saving.resolve({draft_id:1});else saving.reject(Error('offline'))
    await saving.promise
    assert.equal(a.hasPendingDraftCellOperation(a.rows[0],10,'final_config'),false)
    a.open();a.flush();a.handleCopyCell()
    assert.equal(a.copiedCell.value.value,success?'optimistic':'X')
  })
}
test('pending saves in another row do not block a settled source menu',async()=>{
  const a=app(),saving=a.save(a.rows[1]);const opened=a.open();a.flush();a.handleCopyCell()
  saving.resolve({draft_id:1});await saving.promise
  assert.equal(opened,true);assert.equal(a.copiedCell.value.value,'X')
})
test('pending source save prevents drag start and failure retry uses the restored value',async()=>{
  const a=app(),saving=a.save();const prevented=a.drag(),started=a.isDragging.value
  saving.reject(Error('offline'));await saving.promise
  assert.equal(prevented,true);assert.equal(started,false)
  assert.equal(a.drag(),false);assert.equal(a.dragSource.value.value,'X')
})
for(const transition of ['pending','row','model','field','batch']) {
  test(`drag execution rejects a source changed by ${transition}`,async()=>{
    const a=app();a.drag();a.highlightDragTarget(2,20,'final_config');let saving
    if(transition==='pending'){saving=a.save();await Promise.resolve()}
    if(transition==='row'){const replacement={...a.rows[0],model_values:JSON.parse(JSON.stringify(a.rows[0].model_values))};a.tableData.value=[replacement,a.rows[1]];a.paginatedTableData.value=a.tableData.value}
    if(transition==='model')a.selectedModels.value=[20]
    if(transition==='field')a.visibleConfigFields.value=['current_config']
    if(transition==='batch')a.draftBatchMap.value.set(5,'B')
    await a.performDragFill();const writes=a.writes.length
    if(saving){saving.resolve({draft_id:1});await saving.promise}
    assert.equal(writes,transition==='pending'?1:0)
  })
}
test('a pending different source field or other row leaves drag of a settled cell available',async()=>{
  const a=app(),saving=a.save(a.rows[0],10,'current_config');const prevented=a.drag()
  saving.resolve({draft_id:1});await saving.promise
  assert.equal(prevented,false);assert.equal(a.dragSource.value.value,'X')
})
