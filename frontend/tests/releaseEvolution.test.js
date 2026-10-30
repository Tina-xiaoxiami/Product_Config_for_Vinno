import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
const app=readFileSync(new URL('../../backend/tracker/static/app.js',import.meta.url),'utf8')
const start=app.indexOf('function scenarioWhitepaperMarkup'),end=app.indexOf('function scenarioVersionMarkup',start)
const escapeHtml=x=>String(x??'').replaceAll('<','&lt;').replaceAll('>','&gt;')
const render=new Function('escapeHtml','escapeAttribute','scenarioPreviewButton',`${app.slice(start,end)};return {scenarioWhitepaperMarkup,scenarioEvolutionMarkup}`)(escapeHtml,escapeHtml,()=>'<button>查看原文</button>')
test('功能展示RN基线、确定性结果与未应用变更，不生成摘要',()=>{
 const html=render.scenarioEvolutionMarkup({baseline:{version:'1.51.20'},content:'原始完整章节\n新增支持',applied_changes:[{}],unresolved_changes:[{version:'1.51.90',text:'<更新内容>',reason:'范围不明确'}],timeline:[],coverage_notice:'仅已收录'},'VATT')
 assert.match(html,/Release Note 起点 1.51.20/);assert.match(html,/原始完整章节\n新增支持/);assert.match(html,/&lt;更新内容&gt;/);assert.match(html,/<details open>/);assert.doesNotMatch(html,/大模型整理|整理后的功能说明|白皮书/)
})
test('没有RN起始章节不以白皮书替代，白皮书单独只显示章节',()=>{
 assert.match(render.scenarioEvolutionMarkup({status:'missing_baseline'},'VATT'),/缺少Release Note完整起始章节/)
 const html=render.scenarioWhitepaperMarkup({baseline:{version:'1.51.90',detail_evidence:{source_id:'p'}},section:{content:'白皮书完整章节'},later_changes:[{text:'不得混入'}]},'VATT')
 assert.match(html,/最新白皮书 · 1.51.90/);assert.match(html,/白皮书完整章节/);assert.doesNotMatch(html,/不得混入|整理后的/)
})
