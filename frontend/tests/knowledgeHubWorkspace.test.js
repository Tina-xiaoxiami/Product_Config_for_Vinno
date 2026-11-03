import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const view = read('../src/views/KnowledgeHub.vue')

function tabNavigation() {
  const start = view.indexOf('watch(() => route.query.tab')
  const marker = '}, { immediate: true })'
  const end = view.indexOf(marker, start) + marker.length
  assert.ok(start >= 0 && end > start)
  const activeTab = { value: 'qa' }, calls = []
  let change
  new Function('watch', 'route', 'router', 'activeTab', view.slice(start, end))(
    (_getter, handler, options) => { change = handler; assert.equal(options.immediate, true) },
    { query: {} }, { replace: value => calls.push(value) }, activeTab
  )
  return { change, activeTab, calls }
}

test('retired knowledge deep links navigate to their canonical management pages', () => {
  const { change, activeTab, calls } = tabNavigation()
  for (const tab of ['features', 'registration', 'documents']) change(tab)
  assert.deepEqual(calls, [
    { path: '/feature-manage' }, { path: '/registration-manage' },
    { path: '/release', query: { tab: 'documents' } }
  ])
  assert.equal(activeTab.value, 'qa')
})

test('remaining knowledge deep links select the requested workspace', () => {
  const { change, activeTab, calls } = tabNavigation()
  for (const tab of ['qa', 'history', 'parameters']) {
    change(tab)
    assert.equal(activeTab.value, tab)
  }
  change('unknown-retired-pane')
  assert.equal(activeTab.value, 'qa')
  assert.deepEqual(calls, [])
})

test('source management stays available through canonical documents and QA citations', () => {
  assert.doesNotMatch(view, /beforeKnowledgeTabLeave|label="资料管理" name="documents"/)
  assert.doesNotMatch(view, /knowledge-document-list|archiveKnowledgeDocument|extractKnowledgeDocument|previewVisible/)
  assert.match(view, /v-for="document in documents"/)
  assert.match(view, /getKnowledgeDocumentPreviewUrl/)
  assert.match(read('../src/views/ReleaseWorkspace.vue'), /KnowledgeDocumentsWorkspace/)
  assert.match(read('../src/api/data.js'), /export const getKnowledgeFeatureCoverage/)
})
