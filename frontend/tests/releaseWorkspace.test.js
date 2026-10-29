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
  assert.match(workspace, /<FeatureRelease\s+ref="nativeRelease"\s+\/>/)
  assert.match(workspace, /<h2>功能发布<\/h2>/)
  assert.doesNotMatch(workspace, /同源工作台/)
})

test('embedded workbench keeps one persistent frame while outer tabs activate child views', () => {
  const workspace = read('../src/views/ReleaseWorkspace.vue')

  assert.equal((workspace.match(/<iframe\b/g) || []).length, 1)
  assert.doesNotMatch(workspace, /v-for="tab in mountedWorkbenchTabs"/)
  assert.match(workspace, /ref="workbenchFrame"/)
  assert.match(workspace, /:src="workbenchFrameUrl"/)
  assert.match(workspace, /if \(!workbenchFrameUrl\.value\) workbenchFrameUrl\.value = releaseWorkbenchUrl\(tab\)/)
  assert.match(workspace, /type: 'release-workspace:activate'/)
  assert.match(workspace, /workbenchFrame\.value\?\.contentWindow\?\.postMessage/)
  assert.doesNotMatch(workspace, /:src="releaseWorkbenchUrl\(tab\)"/)
  assert.match(workspace, /data-testid="release-workbench-retry"/)
  assert.match(workspace, /data-testid="release-workbench-standalone"/)
  assert.match(workspace, /checkWorkbenchAvailability/)
  assert.match(workspace, /window\.addEventListener\('message'/)
  assert.match(workspace, /router\.replace/)
  assert.doesNotMatch(workspace, /同进程/)
})

test('switching outer views preserves the child project and selected release state', () => {
  const workspace = read('../src/views/ReleaseWorkspace.vue')
  const functionSource = workspace.slice(
    workspace.indexOf('function mountWorkbench(tab)'),
    workspace.indexOf('function markWorkbenchLoaded()')
  )
  const sent = []
  const childWindow = {
    selection: { project: 'VINNO 10', version: '1.14.80' },
    postMessage: (message, origin) => sent.push({ message, origin })
  }
  const context = {
    isWorkbenchTab: tab => ['search', 'review', 'releases', 'compare'].includes(tab),
    workbenchFrameUrl: { value: '' },
    releaseWorkbenchUrl,
    checkWorkbenchAvailability() {},
    workbenchFrame: { value: { contentWindow: childWindow } },
    window: { location: { origin: 'http://127.0.0.1:3006' } }
  }
  const { mountWorkbench, postWorkbenchActivation } = new Function(
    ...Object.keys(context),
    `${functionSource}; return { mountWorkbench, postWorkbenchActivation }`
  )(...Object.values(context))

  mountWorkbench('search')
  postWorkbenchActivation('releases')

  assert.equal(context.workbenchFrameUrl.value, '/release-workbench/?embedded=1#search')
  assert.deepEqual(childWindow.selection, { project: 'VINNO 10', version: '1.14.80' })
  assert.deepEqual(sent, [{
    message: { type: 'release-workspace:activate', view: 'releases' },
    origin: 'http://127.0.0.1:3006'
  }])
})

test('knowledge hub links to release source search and dev server proxies the mounted module', () => {
  const knowledge = read('../src/views/KnowledgeHub.vue')
  const vite = read('../vite.config.js')

  assert.match(knowledge, /to="\/release\?tab=search"/)
  assert.match(knowledge, />\s*搜索发布资料\s*</)
  assert.match(vite, /'\/release-workbench'/)
  assert.match(vite, /target:\s*'http:\/\/127\.0\.0\.1:8086'/)
})
