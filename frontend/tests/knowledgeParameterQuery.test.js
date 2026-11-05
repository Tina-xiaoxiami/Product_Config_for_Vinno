import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { createLatestParameterRequest } from '../src/utils/knowledgeParameters.js'

const workspace = readFileSync(new URL('../src/components/KnowledgeParameterWorkspace.vue', import.meta.url), 'utf8')
const hub = readFileSync(new URL('../src/views/KnowledgeHub.vue', import.meta.url), 'utf8')

test('topic refresh reports failure or invalidation so navigation cannot use stale cached topics', async () => {
  const requests = createLatestParameterRequest()
  assert.equal(await requests.run(async () => 'ok', {}), true)
  assert.equal(await requests.run(async () => { throw new Error('unavailable') }, {}), false)
  let resolve
  const stale = requests.run(() => new Promise(done => { resolve = done }), {})
  requests.invalidate()
  resolve('old topic')
  assert.equal(await stale, false)
})

function setup({ refresh = true, items = [{ id: 7 }], editing = false } = {}) {
  const start = workspace.indexOf('let topicOpenRequestId = 0')
  const end = workspace.indexOf('\ndefineExpose', start)
  assert.ok(start > 0 && end > start, 'workspace exposes guarded topic selection')
  const events = []
  const context = {
    editorState: { visible: editing }, parameterSelectionRevision: { value: 0 }, topics: { value: items }, topicId: { value: 1 },
    seriesId: { value: 8 }, loadTopics: async () => refresh,
    onSeriesChange: () => { events.push('clear snapshot, models and preview') },
    onTopicChange: () => { events.push('load selected specs') },
    ElMessage: { warning: message => events.push(message) }
  }
  const actions = new Function(...Object.keys(context), `${workspace.slice(start, end)};return {openFromQuestion}`)(...Object.values(context))
  return { context, events, ...actions }
}

test('a question selects only its explicit saved topic and clears previous snapshot context', async () => {
  const { context, events, openFromQuestion } = setup()
  assert.equal(await openFromQuestion(7), true)
  assert.equal(context.topicId.value, 7)
  assert.equal(context.seriesId.value, null)
  assert.deepEqual(events, ['clear snapshot, models and preview', 'load selected specs'])
})

test('invalid, removed and failed-refresh topics preserve current selection and preview', async () => {
  for (const [options, id] of [[{}, '7'], [{}, -1], [{}, 7.5], [{}, 99], [{ refresh: false }, 7]]) {
    const { context, events, openFromQuestion } = setup(options)
    assert.equal(await openFromQuestion(id), false)
    assert.equal(context.topicId.value, 1)
    assert.equal(context.seriesId.value, 8)
    assert.ok(!events.includes('clear snapshot, models and preview'))
  }
})

test('question navigation cannot overwrite an open parameter editor or a newer topic selection', async () => {
  const editing = setup({ editing: true })
  assert.equal(await editing.openFromQuestion(7), false)
  assert.equal(editing.context.topicId.value, 1)
  const start = workspace.indexOf('let topicOpenRequestId = 0')
  const end = workspace.indexOf('\ndefineExpose', start)
  const waits = [], events = [], context = {
    editorState: { visible: false }, parameterSelectionRevision: { value: 0 }, topics: { value: [{ id: 7 }, { id: 8 }] },
    topicId: { value: 1 }, seriesId: { value: 4 },
    loadTopics: () => new Promise(resolve => waits.push(resolve)),
    onSeriesChange() {}, onTopicChange() { events.push(context.topicId.value) }, ElMessage: { warning() {} }
  }
  const open = new Function(...Object.keys(context), `${workspace.slice(start, end)};return openFromQuestion`)(...Object.values(context))
  const first = open(7), second = open(8)
  waits[1](true)
  assert.equal(await second, true)
  waits[0](true)
  assert.equal(await first, false)
  assert.deepEqual(events, [8])
})

test('manual topic or snapshot edits cancel older question navigation', async () => {
  const start = workspace.indexOf('let topicOpenRequestId = 0')
  const end = workspace.indexOf('\ndefineExpose', start)
  let finish
  const context = {
    editorState: { visible: false }, parameterSelectionRevision: { value: 0 },
    topics: { value: [{ id: 7 }, { id: 8 }] }, topicId: { value: 1 }, seriesId: { value: 4 },
    loadTopics: () => new Promise(resolve => { finish = resolve }),
    onSeriesChange() {}, onTopicChange() {}, ElMessage: { warning() {} }
  }
  const open = new Function(...Object.keys(context), `${workspace.slice(start, end)};return openFromQuestion`)(...Object.values(context))
  const pending = open(7)
  context.topicId.value = 8
  context.seriesId.value = 9
  context.parameterSelectionRevision.value += 1
  finish(true)
  assert.equal(await pending, false)
  assert.equal(context.topicId.value, 8)
  assert.equal(context.seriesId.value, 9)
  assert.match(workspace, /const invalidatePreview = \(\) => \{ parameterSelectionRevision\.value \+= 1/)
})

test('the hub changes tabs only after successful topic selection and respects a newer tab choice', async () => {
  const start = hub.indexOf('const openParameterTopic = async')
  const end = hub.indexOf('\nwatch(', start)
  assert.ok(start > 0 && end > start)
  let finish
  const parameterWorkspace = { value: { openFromQuestion: () => new Promise(resolve => { finish = resolve }) } }
  const activeTab = { value: 'qa' }
  const open = new Function('parameterWorkspace', 'activeTab', `${hub.slice(start, end)};return openParameterTopic`)(parameterWorkspace, activeTab)
  let pending = open(7)
  finish(false)
  await pending
  assert.equal(activeTab.value, 'qa')
  pending = open(7)
  activeTab.value = 'history'
  finish(true)
  await pending
  assert.equal(activeTab.value, 'history')
  activeTab.value = 'qa'
  pending = open(7)
  finish(true)
  await pending
  assert.equal(activeTab.value, 'parameters')
})

test('ordinary question results offer all parameter candidates without treating them as confirmed answers', () => {
  assert.match(hub, /qaResult\.parameter_topics/)
  assert.match(hub, /v-for="topic in qaResult\.parameter_topics"/)
  assert.match(hub, /@click="openParameterTopic\(topic\.id\)"/)
  assert.match(hub, /尚未匹配配置/)
  assert.match(hub, /ref="parameterWorkspace"/)
  assert.match(workspace, /defineExpose\(\{ openFromQuestion \}\)/)
  assert.doesNotMatch(workspace.slice(workspace.indexOf('let topicOpenRequestId'), workspace.indexOf('\ndefineExpose')), /runPreview|getVersions|versionId\.value\s*=\s*\d/)
})
