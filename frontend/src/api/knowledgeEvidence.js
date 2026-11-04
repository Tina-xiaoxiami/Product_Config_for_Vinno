import api from './index'

export const getKnowledgeEvidenceCapabilities = signal => api.get('/knowledge/document-answer/capabilities', { signal })
export const generateKnowledgeEvidenceAnswer = (data, signal) => api.post('/knowledge/document-answer', data, { signal, timeout: 240000 })
