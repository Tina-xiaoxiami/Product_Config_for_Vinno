import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolveProbeCategory, applicationEditorState, probeContextBlock, createCategoryApplicationLoader, probeModelRows } from '../src/utils/probeApplications.js'
import { normalizeColumnLayout } from '../src/utils/tableColumnLayout.js'

const deferred = () => { let resolve, reject; const promise = new Promise((yes,no) => { resolve=yes; reject=no }); return { promise,resolve,reject } }

test('one category source resolves initial deep links without refreshing back to an old URL', () => {
  const categories=[{id:1},{id:3}]
  assert.equal(resolveProbeCategory(categories,null,3).id,3)
  assert.equal(resolveProbeCategory(categories,1,null).id,1)
  assert.equal(resolveProbeCategory(categories,99,null).id,1)
  assert.equal(resolveProbeCategory([],1,3),null)
})

test('only the selected category latest request can populate shared applications', async () => {
  const old=deferred(),latest=deferred();let selected=1,loaded=[],errors=[],finishes=0
  const loader=createCategoryApplicationLoader({ readApps:id=>id===1?old.promise:latest.promise,readAvailable:async id=>[{id}],
    selectedId:()=>selected,start(){},loaded:(...args)=>loaded.push(args),failed:error=>errors.push(error),finished:()=>finishes++ })
  const first=loader.load(1);selected=3;const second=loader.load(3)
  latest.resolve({regular:[{id:30}],poc:[]});assert.equal(await second,true)
  old.resolve({regular:[{id:10}],poc:[]});assert.equal(await first,false)
  assert.equal(loaded.length,1);assert.equal(loaded[0][0],3);assert.equal(loaded[0][1].regular[0].id,30)
  assert.equal(finishes,1);assert.deepEqual(errors,[])
  loader.dispose();assert.equal(await loader.load(3),false)
})

test('category loader reports current failure without letting a stale failure clear newer data', async () => {
  const old=deferred();let selected=1,errors=0,applied=0
  const loader=createCategoryApplicationLoader({readApps:id=>id===1?old.promise:Promise.resolve({regular:[],poc:[]}),
    readAvailable:async()=>[],selectedId:()=>selected,start(){},loaded:()=>applied++,failed:()=>errors++,finished(){}})
  const first=loader.load(1);selected=2;await loader.load(2);old.reject(new Error('old'));await first
  assert.equal(applied,1);assert.equal(errors,0)
  const fail=createCategoryApplicationLoader({readApps:async()=>{throw new Error('offline')},readAvailable:async()=>[],selectedId:()=>2,start(){},loaded(){},failed:()=>errors++,finished(){}})
  assert.equal(await fail.load(2),false);assert.equal(errors,1)
})

test('pending applications may cross categories but cannot be lost to refresh deletion or submission', () => {
  const pending=applicationEditorState({pendingCount:2,editMode:true})
  assert.equal(pending.canSwitch,true);assert.equal(pending.canRefresh,false);assert.equal(pending.hasPendingChanges,true)
  assert.equal(probeContextBlock(pending),false);assert.equal(probeContextBlock(pending,true),true)
  for(const state of [{submitting:true},{saving:true},{dialogOpen:true,formDirty:true}]){
    const editor=applicationEditorState(state);assert.equal(editor.canSwitch,false);assert.equal(editor.canRefresh,false)
    assert.equal(probeContextBlock(editor),true)
  }
  assert.equal(applicationEditorState({}).canRefresh,true)
})

test('table presentation keeps each internal model and IPN pair with its history', () => {
  const source=[{id:1,model_number:'Probe',_appCount:0,sort_order:2,_variants:[
    {id:11,internal_model:'A',ipn:'10',history_ids:[11,12]}, {id:13,internal_model:'A',ipn:'20',history_ids:[13]}]}]
  const rows=probeModelRows(source)
  assert.equal(rows[0].position,1);assert.equal(rows[0].application_count,0)
  assert.deepEqual(rows[0].variant_values,['A / 10','A / 20'])
  assert.deepEqual(rows[0]._variants[0].history_ids,[11,12]);assert.equal(source[0].position,undefined)
})

test('one page embeds applications under the shared category and reuses the common table', () => {
  const view=readFileSync(new URL('../src/views/ProbeModelsView.vue',import.meta.url),'utf8')
  const apps=readFileSync(new URL('../src/views/ApplicationsView.vue',import.meta.url),'utf8')
  const table=readFileSync(new URL('../src/components/ProbeDataTable.vue',import.meta.url),'utf8')
  assert.match(view,/<ApplicationsView[\s\S]*?embedded/)
  assert.match(view,/:category-id="selectedCategory\?\.id"/)
  assert.match(view,/<ProbeDataTable/)
  assert.match(apps,/v-if="!embedded" class="panel panel-left"/)
  assert.match(table,/<slot name="cell"/)
  assert.match(table,/format\(row, column\)/)
  assert.doesNotMatch(view,/router\.push\(\{ path: '\/applications'/)
})

const readView = name => readFileSync(new URL(`../src/views/${name}.vue`, import.meta.url),'utf8')
const ref = value => ({value})
test('a fresh probe table shows every model column while retaining saved visibility choices', () => {
  const source=readView('ProbeModelsView')
  const code=source.slice(source.indexOf('const modelColumns ='),source.indexOf('const catDialogVisible ='))
  const columns=new Function(`${code};return modelColumns`)()
  const fresh=normalizeColumnLayout(columns,[])
  assert.deepEqual(fresh.filter(column=>column.visible).map(column=>column.key),
    ['position','model_number','variant_values','application_count','sort_order'])
  const saved=normalizeColumnLayout(columns,[{key:'variant_values',visible:false}])
  assert.equal(saved.find(column=>column.key==='variant_values').visible,false)
  assert.equal(saved.find(column=>column.key==='model_number').fixed,true)
})

test('controlled category changes preserve drafts and submitting cannot switch category', async () => {
  const source=readView('ApplicationsView')
  const code=source.slice(source.indexOf('const selectCategory ='),source.indexOf('const loadCategoryApps ='))
  const selectedCategory=ref({id:1}), addAppId=ref(2), editorState=ref(applicationEditorState({pendingCount:1,editMode:true}))
  const pendingChanges={one:{catId:1,appId:4,probeType:'poc'}}, calls=[]
  const select=new Function('selectedCategory','addAppId','editorState','categoryLoader','pendingChanges',`${code};return selectCategory`)(
    selectedCategory,addAppId,editorState,{load:async id=>{calls.push(id);return true}},pendingChanges)
  await select({id:3});assert.equal(selectedCategory.value.id,3);assert.deepEqual(Object.keys(pendingChanges),['one'])
  editorState.value=applicationEditorState({submitting:true,pendingCount:1})
  assert.equal(await select({id:1}),false);assert.equal(selectedCategory.value.id,3);assert.deepEqual(calls,[3])
})

test('parent refresh and destructive category actions cannot discard application edits', async () => {
  const source=readView('ProbeModelsView'),calls=[]
  const state=ref(applicationEditorState({pendingCount:2,editMode:true}))
  const refreshCode=source.slice(source.indexOf('const refreshData ='),source.indexOf('// Category CRUD'))
  const refresh=new Function('metadataOpen','applicationState','ElMessage','loadData','applicationsPanel',`${refreshCode};return refreshData`)(
    ()=>false,state,{warning:()=>calls.push('warning')},async()=>calls.push('models'),ref({refresh:async()=>calls.push('apps')}))
  assert.equal(await refresh(),false);assert.deepEqual(calls,['warning'])
  const deleteCode=source.slice(source.indexOf('const handleDeleteCategory ='),source.indexOf('// Model CRUD'))
  const remove=new Function('probeContextBlock','applicationState','ElMessage','ElMessageBox','deleteProbeCategory','selectedCategory','loadData',`${deleteCode};return handleDeleteCategory`)(
    probeContextBlock,state,{warning:()=>calls.push('blocked')},{confirm:async()=>calls.push('confirm')},async()=>calls.push('delete'),ref({id:1}),async()=>{})
  await remove({id:1});assert.deepEqual(calls,['warning','blocked'])
  state.value=applicationEditorState({});await refresh();assert.deepEqual(calls,['warning','blocked','models','apps'])
})

test('application changes refresh model counts without recursively refreshing the editor', async () => {
  const source=readView('ProbeModelsView'),calls=[]
  const code=source.slice(source.indexOf('const onApplicationsChanged ='),source.indexOf('const refreshData ='))
  const changed=new Function('loadData',`${code};return onApplicationsChanged`)(async()=>calls.push('models'))
  await changed();assert.deepEqual(calls,['models']);assert.doesNotMatch(code,/applicationsPanel/)
})

test('application definition closing has one confirmation and preserves the form when cancelled', async () => {
  const source=readView('ApplicationsView')
  const code=source.slice(source.indexOf('const closeAppDialog ='),source.indexOf('const discardLocal ='))
  const pending=deferred(),dialogVisible=ref(true),closingAppDialog=ref(false);let confirmations=0
  const close=new Function('saving','formDirty','closingAppDialog','dialogVisible','ElMessageBox',`${code};return closeAppDialog`)(
    ref(false),ref(true),closingAppDialog,dialogVisible,{confirm:()=>{confirmations++;return pending.promise}})
  const first=close();const second=close();assert.equal(confirmations,1)
  pending.reject('cancel');assert.equal(await first,false);assert.equal(await second,false)
  assert.equal(dialogVisible.value,true);assert.equal(closingAppDialog.value,false)
})

test('removing the selected parent category clears its embedded scope without deleting pending edits', async () => {
  const source=readView('ApplicationsView'),start=source.indexOf('watch(() => [props.categoryId, props.categories]')
  const code=source.slice(start,source.indexOf('// ========= Edit mode',start))
  let changed,invalidated=0
  const props={embedded:true},categories=ref([{id:1}]),selectedCategory=ref({id:1}),categoryApps=ref({regular:[{id:5}],poc:[]}),availableApps=ref([{id:6}]),addAppId=ref(6),loadingApps=ref(true)
  const pendingChanges={one:{catId:1,appId:5,probeType:'regular'}}
  const context={props,categories,selectedCategory,categoryApps,availableApps,addAppId,loadingApps,pendingChanges,
    categoryLoader:{invalidate(){invalidated++}},selectCategory:async()=>{},updateCounts:async()=>{},loadAllApps:async()=>{},watch:(_source,handler)=>{changed=handler}}
  new Function(...Object.keys(context),code)(...Object.values(context))
  await changed([undefined,[]],[1,[{id:1}]])
  assert.equal(selectedCategory.value,null);assert.equal(invalidated,1);assert.equal(loadingApps.value,false)
  assert.deepEqual(categoryApps.value,{regular:[],poc:[]});assert.deepEqual(availableApps.value,[]);assert.equal(addAppId.value,null)
  assert.deepEqual(Object.keys(pendingChanges),['one'])
})

test('renaming the current parent category updates embedded metadata without discarding drafts or reselecting', async () => {
  const source=readView('ApplicationsView'),start=source.indexOf('watch(() => [props.categoryId, props.categories]')
  const code=source.slice(start,source.indexOf('// ========= Edit mode',start));let changed,selections=0
  const selectedCategory=ref({id:1,name:'Old'}),latest={id:1,name:'New'},pendingChanges={one:{catId:1}}
  const context={props:{embedded:true},categories:ref([]),selectedCategory,pendingChanges,
    selectCategory:async()=>{selections++},updateCounts:async()=>{},loadAllApps:async()=>{},watch:(_source,handler)=>{changed=handler}}
  new Function(...Object.keys(context),code)(...Object.values(context))
  await changed([1,[latest]],[1,[{id:1,name:'Old'}]])
  assert.equal(selectedCategory.value,latest);assert.equal(selections,0);assert.ok(pendingChanges.one)
})
