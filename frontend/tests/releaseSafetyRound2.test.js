import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { releaseWorkbenchStandaloneUrl } from '../src/utils/releaseWorkspace.js'

const feature = readFileSync(new URL('../src/views/FeatureRelease.vue', import.meta.url), 'utf8')
const workspace = readFileSync(new URL('../src/views/ReleaseWorkspace.vue', import.meta.url), 'utf8')
const source = (start, end) => feature.slice(feature.indexOf(start), feature.indexOf(end))

function closeAction(dirty, busy, confirm) {
  const context = { editSaving: { value: busy }, editDirty: { value: dirty }, editDialogVisible: { value: true }, confirmDiscard: confirm }
  const fn = new Function(...Object.keys(context), `${source('const requestEditClose =', '\nconst editVersion')}; return requestEditClose`)(...Object.values(context))
  return { context, fn }
}

test('version close: clean closes, declined discard retains input, confirmed closes, busy blocks', async () => {
  let calls = 0
  const clean = closeAction(false, false, async () => { calls++; return false })
  await clean.fn(); assert.equal(clean.context.editDialogVisible.value, false); assert.equal(calls, 0)
  const declined = closeAction(true, false, async () => false)
  await declined.fn(); assert.equal(declined.context.editDialogVisible.value, true)
  const accepted = closeAction(true, false, async () => true)
  let done = false; await accepted.fn(() => { done = true }); assert.equal(done, true); assert.equal(accepted.context.editDialogVisible.value, false)
  const busy = closeAction(true, true, async () => { throw Error('must not prompt') })
  await busy.fn(); assert.equal(busy.context.editDialogVisible.value, true)
})

test('workspace leave retains dirty input on cancel, restores baseline on discard and blocks busy', async () => {
  let decision = false
  const context = {
    editSaving: { value: false }, introBusy: { value: false }, editDialogVisible: { value: false }, editDirty: { value: false },
    introDirty: { value: true }, introBaseline: { value: { summary: '原文', applications: '原范围' } },
    introForm: { summary: '修改' }, introApplications: { value: '新范围' }, confirmDiscard: async () => decision
  }
  const fn = new Function(...Object.keys(context), `${source('async function requestWorkspaceLeave()', '\ndefineExpose')}; return requestWorkspaceLeave`)(...Object.values(context))
  assert.equal(await fn(), false); assert.equal(context.introForm.summary, '修改')
  decision = true; assert.equal(await fn(), true); assert.equal(context.introForm.summary, '原文'); assert.equal(context.introApplications.value, '原范围')
  context.introBusy.value = true; assert.equal(await fn(), false)
})

test('timeline ignores old responses and clears old target on failure', async () => {
  const calls = []
  const context = {
    selectedFeatureId: { value: 1 }, seriesFilter: { value: 'V10' }, timeline: { value: { feature: 'old' } },
    timelineError: { value: '' }, timelineLoading: { value: false },
    getFeatureReleaseTimeline: (id, params) => new Promise((resolve, reject) => calls.push({ id, params, resolve, reject }))
  }
  const load = new Function(...Object.keys(context), `let timelineRequestId = 0; ${source('const loadTimeline =', '\nconst openDocument')}; return loadTimeline`)(...Object.values(context))
  const a = load(); assert.equal(context.timeline.value, null)
  context.selectedFeatureId.value = 2; const b = load()
  calls[1].resolve({ feature: 'B' }); await b; calls[0].resolve({ feature: 'A' }); await a
  assert.equal(context.timeline.value.feature, 'B'); assert.equal(context.timelineLoading.value, false)
  const failed = load(); calls[2].reject(new Error('offline')); await failed
  assert.equal(context.timeline.value, null); assert.match(context.timelineError.value, /失败/)
  const retry = load(); calls[3].resolve({ feature: 'B again' }); await retry; assert.equal(context.timeline.value.feature, 'B again')
})

test('standalone links preserve same-origin workbench state and reject unsafe targets', () => {
  const origin = 'http://localhost:3006'
  const url = `${origin}/release-workbench/?embedded=1#search?project=1&q=%E5%90%8E%E5%8F%B0&task=earliest&versions=1.14.80`
  assert.equal(releaseWorkbenchStandaloneUrl('search', url, origin), '/release-workbench/#search?project=1&q=%E5%90%8E%E5%8F%B0&task=earliest&versions=1.14.80')
  assert.equal(releaseWorkbenchStandaloneUrl('search', 'https://evil.test/release-workbench/#search?x=1', origin), '/release-workbench/#search')
  assert.equal(releaseWorkbenchStandaloneUrl('search', `${origin}/evil/#search?x=1`, origin), '/release-workbench/#search')
  assert.equal(releaseWorkbenchStandaloneUrl('review', url, origin), '/release-workbench/#review')
})

test('component wires protection to close, tabs, routing and browser exit', () => {
  assert.match(feature, /:before-close="requestEditClose"/)
  assert.match(feature, /@click="requestEditClose"/)
  assert.match(feature, /addEventListener\('beforeunload', handleBeforeUnload\)/)
  assert.match(feature, /defineExpose\(\{ requestWorkspaceLeave \}\)/)
  assert.match(workspace, /:before-leave="beforeWorkspaceTabLeave"/)
  assert.match(workspace, /onBeforeRouteLeave\(/)
  assert.match(workspace, /onBeforeRouteUpdate\(/)
  assert.match(workspace, /event\.origin !== window\.location\.origin/)
  assert.match(workspace, /workbenchFrame\.value\?\.contentWindow !== event\.source/)
})

test('outer tab and route guards call the same component guard without a second discard prompt', async () => {
  let dirty = true, prompts = 0
  const context = { nativeRelease: { value: { requestWorkspaceLeave: async () => { if (dirty) { prompts++; dirty = false }; return true } } } }
  const block = workspace.slice(workspace.indexOf('async function beforeWorkspaceTabLeave'), workspace.indexOf('\nonBeforeRouteLeave'))
  const before = new Function(...Object.keys(context), `${block}; return beforeWorkspaceTabLeave`)(...Object.values(context))
  assert.equal(await before('search', 'feature-versions'), true)
  assert.equal(await before('search', 'feature-versions'), true)
  assert.equal(prompts, 1)
  assert.equal(await before('review', 'search'), true)
})

test('changing introduction target while dirty waits for consent and preserves input when declined', async () => {
  let requests = 0
  const context = {
    introBusy: { value: false }, introDirty: { value: true }, confirmDiscard: async () => false,
    introVersion: { value: { id: 1 } }, introFeatureName: { value: '' }, timeline: { value: null }, activeTab: { value: 'timeline' },
    introHistory: { value: [] }, introLoading: { value: false }, introLoadError: { value: false }, introBaseline: { value: {} },
    introForm: { summary: '未保存' }, introApplications: { value: '' }, introAttachments: { value: [] }, introSnapshot: () => ({}),
    getReleaseIntroduction: async () => { requests++; return {} }, ElMessage: { error() {} }
  }
  const open = new Function(...Object.keys(context), `let introRequestId = 0; ${source('const openIntroduction =', '\nconst saveIntroduction')}; return openIntroduction`)(...Object.values(context))
  await open({ id: 2 })
  assert.equal(requests, 0); assert.equal(context.introVersion.value.id, 1); assert.equal(context.introForm.summary, '未保存')
  context.confirmDiscard = async () => true
  const openAllowed = new Function(...Object.keys(context), `let introRequestId = 0; ${source('const openIntroduction =', '\nconst saveIntroduction')}; return openIntroduction`)(...Object.values(context))
  await openAllowed({ id: 2 }); assert.equal(requests, 1); assert.equal(context.introVersion.value.id, 2)
})

test('attachment upload rejects overlap explicitly and unlocks after failure for retry', async () => {
  let rejectUpload, calls = 0
  const attachmentBusy = { value: false }, introSaving = { value: false }
  const context = {
    introVersion: { value: { id: 1 } }, attachmentBusy,
    introBusy: { get value() { return attachmentBusy.value || introSaving.value } },
    introAttachments: { value: [] }, introRequestId: 1, messages: [],
    uploadReleaseAttachment: () => { calls++; return new Promise((resolve, reject) => { rejectUpload = reject }) },
    ElMessage: { warning: value => context.messages.push(value), error: value => context.messages.push(value), success() {} }
  }
  const upload = new Function(...Object.keys(context), `${source('const uploadAttachment =', '\nconst removeAttachment')}; return uploadAttachment`)(...Object.values(context))
  const first = upload('a'); await upload('b')
  assert.equal(calls, 1); assert.match(context.messages[0], /等待/)
  rejectUpload(Error('offline')); await first; assert.equal(attachmentBusy.value, false)
})

test('same-route navigation invokes native protection before the selected tab changes', async () => {
  const callbacks = {}
  let allowed = false, guarded = 0
  const nativeRelease = { value: { requestWorkspaceLeave: async () => { guarded++; return allowed } } }
  const activeTab = { value: 'feature-versions' }
  const onBeforeRouteUpdate = fn => { callbacks.update = fn }
  const onBeforeRouteLeave = fn => { callbacks.leave = fn }
  const normalizeReleaseTab = value => value || 'search'
  const block = workspace.slice(workspace.indexOf('async function beforeWorkspaceTabLeave'), workspace.indexOf('\nconst workbenchFrameUrl'))
  new Function('nativeRelease', 'activeTab', 'onBeforeRouteUpdate', 'onBeforeRouteLeave', 'normalizeReleaseTab', block)(nativeRelease, activeTab, onBeforeRouteUpdate, onBeforeRouteLeave, normalizeReleaseTab)
  assert.equal(await callbacks.update({ query: { tab: 'search' } }, { query: { tab: 'feature-versions' } }), false)
  assert.equal(activeTab.value, 'feature-versions')
  allowed = true
  assert.equal(await callbacks.update({ query: { tab: 'search' } }, { query: { tab: 'feature-versions' } }), true)
  assert.equal(guarded, 2)
})

test('iframe messages cannot navigate away from native edits or inject an external standalone URL', () => {
  const handlers = workspace.slice(workspace.indexOf('function handleWorkbenchMessage'), workspace.indexOf('\nwatch(() => route.query.tab'))
  const child = {}, activeTab = { value: 'feature-versions' }, workbenchLocations = {}
  const origin = 'http://localhost:3006'
  const isWorkbenchTab = value => ['search', 'review', 'releases', 'compare'].includes(value)
  const isWorkbenchNavigationMessage = event => event.data.type === 'release-workbench:navigate' && isWorkbenchTab(event.data.view)
  const handle = new Function('window', 'workbenchFrame', 'activeTab', 'workbenchLocations', 'isWorkbenchTab', 'isWorkbenchNavigationMessage', 'releaseWorkbenchStandaloneUrl', `${handlers}; return handleWorkbenchMessage`)({ location: { origin } }, { value: { contentWindow: child } }, activeTab, workbenchLocations, isWorkbenchTab, isWorkbenchNavigationMessage, releaseWorkbenchStandaloneUrl)
  handle({ origin, source: child, data: { type: 'release-workbench:navigate', view: 'search' } })
  assert.equal(activeTab.value, 'feature-versions')
  handle({ origin, source: child, data: { type: 'release-workbench:location', url: 'https://evil.test/release-workbench/#search?q=x' } })
  assert.equal(workbenchLocations.search, undefined)
  handle({ origin, source: child, data: { type: 'release-workbench:location', url: `${origin}/release-workbench/#search?q=x` } })
  assert.equal(workbenchLocations.search, `${origin}/release-workbench/#search?q=x`)
  handle({ origin: 'https://evil.test', source: child, data: { type: 'release-workbench:location', url: `${origin}/release-workbench/#search?q=bad` } })
  assert.equal(workbenchLocations.search, `${origin}/release-workbench/#search?q=x`)
})

test('a no-match search invalidates an in-flight timeline request', async () => {
  let resolveTimeline
  const context = {
    selectedFeatureId: { value: 1 }, seriesFilter: { value: '' }, timeline: { value: null }, timelineError: { value: '' }, timelineLoading: { value: false },
    featureQuery: { value: 'missing' }, featureOptions: { value: [] }, featureLoading: { value: false },
    getFeatureReleaseTimeline: () => new Promise(resolve => { resolveTimeline = resolve }),
    getKnowledgeFeatures: async () => ({ items: [] }), ElMessage: { info() {}, error() {} }
  }
  const searchBlock = source('const searchFeatures =', '\nconst searchFeaturesForDialog')
  const timelineBlock = source('const loadTimeline =', '\nconst openDocument')
  const actions = new Function(...Object.keys(context), `let timelineRequestId = 0; ${searchBlock}; ${timelineBlock}; return { searchFeatures, loadTimeline }`)(...Object.values(context))
  const pending = actions.loadTimeline()
  await actions.searchFeatures()
  resolveTimeline({ feature: 'old' }); await pending
  assert.equal(context.selectedFeatureId.value, null); assert.equal(context.timeline.value, null); assert.equal(context.timelineLoading.value, false)
})

test('deleting current version clears its introduction but preserves a different version draft', async () => {
  const removeBlock = source('const removeVersion =', '\n// ---------- 按版本查询')
  async function remove(currentId, dirty) {
    const context = {
      editForm: { id: 2 }, editDialogVisible: { value: true }, editSaving: { value: false }, introBusy: { value: false }, introDirty: { value: dirty },
      introVersion: { value: { id: currentId } }, introBaseline: { value: { summary: 'original' } },
      introAttachments: { value: ['attachment'] }, introHistory: { value: ['history'] }, introLoading: { value: false }, introLoadError: { value: false },
      ElMessageBox: { confirm: async () => {} }, ElMessage: { warning() {}, success() {}, error() {} },
      deleteReleaseVersion: async () => {}, loadTimeline: async () => {}, loadOverview: async () => {}
    }
    const action = new Function(...Object.keys(context), `let introRequestId = 0; ${removeBlock}; return removeVersion`)(...Object.values(context))
    await action(); return context
  }
  const current = await remove(2, false)
  assert.equal(current.introVersion.value, null); assert.deepEqual(current.introAttachments.value, [])
  const other = await remove(3, true)
  assert.equal(other.introVersion.value.id, 3); assert.deepEqual(other.introAttachments.value, ['attachment'])
  const protectedDraft = await remove(2, true)
  assert.equal(protectedDraft.introVersion.value.id, 2); assert.equal(protectedDraft.editDialogVisible.value, true)
})

test('all introduction fields participate in dirty detection and reverting disables save', () => {
  const block = source('const introBaseline = ref(null)', '\nconst introLoading = ref(false)')
  const introForm = { summary: '', clinical_significance: '', workflow: '', change_note: '', review_status: 'draft' }
  const introApplications = { value: '' }
  const ref = value => ({ value })
  const computed = get => ({ get value() { return get() } })
  const { introBaseline, introSnapshot, introDirty } = new Function('ref', 'computed', 'introForm', 'introApplications', `${block}; return { introBaseline, introSnapshot, introDirty }`)(ref, computed, introForm, introApplications)
  introBaseline.value = introSnapshot()
  for (const field of Object.keys(introForm)) {
    const previous = introForm[field]; introForm[field] = 'modified'
    assert.equal(introDirty.value, true, field)
    introForm[field] = previous; assert.equal(introDirty.value, false, field)
  }
  introApplications.value = 'one'; assert.equal(introDirty.value, true)
  introApplications.value = ''; assert.equal(introDirty.value, false)
})

test('delete locks the editor until completion and uses the captured version id', async () => {
  let finishDelete, deletedId
  const context = {
    editForm: { id: 2 }, editDialogVisible: { value: true }, editSaving: { value: false }, introBusy: { value: false }, introDirty: { value: false },
    introVersion: { value: { id: 3 } }, introBaseline: { value: {} }, introAttachments: { value: ['B'] }, introHistory: { value: [] }, introLoading: { value: false }, introLoadError: { value: false },
    ElMessageBox: { confirm: async () => {} }, ElMessage: { warning() {}, success() {}, error() {} },
    deleteReleaseVersion: id => { deletedId = id; return new Promise(resolve => { finishDelete = resolve }) }, loadTimeline: async () => {}, loadOverview: async () => {}
  }
  const remove = new Function(...Object.keys(context), `let introRequestId = 0; ${source('const removeVersion =', '\n// ---------- 按版本查询')}; return removeVersion`)(...Object.values(context))
  const pending = remove(); await Promise.resolve()
  assert.equal(context.editSaving.value, true); assert.equal(deletedId, 2)
  context.editForm.id = 3
  finishDelete(); await pending
  assert.equal(context.editSaving.value, false); assert.equal(context.introVersion.value.id, 3)
})

test('standalone workbench link keeps the independent whitepaper model selection', () => {
  const origin = 'http://127.0.0.1:3006'
  const url = `${origin}/release-workbench/?embedded=1#search?q=子宫&source_group=whitepaper&whitepaper_model=model%3A6s`
  assert.equal(releaseWorkbenchStandaloneUrl('search', url, origin), '/release-workbench/#search?q=%E5%AD%90%E5%AE%AB&source_group=whitepaper&whitepaper_model=model%3A6s')
  assert.equal(releaseWorkbenchStandaloneUrl('search', 'https://evil.test/release-workbench/#search?whitepaper_model=model%3A6s', origin), '/release-workbench/#search')
})
