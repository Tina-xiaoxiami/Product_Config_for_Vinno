import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
const app = readFileSync(new URL('../../backend/tracker/static/app.js', import.meta.url), 'utf8')
const template = readFileSync(new URL('../../backend/tracker/templates/index.html', import.meta.url), 'utf8')
const styles = readFileSync(new URL('../../backend/tracker/static/styles.css', import.meta.url), 'utf8')
const block = (start, end) => app.slice(app.indexOf(start), app.indexOf(end, app.indexOf(start)))
const escapeHtml = value => String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;')
const context = { escapeHtml, escapeAttribute: escapeHtml, categoryLabels: { function:'功能', config:'配置' }, verificationLabel: value => value === 'unverified' ? '未复核' : value }
const render = new Function(...Object.keys(context), `${block('function scenarioPreviewButton', 'async function runScenario')}; return {scenarioProbeMarkup, scenarioFeatureMarkup, scenarioVersionMarkup}`)(...Object.values(context))

test('多个探头身份在界面选择，证据标签保留最早可证实边界', () => {
  const options = render.scenarioProbeMarkup({identities:[{model:'F4-9E',code:'V20131',series:'V10'},{model:'F4-9E',code:'V20064',series:'V10'}], selected:null},'F4-9E')
  assert.match(options,/V20131/); assert.match(options,/V20064/)
  const answer = render.scenarioProbeMarkup({identities:[{}],selected:{model:'F4-9E',code:'V20131',series:'V10'},evidence:{version:'1.14.80',preview_id:'release:table:2567',locator:'表格记录'}},'F4-9E')
  assert.match(answer,/最早可证实新增支持/); assert.match(answer,/release:table:2567/); assert.match(answer,/不等于已确认的绝对首次/)
})

test('功能直接渲染完整文本及原始状态，较新候选未核实不声称最新', () => {
  const answer = render.scenarioFeatureMarkup({latest_certified:false,baseline:{version:'1.51.80',title:'6S白皮书',scope:'范围未登记',detail_evidence:{title:'5.63',source_id:'controlled:35:pdf',locator:'第 13 页',verification:'unverified'}},section:{content:'第一段\n第二段'},later_changes:[{version:'1.51.90',category:'config',title_cn:'配置限制',preview_id:'release:change:4'}]},'子宫畸形分类')
  assert.match(answer,/完整描述候选/); assert.match(answer,/第一段\n第二段/); assert.match(answer,/未复核/); assert.match(answer,/后续变更待整合/); assert.match(answer,/controlled:35:pdf/)
})

test('版本结果显示目标变化和可选对比概要', () => {
  const answer = render.scenarioVersionMarkup({target:{version:'1.51.80',changes:[{id:1,category:'function',title_cn:'功能 A'}]},comparison:{added:{function:[{}]},removed:{},common:{}}})
  assert.match(answer,/1.51.80/); assert.match(answer,/功能 A/); assert.match(answer,/新增 1/); assert.match(answer,/data-scenario-compare/)
})

test('实际查询函数抑制旧请求且错误可重试', async () => {
  let resolveFirst, rejectSecond, resolveThird
  const nodes = { '#advanced-search-wrap':{open:true}, '#scenario-query':{value:'F4-9E'}, '#scenario-target':{value:''}, '#scenario-base':{value:''}, '#scenario-result':{innerHTML:''} }
  const state = { activeProjectId:2 }, scenarioState = {task:'probe',request:0,code:'',series:'',model:''}
  let calls=0
  const ctx = {state,scenarioState,document:{querySelector:key=>nodes[key]}, loadingMarkup:()=> 'loading',syncLocation(){},projectPath:x=>x,
    api:()=>{calls++; return new Promise((resolve,reject)=>{ if(calls===1)resolveFirst=resolve; else if(calls===2)rejectSecond=reject; else resolveThird=resolve })},
    scenarioProbeMarkup:data=>data.value,scenarioFeatureMarkup:()=>'',scenarioVersionMarkup:()=>'',escapeHtml}
  const run = new Function(...Object.keys(ctx), `${block('async function runScenario', 'function switchView')};return runScenario`)(...Object.values(ctx))
  const first=run(), second=run(); resolveFirst({value:'旧结果'}); await first; assert.equal(nodes['#scenario-result'].innerHTML,'loading')
  assert.equal(nodes['#advanced-search-wrap'].open, false)
  rejectSecond(Error('离线')); await second; assert.match(nodes['#scenario-result'].innerHTML,/查询失败/)
  const third=run(); assert.equal(calls,3); resolveThird({value:'重试结果'}); await third
  assert.equal(nodes['#scenario-result'].innerHTML,'重试结果')
})

test('三个任务、隐藏高级检索和窄屏换行均接入实际页面', () => {
  for (const task of ['probe','feature','version']) assert.match(template,new RegExp(`data-scenario-task="${task}"`))
  assert.match(template,/<details id="advanced-search-wrap"/); assert.match(app,/scenario-form'\)\.addEventListener\('submit'/)
  assert.match(styles,/@media \(max-width: 600px\)/); assert.match(styles,/flex: 1 1 100%/)
})


test('英文版本变化定位英文原文，资料范围不明确时可选择', () => {
  const version = render.scenarioVersionMarkup({target:{version:'1.51.80',changes:[{id:2,category:'function',title_en:'Added function',description_en:'details'}]},comparison:null})
  assert.match(version,/data-scenario-locator="English record"/)
  const choice = render.scenarioFeatureMarkup({baseline:null,section:null,documents:[{value:'1',label:'中文资料',scope:'国内'},{value:'2',label:'English',scope:'海外'}]},'功能')
  assert.match(choice,/请选择资料范围/); assert.match(choice,/data-scenario-document="1"/); assert.match(choice,/English/)
})

test('场景对比先设置两个版本，再切页触发现有对比请求', () => {
  const handler = block("  if (event.target.closest('[data-scenario-compare]'))", "\n  }\n});") + '\n  }'
  const fields = { '#scenario-target':{value:'1.51.80'}, '#scenario-base':{value:'1.51.70'}, '#from-version':{value:'old'}, '#to-version':{value:'old'} }
  let used
  const run = new Function('event','document','switchView',handler)
  run({target:{closest:()=>true}},{querySelector:key=>fields[key]},view=>{used=[view,fields['#from-version'].value,fields['#to-version'].value]})
  assert.deepEqual(used,['compare','1.51.70','1.51.80'])
})

test('空场景链接清除旧结论并使在途响应失效', async () => {
  const source = block('    if (params.scenario) {', '\n    state.previewLocation = null;')
  const nodes = {'#scenario-result':{innerHTML:'旧结论'}, '#scenario-query':{value:'旧输入'}}
  const scenarioState = {task:'probe',request:3}, state = {previewLocation:{preview:'old'},evidenceNavigation:1}
  let restored = false
  const execute = new Function('scenarioState','state','document','params','navigation','setScenarioTask','renderScenarioVersionOptions','runScenario','restoreEvidenceLocation', `return (async () => {${source}})()`)
  await execute(scenarioState,state,{querySelector:key=>nodes[key]}, {scenario:'probe'}, 1,
    task=>{scenarioState.task=task},()=>{},()=>{throw Error('空链接不应查询')},async()=>{restored=true})
  assert.equal(scenarioState.request,4)
  assert.equal(nodes['#scenario-result'].innerHTML,'')
  assert.equal(nodes['#scenario-query'].value,'')
  assert.equal(state.previewLocation,null)
  assert.equal(restored,true)
})

test('重叠版本对比只保留最新组合且恢复按钮', async () => {
  const nodes = {'#from-version':{value:'1.51.20'},'#to-version':{value:'1.51.80'},
    '#compare-result':{innerHTML:'',textContent:'',className:''},'#compare-button':{textContent:'开始对比',dataset:{},disabled:false}}
  const state = {activeProjectId:1}, pending=[]
  const execute = new Function('state','document','api','projectPath','showNotice','escapeHtml','releaseTableTypeLabels','marketLabels',
    `${block('async function compareVersions', 'function ensureComparisonLoaded')};return compareVersions`)(
      state,{querySelector:key=>nodes[key]},()=>new Promise((resolve,reject)=>pending.push({resolve,reject})),value=>value,()=>{},escapeHtml,{}, {})
  const response = title => ({added:{function:[{title_cn:title}]},removed:{},common:{},structured:{added:[],modified:[],removed:[]}})
  const first=execute()
  nodes['#from-version'].value='1.51.35'
  const second=execute()
  pending[1].resolve(response('最新组合')); await second
  pending[0].resolve(response('旧组合')); await first
  assert.match(nodes['#compare-result'].innerHTML,/最新组合/)
  assert.doesNotMatch(nodes['#compare-result'].innerHTML,/旧组合/)
  assert.equal(state.comparisonKey,'1:1.51.35::1.51.80')
  assert.equal(nodes['#compare-button'].textContent,'开始对比')
  assert.equal(nodes['#compare-button'].disabled,false)
  nodes['#from-version'].value='1.51.30'
  const third=execute()
  pending[2].reject(Error('离线'))
  await assert.rejects(third,/离线/)
  assert.equal(state.comparisonKey,null)
  assert.match(nodes['#compare-result'].textContent,/比较失败/)
  assert.equal(nodes['#compare-button'].disabled,false)
})
