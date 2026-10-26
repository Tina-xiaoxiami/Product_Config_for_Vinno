import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { computed, effectScope, nextTick, reactive, ref, watch } from 'vue'
const source = readFileSync(new URL('../src/views/Config.vue', import.meta.url), 'utf8')
function fieldApp() {
  const scope=effectScope()
  const context={ reactive,computed,watch, selectedModels:ref([10,20]), visibleConfigFields:ref(['final_config','current_config']),currentPage:ref(3),pageSize:ref(100),filteredTableData:ref(Array.from({length:250},(_,i)=>({id:i+1}))) }
  const fields=source.slice(source.indexOf('const fieldFilters ='),source.indexOf('const tempSelectedModels ='))
  const pagination=source.slice(source.indexOf('const paginatedTableData ='),source.indexOf('// tableData / originalData O(1)'))
  const methods=scope.run(()=>new Function(...Object.keys(context),`${fields}\n${pagination};return {fieldFilters,pendingFieldFilters,openFieldFilterPopover,applyFieldFilterPopover,paginatedTableData}`)(...Object.values(context)))
  return {...context,...methods,stop:()=>scope.stop()}
}
test('deselecting a model removes pending filters and rejects its late hide callback',async t=>{
  const app=fieldApp();t.after(app.stop)
  app.openFieldFilterPopover('final_config',10);app.pendingFieldFilters['final_config|10']=['X']
  app.selectedModels.value=[20];await nextTick();app.applyFieldFilterPopover('final_config',10)
  assert.equal('final_config|10' in app.fieldFilters,false);assert.equal('final_config|10' in app.pendingFieldFilters,false)
})
test('hiding a field clears its applied and pending filters without reviving them',async t=>{
  const app=fieldApp();t.after(app.stop)
  app.openFieldFilterPopover('current_config',10);app.pendingFieldFilters['current_config|10']=['●'];app.applyFieldFilterPopover('current_config',10)
  app.openFieldFilterPopover('current_config',10);app.pendingFieldFilters['current_config|10']=['X']
  app.visibleConfigFields.value=['final_config'];await nextTick();app.applyFieldFilterPopover('current_config',10)
  assert.equal('current_config|10' in app.fieldFilters,false);assert.equal('current_config|10' in app.pendingFieldFilters,false)
})
test('only an actual filter set change resets the current page',t=>{
  const app=fieldApp();t.after(app.stop)
  app.fieldFilters['final_config|10']=['X','●'];app.openFieldFilterPopover('final_config',10);app.pendingFieldFilters['final_config|10']=['●','X'];app.applyFieldFilterPopover('final_config',10)
  assert.equal(app.currentPage.value,3)
  app.openFieldFilterPopover('final_config',10);app.pendingFieldFilters['final_config|10']=['X'];app.applyFieldFilterPopover('final_config',10)
  assert.equal(app.currentPage.value,1)
})
test('zero results followed by a small result set always displays a valid page',async t=>{
  const app=fieldApp();t.after(app.stop)
  assert.equal(app.currentPage.value,3)
  app.filteredTableData.value=[];await nextTick();assert.equal(app.currentPage.value,1)
  app.filteredTableData.value=[{id:1},{id:2}];await nextTick();assert.equal(app.paginatedTableData.value.length,2)
})
test('page clamping covers changed size and programmatic out-of-range pages',async t=>{
  const app=fieldApp();t.after(app.stop)
  app.pageSize.value=200;await nextTick();assert.equal(app.currentPage.value,2)
  app.currentPage.value=99;await nextTick();assert.equal(app.currentPage.value,2)
  app.currentPage.value=0;await nextTick();assert.equal(app.currentPage.value,1)
})
test('same visible-model filters remain active when other models or fields change',async t=>{
  const app=fieldApp();t.after(app.stop)
  app.openFieldFilterPopover('final_config',10);app.pendingFieldFilters['final_config|10']=['X'];app.applyFieldFilterPopover('final_config',10)
  app.selectedModels.value=[10];app.visibleConfigFields.value=['final_config'];await nextTick()
  assert.deepEqual(app.fieldFilters['final_config|10'],['X'])
})
