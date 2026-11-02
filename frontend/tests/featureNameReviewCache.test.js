import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
const source=readFileSync(new URL('../src/utils/featureNameStandard.js',import.meta.url),'utf8').replace(/^import .*$/gm,'').replace(/export /g,'')
const cache=get=>new Function('computed','ref','getFeatureNameStandardFlags',source+';return {loadFeatureNameStandardFlags,featureNameFlag}')(fn=>({get value(){return fn()}}),value=>({value}),get)
const deferred=()=>{let resolve,reject;const promise=new Promise((ok,bad)=>{resolve=ok;reject=bad});return{promise,resolve,reject}}
test('confirmation refresh clears resolved flags globally and stale loads cannot restore them',async()=>{
  const old=deferred(),fresh=deferred();let calls=0
  const state=cache(()=>++calls===1?old.promise:fresh.promise)
  const initial=state.loadFeatureNameStandardFlags()
  const confirmed=state.loadFeatureNameStandardFlags({force:true,strict:true})
  fresh.resolve({by_feature:{},by_name:{}});await confirmed
  old.resolve({by_feature:{1:{severity:'differs'}}});await initial
  assert.equal(state.featureNameFlag({featureId:1}),null)
})
test('failed refresh preserves previous warning and reports strict failures',async()=>{
  let calls=0
  const state=cache(()=>++calls===1?Promise.resolve({by_feature:{1:{severity:'differs'}}}):Promise.reject(new Error('offline')))
  await state.loadFeatureNameStandardFlags()
  await assert.rejects(state.loadFeatureNameStandardFlags({force:true,strict:true}),/offline/)
  assert.equal(state.featureNameFlag({featureId:1}).severity,'differs')
})

test('an explicit feature ID never borrows a same-name feature warning after confirmation',async()=>{
  const other={feature_id:2,severity:'differs'}
  const state=cache(()=>Promise.resolve({by_feature:{2:other},by_name:{same:other}}))
  await state.loadFeatureNameStandardFlags()
  assert.equal(state.featureNameFlag({featureId:1,names:['same']}),null)
  assert.equal(state.featureNameFlag({featureId:2,names:['same']}),other)
  assert.equal(state.featureNameFlag({names:['same']}),other)
})
