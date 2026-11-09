import api from './index'
const base = '/probes/workspaces'
export const listProbeWorkspaces = () => api.get(base)
export const getProbeCatalog = () => api.get(`${base}/catalog`)
export const createProbeWorkspace = data => api.post(base, data)
export const getProbeWorkspace = (id, refreshTemplate = false) => api.get(`${base}/${id}`, { params: { refresh_template: refreshTemplate } })
export const saveProbeDraft = (id, data) => api.put(`${base}/${id}/draft`, data)
export const discardProbeDraft = (id, revision) => api.post(`${base}/${id}/discard`, { revision })
export const getProbeResults = id => api.get(`${base}/${id}/results`)
export const previewProbeRelease = (id, data) => api.post(`${base}/${id}/preview`, data)
export const publishProbeRelease = (id, data) => api.post(`${base}/${id}/publish`, data)
export const listProbeReleases = id => api.get(`${base}/${id}/releases`)
export const getProbeRelease = (id, release) => api.get(`${base}/${id}/releases/${release}`)
export const restoreProbeRelease = (id, release, revision) => api.post(`${base}/${id}/releases/${release}/restore`, { revision })
export const compareProbeReleases = (id, before, after) => api.get(`${base}/${id}/compare`, { params: { before, after } })
export const exportProbeWorkbook = (id, releaseId) => api.get(`${base}/${id}/export`, { params: { release_id: releaseId }, responseType: 'blob' })
export const previewProbeImport = (id, file) => { const data = new FormData(); data.append('file', file); return api.post(`${base}/${id}/import-preview`, data) }
