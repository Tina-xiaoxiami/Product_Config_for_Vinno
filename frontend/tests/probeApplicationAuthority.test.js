import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
const read = name => readFileSync(new URL(`../src/views/${name}.vue`, import.meta.url), 'utf8')
const source = read('ApplicationsView')
const ref = value => ({ value })
import { applicationChangeStillPending } from '../src/utils/probeApplications.js'
function submitHarness(post) {
  const changes = { one: { action:'add', catId:1, appId:2, probeType:'poc' } }
  const context = { pendingChanges: changes, submitting: ref(false), editMode: ref(true), api:{ post, get: async()=>({regular:[],poc:[]}) }, ElMessage:{ warning(){},success(){},error(){} }, refreshData: async()=>{}, emit() {}, committedUncleared:ref(false), draftError:ref(''), applicationChangeStillPending }
  context.clearLocalChanges = () => { Object.keys(changes).forEach(key=>delete changes[key]); context.editMode.value=false; return true }
  const block = source.slice(source.indexOf('const submitChanges ='), source.indexOf('// ========= CRUD'))
  const submit = new Function(...Object.keys(context), `${block}; return submitChanges`)(...Object.values(context))
  return { ...context, submit }
}

test('application changes submit a single batch, with regular/POC preserved', async () => {
  const calls=[]
  const app=submitHarness(async (...args)=>calls.push(args))
  await app.submit()
  assert.equal(calls.length,1)
  assert.equal(calls[0][0],'/applications/associations/batch')
  assert.deepEqual(calls[0][1].changes,[{action:'add',category_id:1,application_id:2,probe_type:'poc'}])
  assert.deepEqual(app.pendingChanges,{})
  assert.equal(app.editMode.value,false)
  assert.equal(app.submitting.value,false)
})

test('failed batch keeps editing changes for retry', async () => {
  const app=submitHarness(async()=>{throw new Error('offline')})
  await app.submit()
  assert.ok(app.pendingChanges.one)
  assert.equal(app.editMode.value,true)
  assert.equal(app.submitting.value,false)
})

test('quick add enters edit mode so the pending change is visible and protected', () => {
  const context={addAppId:ref(2),selectedCategory:ref({id:1}),availableApps:ref([{id:2,name:'App'}]),addAppType:ref('poc'),pendingChanges:{},editMode:ref(false),submitting:ref(false),committedUncleared:ref(false)}
  const block=source.slice(source.indexOf('const stageAdd ='),source.indexOf('const stageRemove ='))
  const add=new Function(...Object.keys(context),`${block}; return stageAdd`)(...Object.values(context))
  add()
  assert.equal(context.editMode.value,true)
  assert.equal(context.pendingChanges['1_2_poc'].probeType,'poc')
})

test('submitting locks draft changes and duplicate submissions until the batch completes', async () => {
  let finish, posts = 0
  const app = submitHarness(() => { posts++; return new Promise(resolve => { finish = resolve }) })
  const context = {
    ...app, addAppId: ref(3), selectedCategory: ref({ id: 1 }),
    availableApps: ref([{ id: 3, name: 'Second' }]), addAppType: ref('regular')
  }
  const block = source.slice(source.indexOf('const enterEditMode ='), source.indexOf('// ========= CRUD'))
  const actions = new Function(...Object.keys(context), `${block}; return { enterEditMode, cancelEdit, discardChanges, stageAdd, stageRemove, undoPending, submitChanges }`)(...Object.values(context))
  const work = actions.submitChanges()
  actions.stageAdd(); actions.stageRemove({ id: 2, name: 'First' }, 'poc'); actions.undoPending('one')
  actions.enterEditMode(); actions.cancelEdit(); actions.discardChanges(); await actions.submitChanges()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(posts, 1)
  assert.deepEqual(Object.keys(app.pendingChanges), ['one'])
  assert.equal(app.editMode.value, true)
  finish(); await work
  assert.deepEqual(app.pendingChanges, {})
  assert.equal(app.submitting.value, false)
})

test('model application maintenance focuses its shared category without a second route or obsolete writes', async () => {
  const view=read('ProbeModelsView'), calls=[]
  const block=view.slice(view.indexOf('const openAppDialog ='),view.indexOf('// Variant management'))
  const open=new Function('categories','selectCategory','focusApplications',`${block}; return openAppDialog`)(
    ref([{id:3}]), category=>{calls.push(['select',category.id]);return true},async()=>calls.push(['focus']))
  assert.equal(await open({id:9,category_id:3}),true)
  assert.deepEqual(calls,[['select',3],['focus']])
  assert.doesNotMatch(block,/router\.push/)
  assert.doesNotMatch(view,/setProbeModelApps|selectedAppIds/)
  assert.match(view,/useWorkspaceRefresh\(loadData/)
  assert.match(source,/useWorkspaceRefresh\([\s\S]*?canRefresh: \(\) => !categories.value.length \|\| editorState.value.canRefresh/)
  assert.match(source,/Number\(route.query.category_id\)/)
})

test('published-but-uncleared draft is reported separately and cannot submit a second version',async()=>{
  let posts=0
  const app=submitHarness(async()=>{posts++})
  app.clearLocalChanges=()=>false
  const block=source.slice(source.indexOf('const submitChanges ='),source.indexOf('// ========= CRUD'))
  const submit=new Function(...Object.keys(app),block+';return submitChanges')(...Object.values(app))
  await submit();assert.equal(posts,1);assert.equal(app.committedUncleared.value,true)
  assert.match(app.draftError.value,/服务器已提交/)
  assert.ok(app.pendingChanges.one)
  await submit();assert.equal(posts,1)
})
test('recovered changes already present on server clear locally without posting or creating a version',async()=>{
  let posts=0
  const app=submitHarness(async()=>{posts++})
  app.api.get=async()=>({regular:[],poc:[{id:2}]})
  await app.submit()
  assert.equal(posts,0);assert.deepEqual(app.pendingChanges,{})
})
