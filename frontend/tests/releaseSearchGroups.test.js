import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../../backend/tracker/static/app.js', import.meta.url), 'utf8')
function functions(names, context = {}) {
  const bodies = names.map(name => {
    const start = source.indexOf(`function ${name}(`)
    assert.ok(start >= 0, name)
    const next = source.slice(start + 1).search(/\n(?:async )?function /)
    return source.slice(start, next < 0 ? undefined : start + 1 + next)
  })
  return new Function(...Object.keys(context), `${bodies.join('\n')}; return { ${names.join(',')} }`)(...Object.values(context))
}
const escape = text => String(text ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;')
const state = { searchComparison: [], searchComparisonOptions: [] }
const release = (overrides = {}) => ({ source_type: 'release', source_label: '版本与功能', project_id: 1, scope: 'ULTIMUS G2 · 1.51.36', version: '1.51.36', evidence_kind: 'version_record', title: '记录', matched_text: '中文原文', verification: 'approved', preview_id: 'release:change:603', locator: '中文记录', ...overrides })
const controlled = (overrides = {}) => ({ source_type: 'controlled', source_label: '受控资料', document_version_id: 18, scope: '国内 · 机型范围未登记', version: '1.51.36', file_format: 'docx', title: 'ULTIMUS Release Note', matched_text: '文件原文', verification: 'unverified', preview_id: 'controlled:18:docx', locator: '段落 83', ...overrides })
const context = { escapeHtml: escape, escapeAttribute: escape, highlightSearchText: escape,
  verificationLabel: value => ({approved:'已确认', unverified:'未复核', expired:'已过复核期限'})[value] || value,
  fileFormatLabel: value => ({docx:'Word', pdf:'PDF'})[value] || '', searchEvidenceLabel: value => ({version_record:'当时版本记录', source_snapshot:'Release Note 原文提及'})[value] || value,
  searchQueryOrigin: () => '', state }
const names = ['preferredSearchEvidence', 'searchEvidenceActions', 'normalizeComparisonText', 'searchEvidenceGroupKey', 'groupSearchResults', 'searchGroupItemSummary', 'searchConfigurationSummary', 'renderSearchGroups', 'resultGroupCoversDetail', 'searchComparisonButton', 'compactSearchCard']
const helpers = functions(names, context)

test('only server-proven identical chapters group; ordinary same-version evidence stays separate', () => {
  const first = release(), snapshot = release({evidence_kind:'source_snapshot',preview_id:'release:source:12',verification:'unverified'})
  const word = controlled(), pdf = controlled({file_format:'pdf',preview_id:'controlled:18:pdf'})
  assert.deepEqual(helpers.groupSearchResults([first,word,snapshot,pdf]).map(group => group.items.length),[1,1,1,1])
  const id = 'a'.repeat(64), detail = {source_id:'release:source:12',locator:'原文行 123',title:'新增功能',verification:'unverified',excerpt:'完整章节摘要'}
  const proven = [release({chapter_group_id:id,detail_evidence:detail}), release({chapter_group_id:id,detail_evidence:detail,evidence_kind:'source_snapshot'}), controlled({chapter_group_id:id,detail_evidence:{...detail,source_id:'controlled:18:docx'}})]
  assert.deepEqual(helpers.groupSearchResults(proven).map(group=>group.items.length),[3])
  assert.equal(helpers.searchEvidenceGroupKey({...proven[0],is_stale:true}),null)
})

test('multi-version historical files and unsupported identity never join a version group', () => {
  for (const item of [
    controlled({ source_label:'历史补充资料', file_format:'xlsx', title:'多版本历史记录' }),
    controlled({ matched_versions:['1.51.36','1.51.90'] }),
    controlled({ version_matches:[{version:'1.51.36'},{version:'1.51.90'}] }),
    release({project_id:null}), release({evidence_kind:'current_description'}), release({version:'1.51'})
  ]) assert.equal(helpers.searchEvidenceGroupKey(item), null)
})

test('one verified chapter card keeps each independent source and original actions folded', () => {
  state.searchComparisonOptions = []
  const id='b'.repeat(64), detail={source_id:'release:source:12',locator:'原文行 123',title:'新增子宫畸形分类',excerpt:'唯一章节摘要',verification:'unverified'}
  const record=release({chapter_group_id:id,detail_evidence:detail,matched_text:'已确认变更记录'})
  const snapshot=release({chapter_group_id:id,detail_evidence:detail,evidence_kind:'source_snapshot',verification:'unverified',preview_id:'release:source:12',locator:'原文行 123'})
  const word=controlled({chapter_group_id:id,detail_evidence:{...detail,source_id:'controlled:18:docx',locator:'段落 83'},matched_text:'Word 原命中'})
  const html=helpers.renderSearchGroups([word,record,snapshot],()=>{throw Error('unexpected ungrouped card')},'子宫')
  const folded=html.indexOf('<details class="search-group-details">')
  assert.ok(folded>0); const visible=html.slice(0,folded), sources=html.slice(folded)
  assert.equal((visible.match(/唯一章节摘要/g)||[]).length,1)
  assert.equal((visible.match(/查看完整功能描述/g)||[]).length,1)
  assert.match(visible,/新增子宫畸形分类/); assert.match(visible,/未复核/)
  assert.doesNotMatch(visible,/已确认变更记录|国内 · 机型范围未登记|Word 原命中/)
  assert.match(sources,/来源依据（3）/); assert.match(sources,/已确认/); assert.match(sources,/未复核/)
  assert.match(sources,/国内 · 机型范围未登记/); assert.match(sources,/当时版本记录/); assert.match(sources,/Release Note 原文提及/); assert.match(sources,/中文记录/); assert.match(sources,/原文行 123/)
  for (const id of ['controlled:18:docx','release:change:603','release:source:12']) assert.ok(sources.includes(id))
  assert.equal(state.searchComparisonOptions.length,3)
  assert.deepEqual(state.searchComparisonOptions.map(item=>item.preview_id),['controlled:18:docx','release:change:603','release:source:12'])
})

test('text equality ignores only whitespace and preserves numbers, case and punctuation', () => {
  const { comparisonTextStatus, comparisonNotice } = functions(['readableSearchEvidence','normalizeComparisonText','normalizeChapterComparisonText','comparisonTextStatus','comparisonNotice'])
  const entry = text => ({item:{locator:'p1'}, preview:{chunks:[{locator:'p1',text}]}})
  assert.equal(comparisonTextStatus([entry('A  10\nmm'), entry('A 10 mm')]), 'same')
  assert.doesNotMatch(comparisonNotice([entry('A 10'), entry('A\n10')]), /差异不自动/)
  for (const different of ['a 10', 'A 11', 'A 10+', 'A 10。']) assert.equal(comparisonTextStatus([entry('A 10'), entry(different)]), 'different')
  assert.equal(comparisonTextStatus([entry(''), entry('')]), 'incomplete')
  assert.equal(comparisonTextStatus([entry('A'), {item:{locator:'p2'},error:'missing'}]), 'incomplete')
})

test('group summary reflects current comparison selections while collapsed', () => {
  const label = {textContent:''}, row = {dataset:{groupPreview:'controlled:18:docx'},querySelector:()=>label}
  const tray = {innerHTML:''}
  const document = {querySelector: () => tray, querySelectorAll: selector => selector === '[data-group-preview]' ? [row] : []}
  state.searchComparison = [{preview_id:'controlled:18:docx',title:'a',scope:'x',version:'1.51.36'}]
  const { renderSearchComparisonTray } = functions(['renderSearchComparisonTray'], {...context, document})
  renderSearchComparisonTray(); assert.match(label.textContent, /已选 1 处对照/)
  state.searchComparison = []; renderSearchComparisonTray(); assert.equal(label.textContent, '')
})

test('both result layouts show page card/source counts and preserve original pagination', () => {
  const id='c'.repeat(64), detail={source_id:'release:source:12',locator:'原文行 123',title:'新增功能',excerpt:'一份章节摘要',verification:'unverified'}
  const record=release({chapter_group_id:id,detail_evidence:detail})
  const snapshot=release({chapter_group_id:id,detail_evidence:detail,evidence_kind:'source_snapshot',verification:'unverified',preview_id:'release:source:12',locator:'原文行 123'})
  const word=controlled({chapter_group_id:id,detail_evidence:{...detail,source_id:'controlled:18:docx',locator:'段落 83'},version_matches:[{version:'1.51.36',locator:'段落 83',text:'第一处',query:'导出'},{version:'1.51.36',locator:'段落 84',text:'第二处',query:'导出'}]})
  for (const embedded of [true, false]) {
    const container={innerHTML:''}, state={searchComparison:[],searchComparisonOptions:[],searchSourceGroup:'release_note'}
    const context={...globalContext(),state,workbenchConfig:{embedded},document:{querySelector:()=>container},SEARCH_SOURCE_LABELS:{},renderSavedSearches(){},renderSearchComparisonTray(){},compactSearchSourceNotice:()=>'',compactSearchAnswer:()=>'',searchTaskSummary:()=>'',searchCoverageMarkup:()=>'',searchEmptyMarkup:()=>'',activeProject:()=>({name:'ULTIMUS G2'}),buildHash:()=>''}
    const all=functions([...names,'searchTaxonomyMarkup','renderUnifiedSearch','restoreTaxonomyFocus'],{...context,categoryLabels:{function:'功能'}})
    all.renderUnifiedSearch({results:[word,record,snapshot],query:'导出',source_errors:{},total:81,page_size:40,page:1,scope:'current',task:'search'})
    assert.match(container.innerHTML,/本页 <strong>1<\/strong> 项内容 · 3 条来源/)
    assert.match(container.innerHTML,/仅合并本页同章来源/); assert.match(container.innerHTML,/共 81 条/)
    assert.match(container.innerHTML,/data-search-result-locator="段落 83"/); assert.match(container.innerHTML,/data-search-result-locator="段落 84"/)
    assert.match(container.innerHTML,/第一处/); assert.match(container.innerHTML,/第二处/)
    assert.equal(state.searchComparisonOptions.length,4)
  }
})

function globalContext() {
  return { ...context, searchQueryOrigin:()=>'' }
}

test('copied comparison retains all evidence and varies the warning according to original text', () => {
  const { buildComparisonCitation } = functions(['readableSearchEvidence','normalizeComparisonText','normalizeChapterComparisonText','comparisonTextStatus','comparisonNotice','buildComparisonCitation'], {formatEvidenceCitation: (preview, item) => `${item.locator}: ${preview.chunks[0].text}`})
  const entry = (locator, text) => ({item:{locator},preview:{chunks:[{locator,text}]}})
  const same = buildComparisonCitation([entry('p1', 'A 10'), entry('p2', 'A\n10')], 'url')
  assert.match(same, /所选原文一致/); assert.match(same, /p1: A 10/); assert.match(same, /p2: A\n10/)
  const changed = buildComparisonCitation([entry('p1','A 10'),entry('p2','A 11')], 'url')
  assert.match(changed, /差异不自动代表新增能力/)
  assert.throws(() => buildComparisonCitation([entry('p1','A'),{item:{locator:'p2'},error:'bad'}], 'url'))
})

test('both integrated and standalone result renderers show whitepaper chapter instead of directory excerpt', () => {
  const item = controlled({source_label:'白皮书', file_format:'pdf', preview_id:'controlled:35:pdf', locator:'第 3 页', matched_text:'目录 ......9', detail_evidence:{source_id:'controlled:35:pdf',locator:'第 13 页',verification:'unverified',excerpt:'5.63 子宫畸形分类\n支持 ESHRE 和 ARSM。'}})
  for (const embedded of [true,false]) {
    const container = {innerHTML:''}, state={searchComparison:[],searchComparisonOptions:[],searchSourceGroup:'whitepaper',searchReleaseCategory:'all'}
    const context = {...globalContext(),state,workbenchConfig:{embedded},document:{querySelector:()=>container},SEARCH_SOURCE_LABELS:{},renderSavedSearches(){},renderSearchComparisonTray(){},compactSearchSourceNotice:()=>'',compactSearchAnswer:()=>'',searchTaskSummary:()=>'',searchCoverageMarkup:()=>'',searchEmptyMarkup:()=>'',activeProject:()=>({name:'V'}),buildHash:()=>''}
    const all=functions([...names,'searchTaxonomyMarkup','renderUnifiedSearch','restoreTaxonomyFocus'],{...context,categoryLabels:{function:'功能'}})
    all.renderUnifiedSearch({results:[item],query:'子宫',source_errors:{},total:1,page_size:40,page:1,scope:'current',task:'search',taxonomy_counts:{sources:{whitepaper:1}}})
    assert.match(container.innerHTML,/支持 ESHRE 和 ARSM/)
    assert.match(container.innerHTML,/查看原命中位置/)
    assert.doesNotMatch(container.innerHTML,/目录 \.\.\.\.\.\.9/)
  }
})

test('earliest conclusion keeps its qualification without duplicating a grouped chapter action', () => {
  const id='d'.repeat(64), detail={source_id:'release:source:12',locator:'原文行 123',title:'功能',excerpt:'正文',verification:'unverified'}
  const record=release({chapter_group_id:id,detail_evidence:detail})
  const snapshot=release({chapter_group_id:id,detail_evidence:detail,evidence_kind:'source_snapshot',preview_id:'release:source:12'})
  const {compactSearchAnswer,groupSearchResults}=functions([...names,'compactSearchAnswer'],context)
  const groups=groupSearchResults([record,snapshot])
  const html=compactSearchAnswer({query:'功能',earliest_records:[record]},groups)
  assert.match(html,/版本库最早记载/); assert.match(html,/不代表首次支持/)
  assert.doesNotMatch(html,/查看完整功能描述/)
  assert.match(compactSearchAnswer({query:'功能',earliest_records:[record]},[]),/查看完整功能描述/)
  const differentRecord = {...record,preview_id:'release:change:999'}
  assert.match(compactSearchAnswer({query:'功能',earliest_records:[differentRecord]},groups),/查看变更依据/)
})


test('a chapter card without a snapshot hit uses the release chapter status, not a controlled document approval', () => {
  const id='e'.repeat(64), detail={source_id:'release:source:12',locator:'原文行 123',title:'功能章节',excerpt:'完整正文',verification:'unverified'}
  const record=release({chapter_group_id:id,detail_evidence:detail})
  const word=controlled({chapter_group_id:id,verification:'approved',detail_evidence:{...detail,source_id:'controlled:18:docx',locator:'段落 83',verification:'approved'}})
  const html=helpers.renderSearchGroups([word,record],()=>'', '功能')
  const main=html.slice(0,html.indexOf('<details'))
  assert.match(main,/未复核/); assert.doesNotMatch(main,/已确认/)
  assert.match(main,/data-search-result-preview="release:source:12"/)
  assert.match(html.slice(html.indexOf('<details')),/已确认/)
})

test('configuration category displays configuration records and original evidence, not feature description', () => {
  const detail={source_id:'release:source:16',locator:'原文行 123',title:'功能全文',excerpt:'完整功能描述',verification:'unverified'}
  const config='子宫畸形分类 | 6000363 | V30894 | 全系列 | 妇产机标配，其他机型选配'
  const items=[release({preview_id:'release:table:4',locator:'表格记录',category:'config',title:'子宫畸形分类',detail_evidence:detail,config_evidence:config}),
    release({preview_id:'release:change:8',category:'config',title:'子宫畸形分类（V30894）',detail_evidence:detail,config_evidence:config+'\n更新后，各功能支持的探头/应用如下：'})]
  for (const embedded of [true,false]) {
    const container={innerHTML:''},state={searchComparison:[],searchComparisonOptions:[],searchSourceGroup:'release_note',searchReleaseCategory:'config'}
    const ctx={...globalContext(),state,workbenchConfig:{embedded},document:{querySelector:()=>container},SEARCH_SOURCE_LABELS:{},renderSavedSearches(){},renderSearchComparisonTray(){},compactSearchSourceNotice:()=>'',searchTaskSummary:()=>'',searchCoverageMarkup:()=>'',searchEmptyMarkup:()=>'',activeProject:()=>({name:'V'}),buildHash:()=>''}
    const all=functions([...names,'compactSearchAnswer','searchTaxonomyMarkup','renderUnifiedSearch','restoreTaxonomyFocus'],{...ctx,categoryLabels:{config:'配置'}})
    all.renderUnifiedSearch({results:items,earliest_records:[items[0]],query:'子宫',source_errors:{},total:2,page_size:40,page:1,scope:'current',task:'search'})
    assert.match(container.innerHTML,/6000363/); assert.match(container.innerHTML,/V30894/)
    assert.match(container.innerHTML,/妇产机标配，其他机型选配/); assert.match(container.innerHTML,/探头\/应用/)
    assert.match(container.innerHTML,/查看配置依据/); assert.doesNotMatch(container.innerHTML,/完整功能描述/)
    assert.doesNotMatch(container.innerHTML,/功能全文|完整功能描述/)
  }
})

test('all-category chapter retains an explicit configuration summary and full source details', () => {
  const id='f'.repeat(64), detail={source_id:'release:source:12',locator:'原文行 123',title:'功能章节',excerpt:'功能正文',verification:'unverified'}
  const state={searchComparison:[],searchComparisonOptions:[],searchReleaseCategory:'all'}
  const all=functions(names,{...context,state})
  const table=release({chapter_group_id:id,preview_id:'release:table:4',locator:'表格记录',category:'config',detail_evidence:detail,
    config_evidence:'子宫畸形分类 | 6000363 | V30894 | 全系列 | 妇产机标配，其他机型选配'})
  const change=release({chapter_group_id:id,preview_id:'release:change:8',category:'config',detail_evidence:detail,
    config_evidence:'IPN：6000363\nV30894\n妇产机标配，其他机型选配\n更新后各功能支持的探头/应用如下：'})
  const html=all.renderSearchGroups([table,change],()=>'', '子宫')
  const first=html.slice(0,html.indexOf('<details'))
  assert.match(first,/配置变更/); assert.match(first,/6000363/); assert.match(first,/妇产机标配，其他机型选配/)
  assert.match(first,/更新后各功能支持的探头\/应用如下/); assert.match(html,/class="search-config-evidence"/)
  assert.match(html,/更新后各功能支持的探头\/应用如下/)
})


test('configuration fields are never lost through substring matching and function cards do not add config text', () => {
  const state={searchComparison:[],searchComparisonOptions:[],searchReleaseCategory:'all'}
  const all=functions(names,{...context,state})
  const text=all.searchConfigurationSummary([{config_evidence:'不支持6S'}, {config_evidence:'适用机型/探头：6S'}], '')
  assert.match(text,/不支持6S/); assert.match(text,/适用机型\/探头：6S/)
  state.searchReleaseCategory='function'
  const row=all.searchGroupItemSummary(release({config_evidence:'配置额外文本',detail_evidence:{excerpt:'功能章节'},
    version_matches:[{version:'1.51.36',locator:'中文记录',text:'配置额外文本'}, {version:'1.51.36',locator:'其他功能位置',text:'其他功能正文'}]}),'')
  assert.match(row,/功能章节/); assert.doesNotMatch(row,/配置额外文本/); assert.match(row,/其他功能正文/)
  assert.match(row,/其他功能位置/)

})


test('all summary deduplicates identical labeled fields and preserves actual differing constraints', () => {
  const {searchConfigurationSummary}=functions(['searchConfigurationSummary'],context)
  const items=[{preview_id:'release:table:1',config_evidence:'子宫畸形分类 | 6000363 | V30894 | 全系列 | 妇产机标配，其他机型选配\nIPN：6000363\n适用机型/探头：全系列\n变更说明：妇产机标配，其他机型选配'},
    {preview_id:'release:change:2',config_evidence:'子宫畸形分类（V30894）\nIPN：6000363\n适用机型/探头：全系列\n变更说明：妇产机标配，其他机型选配\n更新后，各功能支持的探头/应用如下：'},
    {preview_id:'controlled:1:pdf',config_evidence:'子宫畸形分类 6000363 V30894 全系列 妇产机标配，其他机型选配'}]
  const one=searchConfigurationSummary(items,'')
  assert.equal((one.match(/6000363/g)||[]).length,1); assert.doesNotMatch(one,/更新后，各功能支持/)
  const changed=searchConfigurationSummary([...items,{config_evidence:'适用机型/探头：6S\n变更说明：不支持6S'}],'')
  assert.match(changed,/适用机型\/探头：6S/); assert.match(changed,/变更说明：不支持6S/)
})


test('configuration row deduplication preserves field and word boundaries', () => {
  const {searchConfigurationSummary}=functions(['searchConfigurationSummary'],context)
  const items=[{preview_id:'release:table:1',config_evidence:'型号 | AB | C | 全系列 | 选配'},
    {preview_id:'controlled:1:pdf',config_evidence:'型号 A BC 全系列 选配'}]
  assert.match(searchConfigurationSummary(items,''),/型号 A BC 全系列 选配/)
})
