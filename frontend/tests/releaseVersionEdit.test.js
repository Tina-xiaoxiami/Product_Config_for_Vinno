import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { releaseVersionChanged, releaseVersionPayload } from '../src/utils/releaseVersionEdit.js'

const source = readFileSync(new URL('../src/views/FeatureRelease.vue', import.meta.url), 'utf8')
const actionSource = source.slice(source.indexOf('const submitEdit = async () => {'), source.indexOf('\nconst removeVersion'))

function setup() {
  const form = { id: 42, software_version: '1.14.80', product_series: 'V10', release_date: null, change_type: 'unknown', configuration_status: '', lifecycle_status: 'undefined', review_status: 'pending', change_note: '' }
  const baseline = releaseVersionPayload(form)
  const context = {
    editForm: form, editSaving: { value: false }, editDialogVisible: { value: true },
    editDirty: { get value() { return releaseVersionChanged(form, baseline) } },
    releaseVersionPayload, calls: [], messages: [],
    async updateReleaseVersion(id, payload) { context.calls.push({ id, payload }) },
    ElMessage: { success: message => context.messages.push(message), error: message => context.messages.push(message) },
    async loadTimeline() {}, async loadOverview() {}
  }
  const submit = new Function(...Object.keys(context), `${actionSource}; return submitEdit`)(...Object.values(context))
  return { context, submit }
}

test('edit detects changes and reverting fields restores unchanged state', () => {
  const { context } = setup()
  assert.equal(context.editDirty.value, false)
  context.editForm.review_status = 'confirmed'
  assert.equal(context.editDirty.value, true)
  context.editForm.review_status = 'pending'
  assert.equal(context.editDirty.value, false)
  assert.equal(releaseVersionChanged(context.editForm, null), false)
})

test('actual edit action skips unchanged and in-flight submissions, then closes after success', async () => {
  const { context, submit } = setup()
  await submit()
  assert.equal(context.calls.length, 0)
  context.editForm.change_note = '依据已更新'
  context.editSaving.value = true
  await submit()
  assert.equal(context.calls.length, 0)
  context.editSaving.value = false
  await submit()
  assert.equal(context.calls.length, 1)
  assert.equal(context.calls[0].payload.change_note, '依据已更新')
  assert.equal(context.editDialogVisible.value, false)
  assert.equal(context.editSaving.value, false)
})

test('failed edit keeps dialog and input for retry', async () => {
  const { context } = setup()
  context.editForm.change_note = '保留我的输入'
  context.updateReleaseVersion = async () => { throw new Error('offline') }
  const submit = new Function(...Object.keys(context), `${actionSource}; return submitEdit`)(...Object.values(context))
  await submit()
  assert.equal(context.editDialogVisible.value, true)
  assert.equal(context.editForm.change_note, '保留我的输入')
  assert.equal(context.editSaving.value, false)
  assert.ok(context.messages.includes('保存失败'))
})

const introSource = source.slice(source.indexOf('const openIntroduction = async (row) => {'), source.indexOf('\nconst saveIntroduction'))

function setupIntroduction(fetch) {
  const context = {
    introVersion: { value: null }, introFeatureName: { value: '' }, timeline: { value: null }, activeTab: { value: '' },
    introHistory: { value: [] }, introLoading: { value: false }, introLoadError: { value: false },
    introForm: { summary: '上一个版本的内容' }, introApplications: { value: '' }, introAttachments: { value: [] },
    getReleaseIntroduction: fetch, ElMessage: { error() {} }
  }
  const open = new Function(...Object.keys(context), `let introRequestId = 0; ${introSource}; return openIntroduction`)(...Object.values(context))
  return { context, open }
}

test('failed introduction load blocks save and keeps error visible until retry', async () => {
  let fail = true
  const { context, open } = setupIntroduction(async () => {
    if (fail) throw new Error('offline')
    return { summary: '当前版本内容' }
  })
  await open({ id: 2 })
  assert.equal(context.introLoadError.value, true)
  assert.equal(context.introLoading.value, false)
  fail = false
  await open({ id: 2 })
  assert.equal(context.introLoadError.value, false)
  assert.equal(context.introForm.summary, '当前版本内容')
})

test('late introduction response cannot overwrite the newly selected version', async () => {
  let resolveFirst
  const first = new Promise(resolve => { resolveFirst = resolve })
  const { context, open } = setupIntroduction(id => id === 1 ? first : Promise.resolve({ summary: '新版本' }))
  const pending = open({ id: 1 })
  await open({ id: 2 })
  resolveFirst({ summary: '旧版本' })
  await pending
  assert.equal(context.introVersion.value.id, 2)
  assert.equal(context.introForm.summary, '新版本')
  assert.equal(context.introLoading.value, false)
})

test('actual introduction save action refuses failed or pending loads', async () => {
  const saveSource = source.slice(source.indexOf('const saveIntroduction = async () => {'), source.indexOf('\nconst loadIntroductionHistory'))
  let calls = 0
  const context = {
    introRequestId: 1, introVersion: { value: { id: 2 } }, introLoading: { value: true }, introLoadError: { value: false }, introSaving: { value: false },
    introForm: { summary: '旧内容' }, introApplications: { value: '' }, introAttachments: { value: [] },
    saveReleaseIntroduction: async () => { calls++; return {} }, ElMessage: { success() {}, error() {} },
    loadIntroductionHistory: async () => {}
  }
  const save = new Function(...Object.keys(context), `${saveSource}; return saveIntroduction`)(...Object.values(context))
  await save()
  context.introLoading.value = false
  context.introLoadError.value = true
  await save()
  assert.equal(calls, 0)
})

test('saving a previous introduction cannot replace the current attachments', async () => {
  const saveSource = source.slice(source.indexOf('const saveIntroduction = async () => {'), source.indexOf('\nconst loadIntroductionHistory'))
  let resolveSave
  const pendingSave = new Promise(resolve => { resolveSave = resolve })
  const context = {
    introVersion: { value: { id: 1 } }, introLoading: { value: false }, introLoadError: { value: false }, introSaving: { value: false },
    introForm: { summary: '旧版本' }, introApplications: { value: '' }, introAttachments: { value: [] },
    saveReleaseIntroduction: () => pendingSave, ElMessage: { success() {}, error() {} },
    loadIntroductionHistory: async () => { throw new Error('must not load history for changed version') }
  }
  const actions = new Function(...Object.keys(context), `let introRequestId = 1; ${saveSource}; return { saveIntroduction, nextVersion() { introRequestId++ } }`)(...Object.values(context))
  const saving = actions.saveIntroduction()
  actions.nextVersion()
  context.introVersion.value = { id: 2 }
  context.introAttachments.value = ['新版本附件']
  resolveSave({ attachments: ['旧版本附件'] })
  await saving
  assert.deepEqual(context.introAttachments.value, ['新版本附件'])
})

test('edit dialog locks form, closing and deletion while save is running', () => {
  const dialog = source.slice(source.indexOf('<el-dialog v-model="editDialogVisible"'), source.indexOf('<el-dialog\n      v-model="batchDialogVisible"'))
  assert.match(dialog, /:disabled="editSaving"/)
  assert.match(dialog, /:show-close="!editSaving"/)
  assert.match(dialog, /:close-on-click-modal="!editSaving"/)
  assert.match(dialog, /:close-on-press-escape="!editSaving"/)
})

test('old attachment upload does not overwrite the newly selected version', async () => {
  const attachmentSource = source.slice(source.indexOf('const uploadAttachment = async (file) => {'), source.indexOf('\nconst removeAttachment'))
  let resolveUpload
  const context = {
    introVersion: { value: { id: 1 } }, introAttachments: { value: [] },
    uploadReleaseAttachment: () => new Promise(resolve => { resolveUpload = resolve }),
    ElMessage: { success() {}, warning() {}, error() {} }
  }
  const actions = new Function(...Object.keys(context), `let introRequestId = 1; ${attachmentSource}; return { uploadAttachment, nextVersion() { introRequestId++ } }`)(...Object.values(context))
  const upload = actions.uploadAttachment('file')
  actions.nextVersion()
  context.introVersion.value = { id: 2 }
  context.introAttachments.value = ['新版本附件']
  resolveUpload({ attachments: ['旧版本附件'] })
  await upload
  assert.deepEqual(context.introAttachments.value, ['新版本附件'])
})

test('old attachment deletion does not alter the newly selected version', async () => {
  const removeSource = source.slice(source.indexOf('const removeAttachment = async (row) => {'), source.indexOf('\n// ---------- 候选回填'))
  let resolveDelete
  const context = {
    introAttachments: { value: [{ id: 7 }] },
    deleteReleaseAttachment: () => new Promise(resolve => { resolveDelete = resolve }),
    ElMessage: { success() {}, error() {} }
  }
  const actions = new Function(...Object.keys(context), `let introRequestId = 1; ${removeSource}; return { removeAttachment, nextVersion() { introRequestId++ } }`)(...Object.values(context))
  const removal = actions.removeAttachment({ id: 7 })
  actions.nextVersion()
  context.introAttachments.value = [{ id: 7 }, { id: 8 }]
  resolveDelete()
  await removal
  assert.deepEqual(context.introAttachments.value, [{ id: 7 }, { id: 8 }])
})
