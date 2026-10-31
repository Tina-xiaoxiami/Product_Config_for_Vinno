import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
const app=readFileSync(new URL('../../backend/tracker/static/app.js',import.meta.url),'utf8')
const block=(start,end)=>app.slice(app.indexOf(start),app.indexOf(end,app.indexOf(start)))
test('功能三个意图保留问题与型号，功能和探头分别保存输入',()=>{
  const nodes={'#scenario-query':{value:'VAid GYN'},'#advanced-search-wrap':{open:true},'#scenario-result':{innerHTML:'old'}}
  const state={task:'feature',featureTask:'feature',drafts:{feature:'',probe:''},request:1,model:'model:6s'}
  const change=new Function('scenarioState','document','setScenarioTask','syncLocation',`${block('function changeScenarioTask','function scenarioFirstMarkup')};return changeScenarioTask`)(state,{querySelector:key=>nodes[key]},task=>{state.task=task},()=>{})
  for(const task of ['first','version','feature']){change(task);assert.equal(nodes['#scenario-query'].value,'VAid GYN');assert.equal(state.model,'model:6s')}
  change('probe');assert.equal(nodes['#scenario-query'].value,'')
  nodes['#scenario-query'].value='F4-9E';change('feature');assert.equal(nodes['#scenario-query'].value,'VAid GYN')
  change('probe');assert.equal(nodes['#scenario-query'].value,'F4-9E');assert.equal(nodes['#scenario-result'].innerHTML,'');assert.ok(state.request>1)
})
test('版本变化和对比统计按功能筛选且不修改原数据',()=>{
  const filter=new Function(`${block('function filterScenarioVersion','function scenarioPreviewButton')};return filterScenarioVersion`)()
  const a={title_en:'VAid GYN',description_cn:'支持新增'},b={title_cn:'其他功能'}
  const data={target:{changes:[a,b]},comparison:{added:{function:[a,b]},removed:{function:[b]},common:{}}}
  const result=filter(data,'vaid gyn')
  assert.deepEqual(result.target.changes,[a]);assert.deepEqual(result.comparison.added.function,[a]);assert.deepEqual(result.comparison.removed.function,[]);assert.equal(data.target.changes.length,2)
})
test('功能和探头内部切换资料来源保留输入，跨对象恢复各自草稿',()=>{
 const nodes={'#scenario-query':{value:'VATT'},'#advanced-search-wrap':{open:false},'#scenario-result':{innerHTML:''}}
 const state={task:'feature',domain:'feature',featureTask:'feature',drafts:{feature:'',probe:''},request:0}
 const change=new Function('scenarioState','document','setScenarioTask','syncLocation',`${block('function changeScenarioTask','function scenarioFirstMarkup')};return changeScenarioTask`)(state,{querySelector:k=>nodes[k]},task=>{state.task=task},()=>{})
 change('whitepaper');assert.equal(nodes['#scenario-query'].value,'VATT');assert.equal(state.domain,'feature');assert.equal(state.featureTask,'feature')
 change('feature');assert.equal(nodes['#scenario-query'].value,'VATT')
 state.model='old-model';state.document='old-doc';state.section='old-section';
 change('probe');assert.equal(state.model,'');assert.equal(state.document,'');assert.equal(state.section,'');nodes['#scenario-query'].value='F4-9E'
 change('whitepaper');assert.equal(nodes['#scenario-query'].value,'F4-9E');assert.equal(state.domain,'probe')
 change('probe');assert.equal(nodes['#scenario-query'].value,'F4-9E')
 change('feature');assert.equal(nodes['#scenario-query'].value,'VATT');assert.equal(state.domain,'feature')
})
