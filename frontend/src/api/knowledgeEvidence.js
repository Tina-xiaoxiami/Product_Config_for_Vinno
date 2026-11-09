import api from './index'

export const getKnowledgeEvidenceCapabilities = signal => api.get('/knowledge/document-answer/capabilities', { signal })
export const generateKnowledgeEvidenceAnswer = (data, signal) => api.post('/knowledge/document-answer', data, { signal, timeout: 240000 })
export const getKnowledgeCitation = (documentId, params, signal) => api.get(`/knowledge/documents/${documentId}/evidence`, { params, signal })
export const getKnowledgeSpreadsheetCitations = (questionId, version, signal) => api.get(`/knowledge/questions/${questionId}/spreadsheet-citations`, { params: { expected_version: version }, signal })
export const getKnowledgeConfigurationHistory = (recipe, modelId) => api.get('/knowledge/questions/configuration-history', { params: { recipe, model_id: modelId } })
