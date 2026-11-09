import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import * as navigation from '../src/utils/probeManagementNavigation.js'
import { workspaceForPath } from '../src/utils/workspaceNavigation.js'

test('probe models and applications have one management entry and one workspace identity', () => {
  assert.deepEqual(navigation.PROBE_MANAGEMENT_TABS.map(tab => tab.label), ['模板管理', '探头&应用'])
  for (const path of ['/probe-models', '/applications']) {
    assert.equal(navigation.probeManagementMenuPath(path), '/template-features')
    assert.equal(workspaceForPath(path).title, '探头&应用')
  }
  assert.equal(navigation.probeManagementMenuPath('/applications-extra'), '/applications-extra')
  assert.equal(workspaceForPath('/feature-manage').title, '模板管理')
})

test('old application links retain the category and enter the applications area on the combined page', () => {
  const query = { category_id: '3', unrelated: 'preserved' }
  assert.deepEqual(navigation.probeApplicationsRedirect({ query, hash: '#details' }), {
    path: '/probe-models', query: { category_id: '3', unrelated: 'preserved', focus: 'applications' }, hash: '#details'
  })
  assert.deepEqual(query, { category_id: '3', unrelated: 'preserved' })
  const router = readFileSync(new URL('../src/router/index.js', import.meta.url), 'utf8')
  const block = router.match(/path: 'applications'[\s\S]*?\n      }/)[0]
  assert.match(block, /redirect: probeApplicationsRedirect/)
  assert.doesNotMatch(block, /component:/)
})
