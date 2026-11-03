import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { PROBE_MANAGEMENT_TABS, probeManagementMenuPath } from '../src/utils/probeManagementNavigation.js'
const template = readFileSync(new URL('../src/views/TemplateFeatures.vue', import.meta.url), 'utf8')
const layout = readFileSync(new URL('../src/views/Layout.vue', import.meta.url), 'utf8')
test('all management deep links share one sidebar selection and other pages retain theirs', () => {
  assert.deepEqual(PROBE_MANAGEMENT_TABS.map(tab => tab.label), ['模板管理', '探头管理', '应用管理'])
  for (const path of ['/template-features', '/probe-models', '/applications', '/feature-manage']) assert.equal(probeManagementMenuPath(path), '/template-features')
  for (const path of ['/config', '/knowledge', '/probe-config', '/feature-manage-extra']) assert.equal(probeManagementMenuPath(path), path)
})
test('template return uses the shared source refresh while retaining edits', async () => {
  let refresh, canRefresh, loads = 0, drafts = 0
  const editMode = { value: false }
  const code = template.slice(template.indexOf('useWorkspaceRefresh(refreshData'), template.indexOf('</script>'))
  new Function('useWorkspaceRefresh', 'editMode', 'refreshData', code)((callback, options) => {
    refresh = callback; canRefresh = options.canRefresh
  }, editMode, async () => { loads++; drafts++ })
  if (canRefresh()) await refresh(); assert.equal(loads, 1)
  editMode.value = true
  if (canRefresh()) await refresh(); assert.equal(loads, 1)
  editMode.value = false
  if (canRefresh()) await refresh(); assert.equal(drafts, 2)
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

test('template editor initializes selections from the opened category, including combined exclusions', async () => {
  const { expandCombinedName } = await import('../src/utils/probeSupport.js')
  const ref = value => ({ value })
  const context = {
    popoverKey: ref(''), popOldStatus: ref(''), popStatus: ref('supported'), popExcludes: ref([]),
    popSupportedReg: ref([]), popSupportedPoc: ref([]), popSpecialTender: ref(false),
    popReplaceUnknown: ref(false),
    popCatApps: ref({ regular: [{ name: 'Previous category' }], poc: [] }), pendingChanges: {}, pendingExcludes: {},
    tplMap: ref({ '2_9': { default_support: 'supported', default_excludes: '["早\\\\中\\\\晚孕"]' } }),
    categoryAppsMap: ref({ 2: { regular: ['早孕', '中孕', '晚孕', '胎心'].map(name => ({ name })), poc: [{ name: '急诊' }] } }),
    expandCombinedName
  }
  const block = template.slice(template.indexOf('const openPopover ='), template.indexOf('// Per-group computed'))
  const open = new Function(...Object.keys(context), `${block}; return openPopover`)(...Object.values(context))
  open(2, 9)
  assert.deepEqual(context.popSupportedReg.value, ['胎心'])
  assert.deepEqual(context.popSupportedPoc.value, ['急诊'])
  assert.deepEqual(context.popExcludes.value, ['早孕', '中孕', '晚孕'])
})

test('opening and applying a template retains unresolved exclusions until explicitly replaced', async () => {
  const { expandCombinedName } = await import('../src/utils/probeSupport.js')
  const ref = value => ({ value })
  const context = {
    popoverKey: ref(''), popOldStatus: ref(''), popStatus: ref('supported'), popExcludes: ref([]),
    popSupportedReg: ref([]), popSupportedPoc: ref([]), popSpecialTender: ref(false), popReplaceUnknown: ref(false),
    popCatApps: ref({ regular: [], poc: [] }), pendingChanges: {}, pendingExcludes: {},
    tplMap: ref({ '2_9': { default_support: 'supported', default_excludes: '["早","中","晚孕","胎心"]' } }),
    categoryAppsMap: ref({ 2: { regular: ['早孕', '中孕', '晚孕', '胎心'].map(name => ({ name })), poc: [] } }),
    expandCombinedName
  }
  context.popUnknownExcludes = { get value() {
    const names = [...context.popCatApps.value.regular, ...context.popCatApps.value.poc].map(app => app.name)
    return context.popExcludes.value.filter(name => !names.includes(name))
  } }
  const openBlock = template.slice(template.indexOf('const openPopover ='), template.indexOf('// Per-group computed'))
  const applyBlock = template.slice(template.indexOf('const applyPopover ='), template.indexOf('const saveChanges ='))
  const actions = new Function(...Object.keys(context), `${openBlock};${applyBlock};return {openPopover,applyPopover}`)(...Object.values(context))
  actions.openPopover(2, 9); actions.applyPopover()
  assert.deepEqual(context.pendingExcludes['2_9'].excludes, ['早', '中', '晚孕', '胎心'])
  actions.openPopover(2, 9)
  assert.equal(context.popReplaceUnknown.value, false)
  context.popSupportedReg.value = ['早孕']; context.popReplaceUnknown.value = true
  actions.applyPopover()
  assert.deepEqual(context.pendingExcludes['2_9'].excludes, ['中孕', '晚孕', '胎心'])
})
