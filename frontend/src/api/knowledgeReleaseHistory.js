import api from './index'
export const traceReleaseHistory = data => api.post('/knowledge/release-history/trace', data)
export const getReleaseHistoryDocuments = params => api.get('/knowledge/release-history/documents', { params })
export const getReleaseHistoryBindings = params => api.get('/knowledge/release-history/bindings', { params })
export const saveReleaseHistoryBindings = data => api.post('/knowledge/release-history/bindings', data)
export const deactivateReleaseHistoryBinding = (id, revision) => api.delete(`/knowledge/release-history/bindings/${id}`, { params: { expected_revision: revision } })
