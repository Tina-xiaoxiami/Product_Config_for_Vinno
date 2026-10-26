import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  isWorkbenchNavigationMessage,
  normalizeReleaseTab,
  releaseWorkbenchHealthUrl,
  releaseWorkbenchStandaloneUrl,
  releaseWorkbenchUrl
} from '../src/utils/releaseWorkspace.js'

const read = relativePath => readFileSync(new URL(relativePath, import.meta.url), 'utf8')

test('release workspace defaults invalid and missing deep links to source search', () => {
  assert.equal(normalizeReleaseTab(), 'search')
  assert.equal(normalizeReleaseTab('unknown'), 'search')
  assert.equal(normalizeReleaseTab(['review']), 'review')
  assert.equal(normalizeReleaseTab('feature-versions'), 'feature-versions')
})

test('release workbench views use a same-origin embedded URL', () => {
  assert.equal(releaseWorkbenchUrl('search'), '/release-workbench/?embedded=1#search')
  assert.equal(releaseWorkbenchUrl('review'), '/release-workbench/?embedded=1#review')
  assert.equal(releaseWorkbenchUrl('feature-versions'), '')
  assert.equal(releaseWorkbenchStandaloneUrl('review'), '/release-workbench/#review')
  assert.equal(releaseWorkbenchHealthUrl(), '/release-workbench/api/v1/health')
})

test('workbench navigation messages accept only known views from this origin', () => {
  const valid = { origin: 'http://127.0.0.1:3006', data: { type: 'release-workbench:navigate', view: 'compare' } }

  assert.equal(isWorkbenchNavigationMessage(valid, 'http://127.0.0.1:3006'), true)
  assert.equal(isWorkbenchNavigationMessage({ ...valid, origin: 'https://example.test' }, valid.origin), false)
  assert.equal(isWorkbenchNavigationMessage({ ...valid, data: { ...valid.data, view: 'settings' } }, valid.origin), false)
})

test('release route opens the unified workspace while retaining the native records pane', () => {
  const router = read('../src/router/index.js')
  const workspace = read('../src/views/ReleaseWorkspace.vue')

  assert.match(router, /path:\s*'release'/)
  assert.match(router, /name:\s*'ReleaseWorkspace'/)
  assert.match(router, /views\/ReleaseWorkspace\.vue/)
  assert.match(workspace, /label="发布资料检索"\s+name="search"/)
  assert.match(workspace, /label="文件同步"\s+name="review"/)
  assert.match(workspace, /label="发布版本"\s+name="releases"/)
  assert.match(workspace, /label="发布对比"\s+name="compare"/)
  assert.match(workspace, /label="功能版本管理"\s+name="feature-versions"/)
  assert.match(workspace, /<FeatureRelease\s+\/>/)
  assert.match(workspace, /<h2>功能发布<\/h2>/)
  assert.doesNotMatch(workspace, /同源工作台/)
})

test('embedded workbench keeps visited views alive and offers explicit recovery', () => {
  const workspace = read('../src/views/ReleaseWorkspace.vue')

  assert.match(workspace, /v-for="tab in mountedWorkbenchTabs"/)
  assert.match(workspace, /v-show="activeTab === tab"/)
  assert.match(workspace, /data-testid="release-workbench-retry"/)
  assert.match(workspace, /data-testid="release-workbench-standalone"/)
  assert.match(workspace, /checkWorkbenchAvailability/)
  assert.match(workspace, /window\.addEventListener\('message'/)
  assert.match(workspace, /router\.replace/)
})

test('knowledge hub links to release source search and dev server proxies the mounted module', () => {
  const knowledge = read('../src/views/KnowledgeHub.vue')
  const vite = read('../vite.config.js')

  assert.match(knowledge, /to="\/release\?tab=search"/)
  assert.match(knowledge, />\s*搜索发布资料\s*</)
  assert.match(vite, /'\/release-workbench'/)
  assert.match(vite, /target:\s*'http:\/\/127\.0\.0\.1:8086'/)
})
