import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
const source = readFileSync(new URL('../src/views/Config.vue', import.meta.url), 'utf8')
const ref = value => ({ value })
const deferred = () => { let resolve, reject; const promise = new Promise((r,j) => { resolve=r; reject=j }); return { promise, resolve, reject } }
function modelApp(overrides = {}) {
  const messages = []
  const ctx = {
    selectedSeries: ref([1]), seriesList: ref([{ id:1, name:'A' }, { id:2, name:'B' }]),
    allModelsMap: ref(new Map()), selectedModels: ref([]), tempSelectedModels: ref([]), tableData: ref([]), originalData: ref([]),
    configReady: ref(true), configLoadError: ref(''), loading: ref(false), applyingModelGroup: ref(false),
    getModels: async sid => ({ items:[{ id:sid, name:'model' }] }), resolveGroupModels: () => null,
    applySavedOrder() {}, showDiffOnly: ref(false), referenceModel: ref(null),
    loadData: async () => true, initDraft: async () => true, loadSeries: async () => {},
    ElMessage: { error:m => messages.push(m), warning:m => messages.push(m) }, console: { error() {} }, ...overrides
  }
  const code = source.slice(source.indexOf('let modelLoadRequest ='), source.indexOf('// 加载配置数据'))
  return { ...ctx, ...new Function(...Object.keys(ctx), `${code};return { loadModels }`)(...Object.values(ctx)), messages }
}
function dataApp(getConfigRows) {
  const ctx = { selectedSeries:ref([1]), selectedCategories:ref([]), searchText:ref(''), tableData:ref([{id:9}]), originalData:ref([{id:9}]),
    loading:ref(false), configLoadError:ref(''), getConfigRows, ElMessage:{error(){},warning(){}}, loadSeries:async()=>{}, applyingModelGroup:ref(false), console:{error(){}} }
  const code=source.slice(source.indexOf('let dataLoadRequest ='), source.indexOf('// 检查字段是否被修改'))
  return { ...ctx, ...new Function(...Object.keys(ctx), `${code};return {loadData}`)(...Object.values(ctx)) }
}
test('model and draft failures expose a persistent recovery message instead of indefinite loading', async () => {
  const models=modelApp({tableData:ref([{id:9}]), originalData:ref([{id:9}]), getModels:async()=>{throw new Error('offline')}})
  assert.equal(await models.loadModels(), false)
  assert.match(models.configLoadError.value,/机型/)
  assert.deepEqual(models.tableData.value,[])
  assert.deepEqual(models.originalData.value,[])
  const drafts=modelApp({initDraft:async()=>false})
  assert.equal(await drafts.loadModels(),false)
  assert.match(drafts.configLoadError.value,/草稿/)
  const code=source.match(/const configLoading = computed\(\(\) => \([\s\S]*?\)\)/)[0]
  const ctx={loading:models.loading,applyingModelGroup:models.applyingModelGroup,selectedSeries:models.selectedSeries,configReady:models.configReady,configLoadError:models.configLoadError,computed:fn=>({get value(){return fn()}})}
  const spinner=new Function(...Object.keys(ctx),`${code};return configLoading`)(...Object.values(ctx))
  assert.equal(spinner.value,false)
})
test('a successful reload clears failure only after all configuration and draft initialization succeeds',async()=>{
  let failed=true
  const a=modelApp({getModels:async()=>{if(failed)throw new Error('offline');return {items:[{id:1,name:'M'}]}}})
  await a.loadModels(); failed=false
  assert.equal(await a.loadModels(),true)
  assert.equal(a.configLoadError.value,'')
  assert.equal(a.configReady.value,true)
})
test('an old model request failure cannot display an error after switching series succeeds',async()=>{
  const old=deferred()
  const a=modelApp({getModels:sid=>sid===1?old.promise:Promise.resolve({items:[{id:2,name:'B'}]})})
  const first=a.loadModels(); a.selectedSeries.value=[2]; await a.loadModels()
  old.reject(new Error('old offline')); assert.equal(await first,false)
  assert.equal(a.configLoadError.value,'')
  assert.deepEqual(a.messages,[])
  assert.equal(a.configReady.value,true)
})
test('a data failure is visible and reload restores current rows',async()=>{
  let fail=true
  const a=dataApp(async()=>{if(fail)throw new Error('offline');return {items:[{id:3,ipn:'new',model_values:{}}]}})
  assert.equal(await a.loadData(),false)
  assert.match(a.configLoadError.value,/配置/)
  fail=false; assert.equal(await a.loadData(),true)
  assert.equal(a.configLoadError.value,'')
  assert.equal(a.tableData.value[0].id,3)
})
test('clearing the series selection ends data loading and invalidates its pending error',async()=>{
  const old=deferred(); const a=dataApp(()=>old.promise)
  const first=a.loadData(); a.selectedSeries.value=[]
  await a.loadData()
  assert.equal(a.loading.value,false)
  old.reject(new Error('old offline')); await first
  assert.equal(a.configLoadError.value,'')
  assert.deepEqual(a.tableData.value,[])
})
test('the recovery action blocks duplicate clicks and reloads initial series when needed',async()=>{
  const code=source.match(/const retryConfiguration = [\s\S]*?(?=\/\/ 初始化草稿批次)/)
  assert.ok(code,'load failure requires an explicit recovery control')
  const pending=deferred(); let modelCalls=0,seriesCalls=0
  const ctx={configRetrying:ref(false),loading:ref(false),applyingModelGroup:ref(false),reviewInteractionLocked:ref(false),seriesList:ref([{id:1}]),selectedSeries:ref([1]),
    loadModels:async()=>{modelCalls++},loadSeries:async()=>{seriesCalls++;await pending.promise}}
  const retry=new Function(...Object.keys(ctx),`${code[0]};return retryConfiguration`)(...Object.values(ctx))
  const first=retry(); await retry(); assert.equal(modelCalls,0); assert.equal(seriesCalls,1); assert.equal(ctx.configRetrying.value,true)
  pending.resolve(); await first; assert.equal(ctx.configRetrying.value,false)
  ctx.seriesList.value=[]; await retry(); assert.equal(seriesCalls,2)
})

function seriesApp(getSeriesList) {
  let modelCalls=0
  const ctx={selectedSeries:ref([1]),seriesList:ref([{id:1,name:'cached'}]),allModelsMap:ref(new Map()),selectedModels:ref([]),tempSelectedModels:ref([]),tableData:ref([]),originalData:ref([]),
    configLoadError:ref(''),configReady:ref(true),configRetrying:ref(false),loading:ref(false),applyingModelGroup:ref(false),reviewInteractionLocked:ref(false),
    getSeriesList,loadModels:async()=>{modelCalls++;return true},modelLoadRequest:0,SERIES_SELECTION_KEY:'series_selection',
    ElMessage:{error(){},warning(){}},console:{error(){}},localStorage:{getItem:()=>JSON.stringify({selected_ids:[1]})}}
  const load=source.slice(source.indexOf('// 加载产品系列'),source.indexOf('// 全选系列'))
  const methods=new Function(...Object.keys(ctx),`${load};return {loadSeries}`)(...Object.values(ctx))
  const retryCode=source.match(/const retryConfiguration = [\s\S]*?(?=\/\/ 初始化草稿批次)/)[0]
  const combined={...ctx,...methods}
  const retry=new Function(...Object.keys(combined),`${retryCode};return retryConfiguration`)(...Object.values(combined))
  return {...combined,retry,modelCalls:()=>modelCalls}
}
test('recovery retries series retrieval even when the old series list is non-empty',async()=>{
  let calls=0
  const app=seriesApp(async()=>{calls++;if(calls===1)throw new Error('offline');return {items:[{id:1,name:'refreshed'}]}})
  await app.loadSeries();assert.match(app.configLoadError.value,/产品系列/)
  await app.retry()
  assert.equal(calls,2)
  assert.equal(app.seriesList.value[0].name,'refreshed')
  assert.equal(app.configLoadError.value,'')
  assert.equal(app.modelCalls(),1)
})
test('a superseded series failure cannot hide a successful refreshed list',async()=>{
  const old=deferred();let calls=0
  const app=seriesApp(()=>++calls===1?old.promise:Promise.resolve({items:[{id:1,name:'new'}]}))
  const first=app.loadSeries();await app.loadSeries();old.reject(new Error('old offline'));await first
  assert.equal(app.configLoadError.value,'')
  assert.equal(app.seriesList.value[0].name,'new')
})
test('a superseded series success cannot replace the newest list or reload its models',async()=>{
  const old=deferred();let calls=0
  const app=seriesApp(()=>++calls===1?old.promise:Promise.resolve({items:[{id:1,name:'new'}]}))
  const first=app.loadSeries();await app.loadSeries();old.resolve({items:[{id:1,name:'old'}]});await first
  assert.equal(app.seriesList.value[0].name,'new')
  assert.equal(app.modelCalls(),1)
})
