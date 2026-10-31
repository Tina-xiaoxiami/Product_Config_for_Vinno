import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../../backend/tracker/static/app.js', import.meta.url), 'utf8')
function funcs(names, context = {}) {
  const pieces = names.map(name => {
    const normal = source.indexOf(`function ${name}(`)
    const asyncStart = source.indexOf(`async function ${name}(`)
    const start = asyncStart >= 0 ? asyncStart : normal
    assert.ok(start >= 0, name)
    const next = source.slice(start + 1).search(/\n(?:async )?function /)
    return source.slice(start, next < 0 ? undefined : start + 1 + next)
  })
  return new Function(...Object.keys(context), `${pieces.join('\n')}; return {${names.join(',')}}`)(...Object.values(context))
}
const escape = v => String(v ?? '').replaceAll('&', '&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;')
const categoryLabels = {function:'功能', image:'图像', bug:'Bug', config:'配置', config_note:'配置/兼容性说明', probe:'探头', remark:'备注', unclassified:'待确认', source:'Release Note 原文'}

test('source and Release Note category tabs use server-wide counts and expose the selected state', () => {
  const state = {searchSourceGroup:'release_note', searchReleaseCategory:'function'}
  const {searchTaxonomyMarkup} = funcs(['searchTaxonomyMarkup'], {state, categoryLabels, escapeAttribute:escape, escapeHtml:escape})
  const result = {total:2, taxonomy_counts:{sources:{release_note:82, whitepaper:19, other:9}, release_categories:{function:51,config:4}}}
  const html = searchTaxonomyMarkup(result)
  assert.match(html, /Release Note <span>82<\/span>/); assert.match(html, /白皮书 <span>19<\/span>/)
  assert.match(html, /data-search-release-category="function" aria-selected="true"/)
  assert.match(html, /功能 <span>51<\/span>/); assert.match(html, /配置 <span>4<\/span>/)
  assert.doesNotMatch(html, /data-search-release-category="bug"/)
  state.searchReleaseCategory = 'bug'
  assert.match(searchTaxonomyMarkup(result), /data-search-release-category="bug" aria-selected="true"/)
  state.searchSourceGroup='whitepaper'
  assert.match(searchTaxonomyMarkup(result), /data-search-source-group="whitepaper" aria-selected="true"/)
  assert.doesNotMatch(searchTaxonomyMarkup(result), /data-search-release-category/)
})

test('switching tabs resets page without mutating query/project/version or unrelated selections', () => {
  const state = {searchSourceGroup:'release_note',searchReleaseCategory:'config',searchPage:4,activeProjectId:7, query:'子宫畸形', versions:'1.51.80', searchComparison:[{preview_id:'release:source:16'}]}
  let calls=0
  const {selectSearchTaxonomy} = funcs(['selectSearchTaxonomy'], {state, categoryLabels, searchUnified:()=>{calls++; return Promise.resolve()}, showNotice(){}})
  assert.equal(selectSearchTaxonomy('source','whitepaper'),true)
  assert.equal(state.searchPage,1); assert.equal(state.activeProjectId,7); assert.equal(state.query,'子宫畸形'); assert.equal(state.versions,'1.51.80'); assert.equal(state.searchReleaseCategory,'config'); assert.equal(state.searchComparison.length,1)
  assert.equal(selectSearchTaxonomy('source','unknown'),false); assert.equal(calls,1)
})

test('preferred chapter opens first while original configuration evidence stays accessible', () => {
  const {searchEvidenceActions} = funcs(['preferredSearchEvidence','searchEvidenceActions'], {escapeAttribute:escape,escapeHtml:escape,verificationLabel:()=> '未复核'})
  const item = {source_type:'release',evidence_kind:'version_record',preview_id:'release:change:7',locator:'中文记录',detail_evidence:{source_id:'release:source:16',locator:'原文行 123',section_number:'4.4.4',verification:'unverified',notice:'原文需核对'}}
  const html = searchEvidenceActions(item,'子宫','子宫')
  assert.ok(html.indexOf('release:source:16') < html.indexOf('release:change:7'))
  assert.match(html, /查看完整功能描述/); assert.match(html, /未复核/); assert.match(html, /原文需核对/); assert.match(html, /查看变更依据/); assert.match(html, /原文行 123/)
  const fallback = searchEvidenceActions({preview_id:'release:change:7',locator:'中文记录',detail_evidence_notice:'未能核实完整章节'},'子宫','子宫')
  assert.match(fallback, /release:change:7/); assert.doesNotMatch(fallback, /查看完整功能描述/)
})

test('complete section renders continuous ordered content and copy uses its replayable locator', () => {
  const entries = ['4.4.4 新增子宫畸形分类','适用于3D模式，子宫应用；','支持ESHRE和ARSM两种分类系统。','手动选择对应的分型后，报告的超声描述中会自动添加对应的常规说明。']
  const section = {complete:true,content:entries.join('\n'),locator:'原文行 123',source_id:'release:source:16'}
  const preview = {section, chunks:[{locator:'原文行 125',text:'支持ESHRE'}],title:'Release Note',scope:'ULTIMUS G2 · 1.51.80',verification:'unverified'}
  const helpers = funcs(['readableSearchEvidence','formatEvidenceCitation','mergeSectionTextBlocks','sourceImageMarkup','searchPreviewSectionMarkup'], {escapeHtml:escape,highlightSearchText:escape, verificationLabel:()=> '未复核',searchEvidenceLabel:()=>'',evidenceLink: selection => `${selection.preview_id}#${selection.locator}`})
  const html = helpers.searchPreviewSectionMarkup(preview,'子宫')
  for (const text of entries) assert.ok(html.includes(text))
  assert.ok(html.indexOf(entries[0]) < html.indexOf(entries[1])); assert.ok(html.indexOf(entries[1]) < html.indexOf(entries[2]))
  assert.doesNotMatch(html, /VAim\+优化|自动括约肌/)
  const citation = helpers.formatEvidenceCitation(preview,{locator:'原文行 125',preview_id:'release:source:16'},'url')
  assert.match(citation,/完整章节/); assert.match(citation,/release:source:16#原文行 123/); assert.match(citation,/自动添加对应的常规说明/)
  assert.equal(helpers.searchPreviewSectionMarkup({...preview,section:{...section,complete:false}},'子宫'),'')
  assert.equal(helpers.readableSearchEvidence({...preview,section:{...section,complete:false}},'原文行 125').complete,false)
})

test('preview and URL wiring preserve source/category and use real PDF section page', () => {
  assert.match(source, /'source_group', 'release_category'/)
  assert.match(source, /source_group: state\.searchSourceGroup/)
  assert.match(source, /release_category: state\.searchSourceGroup/)
  assert.match(source, /searchPdfPageLocator\(preview, locator, requestedLocator\)/)
  assert.match(source, /未能核实完整章节；以下为匹配片段/)
  assert.match(source, /ArrowLeft.*ArrowRight.*Home.*End/)
})

test('section renders safe images in their original block sequence and warns on unavailable images', () => {
  const {searchPreviewSectionMarkup} = funcs(['mergeSectionTextBlocks','sourceImageMarkup','searchPreviewSectionMarkup'], {escapeHtml:escape,escapeAttribute:escape,highlightSearchText:escape})
  const section = {complete:true,locator:'原文行 123',content:'标题\n正文',section_number:'4.4.4',images_complete:false,blocks:[
    {type:'text',text:'标题'}, {type:'image',data_url:'data:image/png;base64,aGVsbG8='}, {type:'text',text:'正文'},
    {type:'image',data_url:'data:image/svg+xml;base64,PHN2Zz4='}
  ]}
  const html = searchPreviewSectionMarkup({section},'')
  assert.ok(html.indexOf('标题') < html.indexOf('data:image/png'))
  assert.ok(html.indexOf('data:image/png') < html.indexOf('正文'))
  assert.doesNotMatch(html,/data:image\/svg/)
  assert.match(html,/部分章节图片无法显示/)
  assert.match(html,/alt="章节 4\.4\.4 原文图片"/)
})

test('a complete illustrated chapter does not claim images were compared as equal', () => {
  const entries = [{item:{locator:'p'},preview:{section:{complete:true,content:'相同',locator:'p',has_images:true},chunks:[]}},{item:{locator:'p'},preview:{section:{complete:true,content:'相同',locator:'p',has_images:true},chunks:[]}}]
  const {comparisonTextStatus,comparisonNotice} = funcs(['readableSearchEvidence','normalizeComparisonText','normalizeChapterComparisonText','comparisonTextStatus','comparisonNotice'])
  assert.equal(comparisonTextStatus(entries),'same')
  assert.match(comparisonNotice(entries),/文字一致/)
  assert.match(comparisonNotice(entries),/图片.*核对原文件/)
})

test('adjacent Word runs within one paragraph remain continuous around images', () => {
  const {mergeSectionTextBlocks,searchPreviewSectionMarkup} = funcs(['mergeSectionTextBlocks','sourceImageMarkup','searchPreviewSectionMarkup'], {escapeHtml:escape,escapeAttribute:escape,highlightSearchText:escape})
  const blocks = [{type:'text',locator:'段落 1',text:'支持'},{type:'text',locator:'段落 1',text:'ESHRE'}, {type:'image',locator:'段落 1',data_url:'data:image/png;base64,aGVsbG8='}, {type:'text',locator:'段落 1',text:'分类'},{type:'text',locator:'段落 2',text:'下一段'}]
  const merged = mergeSectionTextBlocks(blocks)
  assert.equal(merged.length,4); assert.equal(merged[0].text,'支持ESHRE'); assert.equal(merged[1].type,'image')
  const html = searchPreviewSectionMarkup({section:{complete:true,locator:'段落 1',content:'支持ESHRE分类\n下一段',blocks}},'')
  assert.match(html, /<p>支持ESHRE<\/p>/)
  assert.ok(html.indexOf('支持ESHRE') < html.indexOf('data:image/png')); assert.ok(html.indexOf('data:image/png') < html.indexOf('分类'))
})

test('comparison of a preferred snapshot retains its own evidence kind and source label', () => {
  const state = {searchComparisonOptions:[]}
  const {searchComparisonButton} = funcs(['preferredSearchEvidence','searchComparisonButton'], {state})
  searchComparisonButton({preview_id:'release:change:7',locator:'中文记录',title:'配置记录',scope:'项目 · 1.51.80',evidence_kind:'version_record',source_label:'版本与功能',detail_evidence:{source_id:'release:source:16',locator:'原文行 123',title:'4.4.4 新增子宫畸形分类',evidence_kind:'source_snapshot',source_label:'Release Note 原文'}}, {}, '子宫')
  assert.deepEqual([state.searchComparisonOptions[0].preview_id,state.searchComparisonOptions[0].evidence_kind,state.searchComparisonOptions[0].source_label], ['release:source:16','source_snapshot','Release Note 原文'])
})

test('actual Word automatic numbering is shown even when not embedded in paragraph text', () => {
  const {searchPreviewSectionMarkup,formatEvidenceCitation} = funcs(['readableSearchEvidence','formatEvidenceCitation','mergeSectionTextBlocks','sourceImageMarkup','searchPreviewSectionMarkup'], {escapeHtml:escape,escapeAttribute:escape,highlightSearchText:escape,verificationLabel:()=> '未复核',searchEvidenceLabel:()=>'',evidenceLink:()=>''})
  const preview = {title:'Release Note',scope:'ULTIMUS',verification:'unverified',chunks:[],section:{complete:true,section_number:'4.4.4',locator:'原文行 123',content:'新增子宫畸形分类\n正文',blocks:[{type:'text',locator:'原文行 123',text:'新增子宫畸形分类'},{type:'text',locator:'原文行 124',text:'正文'}]}}
  assert.match(searchPreviewSectionMarkup(preview,''),/完整章节 4\.4\.4/)
  assert.match(formatEvidenceCitation(preview,{locator:'原文行 123'},''),/完整章节 4\.4\.4/)
})

test('a whitepaper same-file detail does not imply a configuration change or duplicate the same location', () => {
  const {searchEvidenceActions} = funcs(['preferredSearchEvidence','searchEvidenceActions'], {escapeAttribute:escape,escapeHtml:escape,verificationLabel:()=> '未复核'})
  const item = {source_type:'controlled',preview_id:'controlled:35:pdf',locator:'第 3 页',detail_evidence:{source_id:'controlled:35:pdf',locator:'第 13 页'}}
  const html = searchEvidenceActions(item,'子宫','子宫')
  assert.match(html,/查看原命中位置/); assert.doesNotMatch(html,/查看变更依据/)
  item.locator='第 13 页'
  assert.equal((searchEvidenceActions(item,'子宫','子宫').match(/data-search-result-preview/g)||[]).length,1)
})

test('auto-number differences are preserved in chapter comparisons', () => {
  const entry = number => ({item:{locator:'p'},preview:{section:{complete:true,section_number:number,content:'相同正文',locator:'p'},chunks:[]}})
  const {comparisonTextStatus} = funcs(['readableSearchEvidence','normalizeComparisonText','normalizeChapterComparisonText','comparisonTextStatus'])
  assert.equal(comparisonTextStatus([entry('4.4.4'),entry('4.4.5')]), 'different')
  assert.equal(comparisonTextStatus([entry('4.4.4'),entry('4.4.4')]), 'same')
})

test('image warning distinguishes image-free sections from missing images', () => {
  const {searchPreviewSectionMarkup} = funcs(['mergeSectionTextBlocks','sourceImageMarkup','searchPreviewSectionMarkup'], {escapeHtml:escape,escapeAttribute:escape,highlightSearchText:escape})
  const section = {complete:true,locator:'第 13 页',content:'正文',has_images:false,images_complete:false}
  assert.doesNotMatch(searchPreviewSectionMarkup({section},''),/图片无法显示/)
  assert.match(searchPreviewSectionMarkup({section:{...section,has_images:true}},''),/图片无法显示/)
})

test('equal Word and PDF headings normalize only an exact repeated chapter number', () => {
  const entry = (number,text) => ({item:{locator:'p'},preview:{section:{complete:true,section_number:number,content:text,locator:'p'},chunks:[]}})
  const {comparisonTextStatus} = funcs(['readableSearchEvidence','normalizeComparisonText','normalizeChapterComparisonText','comparisonTextStatus'])
  assert.equal(comparisonTextStatus([entry('4.4.4','新增功能\n正文'),entry('4.4.4','4.4.4 新增功能\n正文')]),'same')
  assert.equal(comparisonTextStatus([entry('4.4.4','新增功能\n正文'),entry('4.4.40','4.4.40 新增功能\n正文')]),'different')
  assert.equal(comparisonTextStatus([entry('4.4.4','新增功能 1'),entry('4.4.4','4.4.4 新增功能 2')]),'different')
})

test('comparison preview notice preserves other limitations but corrects image context', () => {
  const {comparisonPreviewNotice} = funcs(['comparisonPreviewNotice'])
  assert.equal(comparisonPreviewNotice({notice:'原文未复核。 本章节图片已随原文显示。 请核对适用范围。'}),'原文未复核。 图片请在完整预览中查看。 请核对适用范围。')
  assert.match(source, /对照仅显示文字；图片请打开完整预览核对/)
})

test('actual comparison dialog preserves notices and explicitly scopes image comparison to text', async () => {
  const content = {innerHTML:''}, notice = {textContent:''}, copy = {disabled:false,title:''}, fallback = {hidden:false}
  const dialog = {open:true, querySelector:()=>fallback}
  const document = {querySelector:selector => ({'#search-compare-dialog':dialog,'#search-compare-content':content,'#copy-search-comparison':copy,'#search-compare-notice':notice})[selector]}
  const item = {preview_id:'release:source:16',locator:'原文行 123',version:'1.51.80',title:'资料',scope:'项目',source_label:'原文',query:'子宫'}
  const state = {searchComparison:[item,{...item,preview_id:'release:source:17'}]}
  const preview = {notice:'原文未复核。 本章节图片已随原文显示。',verification:'unverified',section:{complete:true,section_number:'4.4.4',locator:'原文行 123',content:'新增子宫畸形分类',has_images:true},chunks:[]}
  const context = {document,state,window:{location:{href:'http://localhost'}},api:async()=>preview, buildComparisonCitation:()=> 'ok',escapeHtml:escape,escapeAttribute:escape,verificationLabel:()=> '未复核',searchEvidenceLabel:()=>'',searchQueryOrigin:()=>'',highlightSearchText:escape}
  const {openSearchComparison} = funcs(['readableSearchEvidence','normalizeComparisonText','normalizeChapterComparisonText','comparisonTextStatus','comparisonNotice','comparisonPreviewNotice','openSearchComparison'],context)
  await openSearchComparison()
  assert.match(content.innerHTML,/原文未复核/)
  assert.match(content.innerHTML,/对照仅显示文字；图片请打开完整预览核对/)
  assert.doesNotMatch(content.innerHTML,/图片已随原文显示/)
  assert.match(notice.textContent,/文字一致/)
  assert.equal(copy.disabled,false)
})

test('invalid locator cannot be promoted to a complete section or copied as selected evidence', () => {
  const {readableSearchEvidence,searchPreviewSectionMarkup,formatEvidenceCitation} = funcs(['readableSearchEvidence','formatEvidenceCitation','mergeSectionTextBlocks','sourceImageMarkup','searchPreviewSectionMarkup'], {escapeHtml:escape,escapeAttribute:escape,highlightSearchText:escape,verificationLabel:()=> '未复核',searchEvidenceLabel:()=>'',evidenceLink:()=>''})
  const preview = {locator_status:'unresolved',title:'文件',scope:'范围',verification:'unverified',chunks:[],section:{complete:true,locator:'第 13 页',content:'不相关的另一章节'}}
  assert.equal(readableSearchEvidence(preview,'第 99 页'),null)
  assert.equal(searchPreviewSectionMarkup(preview,''),'')
  assert.throws(() => formatEvidenceCitation(preview,{locator:'第 99 页',preview_id:'controlled:1:pdf'},'url'))
})

test('unresolved empty preview retains location failure and source notices', async () => {
  const content={innerHTML:'',insertAdjacentHTML(){}}, title={textContent:''}, meta={textContent:''}, actions={innerHTML:''}, fallback={hidden:false}
  const dialog={open:true,querySelector:()=>fallback}
  const document={querySelector:selector=>({'#search-preview-dialog':dialog,'#search-preview-content':content,'#search-preview-title':title,'#search-preview-meta':meta,'#search-preview-actions':actions})[selector]}
  const preview={title:'资料',scope:'范围',verification:'unverified',file_format:'docx',notice:'索引过期，请核对原件。',chunks:[],matches:[],locator_status:'unresolved'}
  const state={searchPreviewRequest:0,activeView:'other'}
  const context={document,state,api:async()=>preview,escapeHtml:escape,escapeAttribute:escape,highlightSearchText:escape,searchQueryOrigin:()=>'',fileFormatLabel:()=> 'Word',verificationLabel:()=> '未复核',updatePreviewTools(){},syncLocation(){},workbenchUrl:value=>value}
  const {openSearchPreview} = funcs(['mergeSectionTextBlocks','sourceImageMarkup','searchPreviewSectionMarkup','previewSelectedLocator','previewMatchNavigation','openSearchPreview'],context)
  await openSearchPreview('controlled:1:docx','段落 999','子宫')
  assert.match(content.innerHTML,/原文位置不可用/); assert.match(content.innerHTML,/索引过期/)
})

test('unresolved reference is rejected even without explicit selection locator', () => {
  const {readableSearchEvidence,formatEvidenceCitation} = funcs(['readableSearchEvidence','formatEvidenceCitation'], {verificationLabel:()=>'',searchEvidenceLabel:()=>'',evidenceLink:()=>''})
  const preview={locator_status:'unresolved',title:'x',scope:'x',chunks:[{locator:'p',text:'old'}]}
  assert.equal(readableSearchEvidence(preview,''),null)
  assert.throws(()=>formatEvidenceCitation(preview,{},'url'))
})

test('confirmed table-of-contents redirect cites the real section locator', () => {
  const {formatEvidenceCitation} = funcs(['readableSearchEvidence','formatEvidenceCitation'], {verificationLabel:()=>'',searchEvidenceLabel:()=>'',evidenceLink:selection=>selection.locator})
  const preview={locator_status:'toc_redirect',title:'白皮书',scope:'国内',chunks:[{locator:'第 3 页',text:'目录'}],section:{complete:true,section_number:'5.63',locator:'第 13 页',content:'5.63 子宫畸形分类\n正文'}}
  const text=formatEvidenceCitation(preview,{locator:'第 3 页',preview_id:'controlled:35:pdf'},'url')
  assert.match(text,/第 13 页/); assert.match(text,/5\.63/); assert.doesNotMatch(text,/第 3 页/)
})

test('complete chapter is displayed before collapsed navigation, retaining source warning', async () => {
  const content={innerHTML:'',insertAdjacentHTML(){}}, title={textContent:''}, meta={textContent:''}, actions={innerHTML:''}, fallback={hidden:false}
  const dialog={open:true,querySelector:()=>fallback}
  const document={querySelector:selector=>({'#search-preview-dialog':dialog,'#search-preview-content':content,'#search-preview-title':title,'#search-preview-meta':meta,'#search-preview-actions':actions})[selector]}
  const preview={title:'Release Note',scope:'项目',verification:'unverified',file_format:'docx',notice:'导入时原文快照；请核对适用范围。 本章节包含图片，请在完整预览中查看。',chunks:[{locator:'原文行 123',text:'标题'}],matches:[{locator:'原文行 123'},{locator:'原文行 124'}],match_count:2,locator_status:'exact',section:{complete:true,section_number:'4.4.4',locator:'原文行 123',content:'章节标题\n正文内容',has_images:true,images_complete:true,blocks:[{type:'text',locator:'原文行 123',text:'章节标题'},{type:'image',data_url:'data:image/png;base64,aGVsbG8='},{type:'text',locator:'原文行 124',text:'正文内容'}]}}
  const state={searchPreviewRequest:0,activeView:'other'}
  const context={document,state,api:async()=>preview,escapeHtml:escape,escapeAttribute:escape,highlightSearchText:escape,searchQueryOrigin:()=>'<p>输入词提示</p>',fileFormatLabel:()=> 'Word',verificationLabel:()=> '未复核',updatePreviewTools(){},syncLocation(){},workbenchUrl:value=>value}
  const {openSearchPreview} = funcs(['mergeSectionTextBlocks','sourceImageMarkup','searchPreviewSectionMarkup','previewSelectedLocator','previewMatchNavigation','openSearchPreview'],context)
  await openSearchPreview('release:source:16','原文行 123','子宫')
  assert.match(content.innerHTML,/导入时原文快照/)
  assert.doesNotMatch(content.innerHTML,/本章节包含图片，请在完整预览中查看/)
  assert.ok(content.innerHTML.indexOf('完整章节') < content.innerHTML.indexOf('其他命中与定位'))
  assert.match(content.innerHTML,/<details class="search-preview-context"><summary>其他命中与定位<\/summary>/)
  assert.match(content.innerHTML,/输入词提示/); assert.match(content.innerHTML,/本文件 2 处匹配/)
  assert.match(content.innerHTML,/data:image\/png/)
})

test('compact whitepaper card favors actual chapter excerpt while keeping the original hit action', () => {
  const context={escapeHtml:escape,escapeAttribute:escape,highlightSearchText:escape,verificationLabel:()=> '未复核',fileFormatLabel:()=> 'PDF',searchEvidenceLabel:()=>'', searchComparisonButton:()=>''}
  const {compactSearchCard,searchEvidenceActions} = funcs(['preferredSearchEvidence','searchEvidenceActions','compactSearchCard'],context)
  const item={source_type:'controlled',source_label:'白皮书',title:'白皮书',scope:'国内',verification:'unverified',preview_id:'controlled:35:pdf',locator:'第 3 页',matched_text:'5.63 子宫畸形分类 ......9',detail_evidence:{source_id:'controlled:35:pdf',locator:'第 13 页',verification:'unverified',excerpt:'5.63 子宫畸形分类\n支持 ESHRE 和 ARSM 两种分类系统。'}}
  const card=compactSearchCard(item,{query:'子宫'},searchEvidenceActions(item,'子宫','子宫'),'',[])
  assert.match(card,/支持 ESHRE 和 ARSM/); assert.match(card,/原文章节节选（未复核）/)
  assert.doesNotMatch(card,/\.\.\.\.\.\.9/); assert.match(card,/查看原命中位置/); assert.match(card,/第 13 页/)
})

test('rapid taxonomy switches keep controls responsive and only render the latest response', async () => {
  const controls = {
    '#release-search': {value:'子宫'}, '#release-search-scope': {value:'current'},
    '#release-search-market': {value:'domestic'}, '#release-search-model': {value:''},
    '#release-search-country': {value:''}, '#release-search-verification': {value:'all'},
    '#release-search-current': {checked:false}, '#search-index-status': {textContent:''},
  }
  const document = {activeElement:null, querySelector:selector=>controls[selector]}
  let html = ''
  const container = {focused:[], contains:element=>!!element && element.owner===container,
    get innerHTML() {return html}, set innerHTML(value) {html=value; document.activeElement=null},
    querySelector(selector) { return {owner:container, selector, value:state.searchWhitepaperModel, hasAttribute(name) {return selector.includes(name)}, getAttribute(name) {return selector.match(new RegExp(name+'=\"([^\"]+)\"'))?.[1] || null}, focus() {document.activeElement=this; container.focused.push(selector)}} }}
  controls['#release-search-result'] = container
  const pending = [], rendered = [], locations = []
  const models = {selected:'model:6s',options:[{value:'model:6s',label:'6S',count:1},{value:'model:7p',label:'7P',count:1}]}
  let helpers
  const state = {searchSourceGroup:'release_note',searchReleaseCategory:'all',searchPage:1,activeProjectId:1,searchRequest:0,searchComparison:[]}
  const context = {state, categoryLabels, escapeAttribute:escape, escapeHtml:escape,
    document, window:{clearTimeout(){}}, AbortController,
    renderSearchFilters(){}, selectedSearchSources:()=>['release'], searchTaskParams:()=>({}),
    restoreSearchComparison:()=>[], saveSearchComparison(){}, syncLocation(){locations.push(state.searchSourceGroup + '/' + state.searchReleaseCategory)},
    projectPath:p=>p, api:(path, options)=>new Promise((resolve,reject)=>pending.push({path,options,resolve,reject})),
    renderUnifiedSearch:result=>{rendered.push(result); container.innerHTML='RESULT '+result.id; helpers.restoreTaxonomyFocus(container)},
    searchIndexStatusLabel:()=>'', showNotice(){}
  }
  helpers = funcs(['searchTaxonomyMarkup','restoreTaxonomyFocus','focusedTaxonomyControl','searchUnified','selectSearchTaxonomy'], context)
  const {searchUnified, selectSearchTaxonomy} = helpers
  const first = searchUnified()
  pending[0].resolve({id:'initial',index:{},taxonomy_counts:{sources:{release_note:6,whitepaper:11,other:2},release_categories:{function:3}},whitepaper_models:models})
  await first
  assert.equal(selectSearchTaxonomy('source','whitepaper'), true)
  assert.match(container.innerHTML,/data-search-source-group="whitepaper" aria-selected="true"/)
  assert.match(container.innerHTML,/正在搜索/); assert.doesNotMatch(container.innerHTML,/RESULT initial/)
  assert.equal(selectSearchTaxonomy('source','release_note'), true)
  assert.equal(selectSearchTaxonomy('category','function'), true)
  assert.equal(pending[1].options.signal.aborted,true)
  assert.equal(pending[2].options.signal.aborted,true)
  assert.match(container.innerHTML,/data-search-release-category="function" aria-selected="true"/)
  pending[3].resolve({id:'latest',index:{},taxonomy_counts:{sources:{release_note:6},release_categories:{function:3}}})
  await new Promise(resolve=>setImmediate(resolve))
  pending[1].resolve({id:'stale',index:{}})
  pending[2].resolve({id:'stale2',index:{}})
  await new Promise(resolve=>setImmediate(resolve))
  assert.deepEqual(rendered.map(r=>r.id),['initial','latest'])
  assert.equal(container.innerHTML,'RESULT latest')
  assert.match(document.activeElement.selector,/data-search-release-category="function"/)
  selectSearchTaxonomy('source','whitepaper')
  pending[4].reject(new Error('network failure'))
  await new Promise(resolve=>setImmediate(resolve))
  assert.match(container.innerHTML,/搜索失败：network failure/)
  assert.match(container.innerHTML,/data-search-source-group="whitepaper" aria-selected="true"/)
  assert.doesNotMatch(container.innerHTML,/RESULT latest/)
  assert.match(document.activeElement.selector,/data-search-source-group="whitepaper"/)
  assert.equal(locations.at(-1),'whitepaper/function')
  selectSearchTaxonomy('source','release_note')
  pending[5].resolve({id:'retried',index:{},taxonomy_counts:{sources:{release_note:6},release_categories:{function:3}},whitepaper_models:models})
  await new Promise(resolve=>setImmediate(resolve))
  assert.equal(container.innerHTML,'RESULT retried')
  assert.ok(container.focused.some(selector=>selector.includes('whitepaper')))
  selectSearchTaxonomy('source','whitepaper')
  selectSearchTaxonomy('model','model:7p')
  assert.equal(pending[6].options.signal.aborted,true)
  assert.equal(new URLSearchParams(pending[7].path.split('?')[1]).get('whitepaper_model'),'model:7p')
  assert.match(container.innerHTML,/value="model:7p" selected/)
  pending[7].resolve({id:'7p',index:{},taxonomy_counts:{sources:{whitepaper:11}},whitepaper_models:{...models,selected:'model:7p'}})
  await new Promise(resolve=>setImmediate(resolve))
  pending[6].resolve({id:'stale-6s',index:{},whitepaper_models:models})
  await new Promise(resolve=>setImmediate(resolve))
  assert.equal(container.innerHTML,'RESULT 7p'); assert.equal(state.searchWhitepaperModel,'model:7p')
  assert.match(document.activeElement.selector,/data-search-whitepaper-model/)
  selectSearchTaxonomy('model','model:6s')
  container.querySelector('[data-search-source-group="whitepaper"]').focus()
  pending[8].resolve({id:'6s',index:{},taxonomy_counts:{sources:{whitepaper:11}},whitepaper_models:models})
  await new Promise(resolve=>setImmediate(resolve))
  assert.equal(container.innerHTML,'RESULT 6s')
  assert.match(document.activeElement.selector,/data-search-source-group="whitepaper"/)
})

test('whitepaper model selector uses server options and changes only whitepaper model state', () => {
  const state = {searchSourceGroup:'whitepaper', searchReleaseCategory:'function', searchPage:3,
    searchWhitepaperModel:'model:6s', activeProjectId:4, searchComparison:[{preview_id:'x'}],
    searchWhitepaperOptions:[{value:'model:6s',label:'6S',count:1}, {value:'model:7p妇产版',label:'7P妇产版',count:2}]}
  let calls = 0
  const {searchTaxonomyMarkup,selectSearchTaxonomy} = funcs(['searchTaxonomyMarkup','selectSearchTaxonomy'], {
    state,categoryLabels,escapeAttribute:escape,escapeHtml:escape,searchUnified:()=>{calls++; return Promise.resolve()},showNotice(){}
  })
  const html = searchTaxonomyMarkup({taxonomy_counts:{sources:{whitepaper:3}}})
  assert.match(html,/aria-label="白皮书型号"/)
  assert.match(html, /value="model:6s" selected>6S（1）/)
  assert.match(html, /7P妇产版（2）/)
  assert.equal(selectSearchTaxonomy('model','model:7p妇产版'),true)
  assert.equal(state.searchWhitepaperModel,'model:7p妇产版')
  assert.equal(state.searchPage,1); assert.equal(state.activeProjectId,4)
  assert.equal(state.searchReleaseCategory,'function'); assert.equal(state.searchComparison.length,1)
  assert.equal(selectSearchTaxonomy('model','model:unknown'),false); assert.equal(calls,1)
})


test('model selector change listener is connected to the shared taxonomy action', () => {
  let listener, selection
  const document = {querySelector:()=>({addEventListener:(name, callback)=>{if(name === 'change') listener = callback}})}
  const start = source.indexOf("document.querySelector('#global-search-panel').addEventListener('change'")
  const end = source.indexOf("document.querySelector('#global-search-panel').addEventListener('keydown'", start)
  new Function('document','selectSearchTaxonomy', source.slice(start,end))(document,(kind,value)=>{selection=[kind,value]})
  listener({target:{closest:()=>({value:'model:7p'})}})
  assert.deepEqual(selection,['model','model:7p'])
})


test('loading completion keeps focus on the taxonomy control the user moved to', () => {
  const container = {contains: element => element.owner === container}
  const active = {owner:container, value:'model:6s', hasAttribute:name=>name==='data-search-whitepaper-model'}
  const document = {activeElement:active}
  const {focusedTaxonomyControl} = funcs(['focusedTaxonomyControl'], {document})
  assert.deepEqual(focusedTaxonomyControl(container),{kind:'model',value:'model:6s'})
  document.activeElement = {owner:container,hasAttribute:name=>name==='data-search-source-group',getAttribute:()=> 'whitepaper'}
  assert.deepEqual(focusedTaxonomyControl(container),{kind:'source',value:'whitepaper'})
  document.activeElement = {owner:null,hasAttribute:()=>true}
  assert.equal(focusedTaxonomyControl(container),null)
})

test('automatic model changes with search context while an explicit choice persists', async () => {
  const controls = {'#release-search':{value:'first'}, '#release-search-scope':{value:'current'},
    '#release-search-market':{value:''}, '#release-search-model':{value:''}, '#release-search-country':{value:''},
    '#release-search-verification':{value:''}, '#release-search-current':{checked:false}, '#search-index-status':{textContent:''}}
  const container = {innerHTML:'',contains:()=>false,querySelector:()=>null}
  controls['#release-search-result'] = container
  const state = {searchSourceGroup:'whitepaper', searchReleaseCategory:'all', searchWhitepaperSelectionMode:'auto',
    searchWhitepaperModel:'',searchRequest:0,searchPage:1,activeProjectId:1,searchComparison:[]}
  const requests = []
  let finishLinkedRequest
  const context = {state, categoryLabels, escapeAttribute:escape,escapeHtml:escape,
    document:{querySelector:s=>controls[s],activeElement:null}, window:{clearTimeout(){}}, AbortController,
    renderSearchFilters(){},selectedSearchSources:()=>['controlled'],searchTaskParams:()=>({}),
    restoreSearchComparison:()=>[], saveSearchComparison(){}, syncLocation(){}, projectPath:p=>p,
    api:async path=>{const params = new URLSearchParams(path.split('?')[1]); requests.push(params); const selected=params.get('whitepaper_model') || (params.get('q')==='first'?'model:6s':'model:7p'); const result={index:{},taxonomy_counts:{},whitepaper_models:{selected,options:[{value:selected,label:selected,count:1}]}}; if(params.get('q')==='linked-pending') return new Promise(resolve=>{finishLinkedRequest=()=>resolve(result)}); return result},
    renderUnifiedSearch(){},searchIndexStatusLabel:()=>'',showNotice(){}
  }
  const {searchUnified,restoreSearchWhitepaperSelection} = funcs(['searchTaxonomyMarkup','restoreTaxonomyFocus','focusedTaxonomyControl','restoreSearchWhitepaperSelection','searchUnified'], context)
  await searchUnified('first'); assert.equal(state.searchWhitepaperModel,'model:6s')
  await searchUnified('second'); assert.equal(requests[1].get('whitepaper_model'),''); assert.equal(state.searchWhitepaperModel,'model:7p')
  state.searchWhitepaperSelectionMode='selected'
  await searchUnified('third'); assert.equal(requests[2].get('whitepaper_model'),'model:7p')
  restoreSearchWhitepaperSelection({whitepaper_model:'model:6s',whitepaper_model_mode:'auto'})
  await searchUnified('linked-query'); assert.equal(requests[3].get('whitepaper_model'),'model:6s')
  assert.match(source, /restoreSearchWhitepaperSelection\(params\)/)
  restoreSearchWhitepaperSelection({whitepaper_model:'model:6s',whitepaper_model_mode:'auto'})
  const pending = searchUnified('linked-pending')
  await searchUnified('next-before-link-completes')
  assert.equal(requests[5].get('whitepaper_model'),'')
  finishLinkedRequest(); await pending
  assert.equal(state.searchWhitepaperModel,'model:7p')
})
