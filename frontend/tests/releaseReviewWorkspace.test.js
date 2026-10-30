import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
const source = readFileSync(new URL('../../backend/tracker/static/release-review.js', import.meta.url), 'utf8')
const esc = value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;')
const helpers = new Function('escapeHtml', 'escapeAttribute', 'scenarioDocumentMarkup', 'scenarioIllustrationsMarkup', 'scenarioPreviewButton', `${source};return {releaseReviewPatch,releaseReviewWorkspaceMarkup,releaseReviewCommit,releaseReviewDraftKey,releaseReviewDraftStore,releaseReviewLeaveGuard,releaseReviewRecoverDraft,releaseReviewDecisions,releaseReviewLogMarkup,releaseReviewRestorePayload}`)(esc, esc,
  (text, additions, image) => `<section class="feature-document-section"><p>${esc(text)}</p>${image}</section>`,
  () => '<section class="feature-image-section"><p>图片</p></section>', () => '<button>原文</button>')

test('工作区突出正文与按版本分组的待核原文，图片不成为可选正文', () => {
  const markup = helpers.releaseReviewWorkspaceMarkup({content:'正文<script>',review:{revision:3,body_revision:1,source_fingerprint:'hash',stale:true},
    unresolved_changes:[{id:'one',version:'1.0',text:'第一个',reason:'原因<script>'},{id:'two',version:'1.0',text:'第二个'}],
    change_log:[{id:'ignored',version:'0.9',text:'旧项',log_status:'ignored',review_action:'ignore'}]}, 'VATT')
  assert.match(markup,/feature-review-main/); assert.match(markup,/feature-review-sidebar/)
  assert.equal((markup.match(/<h5>1.0<\/h5>/g)||[]).length,1)
  assert.match(markup,/data-release-review-include="one"/); assert.match(markup,/data-release-review-ignore="two"/)
  assert.match(markup,/<details><summary>待核对原因/); assert.match(markup,/来源有更新/); assert.match(markup,/已忽略/)
  assert.match(markup,/正文&lt;script&gt;/); assert.match(markup,/原因&lt;script&gt;/)
  assert.match(markup,/<p tabindex="0" data-release-review-paragraph>/)
  assert.match(markup,/<section class="feature-image-section"><p>图片<\/p>/)
})

test('精确段落替换、删除、追加可预览，不允许缺少或重复锚点', () => {
  const before='第一段\n\n第二段'
  assert.deepEqual(helpers.releaseReviewPatch(before,'replace','第二段','$&新段'),{content:'第一段\n\n$&新段',before:'第二段',after:'$&新段'})
  assert.equal(helpers.releaseReviewPatch(before,'delete','第二段').content,'第一段\n\n')
  assert.equal(helpers.releaseReviewPatch(before,'append','','新段').content,'第一段\n\n第二段\n\n新段')
  assert.throws(()=>helpers.releaseReviewPatch(before,'replace','','新段'),/先点击/)
  assert.throws(()=>helpers.releaseReviewPatch('重复\n重复','delete','重复'),/唯一定位/)
  assert.throws(()=>helpers.releaseReviewPatch(before,'replace','不存在','新段'),/唯一定位/)
})

const session = () => ({busy:false,error:'',draft:'我的未保存草稿',context:{query:'VATT',target:'1.2',review:{revision:2,source_fingerprint:'hash'}}})
test('保存发送CAS及决定，成功后才提交界面状态', async () => {
  const state=session(); let sent, accepted
  const result=await helpers.releaseReviewCommit(state,'新正文',[{id:'x',action:'include'}],{
    isCurrent:()=>true,path:p=>`project${p}`,api:async(path,options)=>{sent=[path,JSON.parse(options.body)];return {content:'已保存'}},accept:value=>{accepted=value}})
  assert.equal(sent[1].revision,2); assert.equal(sent[1].source_fingerprint,'hash'); assert.equal(sent[1].q,'VATT')
  assert.deepEqual(sent[1].decisions,[{id:'x',action:'include'}]); assert.equal(accepted,result); assert.equal(state.busy,false)
})
test('保存失败和409保留草稿，不替换正文，允许重试', async () => {
  for(const status of [500,409]) {
    const state=session();let accepted=false
    const result=await helpers.releaseReviewCommit(state,state.draft,[],{isCurrent:()=>true,path:p=>p,api:async()=>{throw Object.assign(Error('离线'),{status})},accept:()=>{accepted=true}})
    assert.equal(result,null);assert.equal(accepted,false);assert.equal(state.draft,'我的未保存草稿');assert.equal(state.busy,false)
    assert.match(state.error,status===409?/重新查询/:/草稿已保留/)
  }
})
test('上下文变化阻止提交和迟到结果覆盖，busy阻止重复保存', async () => {
  let sent=0, accepted=0, current=false
  const state=session(), deps={isCurrent:()=>current,path:p=>p,api:async()=>{sent++;current=false;return {}},accept:()=>accepted++}
  await helpers.releaseReviewCommit(state,'正文',[],deps);assert.equal(sent,0)
  current=true;await helpers.releaseReviewCommit(state,'正文',[],deps);assert.equal(sent,1);assert.equal(accepted,0)
  state.busy=true;current=true;await helpers.releaseReviewCommit(state,'正文',[],deps);assert.equal(sent,1)
})

test('草稿按项目、问题、目标、弹窗类型及条目隔离，存储失败明确返回错误', () => {
  const values = new Map(), storage={getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,value),removeItem:key=>values.delete(key)}
  const store=helpers.releaseReviewDraftStore(storage), ctx={project:1,query:'VATT',target:'1.2'}
  const draft={text:'未提交草稿',operation:'replace',selected:'原段',source_fingerprint:'old',revision:1}
  assert.equal(store.write(ctx,'include','id1',draft).ok,true)
  assert.deepEqual(store.read(ctx,'include','id1').draft,draft)
  for(const [scope,kind,id] of [[{...ctx,project:2},'include','id1'],[{...ctx,query:'other'},'include','id1'],[{...ctx,target:''},'include','id1'],[ctx,'edit','id1'],[ctx,'include','id2']]) assert.equal(store.read(scope,kind,id).draft,null)
  assert.equal(store.clear(ctx,'include','id1').ok,true);assert.equal(store.read(ctx,'include','id1').draft,null)
  const unavailable=helpers.releaseReviewDraftStore({getItem(){throw Error('blocked')},setItem(){throw Error('quota')},removeItem(){throw Error('blocked')}})
  assert.match(unavailable.read(ctx,'edit').error,/暂存不可用/)
  assert.equal(unavailable.write(ctx,'edit','',draft).ok,false)
  assert.equal(unavailable.clear(ctx,'edit').ok,false)
})
test('离开保护允许取消，成功保留草稿才关闭，失败不能虚称可恢复', () => {
  let dismissed=0,preserved=0,discarded=0,warned=0
  const active={session:{busy:false},dirty:()=>true,persist:()=>{preserved++;return true},discard:()=>discarded++,dismiss:()=>dismissed++}
  let options={busy:false,confirm:()=>false,warn:()=>warned++}
  assert.equal(helpers.releaseReviewLeaveGuard(active,options),false);assert.equal(dismissed,0);assert.equal(preserved,0)
  options.confirm=()=>true
  assert.equal(helpers.releaseReviewLeaveGuard(active,options),true);assert.equal(dismissed,1);assert.equal(preserved,1);assert.equal(discarded,0)
  active.session.busy=true;assert.equal(helpers.releaseReviewLeaveGuard(active,options),false);assert.equal(dismissed,1)
  active.session.busy=false;active.persist=()=>false;let count=0;options.confirm=()=>++count===1
  assert.equal(helpers.releaseReviewLeaveGuard(active,options),false);assert.equal(dismissed,1)
  options.confirm=()=>true
  assert.equal(helpers.releaseReviewLeaveGuard(active,options),true);assert.equal(discarded,1);assert.equal(dismissed,2);assert.ok(warned>0)
})
test('刷新后恢复文本，来源变化清除旧段落锚点，正文变化也验证唯一性', () => {
  const draft={text:'409后的手工草稿',operation:'replace',selected:'原段',source_fingerprint:'old',revision:1}
  const ctx={review:{source_fingerprint:'new',revision:2},result:{content:'当前正文\n原段'}}
  const recovered=helpers.releaseReviewRecoverDraft(draft,ctx)
  assert.equal(recovered.text,draft.text);assert.equal(recovered.selected,'');assert.match(recovered.warning,/旧来源/)
  ctx.review.source_fingerprint='old';ctx.result.content='原段\n原段'
  assert.equal(helpers.releaseReviewRecoverDraft(draft,ctx).selected,'')
  ctx.result.content='原段'
  assert.equal(helpers.releaseReviewRecoverDraft(draft,ctx).selected,'原段')
  assert.match(helpers.releaseReviewRecoverDraft(draft,ctx).warning,/新修订/)
})

test('正文与版本更新记录分区，采纳按钮默认不要求更新正文，修订号独立',()=>{
 const calls=[]
 const separate=new Function('escapeHtml','escapeAttribute','scenarioDocumentMarkup','scenarioIllustrationsMarkup','scenarioPreviewButton',`${source};return releaseReviewWorkspaceMarkup`)(esc,esc,(content,additions,image)=>{calls.push(additions);return `<p>${esc(content)}</p>${image}`},()=>'',()=>'<button>原文</button>')
 const markup=separate({content:'主要正文',review:{revision:9,body_revision:2,source_fingerprint:'x'},applied_changes:[{after:'不得自动放正文'}],unresolved_changes:[{id:'pending',version:'1.51.90',text:'新记录'}],change_log:[{id:'log',version:'1.51.80',text:'只属于更新记录',log_status:'recognized'}]},'VATT')
 assert.deepEqual(calls,[[]]);assert.match(markup,/正文修订 2/);assert.doesNotMatch(markup,/正文修订 9/)
 const body=markup.slice(markup.indexOf('class="release-feature-body"'),markup.indexOf('class="release-feature-log"'))
 assert.match(body,/主要正文/);assert.doesNotMatch(body,/只属于更新记录/)
 assert.match(markup,/data-release-review-adopt="pending"/);assert.match(markup,/>采纳记录<\/button>/)
 assert.match(markup,/data-release-review-history="body"/);assert.match(markup,/data-release-review-history="log"/)
})
test('采纳和撤销记录保持原正文与其他结论，来源变化也不丢未变化决定',async()=>{
 const state=session();state.context.review.stale=true;state.context.review.decisions=[{id:'kept',action:'ignore'}]
 const before='功能主要正文'
 const adopted=helpers.releaseReviewDecisions(state.context,{id:'new'},'adopt')
 assert.deepEqual(adopted,[{id:'kept',action:'ignore'},{id:'new',action:'adopt'}])
 let sent
 await helpers.releaseReviewCommit(state,before,adopted,{isCurrent:()=>true,path:p=>p,api:async(p,o)=>{sent=JSON.parse(o.body);return {}},accept(){}})
 assert.equal(sent.content,before);assert.equal(sent.body_change,undefined)
 assert.deepEqual(helpers.releaseReviewDecisions({...state.context,review:{...state.context.review,decisions:adopted}},{id:'new'},null),[{id:'kept',action:'ignore'}])
})
test('更新正文发送独立正文修订元信息，历史恢复显式指定body或log',async()=>{
 const state=session();let sent
 const metadata={event_id:'event190',operation:'replace',reason:'更新测量方式'}
 await helpers.releaseReviewCommit(state,'修订后正文',[{id:'event190',action:'include'}],{isCurrent:()=>true,path:p=>p,api:async(p,o)=>{sent=JSON.parse(o.body);return {}},accept(){}},metadata)
 assert.deepEqual(sent.body_change,metadata);assert.equal(sent.decisions[0].action,'include')
 const body=helpers.releaseReviewRestorePayload(state.context,'body',0),log=helpers.releaseReviewRestorePayload(state.context,'log',1)
 assert.equal(body.kind,'body');assert.equal(body.restore_revision,0);assert.equal(log.kind,'log');assert.equal(log.restore_revision,1)
 assert.equal(body.revision,2);assert.equal(log.revision,2)
 assert.throws(()=>helpers.releaseReviewRestorePayload(state.context,'invalid',0),/类型无效/)
})

test('更新正文无实际变化时不发送保存，提示只采纳记录',async()=>{
 const state=session();state.context.result={content:'原正文'};let called=0
 const result=await helpers.releaseReviewCommit(state,'原正文',[{id:'x',action:'include'}],{isCurrent:()=>true,path:p=>p,api:async()=>{called++;return {}},accept(){}},{event_id:'x',operation:'replace',reason:''})
 assert.equal(result,null);assert.equal(called,0);assert.match(state.error,/采纳记录/)
})
