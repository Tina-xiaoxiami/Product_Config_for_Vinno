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
const names = ['preferredSearchEvidence', 'searchEvidenceActions', 'normalizeComparisonText', 'searchEvidenceGroupKey', 'groupSearchResults', 'searchGroupItemSummary', 'renderSearchGroups', 'searchComparisonButton', 'compactSearchCard']
const helpers = functions(names, context)

test('groups by explicit project/version/range and exact document identity without conflating unknown scope', () => {
  const first = release(), snapshot = release({evidence_kind:'source_snapshot', preview_id:'release:source:12', verification:'unverified'})
  const word = controlled(), pdf = controlled({file_format:'pdf', preview_id:'controlled:18:pdf'})
  const items = [first, word, snapshot, pdf, release({project_id:2}), release({scope:'ULTIMUS G2 · 海外 · 1.51.36'}), controlled({document_version_id:19, scope:'适用范围未登记'}), controlled({document_version_id:20, scope:'适用范围未登记'})]
  const groups = helpers.groupSearchResults(items)
  assert.deepEqual(groups.map(group => group.items.length), [2, 2, 1, 1, 1, 1])
  assert.equal(groups[0].items[0], first); assert.equal(groups[0].items[1], snapshot)
  assert.equal(groups[1].items[0], word); assert.equal(groups[1].items[1], pdf)
  assert.notEqual(helpers.searchEvidenceGroupKey(word), helpers.searchEvidenceGroupKey(release()))
})

test('multi-version historical files and unsupported identity never join a version group', () => {
  for (const item of [
    controlled({ source_label:'历史补充资料', file_format:'xlsx', title:'多版本历史记录' }),
    controlled({ matched_versions:['1.51.36','1.51.90'] }),
    controlled({ version_matches:[{version:'1.51.36'},{version:'1.51.90'}] }),
    release({project_id:null}), release({evidence_kind:'current_description'}), release({version:'1.51'})
  ]) assert.equal(helpers.searchEvidenceGroupKey(item), null)
})

test('group shows each summary, format and independent status while retaining every card and action', () => {
  state.searchComparisonOptions = []
  const word = controlled(), pdf = controlled({file_format:'pdf', preview_id:'controlled:18:pdf', verification:'expired', is_stale:true, matched_text:'不同限制内容'})
  const html = helpers.renderSearchGroups([word,pdf], item => helpers.compactSearchCard(item, {query:'原文'}, `<button data-search-result-preview="${escape(item.preview_id)}" data-search-result-locator="${escape(item.locator)}">原文</button>`, '', []))
  assert.match(html, /本页 2 条独立证据/); assert.match(html, /Word/); assert.match(html, /PDF/)
  assert.match(html, /来源 1/); assert.match(html, /来源 2/); assert.match(html, /未复核/); assert.match(html, /已过复核期限/); assert.match(html, /索引待更新/); assert.match(html, /当前节选不同，展开核对/); assert.match(html, /不同限制内容/)
  assert.match(html, /data-search-result-preview="controlled:18:docx"/); assert.match(html, /data-search-result-preview="controlled:18:pdf"/)
  assert.match(html, /data-search-result-locator="段落 83"/); assert.match(html, /data-search-compare-add/)
  const visibleSummary = html.slice(html.indexOf('<ul class="search-group-summaries">'), html.indexOf('</ul>'))
  assert.match(visibleSummary, /data-search-result-preview="controlled:18:docx"/)
  assert.match(visibleSummary, /data-search-result-refresh/)
  assert.match(html, /<details class="search-group-details">/); assert.doesNotMatch(html, /<details class="search-group-details" open/)
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

test('both result layouts use identical groups, preserve source actions and original pagination counts', () => {
  const word = controlled({ version_matches:[{version:'1.51.36',locator:'段落 83',text:'第一处',query:'导出'},{version:'1.51.36',locator:'段落 84',text:'第二处',query:'导出'}] })
  const pdf = controlled({file_format:'pdf', preview_id:'controlled:18:pdf', locator:'第8页'})
  for (const embedded of [true, false]) {
    const container = { innerHTML: '' }, state = { searchComparison: [], searchComparisonOptions: [] }
    const context = { ...globalContext(), state, workbenchConfig:{embedded}, document:{querySelector:()=>container},
      SEARCH_SOURCE_LABELS:{}, renderSavedSearches(){}, renderSearchComparisonTray(){}, compactSearchSourceNotice:()=>'', compactSearchAnswer:()=>'',
      searchTaskSummary:()=>'', searchCoverageMarkup:()=>'', searchEmptyMarkup:()=>'', activeProject:()=>({name:'ULTIMUS G2'}), buildHash:()=>'' }
    const all = functions([...names, 'searchTaxonomyMarkup', 'renderUnifiedSearch', 'restoreTaxonomyFocus'], {...context, categoryLabels:{function:'功能',source:'Release Note 原文'}})
    // The renderer resolves its helper names lexically from this same source bundle.
    all.renderUnifiedSearch({results:[word,pdf],query:'导出',source_errors:{},total:81,page_size:40,page:1,scope:'current',task:'search'})
    assert.match(container.innerHTML, /本页 2 条独立证据/)
    assert.match(container.innerHTML, /仅对本页证据分组/)
    assert.match(container.innerHTML, /共 81 条/)
    assert.match(container.innerHTML, /data-search-result-locator="段落 83"/)
    assert.match(container.innerHTML, /data-search-result-locator="段落 84"/)
    assert.match(container.innerHTML, /data-search-result-preview="controlled:18:pdf"/)
    assert.equal(state.searchComparisonOptions.length, 3)
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
