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
