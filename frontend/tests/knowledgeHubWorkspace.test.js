import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const view = read('../src/views/KnowledgeHub.vue')

test('knowledge documents use one management entry while citation sources stay available', () => {
  assert.match(view, /:before-leave="beforeKnowledgeTabLeave"/)
  assert.match(view, /label="资料管理" name="documents"/)
  assert.match(view, /router\.replace\(\{ path: '\/release', query: \{ tab: 'documents' \} \}\)/)
  assert.doesNotMatch(view, /knowledge-document-list|archiveKnowledgeDocument|extractKnowledgeDocument|previewVisible/)
  assert.match(view, /v-for="document in documents"/)
  assert.match(view, /getKnowledgeDocumentPreviewUrl/)
})

test('clicking documents routes before changing the selected knowledge pane', () => {
  const block = view.slice(view.indexOf('const openDocumentManagement'), view.indexOf('\nwatch(() => route.query.tab'))
  const calls = []
  const beforeLeave = new Function('router', `${block}; return beforeKnowledgeTabLeave`)({ push: value => calls.push(value) })
  assert.equal(beforeLeave('features'), true)
  assert.equal(beforeLeave('documents'), false)
  assert.deepEqual(calls, [{ path: '/release', query: { tab: 'documents' } }])
})

test('catalog coverage is independent of page filters, has loading failure and retry', async () => {
  assert.doesNotMatch(view, /无待确认功能|getKnowledgeStats|class="knowledge-status"/)
  assert.match(view, /coverage\.configured_items/)
  assert.match(view, /coverage\.configured_ipns/)
  assert.match(view, /coverage\.catalog_identities/)
  assert.match(view, /coverage\.missing_cn_names/)
  assert.match(view, /coverage\.missing_en_names/)
  assert.match(view, /coverage\.unlinked_items/)
  assert.match(view, /value="pending"/)
  const block = view.slice(view.indexOf('let coverageRequestId = 0'), view.indexOf('\nlet featureRequestId'))
  const context = {
    coverage: { value: null }, coverageLoading: { value: false }, coverageLoadError: { value: false },
    getKnowledgeFeatureCoverage: async () => { throw new Error('offline') }
  }
  const load = new Function(...Object.keys(context), `${block}; return loadFeatureCoverage`)(...Object.values(context))
  await load()
  assert.equal(context.coverageLoadError.value, true)
  assert.equal(context.coverageLoading.value, false)
  assert.equal(context.coverage.value, null)
  assert.match(view, /@click="loadFeatureCoverage">重试/)
  assert.match(read('../src/api/data.js'), /export const getKnowledgeFeatureCoverage = \(\) => api\.get\('\/knowledge\/feature-coverage'\)/)
})
