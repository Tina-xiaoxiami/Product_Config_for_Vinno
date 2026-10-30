import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
const app=readFileSync(new URL('../../backend/tracker/static/app.js',import.meta.url),'utf8')
const start=app.indexOf('function scenarioDocumentMarkup'),end=app.indexOf('function scenarioVersionMarkup',start)
const escapeHtml=x=>String(x??'').replaceAll('<','&lt;').replaceAll('>','&gt;')
const render=new Function('escapeHtml','escapeAttribute','scenarioPreviewButton','sourceImageMarkup',`${app.slice(start,end)};return {scenarioWhitepaperMarkup,scenarioEvolutionMarkup,scenarioDocumentMarkup,scenarioBaselineImagesMarkup}`)(escapeHtml,escapeHtml,()=>'<button>查看原文</button>', block => String(block.data_url || '').startsWith('data:image/png;base64,') ? '<figure><img></figure>' : '')
test('功能展示RN基线、确定性结果与未应用变更，不生成摘要',()=>{
 const html=render.scenarioEvolutionMarkup({baseline:{version:'1.51.20'},content:'原始完整章节\n新增支持',applied_changes:[{}],unresolved_changes:[{version:'1.51.90',text:'<更新内容>',reason:'范围不明确'}],timeline:[],coverage_notice:'仅已收录'},'VATT')
 assert.match(html,/Release Note 起点 1.51.20/);assert.match(html,/原始完整章节/);assert.match(html,/新增支持/);assert.match(html,/&lt;更新内容&gt;/);assert.match(html,/<details open(?:\s|>)/);assert.doesNotMatch(html,/大模型整理|整理后的功能说明|白皮书/)
})
test('没有RN起始章节不以白皮书替代，白皮书单独只显示章节',()=>{
 assert.match(render.scenarioEvolutionMarkup({status:'missing_baseline'},'VATT'),/缺少Release Note完整起始章节/)
 const html=render.scenarioWhitepaperMarkup({baseline:{version:'1.51.90',detail_evidence:{source_id:'p'}},section:{content:'白皮书完整章节'},later_changes:[{text:'不得混入'}]},'VATT')
 assert.match(html,/最新白皮书 · 1.51.90/);assert.match(html,/白皮书完整章节/);assert.doesNotMatch(html,/不得混入|整理后的/)
})

test('章节标题、步骤、参数和后续补充分区，文字转义保留',()=>{
 const html=render.scenarioDocumentMarkup('新增VATT\n适用探头/应用：S1-8C\n临床意义：\n完整临床说明\n参数：\n标尺：0-4\n操作步骤：\n点击Measure；\n新增支持A；',[{operation:'append',version:'1.51.80',after:'新增支持A；'}])
 assert.match(html,/<h4>临床意义<\/h4>/);assert.match(html,/<ol class="feature-steps">/);assert.match(html,/feature-parameters/);assert.match(html,/feature-scope/);assert.match(html,/版本 1.51.80 补充/)
 assert.doesNotMatch(render.scenarioDocumentMarkup('<script>bad</script>'),/<script>/)
})
test('基线图示带版本来源，图片不可用仍提供原文入口',()=>{
 const base={version:'1.51.30',section:{has_images:true,images_complete:true,blocks:[{type:'image',data_url:'data:image/png;base64,AA=='}]}}
 assert.match(render.scenarioBaselineImagesMarkup(base,'VATT'),/<img>/)
 assert.match(render.scenarioBaselineImagesMarkup(base,'VATT'),/1.51.30 原文/)
 assert.match(render.scenarioBaselineImagesMarkup({...base,section:{...base.section,images_complete:false,blocks:[]}},'VATT'),/部分图片无法展示/)
})
test('图片放在效果图示分区内且先于后续补充，不重复展示',()=>{
 const html=render.scenarioDocumentMarkup('效果图示：\n新增支持A；',[{operation:'append',version:'1.51.80',after:'新增支持A；'}],'<figure>原图</figure>')
 assert.equal(html.split('<figure>').length-1,1)
 assert.ok(html.indexOf('<figure>')<html.indexOf('版本 1.51.80 补充'))
})
