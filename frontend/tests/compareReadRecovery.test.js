import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { ref, watch, effectScope } from 'vue'

const source = readFileSync(new URL('../src/views/Compare.vue', import.meta.url), 'utf8')
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }
function readController(overrides = {}) {
  const ticks = [], creates = [], messages = []
  const context = {
    watch, selectedSeries: ref([1]), seriesList: ref([{ id: 1, name: 'One' }, { id: 2, name: 'Two' }]),
    selectedModels: ref([11, 12]), referenceModel: ref(12), modelFilterText: ref(''), allModelsMap: ref(new Map()),
    compareFields: ref(['final_config']), showOnlyDiff: ref(false), compareResult: ref(null), loading: ref(false), currentPage: ref(1),
    seriesLoading: ref(false), modelsLoading: ref(false), comparisonRetrying: ref(false),
    seriesLoadError: ref(''), modelLoadError: ref(''), comparisonError: ref(''),
    originalValues: ref(new Map()), draftChanges: ref(new Map()), draftItemTypes: ref(new Map()), draftBatchMap: ref(new Map()), draftStats: ref({total:0,create:0,update:0,delete:0}),
    getSeriesList: async () => ({ items: [{ id:1, name:'One' }, { id:2, name:'Two' }] }),
    getModels: async id => ({ items:[{ id:id * 10 + 1,name:'A' }, { id:id * 10 + 2,name:'B' }] }),
    compareConfigs: async () => ({ total:1,diff_count:1,items:[{item_id:1,field_name:'final_config',values:{11:'S',12:'O'}}] }),
    getCurrentDraftBatch: async () => ({exists:true,batch:{id:'batch-A'}}), getDraftList: async () => ({items:[]}),
    createDraftBatch: async id => { creates.push(id); return {id:'created'} }, loadEnumValues: async () => {},
    compareTableRef: ref(null), nextTick: callback => ticks.push(callback), console:{error(){}},
    ElMessage:Object.fromEntries(['warning','error','success','info'].map(type=>[type,message=>messages.push({type,message})])), ...overrides
  }
  const start=source.indexOf('// 加载产品系列\nconst loadSeries')
  const code=source.slice(start,source.indexOf('// 加载枚举值\nconst loadEnumValues',start))
  const lifecycleStart=source.indexOf('// 对比条件生命周期')
  const lifecycle=source.slice(lifecycleStart,source.indexOf('// 对比条件生命周期结束',lifecycleStart))
  const scope=effectScope()
  const functions=scope.run(()=>new Function(...Object.keys(context),`${code}\n${lifecycle}\nreturn {loadSeries,loadModels,autoCompare,retryComparison: typeof retryComparison === 'function' ? retryComparison : async () => false}`)(...Object.values(context)))
  return {...context,...functions,creates,messages,stop:()=>scope.stop(),flush:async()=>{ ticks.splice(0).forEach(callback=>callback());await new Promise(resolve=>setImmediate(resolve)) }}
}

test('a current-batch read failure never creates a batch or publishes incomplete results',async()=>{
  const app=readController({getCurrentDraftBatch:async()=>{throw Error('offline')}})
  assert.equal(await app.autoCompare(),false)
  assert.deepEqual(app.creates,[])
  assert.equal(app.compareResult.value,null)
  assert.match(app.comparisonError.value,/草稿/)
  assert.equal(app.loading.value,false)
  app.stop()
})
test('explicit exists:false skips draft reads and all creation on a read-only page',async()=>{
  let drafts=0
  const app=readController({getCurrentDraftBatch:async()=>({exists:false}),getDraftList:async()=>{drafts++;return{items:[]}}})
  assert.equal(await app.autoCompare(),true)
  assert.deepEqual(app.creates,[]);assert.equal(drafts,0)
  assert.equal(app.compareResult.value.items.length,1)
  assert.equal(app.draftStats.value.total,0)
  assert.equal(app.comparisonError.value,'')
  app.stop()
})
test('draft-list failure does not publish partial series statistics and retries the same scope',async()=>{
  let fail=true;const compared=[]
  const app=readController({
    compareConfigs:async payload=>{compared.push(payload);return{total:1,diff_count:1,items:[]}},
    getDraftList:async()=>{if(fail)throw Error('offline');return{items:[{id:1,item_id:1,model_id:11,field_name:'final_config',change_type:'update',old_value:'S',new_value:'O'}]}}
  })
  assert.equal(await app.autoCompare(),false)
  assert.equal(app.compareResult.value,null);assert.match(app.comparisonError.value,/草稿/)
  fail=false;assert.equal(await app.retryComparison(),true)
  assert.deepEqual(compared[0],compared[1]);assert.equal(app.draftStats.value.total,1)
  assert.equal(app.comparisonError.value,'');assert.equal(app.comparisonRetrying.value,false)
  app.stop()
})
test('model read failure has persistent recovery and successful retry restores valid model choices',async()=>{
  let fail=true
  const app=readController({getModels:async()=>{if(fail)throw Error('offline');return{items:[{id:11,name:'A'},{id:12,name:'B'}]}}})
  assert.equal(await app.loadModels(),false)
  assert.match(app.modelLoadError.value,/机型/);assert.equal(app.modelsLoading.value,false)
  assert.deepEqual(app.selectedModels.value,[])
  fail=false;assert.equal(await app.retryComparison(),true)
  assert.deepEqual(app.selectedModels.value,[11,12]);assert.equal(app.referenceModel.value,12)
  assert.equal(app.modelLoadError.value,'')
  await app.flush();assert.ok(app.compareResult.value)
  app.stop()
})
test('series read failure is persistent and can retry through the existing loader',async()=>{
  let fail=true
  const app=readController({getSeriesList:async()=>{if(fail)throw Error('offline');return{items:[{id:1,name:'One'}]}}})
  assert.equal(await app.loadSeries(),false)
  assert.match(app.seriesLoadError.value,/系列/);assert.equal(app.seriesLoading.value,false)
  fail=false;assert.equal(await app.retryComparison(),true)
  assert.equal(app.seriesLoadError.value,'');assert.deepEqual(app.selectedModels.value,[11,12])
  app.stop()
})
test('older model failure cannot replace the successful current series recovery state',async()=>{
  const slow=deferred()
  const app=readController({getModels:id=>id===1?slow.promise:Promise.resolve({items:[{id:21,name:'new'}]})})
  const old=app.loadModels();app.selectedSeries.value=[2];await app.loadModels()
  slow.reject(Error('stale offline'));await old
  assert.equal(app.modelLoadError.value,'');assert.equal(app.modelsLoading.value,false)
  assert.deepEqual([...app.allModelsMap.value.keys()],[21])
  app.stop()
})
test('a stale draft read failure cannot restore an error after new conditions succeed',async()=>{
  const oldDrafts=deferred();let calls=0
  const app=readController({getDraftList:()=>++calls===1?oldDrafts.promise:Promise.resolve({items:[]})})
  const old=app.autoCompare();await new Promise(resolve=>setImmediate(resolve))
  app.compareFields.value=['current_config'];await app.autoCompare()
  oldDrafts.reject(Error('stale offline'));await old
  assert.equal(app.comparisonError.value,'');assert.ok(app.compareResult.value)
  app.stop()
})
test('repeated retry clicks cannot overlap a recovery request',async()=>{
  const pending=deferred();let calls=0
  const app=readController({getModels:async()=>{calls++;return pending.promise}})
  app.modelLoadError.value='机型加载失败'
  const first=app.retryComparison();await app.retryComparison()
  assert.equal(calls,1);assert.equal(app.comparisonRetrying.value,true)
  pending.resolve({items:[]});await first
  assert.equal(app.comparisonRetrying.value,false)
  app.stop()
})
test('persistent errors and retry control are rendered separately from loading and empty selections',()=>{
  assert.match(source,/<el-alert[\s\S]*?:title="compareLoadError"/)
  assert.match(source,/@click="retryComparison"/)
  assert.match(source,/:loading="comparisonRetrying"/)
  assert.match(source,/:description="comparisonEmptyDescription"/)
})
