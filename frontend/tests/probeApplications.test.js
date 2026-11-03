import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolveProbeCategory, applicationEditorState, probeContextBlock, createCategoryApplicationLoader, probeModelRows } from '../src/utils/probeApplications.js'

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
