import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
const source=readFileSync(new URL('../src/views/Config.vue',import.meta.url),'utf8')
test('model selector uses shared subseries while matrix retains series grouping',()=>{
  assert.match(source,/v-for="group in filteredModelGroups"[\s\S]*?:key="group.key"/)
  assert.match(source,/sub_series: m.sub_series \|\| \[\]/)
  assert.match(source,/其他机型/)
  assert.match(source,/selectSubseriesModels/)
})
const ref=value=>({value})
const computed=fn=>({get value(){return fn()}})
function app(){
 const selected=ref([99]); const ctx={ref,computed, modelGroups:ref([{seriesId:6,seriesName:'Tulip-China',models:[{id:40,name:'科研URM',sub_series:['URM']},{id:42,name:'旗舰',sub_series:['非URM']},{id:43,name:'9L',sub_series:[]}]}]),modelFilterText:ref(''),tempSelectedModels:selected,applyingModelGroup:ref(false),reviewInteractionLocked:ref(false),applyModelSelection(){}}
 const start=source.indexOf('const modelSubseriesProblems =');const end=source.indexOf('// 根据 modelId',start)
 return {...ctx,...new Function(...Object.keys(ctx),source.slice(start,end)+';return {modelSelectionGroups,filteredModelGroups,selectSubseriesModels,isModelGroupExpanded,toggleModelGroup,expandModelGroupsForKeyboard}')(...Object.values(ctx))}
}
test('subseries selectors retain other models, search group labels and preserve previous selections',()=>{
 const a=app();assert.deepEqual(a.modelSelectionGroups.value.map(g=>g.models.map(m=>m.id)),[[40],[42],[43]])
 a.modelFilterText.value='URM';assert.equal(a.filteredModelGroups.value.length,2)
 a.selectSubseriesModels(a.modelSelectionGroups.value[0]);assert.deepEqual(a.tempSelectedModels.value,[99,40])
 a.selectSubseriesModels(a.modelSelectionGroups.value[0]);assert.deepEqual(a.tempSelectedModels.value,[99,40])
 a.reviewInteractionLocked.value=true;a.selectSubseriesModels(a.modelSelectionGroups.value[1]);assert.deepEqual(a.tempSelectedModels.value,[99,40])
})

test('model lists start collapsed, expand explicitly or for search and keyboard without changing selection',()=>{
 const a=app(),group=a.modelSelectionGroups.value[0]
 assert.equal(a.isModelGroupExpanded(group),false)
 a.toggleModelGroup(group);assert.equal(a.isModelGroupExpanded(group),true)
 a.toggleModelGroup(group);assert.equal(a.isModelGroupExpanded(group),false)
 a.modelFilterText.value='科研';assert.equal(a.isModelGroupExpanded(group),true)
 a.modelFilterText.value='';assert.equal(a.isModelGroupExpanded(group),false)
 a.expandModelGroupsForKeyboard({key:'ArrowDown',target:{tagName:'INPUT'}})
 assert.ok(a.modelSelectionGroups.value.every(a.isModelGroupExpanded))
 assert.deepEqual(a.tempSelectedModels.value,[99])
})
test('keyboard navigation expands registered hidden choices before the select consumes the event',()=>{
 assert.match(source,/@keydown\.capture="expandModelGroupsForKeyboard"/)
 for (const key of ['Home','End','PageUp','PageDown']) {
  const a=app();a.expandModelGroupsForKeyboard({key,target:{tagName:'INPUT'}})
  assert.ok(a.modelSelectionGroups.value.every(a.isModelGroupExpanded))
 }
})
