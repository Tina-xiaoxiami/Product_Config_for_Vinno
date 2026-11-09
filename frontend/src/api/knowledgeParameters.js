import api from './index'
export const getParameterTopics = () => api.get('/knowledge/parameter-topics')
export const createParameterTopic = data => api.post('/knowledge/parameter-topics', data)
export const getParameterSpecs = topicId => api.get(`/knowledge/parameter-topics/${topicId}/specs`)
export const createParameterSpec = (topicId, data) => api.post(`/knowledge/parameter-topics/${topicId}/specs`, data)
export const updateParameterSpec = (topicId, specId, data) => api.put(`/knowledge/parameter-topics/${topicId}/specs/${specId}`, data)
export const getParameterSnapshot = versionId => api.get(`/knowledge/parameter-snapshots/${versionId}`)
export const previewParameterTopic = (topicId, data) => api.post(`/knowledge/parameter-topics/${topicId}/preview`, data)
