import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { buildModelSelectionTree, filterModelSelectionTree, primaryModelOccurrences } from '../src/utils/modelSelectionTree.js'
const source=readFileSync(new URL('../src/views/Config.vue',import.meta.url),'utf8')
test('model selector uses shared subseries while matrix retains series grouping',()=>{
  assert.match(source,/v-for="group in section.groups"[\s\S]*?:key="group.key"/)
  assert.match(source,/sub_series: m.sub_series \|\| \[\]/)
  assert.match(source,/其他机型/)
  assert.match(source,/selectSubseriesModels/)
})
const ref=value=>({value})
const computed=fn=>({get value(){return fn()}})
function app(){
 const selected=ref([99]); const ctx={ref,computed,buildModelSelectionTree,filterModelSelectionTree,primaryModelOccurrences, modelGroups:ref([{seriesId:6,seriesName:'Tulip-China',models:[{id:40,name:'科研URM',sub_series:['URM']},{id:42,name:'旗舰',sub_series:['非URM']},{id:43,name:'9L',sub_series:[]}]}]),modelFilterText:ref(''),tempSelectedModels:selected,applyingModelGroup:ref(false),reviewInteractionLocked:ref(false),applyModelSelection(){}}
 const start=source.indexOf('const modelSubseriesProblems =');const end=source.indexOf('// 根据 modelId',start)
 return {...ctx,...new Function(...Object.keys(ctx),source.slice(start,end)+';return {modelSelectionGroups,filteredModelGroups,modelSubseriesCombinations,modelSelectionTree,filteredModelTree,primaryModelGroups,selectSubseriesModels,isModelGroupExpanded,toggleModelGroup,expandModelGroupsForKeyboard,toggleTreeModel}')(...Object.values(ctx))}
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


test('combination hierarchy retains overlap, standalone members and searchable ancestors', () => {
 const a=app()
 a.modelSubseriesCombinations.value=[{name:'科研组合',sub_series:['URM']},{name:'完整组合',sub_series:['URM','非URM']}]
 const tree=a.modelSelectionTree.value
 assert.deepEqual(tree.map(section=>section.label),['科研组合','完整组合',undefined])
 assert.deepEqual(tree[2].groups[0].models.map(model=>model.id),[43])
 assert.equal(tree[0].groups[0].label,'Tulip-China / URM')
 a.modelFilterText.value='科研组合'
 assert.deepEqual(a.filteredModelGroups.value.flatMap(group=>group.models.map(model=>model.id)),[40])
 a.modelFilterText.value='旗舰'
 assert.equal(a.filteredModelTree.value.length,1)
 assert.equal(a.filteredModelTree.value[0].label,'完整组合')
})

test('overlapping branches register one option per model at a visible occurrence and share selection', () => {
 const a=app()
 a.modelSubseriesCombinations.value=[{name:'组合A',sub_series:['URM']},{name:'组合B',sub_series:['URM','非URM']}]
 const [first,second]=a.modelSelectionTree.value
 assert.equal(a.primaryModelGroups.value.size,3)
 assert.equal(a.primaryModelGroups.value.get(40),first.groups[0].key)
 a.toggleModelGroup(second.groups[0])
 assert.equal(a.primaryModelGroups.value.get(40),second.groups[0].key)
 a.selectSubseriesModels(first.groups[0]);a.selectSubseriesModels(second.groups[0])
 assert.deepEqual(a.tempSelectedModels.value,[99,40])
 a.toggleTreeModel(40);assert.deepEqual(a.tempSelectedModels.value,[99])
 a.toggleTreeModel(40);assert.deepEqual(a.tempSelectedModels.value,[99,40])
 a.modelFilterText.value='组合A'
 assert.equal(a.primaryModelGroups.value.get(40),first.groups[0].key)
 a.modelFilterText.value='';a.expandModelGroupsForKeyboard({key:'ArrowDown',target:{tagName:'INPUT'}})
 assert.ok(a.modelSelectionTree.value.every(section=>!section.combination||a.isModelGroupExpanded(section)))
 assert.ok(a.filteredModelGroups.value.every(a.isModelGroupExpanded))
})

test('compact names are the collapse controls and duplicate models do not register duplicate options', () => {
 assert.doesNotMatch(source,/展开机型|收起机型/)
 assert.match(source,/class="model-tree-heading" :aria-expanded="isModelGroupExpanded\(group\)"[\s\S]*?@click.stop="toggleModelGroup\(group\)"/)
 assert.match(source,/<el-option v-if="primaryModelGroups.get\(m.id\) === group.key"/)
})


test('combination count counts subseries identities rather than parent-series buckets', () => {
 const groups=[{key:'china',label:'China / 常规',subseriesName:'常规',models:[{id:1,name:'5'}]}, {key:'oversea',label:'Oversea / 常规',subseriesName:'常规',models:[{id:2,name:'5'}]}]
 const [combination]=buildModelSelectionTree(groups,[{name:'跨系列组合',sub_series:['常规']}])
 assert.equal(combination.subseriesCount,1)
 assert.equal(combination.groups.length,2)
})


test('combinations start expanded while subseries and standalone unclassified models stay hidden', () => {
 const a=app()
 a.modelSubseriesCombinations.value=[{name:'组合',sub_series:['URM']}]
 const [combo,standalone]=a.modelSelectionTree.value
 assert.equal(a.isModelGroupExpanded(combo),true)
 assert.equal(a.isModelGroupExpanded(combo.groups[0]),false)
 const other=standalone.groups.find(group=>group.models.some(model=>model.id===43))
 assert.equal(other.searchOnly,true)
 assert.equal(a.isModelGroupExpanded(other),false)
 assert.equal(standalone.groups.find(group=>group.subseriesName==='非URM').searchOnly,false)
 assert.equal(a.primaryModelGroups.value.has(43),true)
 a.toggleModelGroup(combo);assert.equal(a.isModelGroupExpanded(combo),false)
 a.modelFilterText.value='9L';assert.equal(a.filteredModelGroups.value[0].models[0].id,43)
 assert.equal(a.isModelGroupExpanded(other),true)
 a.modelFilterText.value='';assert.equal(a.isModelGroupExpanded(combo),false)
 a.toggleModelGroup(combo);assert.equal(a.isModelGroupExpanded(combo),true)
 a.modelSubseriesCombinations.value=[]
 assert.equal(a.modelSelectionTree.value[0].groups.some(group=>group.searchOnly),false)
 assert.match(source,/v-show="!group.searchOnly \|\| isModelGroupExpanded\(group\)"/)
})
