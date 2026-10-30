import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { PROBE_MANAGEMENT_TABS, probeManagementMenuPath } from '../src/utils/probeManagementNavigation.js'
const template = readFileSync(new URL('../src/views/TemplateFeatures.vue', import.meta.url), 'utf8')
const layout = readFileSync(new URL('../src/views/Layout.vue', import.meta.url), 'utf8')
test('all management deep links share one sidebar selection and other pages retain theirs', () => {
  assert.deepEqual(PROBE_MANAGEMENT_TABS.map(tab => tab.label), ['模板管理', '探头管理', '应用管理', '功能管理'])
  for (const path of ['/template-features', '/probe-models', '/applications', '/feature-manage']) assert.equal(probeManagementMenuPath(path), '/template-features')
  for (const path of ['/config', '/knowledge', '/probe-config', '/feature-manage-extra']) assert.equal(probeManagementMenuPath(path), path)
})
test('template return refreshes supporting data while retaining edits and skipping duplicate initial load', async () => {
  let activated, loads = 0, drafts = 0
  const editMode = { value: false }
  const code = template.slice(template.indexOf('let templateHasActivated ='), template.indexOf('</script>'))
  new Function('onActivated', 'editMode', 'refreshData', code)(callback => { activated = callback }, editMode, async () => { loads++; drafts++ })
  await activated(); assert.equal(loads, 0)
  await activated(); assert.equal(loads, 1)
  editMode.value = true
  await activated(); assert.equal(loads, 1)
  editMode.value = false
  await activated(); assert.equal(drafts, 2)
})
test('tabs only commit selection when route navigation succeeds', async () => {
  let failed = false, throws = false, errors = 0
  const routes = []
  const route = { path: '/template-features' }
  const code = layout.slice(layout.indexOf('const switchProbeManagementTab ='), layout.indexOf('const sidebarCollapsed ='))
  const change = new Function('router', 'ElMessage', 'route', code + '\nreturn switchProbeManagementTab')({ push: async path => { routes.push(path); if (throws) throw new Error('offline'); return failed ? {} : undefined } }, { error() { errors++ } }, route)
  assert.equal(await change('/applications'), true)
  route.path = '/applications'
  assert.equal(await change('/applications'), true)
  assert.deepEqual(routes, ['/applications'])
  failed = true
  assert.equal(await change('/feature-manage'), false)
  throws = true
  assert.equal(await change('/probe-models'), false)
  assert.equal(errors, 1)
  assert.deepEqual(routes, ['/applications', '/feature-manage', '/probe-models'])
})
