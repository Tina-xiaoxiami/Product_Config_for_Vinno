import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { createEvidenceAnswerController, evidenceCitationUrl, evidenceStatusLabel } from '../src/utils/knowledgeEvidence.js'

const input = () => ({ question: '针增益有哪些版本变化？', scope: { market: 'domestic', product_model_id: 9, software_version: '1.14.81' } })
const answer = text => ({ status: 'draft', claims: [{ text, citations: [] }], coverage: { document_count: 2 }, metrics: { model_calls: 3 }, gaps: [] })
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }
function setup(options = {}) {
  const state = {}, current = input(), calls = [], waits = []
  const controller = createEvidenceAnswerController({ state, getInput: () => current,
    request: (payload, signal) => { calls.push({ payload, signal }); const pending = deferred(); waits.push(pending); return pending.promise },
    capabilities: async () => ({ available: true }), ...options })
  return { state, current, calls, waits, controller }
}

test('capability checks and construction never generate a draft; explicit run freezes the current scope', async () => {
  const { controller, state, current, calls, waits } = setup()
  assert.equal(calls.length, 0)
  await controller.checkAvailability()
  assert.equal(calls.length, 0)
  assert.equal(state.available, true)
  const pending = controller.run()
  assert.deepEqual(calls[0].payload, input())
  assert.notEqual(calls[0].payload.scope, current.scope)
  assert.equal(calls[0].signal.aborted, false)
  assert.equal(await controller.run(), false)
  assert.equal(calls.length, 1)
  waits[0].resolve(answer('有引用的草稿'))
  assert.equal(await pending, true)
  assert.equal(state.result.claims[0].text, '有引用的草稿')
  assert.equal(state.loading, false)
})

test('missing scope, empty questions and unavailable capabilities make no model request', async () => {
  const first = setup()
  await first.controller.checkAvailability()
  first.current.scope.software_version = ''
  assert.equal(await first.controller.run(), false)
  assert.match(first.state.error, /范围/)
  first.current.scope = input().scope
  first.current.question = ' '
  assert.equal(await first.controller.run(), false)
  assert.equal(first.calls.length, 0)
  const second = setup({ capabilities: async () => ({ available: false, reason: '共享服务尚未启用' }) })
  await second.controller.checkAvailability()
  assert.equal(await second.controller.run(), false)
  assert.equal(second.calls.length, 0)
  assert.equal(second.state.unavailableReason, '共享服务尚未启用')
})

test('question or scope edits abort the old request and prevent old results from leaking', async () => {
  const { controller, state, current, waits, calls } = setup()
  await controller.checkAvailability()
  const first = controller.run()
  current.scope.software_version = '1.14.80'
  controller.invalidate()
  assert.equal(calls[0].signal.aborted, true)
  const second = controller.run()
  waits[0].resolve(answer('旧范围'))
  assert.equal(await first, false)
  assert.equal(state.result, null)
  assert.equal(state.loading, true)
  waits[1].resolve(answer('新范围'))
  await second
  assert.equal(state.result.claims[0].text, '新范围')
  current.question = '另一个问题'
  controller.invalidate()
  assert.equal(state.result, null)
})

test('same-scope failure retains the last draft and permits an explicit retry', async () => {
  const { controller, state, waits } = setup()
  await controller.checkAvailability()
  let pending = controller.run()
  waits[0].resolve(answer('上次已核验草稿'))
  await pending
  pending = controller.run()
  waits[1].reject({ response: { data: { detail: '原文已变化，请刷新后重试' } } })
  assert.equal(await pending, false)
  assert.equal(state.result.claims[0].text, '上次已核验草稿')
  assert.match(state.error, /原文已变化/)
  assert.equal(state.loading, false)
  pending = controller.run()
  waits[2].resolve(answer('重试结果'))
  assert.equal(await pending, true)
  assert.equal(state.result.claims[0].text, '重试结果')
})

test('changed input is rejected even before its watcher invalidates the request', async () => {
  const { controller, state, current, waits } = setup()
  await controller.checkAvailability()
  const pending = controller.run()
  current.question = '新问题'
  waits[0].resolve(answer('旧问题'))
  assert.equal(await pending, false)
  assert.equal(state.result, null)
  assert.equal(state.loading, false)
})

test('deterministic questions and failed validation never expose generated claims as an answer', async () => {
  for (const status of ['deterministic_required', 'validation_failed', 'unavailable', 'no_evidence']) {
    const { controller, state, waits } = setup()
    await controller.checkAvailability()
    const pending = controller.run()
    waits[0].resolve({ ...answer('不可展示的结论'), status })
    await pending
    assert.deepEqual(state.result.claims, [])
  }
})

test('disposed or superseded capability requests cannot alter mounted state', async () => {
  const a = deferred(), b = deferred(), queue = [a, b]
  const { controller, state } = setup({ capabilities: () => queue.shift().promise })
  const first = controller.checkAvailability(), second = controller.checkAvailability()
  b.resolve({ available: true })
  await second
  a.resolve({ available: false, reason: '旧错误' })
  await first
  assert.equal(state.available, true)
  const work = setup()
  await work.controller.checkAvailability()
  const pending = work.controller.run()
  work.controller.dispose()
  work.waits[0].resolve(answer('卸载之后'))
  await pending
  assert.equal(work.state.result, null)
  assert.equal(work.calls[0].signal.aborted, true)
})

test('citation links are bound to product document identities and cannot use external or script URLs', () => {
  assert.equal(evidenceCitationUrl({ document_id: 20, preview_url: '/api/knowledge/documents/20/preview#page=4' }), '/api/knowledge/documents/20/preview#page=4')
  for (const url of ['javascript:alert(1)', 'https://example.com', '//example.com', '/api/knowledge/documents/21/preview']) {
    assert.equal(evidenceCitationUrl({ document_id: 20, preview_url: url }), null)
  }
  assert.equal(evidenceStatusLabel('draft'), '资料草稿 · 未发布')
  assert.equal(evidenceStatusLabel('deterministic_required'), '请使用确定性查询')
})

test('the new action shares the existing ask toolbar while the result has a full-width region', () => {
  const hub = readFileSync(new URL('../src/views/KnowledgeHub.vue', import.meta.url), 'utf8')
  const view = readFileSync(new URL('../src/components/KnowledgeEvidenceAnswer.vue', import.meta.url), 'utf8')
  const api = readFileSync(new URL('../src/api/knowledgeEvidence.js', import.meta.url), 'utf8')
  assert.match(hub, /查资料并生成草稿/)
  assert.match(hub, /<KnowledgeEvidenceAnswer[^>]*ref="evidenceAnswer"/)
  assert.match(hub, /const qaQueueMode = ref\('selected'\)/)
  assert.match(view, /未发布|人工确认/)
  assert.match(view, /onBeforeUnmount/)
  assert.match(view, /evidenceCitationUrl/)
  assert.doesNotMatch(view, /v-html|publishKnowledgeAnswer/)
  assert.match(api, /timeout: 240000/)
})
