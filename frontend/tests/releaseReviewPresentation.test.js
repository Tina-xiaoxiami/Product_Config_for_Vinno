import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
const source=readFileSync(new URL('../../backend/tracker/static/app.js',import.meta.url),'utf8')
function extract(name,context={}) {
  const start=source.indexOf(`function ${name}(`)
  assert.ok(start>=0,name)
  const next=source.slice(start+1).search(/\n(?:async )?function /)
  const body=source.slice(start,next<0?undefined:start+1+next)
  return new Function(...Object.keys(context),`${body}; return ${name}`)(...Object.values(context))
}
const escape=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;')

test('empty review hides only navigation and filters; filtered-empty keeps controls',()=>{
  const nav={hidden:false}, filters={hidden:false}, page={classList:{toggle(_name,value){this.empty=value}}}
  const summary={textContent:''}, list={innerHTML:''}
  const controls={'.candidate-version-navigation':nav,'.candidate-filter-panel':filters,'#candidate-version-page':page,'#candidate-filter-summary':summary,'#candidate-list':list}
  const state={candidates:[],activeCandidateVersion:null,activeCandidateCategory:'all',reviewStage:'confirm'}
  const context={state,document:{querySelector:s=>controls[s]},candidateVersions:()=>state.candidates.map(x=>x.version),
    renderCandidateVersionTabs(){},renderCandidateCategoryTabs(){},filteredCandidates:()=>[],
    currentVersionCandidates:()=>state.candidates,ensureCandidateRecommendations(){},renderCandidateHierarchy:()=>'',renderReviewOverview(){}}
  const render=extract('renderCandidateReview',context)
  render(); assert.equal(nav.hidden,true); assert.equal(filters.hidden,true); assert.equal(page.classList.empty,true)
  assert.match(list.innerHTML,/暂无待审核记录/)
  state.candidates=[{version:'1.2.3',category:'function'}]; render()
  assert.equal(nav.hidden,true); assert.equal(filters.hidden,false); assert.equal(page.classList.empty,false)
  assert.match(list.innerHTML,/当前筛选条件下没有待审核记录/)
})

test('PDF displays original page first; auxiliary content is folded and warning remains visible',()=>{
  const render=extract('searchPdfPreviewMarkup',{escapeAttribute:escape})
  const html=render('/file#page=13','Doc','<p>命中正文</p>','<p role="alert">位置不可用</p>')
  assert.ok(html.indexOf('<iframe')<html.indexOf('<details'))
  assert.match(html,/<details class="search-pdf-auxiliary"><summary>命中与章节内容/)
  assert.doesNotMatch(html,/<details[^>]*open/)
  assert.ok(html.indexOf('位置不可用')<html.indexOf('<details'))
  assert.match(render('/file','<script>',''),/&lt;script&gt;/)
})


test('PDF navigation opens the selected page, except a proven directory redirect',()=>{
  const page=extract('searchPdfPageLocator')
  const preview={locator_status:'exact',section:{complete:true,locator:'第 10 页'}}
  assert.equal(page(preview,'第 12 页','第 12 页'),'第 12 页')
  assert.equal(page({...preview,locator_status:'toc_redirect'},'第 3 页','第 3 页'),'第 10 页')
  assert.equal(page({...preview,locator_status:'query'},'第 3 页',''),'第 10 页')
})
