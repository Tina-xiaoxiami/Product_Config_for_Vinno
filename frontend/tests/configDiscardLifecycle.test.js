import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { ref, reactive, computed } from 'vue'

const source=readFileSync(new URL('../src/views/Config.vue',import.meta.url),'utf8')
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no});return{promise,resolve,reject}}
function discardApp(overrides={}) {
  const reads=[],posts=[],directDeletes=[],confirmations=[],messages=[],reloads=[]
  const ctx={
    ref,discardSubmitting:ref(false),configReady:ref(true),loading:ref(false),applyingModelGroup:ref(false),foreignLock:ref(false),
    selectedSeries:ref([1,2]),seriesList:ref([{id:1,name:'One'},{id:2,name:'Two'}]),draftBatchMap:ref(new Map([[1,'b1'],[2,'b2']])),
    batchSubmitResultDialog:reactive({visible:false,action:'submit',results:[],scope:null,error:''}),draftCellOperations:new Map(),
    draftStats:{total:4,create:0,update:4,delete:0},draftChanges:ref(new Map([['first',{changeType:'update'}]])),
    draftFilterMode:ref(false),draftFilters:ref(new Set()),draftExpanded:ref(true),selectedDraftItemIds:ref(new Set()),selectedDraftModelIds:ref(new Set()),draftItemInfo:ref(new Map()),
    getCurrentDraftBatch:async id=>{reads.push(id);return{exists:true,batch:{id:`b${id}`,series_id:id,status:'draft',total_count:2}}},
    batchDiscardDrafts:async params=>{posts.push({batch_ids:[...params.batch_ids]});return{discarded_count:params.batch_ids.length,results:params.batch_ids.map(id=>({batch_id:id,series_id:Number(id.slice(1)),success:true,message:'数据已回滚'}))}},
    discardDraftBatch:async id=>{directDeletes.push(id)},
    loadData:async()=>{reloads.push('data');return true},initDraft:async()=>{reloads.push('draft');return true},
    ElMessageBox:{confirm:async(text)=>{confirmations.push(text)}},
    ElMessage:Object.fromEntries(['info','success','warning','error'].map(type=>[type,message=>messages.push({type,message})])),console:{error(){}},...overrides
  }
  ctx.reviewInteractionLocked=computed(()=>ctx.foreignLock.value||ctx.discardSubmitting.value)
  const waitStart=source.indexOf('const waitForDraftSaves =')
  const wait=source.slice(waitStart,source.indexOf('const handleSubmitDraft =',waitStart))
  const start=source.indexOf('// 废弃草稿（')
  const code=source.slice(start,source.indexOf('// 打开批量提交对话框',start))
  const methods=new Function(...Object.keys(ctx),`${wait}\n${code}\nreturn {handleDiscardDraft,handleBatchDiscardDrafts,retryDiscardDrafts:typeof retryDiscardDrafts==='function'?retryDiscardDrafts:async()=>false}`)(...Object.values(ctx))
  return{...ctx,...methods,reads,posts,directDeletes,confirmations,messages,reloads}
}
for(const entry of ['handleDiscardDraft','handleBatchDiscardDrafts']) {
  test(`${entry} waits for saves and freezes selected series before any reads or writes`,async()=>{
    const saved=deferred(),app=discardApp();app.draftCellOperations.set('pending',{tail:saved.promise})
    const pending=app[entry]();await Promise.resolve()
    assert.deepEqual(app.reads,[]);assert.deepEqual(app.posts,[]);assert.deepEqual(app.directDeletes,[])
    assert.equal(app.discardSubmitting.value,true);assert.equal(app.reviewInteractionLocked.value,true)
    app.selectedSeries.value=[99];saved.resolve();await pending
    assert.deepEqual(app.reads,[1,2]);assert.deepEqual(app.posts,[{batch_ids:['b1','b2']}]);assert.deepEqual(app.directDeletes,[])
    assert.match(app.confirmations[0],/全部草稿/);assert.match(app.confirmations[0],/未选机型/);assert.match(app.confirmations[0],/One/);assert.match(app.confirmations[0],/Two/)
    assert.equal(app.discardSubmitting.value,false)
  })
}
test('either entry is blocked while the other is reading or confirming',async()=>{
  const confirm=deferred();let shown=0
  const app=discardApp({ElMessageBox:{confirm:()=>{shown++;return confirm.promise}}})
  const first=app.handleDiscardDraft();await new Promise(resolve=>setImmediate(resolve))
  const second=app.handleBatchDiscardDrafts(),third=app.handleDiscardDraft()
  await new Promise(resolve=>setImmediate(resolve))
  const count=shown,busy=app.discardSubmitting.value
  confirm.resolve();await Promise.all([first,second,third])
  assert.equal(count,1);assert.equal(busy,true);assert.equal(app.posts.length,1)
})
for(const entry of ['handleDiscardDraft','handleBatchDiscardDrafts']) {
  test(`${entry} rejects any failed series read instead of skipping it or declaring no drafts`,async()=>{
    const readIds=[]
    const app=discardApp({getCurrentDraftBatch:async id=>{readIds.push(id);if(id===2)throw Error('offline');return{exists:true,batch:{id:'b1',series_id:1,status:'draft',total_count:2}}}})
    await app[entry]()
    assert.deepEqual(readIds,[1,2]);assert.deepEqual(app.posts,[]);assert.deepEqual(app.directDeletes,[]);assert.deepEqual(app.confirmations,[])
    assert.equal(app.batchSubmitResultDialog.visible,true);assert.equal(app.batchSubmitResultDialog.action,'discard')
    assert.match(app.batchSubmitResultDialog.error,/核验/)
    assert.ok(app.batchSubmitResultDialog.results.some(row=>row.seriesId===2&&!row.success&&/连接|核验/.test(row.message)))
    assert.equal(app.messages.some(message=>message.type==='info'&&/没有.*草稿/.test(message.message)),false)
    assert.equal(app.discardSubmitting.value,false)
  })
}
for(const response of [{exists:true},{exists:true,batch:{id:'b1',series_id:1,status:'draft'}},{exists:true,batch:{id:'b1',series_id:1,status:'submitted',total_count:2}}]) {
  test(`malformed or closed current batches block the entire discard (${JSON.stringify(response)})`,async()=>{
    const app=discardApp({getCurrentDraftBatch:async()=>response});await app.handleBatchDiscardDrafts()
    assert.deepEqual(app.posts,[]);assert.deepEqual(app.confirmations,[]);assert.match(app.batchSubmitResultDialog.error,/核验/)
  })
}
test('only explicit absent or fully validated zero-change batches skip writes',async()=>{
  const app=discardApp({getCurrentDraftBatch:async id=>id===1?{exists:false}:{exists:true,batch:{id:'b2',series_id:2,status:'draft',total_count:0}}})
  await app.handleDiscardDraft()
  assert.deepEqual(app.posts,[]);assert.deepEqual(app.directDeletes,[]);assert.deepEqual(app.confirmations,[])
  assert.equal(app.batchSubmitResultDialog.results.length,2)
  assert.ok(app.batchSubmitResultDialog.results.every(row=>row.skipped))
  assert.equal(app.discardSubmitting.value,false)
})
test('partial results are mapped by frozen batch IDs, refreshed, and retry excludes successful series',async()=>{
  let attempts=0
  const app=discardApp({batchDiscardDrafts:async params=>{app.posts.push({batch_ids:[...params.batch_ids]});attempts++;return{discarded_count:1,results:params.batch_ids.map(id=>({batch_id:id,series_id:Number(id.slice(1)),success:attempts>1||id==='b1',message:id==='b2'&&attempts===1?'版本已改变':'数据已回滚'}))}}})
  await app.handleDiscardDraft()
  assert.deepEqual(app.batchSubmitResultDialog.results.map(row=>row.success),[true,false])
  assert.equal(app.batchSubmitResultDialog.results[1].message,'版本已改变')
  assert.deepEqual(app.reloads,['data','draft'])
  await app.retryDiscardDrafts()
  assert.deepEqual(app.posts,[{batch_ids:['b1','b2']},{batch_ids:['b2']}])
  assert.deepEqual(app.reads,[1,2,2]);assert.ok(app.batchSubmitResultDialog.results.every(row=>row.success))
})
test('missing response entries never infer success from discarded_count and preserve failed scope for recheck',async()=>{
  const app=discardApp({batchDiscardDrafts:async params=>{app.posts.push(params);return{discarded_count:2,results:[{batch_id:'b1',series_id:1,success:true,message:'数据已回滚'}]}}})
  await app.handleBatchDiscardDrafts()
  assert.deepEqual(app.batchSubmitResultDialog.results.map(row=>row.success),[true,false])
  assert.match(app.batchSubmitResultDialog.results[1].message,/未返回|未确认/)
  assert.deepEqual(app.reloads,['data','draft'])
})
test('retry refuses a replacement nonempty batch instead of discarding new changes',async()=>{
  let changed=false
  const app=discardApp({
    batchDiscardDrafts:async params=>{app.posts.push(params);return{discarded_count:1,results:[{batch_id:'b1',series_id:1,success:true,message:'数据已回滚'},{batch_id:'b2',series_id:2,success:false,message:'失败'}]}},
    getCurrentDraftBatch:async id=>({exists:true,batch:{id:changed&&id===2?'new-b2':`b${id}`,series_id:id,status:'draft',total_count:2}})
  })
  await app.handleDiscardDraft();changed=true;await app.retryDiscardDrafts()
  assert.equal(app.posts.length,1);assert.match(app.batchSubmitResultDialog.error,/核验/)
  assert.match(app.batchSubmitResultDialog.results[1].message,/批次.*变化/)
})
for(const cancellation of ['cancel','close']) {
  test(`${cancellation} releases discard lock without an error or any write`,async()=>{
    const app=discardApp({ElMessageBox:{confirm:async()=>{throw cancellation}}});await app.handleDiscardDraft()
    assert.equal(app.discardSubmitting.value,false);assert.deepEqual(app.posts,[]);assert.deepEqual(app.directDeletes,[])
    assert.equal(app.messages.some(message=>message.type==='error'),false)
  })
}
test('operation stays locked during refresh and refresh failure preserves per-series success without repeating writes',async()=>{
  const refreshing=deferred();let attempt=0
  const app=discardApp({loadData:async()=>{attempt++;app.reloads.push('data');if(attempt===1)return refreshing.promise;return true}})
  const pending=app.handleDiscardDraft();await new Promise(resolve=>setImmediate(resolve))
  assert.equal(app.discardSubmitting.value,true);assert.equal(app.reviewInteractionLocked.value,true)
  await app.handleBatchDiscardDrafts();assert.equal(app.posts.length,1)
  refreshing.resolve(false);await pending
  assert.ok(app.batchSubmitResultDialog.results.every(row=>row.success));assert.match(app.batchSubmitResultDialog.error,/刷新/)
  await app.retryDiscardDrafts();assert.equal(app.posts.length,1);assert.equal(app.batchSubmitResultDialog.error,'')
  assert.deepEqual(app.reloads,['data','data','draft'])
})
test('result dialog reuses series result table with distinct discard labels and retry/close guards',()=>{
  const start=source.indexOf('<!-- 批量提交结果 -->'),template=source.slice(start,source.indexOf('</el-dialog>',start))
  assert.match(template,/:title=/);assert.match(template,/discard/);assert.match(template,/@click="retryDiscardDrafts"/)
  assert.match(template,/:close-on-press-escape="!discardSubmitting"/)
  const lock=source.slice(source.indexOf('const reviewInteractionLocked ='),source.indexOf('const batchSubmitResultDialog ='))
  assert.match(lock,/discardSubmitting\.value/)
})
for(const absent of [true,false]) {
  for(const refreshSucceeds of [true,false]) {
    test(`retry of already resolved ${absent?'absent':'zero-change'} failure refreshes data (${refreshSucceeds?'success':'failure'})`,async()=>{
      let attempt=0,retry=false
      const app=discardApp({
        getCurrentDraftBatch:async id=>{app.reads.push(id);return retry&&id===2?(absent?{exists:false}:{exists:true,batch:{id:'b2',series_id:2,status:'draft',total_count:0}}):{exists:true,batch:{id:`b${id}`,series_id:id,status:'draft',total_count:2}}},
        batchDiscardDrafts:async params=>{app.posts.push(params);return{discarded_count:1,results:[{batch_id:'b1',series_id:1,success:true,message:'已撤销'},{batch_id:'b2',series_id:2,success:false,message:'结果未确认'}]}},
        loadData:async()=>{app.reloads.push('data');attempt++;return attempt===1?false:refreshSucceeds}
      })
      await app.handleDiscardDraft();assert.match(app.batchSubmitResultDialog.error,/刷新/)
      retry=true;await app.retryDiscardDrafts()
      assert.equal(app.posts.length,1);assert.deepEqual(app.reads,[1,2,2])
      assert.ok(app.batchSubmitResultDialog.results.every(row=>row.success))
      assert.deepEqual(app.reloads,refreshSucceeds?['data','data','draft']:['data','data'])
      if(refreshSucceeds)assert.equal(app.batchSubmitResultDialog.error,'')
      else assert.match(app.batchSubmitResultDialog.error,/刷新/)
      assert.equal(app.discardSubmitting.value,false)
    })
  }
}
