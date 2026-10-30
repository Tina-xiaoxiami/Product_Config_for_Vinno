import test from 'node:test'
import assert from 'node:assert/strict'
import { orderModelCatalog, moveModelToTarget, visibleManagementGroups, loadPersonalList, savePersonalList } from '../src/utils/modelPersonalLayout.js'
import { readFileSync } from 'node:fs'

test('personal row order preserves canonical same-name markets, appends new models and drops deleted IDs', () => {
 const models=[{id:1,name:'VINNO 5'},{id:2,name:'VINNO 5'},{id:3,name:'new'}]
 assert.deepEqual(orderModelCatalog(models,['2','removed','2','1']).map(m=>m.id),[2,1,3])
 assert.deepEqual(models.map(m=>m.id),[1,2,3])
})
test('moving a filtered visible row reorders the complete catalog without dropping hidden or paginated rows', () => {
 const models=Array.from({length:60},(_,index)=>({id:index+1}))
 const moved=moveModelToTarget(models,'2','55')
 assert.equal(moved.length,60)
 assert.equal(new Set(moved.map(m=>m.id)).size,60)
 assert.equal(moved[54].id,2)
 assert.deepEqual(moved.filter(m=>![2,55].includes(m.id)).map(m=>m.id),models.filter(m=>![2,55].includes(m.id)).map(m=>m.id))
 assert.deepEqual(moveModelToTarget(models,'missing','55'),models)
})
test('group display hides hierarchy occurrences only; parent hiding never promotes children and new nodes show by default', () => {
 const nodes=[{key:'all'},{key:'packA',children:[{key:'A/group'}]},{key:'packB',children:[{key:'B/group'}]},{key:'new'}]
 assert.deepEqual(visibleManagementGroups(nodes,['all','packA']).map(n=>n.key),['all','packB','new'])
 assert.equal(visibleManagementGroups(nodes,['A/group'])[1].children.length,0)
 assert.equal(visibleManagementGroups(nodes,['A/group'])[2].children.length,1)
 assert.equal(nodes[1].children.length,1)
})
test('personal preferences persist with independent keys and recover from storage failure', () => {
 const data=new Map(), warnings=[],storage={getItem:key=>data.get(key),setItem:(key,value)=>data.set(key,value)}
 savePersonalList(storage,'rows',['2','1'])
 savePersonalList(storage,'groups',['pack'])
 assert.deepEqual(loadPersonalList(storage,'rows'),['2','1'])
 assert.deepEqual(loadPersonalList(storage,'groups'),['pack'])
 data.set('bad','{}')
 assert.deepEqual(loadPersonalList(storage,'bad',m=>warnings.push(m)),[])
 assert.equal(savePersonalList({setItem(){throw Error()}},'rows',[],m=>warnings.push(m)),false)
 assert.equal(warnings.length,2)
})
const component=readFileSync(new URL('../src/components/ModelGroupDisplaySettings.vue',import.meta.url),'utf8')
function displayEditor(confirm=async()=>{}) {
 const emitted=[]
 const ctx={ref:value=>({value}),defineProps:()=>({nodes:[],modelValue:[]}),defineEmits:()=> (...args)=>emitted.push(args),ElMessageBox:{confirm}}
 const code=component.slice(component.indexOf('const props ='),component.indexOf('</script>'))
 return {...new Function(...Object.keys(ctx),code+';return {open,toggle,apply,requestClose,draft,visible}')(...Object.values(ctx)),emitted}
}
test('group display cancel protects unapplied changes and apply emits only selected hidden keys',async()=>{
 const editor=displayEditor(async()=>{throw 'cancel'})
 editor.open();editor.toggle('pack',false);await editor.requestClose()
 assert.equal(editor.visible.value,true)
 assert.deepEqual(editor.draft.value,['pack'])
 editor.apply()
 assert.deepEqual(editor.emitted,[['update:modelValue',['pack']]])
 assert.equal(editor.visible.value,false)
})
test('model dragging changes personal catalog only, with no shared sort-order writes or operation arrows',()=>{
 const source=readFileSync(new URL('../src/views/Models.vue',import.meta.url),'utf8')
 const drag=source.slice(source.indexOf('// Personal ordering'),source.indexOf('const dialogVisible'))
 assert.doesNotMatch(drag,/updateModel|sort_order:/)
 assert.doesNotMatch(source,/moveRow\(row|上移型号|下移型号/)
 assert.match(source,/@header-dragend="resizeColumn"/)
})
