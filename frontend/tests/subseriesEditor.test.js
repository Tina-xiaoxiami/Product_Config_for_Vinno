import test from 'node:test'
import assert from 'node:assert/strict'
import { cloneSubseriesGroups, subseriesGroupOptions, subseriesPayload, subseriesSnapshot } from '../src/utils/subseriesEditor.js'

test('editing preserves existing short names and unmatched members without mutating source',()=>{
 const raw=[{name:'URM',series:'Tulip-China',models:['9E科研版（URM）','旧机型'],options:[{id:40,value:'9E科研版（URM）',label:'ULTIMUS 9E科研版(URM)',series:'Tulip-China'}]}]
 const groups=cloneSubseriesGroups(raw)
 const options=subseriesGroupOptions(groups[0],[{id:40,name:'ULTIMUS 9E科研版(URM)',series:'Tulip-China'},{id:41,name:'ULTIMUS 9L',series:'Tulip-China'},{id:42,name:'ULTIMUS 9L',series:'Tulip-Oversea'}])
 assert.deepEqual(options.map(o=>o.value),['9E科研版（URM）','ULTIMUS 9L','旧机型'])
 groups[0].models.push('ULTIMUS 9L');assert.equal(raw[0].models.length,2)
 assert.deepEqual(subseriesPayload('revision',groups),{revision:'revision',groups:[{name:'URM',series:'Tulip-China',models:['9E科研版（URM）','旧机型','ULTIMUS 9L']}]})
})
test('new group can include configuration-only models and parent changes keep selections for explicit validation',()=>{
 const g={name:'新子系列',series:'China',models:['海外型号']}
 const options=subseriesGroupOptions(g,[{id:1,name:'只有配置的机型',series:'China'},{id:2,name:'海外型号',series:'Oversea'}])
 assert.deepEqual(options.map(o=>o.value),['只有配置的机型','海外型号'])
 assert.deepEqual(g.models,['海外型号'])
 assert.notEqual(subseriesSnapshot([g]),subseriesSnapshot([{...g,name:'改名'}]))
})

import { readFileSync } from 'node:fs'
const component=readFileSync(new URL('../src/components/SubseriesEditor.vue',import.meta.url),'utf8')
function editor(overrides={}) {
 const ref=value=>({value}),computed=fn=>({get value(){return fn()}}),messages=[],events=[]
 const ctx={ref,computed,cloneSubseriesGroups,subseriesGroupOptions,subseriesPayload,subseriesSnapshot,
  getSubseries:async()=>({revision:'r1',groups:[{name:'原组',series:'China',models:['M']}],catalog:[],series:[]}),
  saveSubseries:async()=>{throw {response:{data:{detail:'其他系统已修改，请重新加载'}}}},
  ElMessage:{success:m=>messages.push(m),warning:m=>messages.push(m)},ElMessageBox:{confirm:async()=>{}},emit:e=>events.push(e),...overrides}
 const code=component.slice(component.indexOf('const visible ='),component.indexOf('</script>'))
 const methods=new Function(...Object.keys(ctx),code+';return {open,load,reload,save,requestClose,groups,visible,loading,saving,error,dirty,loaded}')(...Object.values(ctx))
 return {...methods,messages,events}
}
test('save errors retain changes, and declining reload or close keeps the editor intact',async()=>{
 const a=editor({ElMessageBox:{confirm:async()=>{throw 'cancel'}}});a.open();await Promise.resolve();await Promise.resolve()
 a.groups.value[0].name='修改';await a.save()
 assert.equal(a.groups.value[0].name,'修改');assert.match(a.error.value,/其他系统/);assert.equal(a.visible.value,true)
 await a.reload();assert.equal(a.groups.value[0].name,'修改')
 await a.requestClose();assert.equal(a.visible.value,true)
})
test('save blocks duplicate clicks and close until the current write settles',async()=>{
 let resolve,calls=0
 const pending=new Promise(r=>{resolve=r})
 const a=editor({saveSubseries:()=>{calls++;return pending}});a.open();await Promise.resolve();await Promise.resolve()
 a.groups.value[0].name='新组';const save=a.save();await a.save();await a.requestClose()
 assert.equal(calls,1);assert.equal(a.visible.value,true)
 resolve({revision:'r2',groups:[{name:'新组',series:'China',models:['M']}],catalog:[],series:[]});await save
 assert.equal(a.dirty.value,false);assert.deepEqual(a.events,['saved'])
})
