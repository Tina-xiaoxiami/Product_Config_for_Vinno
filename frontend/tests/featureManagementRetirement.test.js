import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { PROBE_MANAGEMENT_TABS, probeManagementMenuPath } from '../src/utils/probeManagementNavigation.js'
import { workspaceForPath } from '../src/utils/workspaceNavigation.js'

test('configuration feature identities are selected within templates rather than another management tab', () => {
  assert.equal(PROBE_MANAGEMENT_TABS.some(tab => tab.path === '/feature-manage'), false)
  assert.equal(PROBE_MANAGEMENT_TABS.find(tab => tab.path === '/template-features')?.label, '模板管理')
  assert.equal(probeManagementMenuPath('/feature-manage'), '/template-features')
  assert.equal(workspaceForPath('/feature-manage')?.title, '模板管理')
})

test('retired feature route redirects without loading its old editor', () => {
  const router = readFileSync(new URL('../src/router/index.js', import.meta.url), 'utf8')
  const block = router.match(/path: 'feature-manage'[\s\S]*?\n      }/)[0]
  assert.match(block, /redirect: '\/template-features'/)
  assert.doesNotMatch(block, /component:/)
  const hub = readFileSync(new URL('../src/views/KnowledgeHub.vue', import.meta.url), 'utf8')
  const featureLink = hub.match(/if \(tab === 'features'\) {[\s\S]*?}/)[0]
  assert.match(featureLink, /path: '\/template-features'/)
})
