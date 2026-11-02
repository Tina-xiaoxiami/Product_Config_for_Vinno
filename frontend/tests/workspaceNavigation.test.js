import test from 'node:test'
import assert from 'node:assert/strict'
import { WORKSPACE_SECTIONS, workspaceForPath } from '../src/utils/workspaceNavigation.js'

test('measurement belongs to master data with one stable navigation identity', () => {
  const measurement = workspaceForPath('/measurements')
  assert.equal(measurement.sectionId, 'master-data')
  assert.equal(measurement.title, '测量库')
  assert.equal(measurement.sidebarGroup, '/manage')
  assert.equal(measurement.activeTab, '/measurements')
  assert.deepEqual(measurement.tabs.map(tab => tab.path), ['/models', '/template-features', '/registration-manage', '/measurements'])
  assert.equal(WORKSPACE_SECTIONS.filter(section => section.path === '/measurements').length, 0)
})

test('probe management deep links retain their page identity and parent selection', () => {
  for (const [path, title] of [['/feature-manage', '功能管理'], ['/applications', '应用管理'], ['/probe-models', '探头管理']]) {
    const page = workspaceForPath(path)
    assert.equal(page.title, title)
    assert.equal(page.activeTab, '/template-features')
    assert.equal(page.sectionId, 'master-data')
  }
})

test('all workspace tabs resolve within their group; unknown routes do not select unrelated modules', () => {
  const paths = new Set()
  for (const section of WORKSPACE_SECTIONS) {
    for (const tab of section.tabs || [section]) {
      assert.equal(paths.has(tab.path), false)
      paths.add(tab.path)
      const page = workspaceForPath(tab.path)
      assert.equal(page.sectionId, section.id)
      assert.ok(page.description.length > 0)
    }
  }
  assert.equal(workspaceForPath('/config-extra'), null)
  assert.equal(workspaceForPath('/'), null)
  assert.equal(workspaceForPath('/probe-versions').sectionId, 'probe-config')
  assert.equal(workspaceForPath('/versions').sectionId, 'model-config')
})
