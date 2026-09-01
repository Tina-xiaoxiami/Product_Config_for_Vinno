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
  assert.match(view, /关联功能/)
  assert.match(view, /relationNote\(feature\)/)
  assert.match(view, /个功能待确认/)
  assert.match(view, /统计信息加载失败/)
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


test('knowledge hub separates domestic registration redlines from product strategy', () => {
  const view = read('../src/views/KnowledgeHub.vue')

  assert.match(view, /label="国内注册与策略"/)
  assert.match(view, /data-testid="registration-model-select"/)
  assert.match(view, /aria-label="国内产品型号"/)
  assert.match(view, /data-testid="registration-probe-search"/)
  assert.match(view, /data-testid="registration-status-filter"/)
  assert.match(view, /aria-label="注册状态"/)
  assert.match(view, /data-testid="effective-status-filter"/)
  assert.match(view, /aria-label="最终判定"/)
  assert.match(view, /data-testid="registration-strategy-table"/)
  assert.match(view, /注册状态/)
  assert.match(view, /选型类别（正式）/)
  assert.match(view, /当前配置（辅助）/)
  assert.match(view, /最终判定/)
  assert.match(view, /X 标配/)
  assert.match(view, /O 选配/)
  assert.match(view, /Δ 招标支持/)
  assert.match(view, /# 未注册/)
  assert.match(view, /注册差异表原文/)
  assert.match(view, /:href="registrationSourceUrl"/)
  assert.match(view, /target="_blank"/)
})


test('frontend API exposes domestic registration query endpoints', () => {
  const api = read('../src/api/data.js')

  assert.match(api, /export const getConfiguredRegistrationModels/)
  assert.match(api, /export const getRegistrationModels/)
  assert.match(api, /export const getRegistrationProbes/)
})
