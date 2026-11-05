import test from 'node:test'
import assert from 'node:assert/strict'
import { cloneSubseriesGroups, cloneSubseriesCombinations, subseriesGroupOptions, subseriesPayload, subseriesSnapshot } from '../src/utils/subseriesEditor.js'

test('same-name markets stay independently selectable with multiple parent series', () => {
 const catalog=[{id:1,name:'VINNO 5',series:'China'},{id:2,name:'VINNO 5',series:'Oversea'}]
 const group=cloneSubseriesGroups([{name:'跨系列',series_names:['China','Oversea'],models:['VINNO 5'],model_ids:[1],missing_models:[]}])[0]
 assert.deepEqual(group.models,['id:1'])
 assert.deepEqual(subseriesGroupOptions(group,catalog).map(o=>o.value),['id:1','id:2'])
 assert.deepEqual(subseriesPayload('r',[group]).groups[0],{name:'跨系列',series_names:['China','Oversea'],model_ids:[1],models:[]})
 group.series_names=['Oversea']
 assert.match(subseriesGroupOptions(group,catalog).find(o=>o.value==='id:1').label,/不属于当前系列/)
})

import { readFileSync } from 'node:fs'
const component=readFileSync(new URL('../src/components/SubseriesEditor.vue',import.meta.url),'utf8')
function editor(overrides={}) {
 const ref=value=>({value}),computed=fn=>({get value(){return fn()}}),messages=[],events=[]
 const ctx={ref,computed,nextTick:async()=>{},defineExpose(){},cloneSubseriesGroups,cloneSubseriesCombinations,subseriesGroupOptions,subseriesPayload,subseriesSnapshot,
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

test('legacy unresolved members and market scope survive editing alongside exact IDs', () => {
 const raw={name:'旧组',series:'China',models:['5','旧机型'],model_ids:[1],missing_models:['旧机型']}
 const group=cloneSubseriesGroups([raw])[0]
 group.models.push('id:2')
 assert.deepEqual(raw.models,['5','旧机型'])
 assert.deepEqual(subseriesPayload('r',[group]).groups[0],{name:'旧组',series_names:['China'],model_ids:[1,2],models:['旧机型']})
 assert.match(subseriesGroupOptions(group,[{id:1,name:'VINNO 5',series:'China'}]).find(o=>o.value==='旧机型').label,/未匹配/)
})

test('missing market identity survives rename and can be explicitly removed', () => {
 const group=cloneSubseriesGroups([{name:'旧组',series_names:[],models:['VINNO 5'],model_ids:[1],missing_models:['VINNO 5'],unresolved_refs:[{name:'VINNO 5',series:'Oversea'}]}])[0]
 group.name='新组'
 assert.deepEqual(subseriesPayload('r',[group]).groups[0].unresolved_refs,[{name:'VINNO 5',series:'Oversea'}])
 group.models=['id:1']
 assert.deepEqual(subseriesPayload('r',[group]).groups[0].unresolved_refs,[])
})
