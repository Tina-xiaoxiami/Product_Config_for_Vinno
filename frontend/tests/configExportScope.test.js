import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
const source = readFileSync(new URL('../src/views/Config.vue', import.meta.url), 'utf8')
const ref = value => ({ value })
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
function exporter(exportExcel = async () => new Uint8Array([1]), waitForDraftSaves = async () => {}) {
  const calls = [], downloads = [], messages = []
  const context = {
    selectedSeries: ref([1,2]), seriesList: ref([{id:1,name:'国内'},{id:2,name:'海外'}]),
    selectedModels: ref([10,20]), allModelsMap: ref(new Map([[10,{seriesId:1,name:'A'}],[20,{seriesId:2,name:'B'}]])),
    selectedCategories: ref(['Probes']), visibleConfigFields: ref(['final_config']),
    filteredTableData: ref([{id:7}]), draftChanges: ref(new Map()), deletedItemModelMap: ref(new Map()), draftDeleteValues: ref(new Map()), newItemModelMap: ref(new Map()),
    draftBatchMap: ref(new Map([[1,11],[2,22]])),
    configReady: ref(true), loading: ref(false), applyingModelGroup: ref(false), reviewInteractionLocked: ref(false), exporting: ref(false),
    waitForDraftSaves, exportExcel: async (id, params) => {calls.push({id,params});return exportExcel(id,params)}, mergeModelNames: names => names.join('-'),
    Blob, window: {URL:{createObjectURL:()=> 'blob:test', revokeObjectURL() {}}},
    document:{createElement:()=>({setAttribute:(_,filename)=>downloads.push(filename),click(){}}),body:{appendChild(){},removeChild(){}}},
    ElMessage:Object.fromEntries(['warning','info','success','error'].map(type=>[type,message=>messages.push({type,message})])), console:{error(){}}
  }
  const code=source.slice(source.indexOf('// 导出Excel -'),source.indexOf('// 合并型号名称'))
  return {...context,...new Function(...Object.keys(context),`${code};return {handleExport}`)(...Object.values(context)),calls,downloads,messages}
}
test('multi-series export includes every selected series and only visible row/model/field scope', async()=>{
  const a=exporter(); await a.handleExport()
  assert.deepEqual(a.calls[0].params.series_ids,[1,2])
  assert.equal(a.calls[0].params.model_ids,'10,20')
  assert.equal(a.calls[0].params.item_ids,'7')
  assert.equal(a.calls[0].params.visible_fields,'final_config')
  assert.match(a.downloads[0],/\.zip$/)
})
test('a series with no selected models is excluded rather than exporting every model in it',async()=>{
  const a=exporter();a.selectedModels.value=[20];await a.handleExport()
  assert.equal(a.calls[0].id,2)
  assert.equal(a.calls[0].params.model_ids,'20')
  assert.match(a.downloads[0],/\.xlsx$/)
})
for (const field of ['selectedModels','visibleConfigFields']) test(`empty ${field} does not broaden export to hidden scope`,async()=>{
  const a=exporter();a[field].value=[];await a.handleExport();assert.equal(a.calls.length,0)
})
test('export blocks duplicate requests and uses captured names after controls change',async()=>{
  const pending=deferred(),a=exporter(()=>pending.promise)
  const first=a.handleExport();await Promise.resolve();assert.equal(a.exporting.value,true)
  await a.handleExport();a.seriesList.value=[];a.allModelsMap.value=new Map();a.selectedCategories.value=['Changed']
  pending.resolve(new Uint8Array([1]));await first
  assert.equal(a.calls.length,1);assert.match(a.downloads[0],/国内/);assert.match(a.downloads[0],/海外/)
  assert.equal(a.exporting.value,false)
})
test('export waits for pending edits before requesting workbook data',async()=>{
  const pending=deferred(),a=exporter(undefined,()=>pending.promise)
  const first=a.handleExport();await Promise.resolve();assert.equal(a.calls.length,0)
  pending.resolve();await first;assert.equal(a.calls.length,1)
})
