import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
const source=readFileSync(new URL('../src/views/Models.vue',import.meta.url),'utf8')
function editor(createSeries) {
 const messages=[], ctx={ref:value=>({value}),createSeries,ElMessageBox:{confirm:async()=>{throw 'cancel'}},ElMessage:{warning:m=>messages.push(m),success:m=>messages.push(m),error:m=>messages.push(m)}}
 const code=source.slice(source.indexOf('const seriesList ='),source.indexOf('const catalog ='))
 return {...new Function(...Object.keys(ctx),code+';return {saveNewSeries,closeSeriesDialog,seriesList,seriesName,seriesDialogVisible,savingSeries}')(...Object.values(ctx)),messages}
}
test('series creation validates, submits once and immediately exposes created series to model selector',async()=>{
 let resolve,calls=0
 const a=editor(async data=>{calls++;assert.deepEqual(data,{name:'New'});return new Promise(r=>resolve=r)})
 await a.saveNewSeries();assert.equal(calls,0)
 a.seriesList.value=[{id:1,name:'Old'}];a.seriesName.value='Old';await a.saveNewSeries();assert.equal(calls,0)
 a.seriesName.value=' New ';a.seriesDialogVisible.value=true
 const pending=a.saveNewSeries();await a.saveNewSeries();assert.equal(calls,1)
 resolve({id:2,name:'New'});await pending
 assert.deepEqual(a.seriesList.value.map(s=>s.id),[1,2]);assert.equal(a.seriesDialogVisible.value,false)
})
test('failure retains series name and dialog for retry; old menu route redirects',async()=>{
 const a=editor(async()=>{throw Error()});a.seriesName.value='New';a.seriesDialogVisible.value=true;await a.saveNewSeries()
 assert.equal(a.seriesName.value,'New');assert.equal(a.seriesDialogVisible.value,true);assert.equal(a.savingSeries.value,false)
 assert.doesNotMatch(readFileSync(new URL('../src/views/Layout.vue',import.meta.url),'utf8'),/index="\/series"/)
 assert.match(readFileSync(new URL('../src/router/index.js',import.meta.url),'utf8'),/path: 'series',\s*redirect: '\/models'/)
})

test('declining close retains the unsaved series name',async()=>{
 const a=editor(async()=>{});a.seriesName.value='Unsaved';a.seriesDialogVisible.value=true
 await a.closeSeriesDialog();assert.equal(a.seriesDialogVisible.value,true);assert.equal(a.seriesName.value,'Unsaved')
})
