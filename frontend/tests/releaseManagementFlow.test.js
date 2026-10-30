import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
const source = readFileSync(new URL('../../backend/tracker/static/app.js', import.meta.url), 'utf8')
const escape = value => String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;')
function extract(name, context = {}) {
  const start = source.indexOf(`function ${name}(`)
  assert.ok(start >= 0, name)
  const next = source.slice(start + 1).search(/\n(?:async )?function /)
  return new Function(...Object.keys(context), `${source.slice(start, next < 0 ? undefined : start + 1 + next)}; return ${name}`)(...Object.values(context))
}

test('概览区分本次新增与历史待确认，目录和下一步明确可见', () => {
  const overview = extract('reviewOverviewMarkup', {escapeHtml:escape, formatDateTime:value=>value})
  const view = overview({name:'ULTIMUS G2',sources:[{enabled:1,path:'/ReleaseNote'}]},
    [{version:'1.51.90'},{version:'1.51.90'}], [{status:'completed',completed_at:'2026-10-29',stats:{candidates_created:0}}])
  const html = view.source + view.pending
  assert.match(html,/\/ReleaseNote/)
  assert.match(html,/本次新增 0 条/)
  assert.match(html,/待确认总计 2 条/)
  assert.match(html,/data-review-confirm/)
  assert.doesNotMatch(html,/candidate-card|双语质量|全选本版本/)
})

test('空态不显示审核入口，失败同步不会冒充成功且路径转义', () => {
  const overview = extract('reviewOverviewMarkup', {escapeHtml:escape, formatDateTime:value=>value})
  const emptyView = overview({sources:[]},[],[]), empty = emptyView.source + emptyView.pending
  assert.match(empty,/尚未设置发布目录/)
  assert.doesNotMatch(empty,/data-review-confirm/)
  const failedView = overview({sources:[{enabled:1,path:'<unsafe>'}]},[],[{status:'failed',stats:{candidates_created:3}}]), failed = failedView.source + failedView.pending
  assert.match(failed,/同步失败/)
  assert.match(failed,/&lt;unsafe&gt;/)
  assert.doesNotMatch(failed,/本次新增 3 条/)
})

test('只有进入确认步骤才切换列表，返回概览不写业务数据', () => {
  const state = {}, calls=[]
  const setStage = extract('setReviewStage', {state,renderCandidateReview:()=>calls.push('render'),syncLocation:()=>calls.push('url')})
  setStage('confirm');assert.equal(state.reviewStage,'confirm')
  setStage('overview');assert.equal(state.reviewStage,'overview')
  assert.deepEqual(calls,['render','url','render','url'])
})

test('记录默认折叠，原双语内容和操作保留在展开区', () => {
  const render = extract('renderReviewItem', {escapeHtml:escape, categoryLabels:{config:'配置'},renderCandidateCard:()=>'<article>原双语与确认操作</article>'})
  const html = render({title_en:'S1-6PE',category:'config',title_cn:''})
  assert.match(html,/<summary>/);assert.match(html,/S1-6PE/);assert.match(html,/缺中文/)
  assert.match(html,/原双语与确认操作/);assert.doesNotMatch(html,/<details[^>]*\bopen/)
})

test('旧审核定位链接进入确认步骤，默认和概览链接不展开97条', () => {
  const stage = extract('reviewStageFromParams')
  assert.equal(stage({}),'overview')
  assert.equal(stage({version:'1.51.90',category:'config'}),'confirm')
  assert.equal(stage({review_mode:'overview',version:'1.51.90'}),'overview')
  assert.equal(stage({review_mode:'confirm'}),'confirm')
})
