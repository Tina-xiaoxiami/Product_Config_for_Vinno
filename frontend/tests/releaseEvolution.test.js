import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
const app=readFileSync(new URL('../../backend/tracker/static/app.js',import.meta.url),'utf8')
const start=app.indexOf('function scenarioDocumentMarkup'),end=app.indexOf('function scenarioVersionMarkup',start)
const escapeHtml=x=>String(x??'').replaceAll('<','&lt;').replaceAll('>','&gt;')
const reviewSource=readFileSync(new URL('../../backend/tracker/static/release-review.js',import.meta.url),'utf8')
const render=new Function('escapeHtml','escapeAttribute','scenarioPreviewButton','sourceImageMarkup',`${reviewSource}\n${app.slice(start,end)};return {scenarioWhitepaperMarkup,scenarioEvolutionMarkup,scenarioDocumentMarkup,scenarioBaselineImagesMarkup,scenarioIllustrationsMarkup,scenarioUnverifiedSourcesMarkup}`)(escapeHtml,escapeHtml,(id,locator,query,label)=>`<button data-source="${escapeHtml(id)}">${escapeHtml(label || '查看原文')}</button>`, block => String(block.data_url || '').startsWith('data:image/png;base64,') ? '<figure><img></figure>' : '')
test('功能展示RN基线、确定性结果与未应用变更，不生成摘要',()=>{
 const html=render.scenarioEvolutionMarkup({baseline:{version:'1.51.20'},content:'原始完整章节\n新增支持',applied_changes:[{}],unresolved_changes:[{version:'1.51.90',text:'<更新内容>',reason:'范围不明确'}],timeline:[],coverage_notice:'仅已收录'},'VATT')
 assert.match(html,/正文起点 1.51.20/);assert.match(html,/原始完整章节/);assert.match(html,/新增支持/);assert.match(html,/&lt;更新内容&gt;/);assert.match(html,/feature-review-sidebar/);assert.doesNotMatch(html,/大模型整理|整理后的功能说明|白皮书/)
})
test('没有RN起始章节不以白皮书替代，白皮书单独只显示章节',()=>{
 assert.match(render.scenarioEvolutionMarkup({status:'missing_baseline'},'VATT'),/缺少Release Note完整起始章节/)
 const html=render.scenarioWhitepaperMarkup({baseline:{version:'1.51.90',detail_evidence:{source_id:'p'}},section:{content:'白皮书完整章节'},later_changes:[{text:'不得混入'}]},'VATT')
 assert.match(html,/最新白皮书 · 1.51.90/);assert.match(html,/白皮书完整章节/);assert.doesNotMatch(html,/不得混入|整理后的/)
})

test('章节标题、步骤、参数和后续补充分区，文字转义保留',()=>{
 const html=render.scenarioDocumentMarkup('新增VATT\n适用探头/应用：S1-8C\n临床意义：\n完整临床说明\n参数：\n标尺：0-4\n操作步骤：\n点击Measure；\n新增支持A；',[{operation:'append',version:'1.51.80',after:'新增支持A；'}])
 assert.match(html,/<h4>临床意义<\/h4>/);assert.match(html,/<ol class="feature-steps">/);assert.match(html,/feature-parameters/);assert.match(html,/feature-scope/);assert.doesNotMatch(html,/版本 1.51.80 补充/)
 assert.doesNotMatch(render.scenarioDocumentMarkup('<script>bad</script>'),/<script>/)
})
test('基线图示带版本来源，图片不可用仍提供原文入口',()=>{
 const base={version:'1.51.30',section:{has_images:true,images_complete:true,blocks:[{type:'image',data_url:'data:image/png;base64,AA=='}]}}
 assert.match(render.scenarioBaselineImagesMarkup(base,'VATT'),/<img>/)
 assert.match(render.scenarioBaselineImagesMarkup(base,'VATT'),/1.51.30/)
 assert.match(render.scenarioBaselineImagesMarkup({...base,section:{...base.section,images_complete:false,blocks:[]}},'VATT'),/部分图片无法展示/)
})
test('图片放在效果图示分区内且先于后续补充，不重复展示',()=>{
 const html=render.scenarioDocumentMarkup('效果图示：\n新增支持A；',[{operation:'append',version:'1.51.80',after:'新增支持A；'}],'<figure>原图</figure>')
 assert.equal(html.split('<figure>').length-1,1)
 assert.ok(html.indexOf('<figure>')<html.indexOf('新增支持A；'))
})

test('默认图示使用独立最新版本，起始正文不被图示替换',()=>{
 const section={has_images:true,images_complete:true,blocks:[{type:'image',data_url:'data:image/png;base64,AA=='}]}
 const data={baseline:{version:'1.51.30',section},illustrations:[{version:'1.51.90',title:'VATT图像优化',section}],content:'基线完整内容',timeline:[],applied_changes:[],unresolved_changes:[]}
 const html=render.scenarioEvolutionMarkup(data,'VATT')
 assert.match(html,/正文起点 1.51.30/);assert.match(html,/基线完整内容/);assert.match(html,/最近版本图示/);assert.match(html,/1.51.90/);assert.doesNotMatch(html,/起始版本图示/)
 assert.equal((html.match(/<img>/g)||[]).length,1)
})
test('最新图不可用时保留版本和原文入口，不悄悄展示旧图',()=>{
 const html=render.scenarioIllustrationsMarkup({baseline:{version:'1.0.0',section:{has_images:true,blocks:[{type:'image',data_url:'data:image/png;base64,AA=='}]}},illustrations:[{version:'1.1.0',section:{has_images:true,images_complete:false,blocks:[]}}]},'VATT')
 assert.match(html,/1.1.0/);assert.match(html,/部分图片无法展示/);assert.doesNotMatch(html,/<img>/)
})

test('正文追加不再被最后一个历史版本分组吸收',()=>{
 const additions=[{operation:'append',version:'1.51.80',after:'原80记录；'}]
 const html=render.scenarioDocumentMarkup('效果图示：\n兼容性说明：1.51.90修改后的测量值会变化。',additions,'<figure>修改后图</figure>')
 assert.doesNotMatch(html,/版本 1.51.80 补充|is-update/)
 assert.match(html,/兼容性说明：1.51.90/)
 assert.ok(html.indexOf('<figure>')<html.indexOf('兼容性说明'))
})

test('相同核对来源只有一个入口，不同文件折叠且名称可区分',()=>{
 const one={source_id:'release:source:39',version:'1.51.90',record_count:4,filename:'Release Note.docx'}
 const single=render.scenarioUnverifiedSourcesMarkup([one,one],'VATT')
 assert.equal((single.match(/<button/g)||[]).length,1)
 const distinct=render.scenarioUnverifiedSourcesMarkup([one,{...one,source_id:'release:source:40',filename:'另一份<script>.docx'}],'VATT')
 assert.match(distinct,/<details class="feature-original-sources">/);assert.match(distinct,/核对原文（2 份资料）/)
 assert.match(distinct,/#39/);assert.match(distinct,/#40/);assert.match(distinct,/另一份&lt;script&gt;.docx/)
 assert.doesNotMatch(distinct,/<details[^>]*open/)
})

test('修改后图默认显示，修改前只在折叠对照中，普通多图不误判',()=>{
 const section={has_images:true,images_complete:true,blocks:[{type:'image',comparison_role:'before',data_url:'data:image/png;base64,AA=='},{type:'image',comparison_role:'after',data_url:'data:image/png;base64,AQ=='}]}
 const html=render.scenarioBaselineImagesMarkup({version:'1.51.90',section},'VATT',true)
 const gallery=html.slice(html.indexOf('<div class="feature-image-gallery">'),html.indexOf('<details'))
 assert.equal((gallery.match(/<img>/g)||[]).length,1)
 assert.match(html,/<details class="feature-image-comparison">/)
 assert.match(gallery,/修改后/);assert.doesNotMatch(gallery,/修改前/)
 const ordinary=render.scenarioBaselineImagesMarkup({version:'1.51.90',section:{...section,blocks:section.blocks.map(block=>({...block,comparison_role:'neutral'}))}},'VATT',true)
 assert.equal((ordinary.match(/<img>/g)||[]).length,2)
 assert.doesNotMatch(ordinary,/feature-image-comparison/)
})
test('不明确前后角色时提供原图选择，不能凭图片顺序自动取后一张',()=>{
 const html=render.scenarioBaselineImagesMarkup({version:'1.51.90',source_id:'release:source:40',locator:'原文行 72',section:{has_images:true,images_complete:true,blocks:[{type:'image',comparison_role:'unknown',image_hash:'a'.repeat(64),data_url:'data:image/png;base64,AA=='}]}},'VATT',true)
 assert.match(html,/尚不能明确区分修改前后/);assert.match(html,/设为修改后图示/)
})

test('首次人工选择后保留其他图重选入口，当前图禁止重复提交',()=>{
 const selected='b'.repeat(64)
 const html=render.scenarioBaselineImagesMarkup({version:'1.51.90',source_id:'release:source:40',locator:'原文行 72',selection:{image_hash:selected},section:{has_images:true,images_complete:true,blocks:[{type:'image',comparison_role:'unknown',display_role:'comparison',image_hash:'a'.repeat(64),data_url:'data:image/png;base64,AA=='},{type:'image',comparison_role:'unknown',display_role:'after',image_hash:selected,data_url:'data:image/png;base64,AQ=='}]}},'VATT',true)
 assert.match(html,/data-illustration-select="a{64}"/)
 assert.match(html,/disabled>当前修改后图示/)
 assert.match(html,/设为修改后图示/)
})

test('已核实的修改前图片不能因同组未知图而出现人工覆盖入口',()=>{
 const html=render.scenarioBaselineImagesMarkup({version:'1.51.90',source_id:'release:source:40',locator:'原文行 72',section:{has_images:true,images_complete:true,blocks:[{type:'image',comparison_role:'before',image_hash:'a'.repeat(64),data_url:'data:image/png;base64,AA=='},{type:'image',comparison_role:'unknown',image_hash:'b'.repeat(64),data_url:'data:image/png;base64,AQ=='}]}},'VATT',true)
 assert.doesNotMatch(html,/data-illustration-select="a{64}"/);assert.match(html,/data-illustration-select="b{64}"/)
})
