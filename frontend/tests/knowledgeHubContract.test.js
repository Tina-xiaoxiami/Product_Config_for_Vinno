import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'


const read = (relativePath) => readFileSync(new URL(relativePath, import.meta.url), 'utf8')


test('knowledge hub is reachable from router and primary navigation', () => {
  const router = read('../src/router/index.js')
  const layout = read('../src/views/Layout.vue')

  assert.match(router, /path:\s*'knowledge'/)
  assert.match(router, /name:\s*'KnowledgeHub'/)
  assert.match(layout, /index="\/knowledge"/)
  assert.match(layout, />\s*产品知识库\s*</)
})


test('knowledge hub exposes search, status filters, identity details and documents', () => {
  const view = read('../src/views/KnowledgeHub.vue')

  assert.match(view, /data-testid="knowledge-search"/)
  assert.match(view, /data-testid="knowledge-status-filter"/)
  assert.match(view, /data-testid="feature-knowledge-list"/)
  assert.match(view, /备用名/)
  assert.match(view, /版本关系/)
  assert.match(view, /data-testid="knowledge-document-list"/)
  assert.match(view, /data-testid="document-preview-dialog"/)
  assert.match(view, /<iframe/)
})


test('frontend API exposes knowledge feature, stats and document endpoints', () => {
  const api = read('../src/api/data.js')

  assert.match(api, /export const getKnowledgeFeatures/)
  assert.match(api, /export const getKnowledgeStats/)
  assert.match(api, /export const getKnowledgeDocuments/)
  assert.match(api, /export const getKnowledgeDocumentPreviewUrl/)
})
