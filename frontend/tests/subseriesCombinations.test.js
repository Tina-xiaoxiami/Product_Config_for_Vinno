import test from 'node:test'
import assert from 'node:assert/strict'
import { cloneSubseriesCombinations, buildSubseriesCombinationSelection, subseriesPayload, subseriesSnapshot } from '../src/utils/subseriesEditor.js'

test('combinations reference editor identities so subseries renames update saved relationships',()=>{
 const groups=[{editorKey:1,name:'URM',series:'China',models:['M']},{editorKey:2,name:'非URM',series:'China',models:['N']}]
 const combos=cloneSubseriesCombinations([{name:'科研包',sub_series:['URM','非URM']}],groups)
 assert.deepEqual(combos[0].groupKeys,[1,2])
 const before=subseriesSnapshot(groups,combos);groups[0].name='URM新版'
 const payload=subseriesPayload('r',groups,combos)
 assert.deepEqual(payload.combinations,[{name:'科研包',sub_series:['URM新版','非URM']}])
 assert.notEqual(subseriesSnapshot(groups,combos),before)
 assert.throws(()=>subseriesPayload('r',[groups[0]],combos),/删除|不存在/)
 assert.equal(subseriesPayload('r',groups).combinations,undefined)
})
test('combination application reuses model-group identity selection and rejects incomplete scope',()=>{
 const catalog=[{id:1,name:'M',series_id:1,series:'China'},{id:2,name:'M',series_id:2,series:'Oversea'}]
 const result=buildSubseriesCombinationSelection({name:'组合',model_ids:[1,2,1],missing_models:[]},catalog)
 assert.deepEqual(result.models,[{id:1,name:'M',seriesId:1,seriesName:'China'},{id:2,name:'M',seriesId:2,seriesName:'Oversea'}])
 assert.throws(()=>buildSubseriesCombinationSelection({name:'组合',model_ids:[1],missing_models:['URM：旧机型']},catalog),/未匹配|无法匹配/)
 assert.throws(()=>buildSubseriesCombinationSelection({name:'组合',model_ids:[3],missing_models:[]},catalog),/不存在|变化/)
})

import { resolveGroupModels } from '../src/utils/modelSelectionGroups.js'
test('fresh combinations preserve exact IDs and reject any changed member as a whole',()=>{
 const catalog=[{id:1,name:'M',series_id:1,series:'China'},{id:2,name:'M',series_id:1,series:'China'},{id:3,name:'N',series_id:1,series:'China'}]
 const combination=buildSubseriesCombinationSelection({name:'组合',model_ids:[1,2,3],missing_models:[]},catalog)
 const models=new Map(catalog.map(m=>[m.id,{...m,seriesName:m.series}]))
 assert.deepEqual(resolveGroupModels(combination,models),{ids:[1,2,3],missing:0})
 models.delete(1)
 assert.deepEqual(resolveGroupModels(combination,models),{ids:[],missing:1})
})

import { readFileSync } from 'node:fs'
const component=readFileSync(new URL('../src/components/SubseriesCombinations.vue',import.meta.url),'utf8')
function picker(getSubseries){
 const events=[],props={disabled:false,selectionKey:'A'}
 const context={ref:value=>({value}),getSubseries,buildSubseriesCombinationSelection,props,emit:(...args)=>events.push(args),ElMessage:{warning(){}}}
 const code=component.slice(component.indexOf('const popover ='),component.indexOf('</script>'))
 const methods=new Function(...Object.keys(context),code+';return {load,apply,loading,applying,combinations}')(...Object.values(context))
 return {...methods,props,events}
}
test('each application resolves the latest combination members',async()=>{
 let calls=0
 const a=picker(async()=>({catalog:[{id:1,name:'M',series_id:1,series:'China'},{id:2,name:'N',series_id:1,series:'China'}],combinations:[{name:'包',sub_series:['URM'],model_ids:[++calls===1?1:2],missing_models:[]}]}))
 await a.load();await a.apply('包')
 assert.deepEqual(a.events[0][1].exactModelIds,[2])
})
test('a delayed combination lookup cannot override a newer user selection',async()=>{
 let resolve
 const pending=new Promise(r=>{resolve=r}),a=picker(()=>pending)
 const apply=a.apply('包');a.props.selectionKey='B'
 resolve({catalog:[{id:1,name:'M',series_id:1,series:'China'}],combinations:[{name:'包',sub_series:['URM'],model_ids:[1],missing_models:[]}]});await apply
 assert.deepEqual(a.events,[]);assert.equal(a.applying.value,false)
})
