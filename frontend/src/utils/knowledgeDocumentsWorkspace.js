export const DOCUMENT_TYPE_OPTIONS = [
  { label: '注册证/注册变更', value: 'registration_certificate' },
  { label: '注册差异表', value: 'registration_difference' },
  { label: '注册跟踪表', value: 'registration_tracking' },
  { label: '产品说明书', value: 'manual' },
  { label: '产品白皮书', value: 'whitepaper' },
  { label: 'Release Note', value: 'release_note' }
]

export const documentTypeLabel = type => type === 'registration_certificate' ? '注册证/变更' : DOCUMENT_TYPE_OPTIONS.find(item => item.value === type)?.label || type
export const canInlineDocument = document => document.mime_type === 'application/pdf' || Boolean(document.mime_type?.startsWith('image/'))
export function formatDocumentFileSize(size) {
  if (!size) return '0 KB'
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

export function createDocumentState() {
  return {
    query: '', documentType: '', page: 1, pageSize: 50,
    items: [], total: 0, loading: false, error: '', operationError: '',
    extractionLoading: {}, archiveLoading: {}
  }
}

const errorMessage = (error, fallback) => error?.response?.data?.detail || error?.message || fallback

export function createDocumentWorkspace(api, state) {
  let requestId = 0, disposed = false

  async function loadDocuments() {
    if (disposed) return false
    const currentRequest = ++requestId
    state.loading = true
    state.error = ''
    try {
      const result = await api.getKnowledgeDocuments({
        q: state.query.trim() || undefined,
        document_type: state.documentType || undefined,
        skip: (state.page - 1) * state.pageSize,
        limit: state.pageSize
      })
      if (disposed || currentRequest !== requestId) return false
      state.items = result.items || []
      state.total = result.total || 0
      const lastPage = Math.max(1, Math.ceil(state.total / state.pageSize))
      if (!state.items.length && state.page > lastPage) {
        state.page = lastPage
        return await loadDocuments()
      }
      return true
    } catch (error) {
      if (!disposed && currentRequest === requestId) state.error = errorMessage(error, '资料加载失败，请重试')
      return false
    } finally {
      if (!disposed && currentRequest === requestId) state.loading = false
    }
  }

  function searchDocuments() {
    state.page = 1
    return loadDocuments()
  }

  async function extractDocument(document) {
    if (disposed || state.extractionLoading[document.id] || state.archiveLoading[document.id]) return false
    state.extractionLoading = { ...state.extractionLoading, [document.id]: true }
    state.operationError = ''
    try {
      const result = await api.extractKnowledgeDocument(document.id, document.extraction_status === 'completed')
      if (disposed) return false
      api.notify(`正文提取完成：${result.chunk_count} 个片段`)
      await loadDocuments()
      return true
    } catch (error) {
      if (!disposed) state.operationError = errorMessage(error, '正文提取失败')
      return false
    } finally {
      if (!disposed) state.extractionLoading = { ...state.extractionLoading, [document.id]: false }
    }
  }

  async function archiveDocument(document) {
    if (disposed || state.archiveLoading[document.id] || state.extractionLoading[document.id]) return false
    state.archiveLoading = { ...state.archiveLoading, [document.id]: true }
    state.operationError = ''
    try {
      if (!await api.confirmArchive(document) || disposed) return false
      const result = await api.archiveKnowledgeDocument(document.id)
      if (disposed) return false
      api.notify(`已归档「${document.title}」，清除正文片段 ${result.removed_chunks} 条`)
      await loadDocuments()
      return true
    } catch (error) {
      if (!disposed) state.operationError = errorMessage(error, '归档失败')
      return false
    } finally {
      if (!disposed) state.archiveLoading = { ...state.archiveLoading, [document.id]: false }
    }
  }

  async function openDocumentLocally(document, mode) {
    if (disposed) return false
    state.operationError = ''
    try {
      const result = await api.openKnowledgeDocumentLocally(document.id, mode)
      if (disposed) return false
      api.notify(mode === 'reveal' ? `已在访达中定位 ${result.file_name}` : `已在本机打开 ${result.file_name}`)
      return true
    } catch (error) {
      if (!disposed) state.operationError = errorMessage(error, '本机打开失败')
      return false
    }
  }

  function dispose() { disposed = true; requestId++ }
  return { loadDocuments, searchDocuments, extractDocument, archiveDocument, openDocumentLocally, dispose }
}
