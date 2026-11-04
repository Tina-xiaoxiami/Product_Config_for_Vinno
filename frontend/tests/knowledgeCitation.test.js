import assert from 'node:assert/strict'
import test from 'node:test'

const sha = 'a'.repeat(64)
const citation = () => ({ document_id: 1, page: 2, version_id: sha, quote: '原文中的明确记录' })
const response = () => ({ ...citation(), chunk_id: null, title: '资料', source_ref: '第2页', text: '完整原文中的明确记录和限制。', verification: { source: 'hash_verified', extraction: 'hash_verified', quote: 'matched' }, preview_url: `/api/knowledge/documents/1/preview?version_id=${sha}#page=2` })
const wait = () => { let resolve, reject; const promise = new Promise((yes,no) => { resolve=yes;reject=no }); return { promise,resolve,reject } }

test('version-bound locator accepts PDF or chunk without inventing a page and excludes candidate ellipsis', async () => {
  const { citationRequest } = await import('../src/utils/knowledgeCitation.js')
  assert.deepEqual(citationRequest(citation()), { document_id: 1, params: { version_id: sha, page: 2, quote: '原文中的明确记录' } })
  assert.deepEqual(citationRequest({ document_id: 1, version_id: sha, chunk_id: 6, page_number: null, excerpt: '截断…' }), { document_id: 1, params: { version_id: sha, chunk_id: 6 } })
  assert.equal(citationRequest({ document_id: 1, page: 1 }), null)
  assert.equal(citationRequest({ ...citation(), version_id: '../secret' }), null)
})
test('close and rapid reopen discard stale evidence and abort old requests', async () => {
  const { createCitationController } = await import('../src/utils/knowledgeCitation.js')
  const state={}, calls=[]
  const controller=createCitationController({ state, request: (...args) => {const next=wait();calls.push({next,args});return next.promise} })
  const first=controller.open(citation());controller.close()
  assert.equal(calls[0].args[2].aborted,true)
  const second=controller.open(citation());calls[0].next.resolve(response());await first
  assert.equal(state.result,null)
  calls[1].next.resolve(response());assert.equal(await second,true);assert.equal(state.result.source_ref,'第2页')
  controller.dispose();assert.equal(state.result,null)
})
test('source changes clear earlier evidence and never fall back to an unversioned source', async () => {
  const { createCitationController } = await import('../src/utils/knowledgeCitation.js')
  let fail=false;const state={}
  const controller=createCitationController({state,request:async()=>{if(fail)throw {response:{status:409,data:{detail:'原件已变化'}}};return response()}})
  await controller.open(citation());fail=true;await controller.open(citation())
  assert.equal(state.result,null);assert.match(state.error,/重新查询/)
})
test('mismatched server identity, location and verification never become viewable evidence', async () => {
  const { createCitationController } = await import('../src/utils/knowledgeCitation.js')
  for (const change of [{version_id:'b'.repeat(64)},{document_id:3},{page:9},{verification:{}},{preview_url:'https://bad.invalid'}]) {
    const state={};const controller=createCitationController({state,request:async()=>({...response(),...change})})
    assert.equal(await controller.open(citation()),false);assert.equal(state.result,null);assert.ok(state.error)
  }
})
test('quote highlighting handles whitespace without interpreting source HTML', async () => {
  const { citationTextParts } = await import('../src/utils/knowledgeCitation.js')
  assert.deepEqual(citationTextParts('原文\n 引用 <script>尾部','原文 引用'),[{text:'原文\n 引用',highlight:true},{text:' <script>尾部',highlight:false}])
  assert.deepEqual(citationTextParts('完整正文',null),[{text:'完整正文',highlight:false}])
})
test('only actual visual audit marks a citation as model checked; never human approval',async()=>{
  const { citationVisualLabel } = await import('../src/utils/knowledgeCitation.js')
  assert.match(citationVisualLabel({verification_status:'model_visual_checked'}),/模型已看原页.*未人工确认/)
  assert.match(citationVisualLabel({}),/未看图/)
})

test('versioned preview links stay on the registered product document route',async()=>{
  const { evidenceCitationUrl }=await import('../src/utils/knowledgeEvidence.js')
  assert.equal(evidenceCitationUrl({...citation(),preview_url:response().preview_url}),response().preview_url)
  assert.equal(evidenceCitationUrl({...citation(),preview_url:`/api/knowledge/documents/2/preview?version_id=${sha}#page=2`}),null)
  assert.equal(evidenceCitationUrl({...citation(),preview_url:`/api/knowledge/documents/1/preview?version_id=${sha}&path=bad`}),null)
})
