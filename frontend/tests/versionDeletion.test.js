import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
const source = readFileSync(new URL('../src/views/Versions.vue', import.meta.url), 'utf8')
const ref = value => ({value})
function app(confirm = async () => {}, remove = async () => {}) {
  const calls = [], errors = []
  const context = { ref, selectedSeries:ref(1), seriesList:ref([{id:1,name:'China'}]), currentPage:ref(2), pageSize:ref(20), total:ref(21), currentVersion:ref(null), versionDetail:ref(null), detailDialogVisible:ref(false), editVersionForm:ref({id:null}), editDialogVisible:ref(false), ElMessageBox:{confirm}, ElMessage:{success(){}, error:message=>errors.push(message)}, deleteVersion:async id=>{calls.push(id);await remove(id)}, loadVersions:async()=>calls.push('reload') }
  const code = source.slice(source.indexOf('const deletingVersionId ='),source.indexOf('// 编辑版本信息'))
  return {...context,calls,errors,...new Function(...Object.keys(context),code+';return {handleDeleteVersion,deletingVersionId}')(...Object.values(context))}
}
const version = {id:7,series_id:1,version_number:'1.2.3'}
test('version deletion confirms identity and resets last-page pagination after success',async()=>{
  let message
  const a=app(async text=>{message=text})
  await a.handleDeleteVersion(version)
  assert.match(message,/China.*1\.2\.3/)
  assert.match(message,/当前配置不会改变/)
  assert.deepEqual(a.calls,[7,'reload'])
  assert.equal(a.currentPage.value,1)
  assert.equal(a.deletingVersionId.value,null)
})
test('cancel and close do not delete; failure preserves history and reports error',async()=>{
  for(const action of ['cancel','close']) {
    const a=app(async()=>{throw action});await a.handleDeleteVersion(version)
    assert.deepEqual(a.calls,[]);assert.deepEqual(a.errors,[])
  }
  const a=app(undefined,async()=>{throw {response:{data:{detail:'版本不存在'}}}})
  await a.handleDeleteVersion(version)
  assert.deepEqual(a.calls,[7]);assert.deepEqual(a.errors,['版本不存在']);assert.equal(a.currentPage.value,2)
})
test('duplicate clicks are blocked and delayed deletion cannot reload another series',async()=>{
  let resolve
  const pending=new Promise(done=>{resolve=done})
  const a=app(()=>pending)
  const first=a.handleDeleteVersion(version)
  await a.handleDeleteVersion({id:8,series_id:1})
  a.selectedSeries.value=2
  resolve();await first
  assert.deepEqual(a.calls,[7]);assert.equal(a.currentPage.value,2)
})
