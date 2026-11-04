import test from 'node:test'
import assert from 'node:assert/strict'
import { createApplicationDraftStore } from '../src/utils/probeApplications.js'

const changes = { '1_2_regular': { action:'remove',catId:1,appId:2,appName:'腹部常规',probeType:'regular' },
  '3_4_poc': { action:'add',catId:3,appId:4,appName:'FAST',probeType:'poc' } }
function memory() { const data=new Map();return {data,getItem:key=>data.get(key)||null,setItem:(key,value)=>data.set(key,value),removeItem:key=>data.delete(key)} }
test('staged associations survive an immediate reload without creating a version',()=>{
  const storage=memory(),store=createApplicationDraftStore(storage)
  assert.deepEqual(store.restore().changes,{})
  assert.equal(store.save(changes,{categoryId:3,editMode:true}),true)
  const restored=createApplicationDraftStore(storage).restore()
  assert.deepEqual(restored.changes,changes);assert.equal(restored.categoryId,3);assert.equal(restored.editMode,true)
  restored.changes['1_2_regular'].appName='改动内存'
  assert.equal(createApplicationDraftStore(storage).restore().changes['1_2_regular'].appName,'腹部常规')
  assert.equal(store.clear(),true)
  assert.deepEqual(createApplicationDraftStore(storage).restore().changes,{})
})
test('quota failure keeps the last durable draft and reports unsaved current changes',()=>{
  const storage=memory(),warnings=[],store=createApplicationDraftStore(storage,message=>warnings.push(message))
  store.restore();assert.equal(store.save(changes,{editMode:true}),true)
  storage.setItem=()=>{throw Error('quota')}
  assert.equal(store.save({}, {editMode:true}),false)
  assert.deepEqual(createApplicationDraftStore(storage).restore().changes,changes)
  assert.ok(warnings.length>0)
})
test('corrupt data and cross-tab changes cannot be silently overwritten',()=>{
  const storage=memory(),first=createApplicationDraftStore(storage),second=createApplicationDraftStore(storage)
  first.restore();second.restore();assert.equal(first.save(changes,{}),true)
  assert.equal(second.save({},{}),false)
  const key=[...storage.data.keys()][0];storage.data.set(key,'broken json')
  const bad=createApplicationDraftStore(storage);assert.ok(bad.restore().error)
  assert.equal(bad.save(changes,{}),false);assert.equal(storage.data.get(key),'broken json')
})

import { readFileSync } from 'node:fs'
import { applicationChangeStillPending, applicationEditorState } from '../src/utils/probeApplications.js'
const view=readFileSync(new URL('../src/views/ApplicationsView.vue',import.meta.url),'utf8')
test('discard refuses to erase working edits or report success when durable clear fails',()=>{
  const state={pendingChanges:structuredClone(changes),editMode:{value:true},draftStore:{clear:()=>false},draftSaved:{value:true},draftError:{value:''},committedUncleared:{value:false}}
  const block=view.slice(view.indexOf('const clearLocalChanges ='),view.indexOf('const enterEditMode ='))
  const clear=new Function(...Object.keys(state), 'let draftWritePaused=false;'+block+';return clearLocalChanges')(...Object.values(state))
  assert.equal(clear(),false);assert.deepEqual(state.pendingChanges,changes);assert.equal(state.editMode.value,true);assert.equal(state.draftSaved.value,false)
})
test('restored already-published edits are filtered before a version can be created',()=>{
  assert.equal(applicationChangeStillPending(changes['1_2_regular'],{regular:[],poc:[]}),false)
  assert.equal(applicationChangeStillPending(changes['3_4_poc'],{regular:[],poc:[{id:4}]}),false)
  assert.equal(applicationChangeStillPending(changes['1_2_regular'],{regular:[{id:2}],poc:[]}),true)
  assert.equal(applicationChangeStillPending(changes['3_4_poc'],{regular:[],poc:[]}),true)
  assert.equal(applicationEditorState({pendingCount:2,editMode:true,draftSaved:true}).protected,false)
  assert.equal(applicationEditorState({pendingCount:2,editMode:true,draftSaved:false}).protected,true)
})

test('a committed addition retained for cleanup appears only once after official data refreshes',()=>{
  for(const kind of ['regular','poc']) {
    const start=view.indexOf(`const ${kind}Apps = computed(`)
    const end=view.indexOf('\n})',start)+3
    const refs={editMode:{value:true},selectedCategory:{value:{id:1}},categoryApps:{value:{[kind]:[{id:2,name:'应用'}]}},pendingChanges:{one:{action:'add',catId:1,appId:2,appName:'应用',probeType:kind}},computed:fn=>({get value(){return fn()}})}
    const apps=new Function(...Object.keys(refs),view.slice(start,end)+`;return ${kind}Apps`)(...Object.values(refs))
    assert.equal(apps.value.length,1)
  }
})
