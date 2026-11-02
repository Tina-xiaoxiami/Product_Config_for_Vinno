import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  canInlineDocument,
  createDocumentState,
  createDocumentWorkspace,
  documentTypeLabel
} from '../src/utils/knowledgeDocumentsWorkspace.js'
import { isWorkbenchNavigationMessage, normalizeReleaseTab, releaseWorkbenchUrl } from '../src/utils/releaseWorkspace.js'

const deferred = () => {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
function workspace(overrides = {}) {
  const calls = [], notifications = [], state = createDocumentState()
  const api = {
    getKnowledgeDocuments: async params => { calls.push(params); return { items: [{ id: 1 }], total: 1 } },
    extractKnowledgeDocument: async () => ({ chunk_count: 3 }),
    archiveKnowledgeDocument: async () => ({ removed_chunks: 3 }),
    openKnowledgeDocumentLocally: async () => ({ file_name: 'source.pdf' }),
    confirmArchive: async () => true,
    notify: message => notifications.push(message),
    ...overrides
  }
  return { ...createDocumentWorkspace(api, state), state, calls, notifications }
}

test('documents has one native management destination and cannot create a workbench iframe', () => {
  assert.equal(normalizeReleaseTab('documents'), 'documents')
  assert.equal(releaseWorkbenchUrl('documents'), '')
  const view = readFileSync(new URL('../src/views/ReleaseWorkspace.vue', import.meta.url), 'utf8')
  assert.match(view, /label="原始资料"\s+name="documents"/)
  assert.match(view, /<KnowledgeDocumentsWorkspace\s+:active="activeTab === 'documents'"\s*\/>/)
  assert.match(view, /activeTab\.value === 'search' \? 'documents'/)
})

test('background workbench navigation cannot take over the native documents manager', () => {
  const source = readFileSync(new URL('../src/views/ReleaseWorkspace.vue', import.meta.url), 'utf8')
  const body = source.slice(source.indexOf('function handleWorkbenchMessage(event)'), source.indexOf('\nwatch(() => route.query.tab'))
  const child = {}, origin = 'http://127.0.0.1:3006'
  const context = {
    window: { location: { origin } }, workbenchFrame: { value: { contentWindow: child } },
    activeTab: { value: 'documents' }, isWorkbenchTab: tab => ['search', 'review', 'releases', 'compare'].includes(tab),
    isWorkbenchNavigationMessage
  }
  const handle = new Function(...Object.keys(context), `${body};return handleWorkbenchMessage`)(...Object.values(context))
  const event = { origin, source: child, data: { type: 'release-workbench:navigate', view: 'compare' } }
  handle(event); assert.equal(context.activeTab.value, 'documents')
  context.activeTab.value = 'search'; handle(event); assert.equal(context.activeTab.value, 'compare')
})

test('document paging and search reuse the existing catalog API with complete scope', async () => {
  const x = workspace()
  x.state.query = 'V10'; x.state.documentType = 'release_note'; x.state.page = 3
  await x.loadDocuments()
  assert.deepEqual(x.calls[0], { q: 'V10', document_type: 'release_note', skip: 100, limit: 50 })
  await x.searchDocuments()
  assert.equal(x.state.page, 1)
  assert.equal(x.calls.at(-1).skip, 0)
})

test('late catalog responses cannot replace results for the latest filter', async () => {
  const old = deferred()
  const x = workspace({ getKnowledgeDocuments: params => params.q === 'old' ? old.promise : Promise.resolve({ items: [{ id: 2 }], total: 1 }) })
  x.state.query = 'old'; const first = x.loadDocuments()
  x.state.query = 'new'; await x.searchDocuments()
  old.resolve({ items: [{ id: 1 }], total: 1 }); await first
  assert.deepEqual(x.state.items, [{ id: 2 }])
  assert.equal(x.state.loading, false)
})

test('failed loads retain the previous rows and filter while exposing a retryable error', async () => {
  let failed = false
  const x = workspace({ getKnowledgeDocuments: async () => {
    if (failed) throw new Error('offline')
    return { items: [{ id: 3 }], total: 1 }
  } })
  await x.loadDocuments(); failed = true; x.state.query = 'whitepaper'
  assert.equal(await x.loadDocuments(), false)
  assert.deepEqual(x.state.items, [{ id: 3 }]); assert.equal(x.state.query, 'whitepaper')
  assert.match(x.state.error, /offline/)
  failed = false; await x.loadDocuments(); assert.equal(x.state.error, '')
})

test('archiving the last row on a page returns to the remaining last page', async () => {
  const pages = []
  const x = workspace({ getKnowledgeDocuments: async params => {
    pages.push(params.skip)
    return params.skip ? { items: [], total: 50 } : { items: [{ id: 5 }], total: 50 }
  } })
  x.state.page = 2
  assert.equal(await x.archiveDocument({ id: 7, title: 'Source' }), true)
  assert.deepEqual(pages, [50, 0]); assert.equal(x.state.page, 1)
  assert.deepEqual(x.state.items, [{ id: 5 }])
})

test('archive cancellation and cited-document rejection never report successful removal', async () => {
  let writes = 0
  const cancelled = workspace({ confirmArchive: async () => false, archiveKnowledgeDocument: async () => { writes++ } })
  assert.equal(await cancelled.archiveDocument({ id: 1, title: 'Source' }), false)
  assert.equal(writes, 0)
  const rejected = workspace({ archiveKnowledgeDocument: async () => { throw { response: { data: { detail: '仍被正式答案引用' } } } } })
  assert.equal(await rejected.archiveDocument({ id: 1, title: 'Source' }), false)
  assert.match(rejected.state.operationError, /正式答案引用/)
  assert.deepEqual(rejected.notifications, [])
})

test('extracting is deduplicated and re-extraction uses the existing force flag', async () => {
  const extraction = deferred(), extracted = []
  const x = workspace({ extractKnowledgeDocument: (id, force) => { extracted.push({ id, force }); return extraction.promise } })
  const document = { id: 9, extraction_status: 'completed' }
  const first = x.extractDocument(document)
  assert.equal(await x.extractDocument(document), false)
  extraction.resolve({ chunk_count: 4 }); assert.equal(await first, true)
  assert.deepEqual(extracted, [{ id: 9, force: true }])
  assert.equal(x.state.extractionLoading[9], false)
})

test('extract and archive never race against each other on one document', async () => {
  const pending = deferred(); let archives = 0
  const x = workspace({ extractKnowledgeDocument: () => pending.promise, archiveKnowledgeDocument: async () => { archives++; return { removed_chunks: 1 } } })
  const first = x.extractDocument({ id: 4 })
  assert.equal(await x.archiveDocument({ id: 4, title: 'Source' }), false)
  assert.equal(archives, 0)
  pending.resolve({ chunk_count: 1 }); await first
})

test('disposed document workspaces cannot update rows or show a late extraction notification', async () => {
  const extraction = deferred()
  const x = workspace({ extractKnowledgeDocument: () => extraction.promise })
  const first = x.extractDocument({ id: 5 })
  x.dispose(); extraction.resolve({ chunk_count: 2 }); await first
  assert.deepEqual(x.notifications, []); assert.deepEqual(x.calls, [])
})

test('document previews preserve PDF/image behavior and the existing local-open operation', async () => {
  assert.equal(canInlineDocument({ mime_type: 'application/pdf' }), true)
  assert.equal(canInlineDocument({ mime_type: 'image/png' }), true)
  assert.equal(canInlineDocument({ mime_type: 'application/msword' }), false)
  assert.equal(documentTypeLabel('registration_tracking'), '注册跟踪表')
  const opened = []
  const x = workspace({ openKnowledgeDocumentLocally: async (id, mode) => { opened.push({ id, mode }); return { file_name: 'source.pdf' } } })
  await x.openDocumentLocally({ id: 8 }, 'reveal')
  assert.deepEqual(opened, [{ id: 8, mode: 'reveal' }])
})
