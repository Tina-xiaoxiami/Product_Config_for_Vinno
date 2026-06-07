import api from './index'

// ==================== 产品系列 ====================
export const getSeriesList = (params) => api.get('/series', { params })
export const getSeries = (id) => api.get(`/series/${id}`)
export const createSeries = (data) => api.post('/series', data)
export const updateSeries = (id, data) => api.put(`/series/${id}`, data)
export const deleteSeries = (id) => api.delete(`/series/${id}`)

// ==================== 产品型号 ====================
export const getModels = (seriesId, params) => api.get('/models', { params: { series_id: seriesId, ...params } })
export const getModel = (id) => api.get(`/models/${id}`)
export const createModel = (data) => api.post('/models', data)
export const updateModel = (id, data) => api.put(`/models/${id}`, data)
export const deleteModel = (id) => api.delete(`/models/${id}`)

// ==================== 配置数据 ====================
export const getConfigRows = (params) => api.get('/config/rows', { params })
export const updateConfigValue = (valueId, data) => api.put(`/config/value/${valueId}`, null, { params: data })
export const compareConfigs = (data) => api.post('/config/compare', data)
export const exportCompareResult = (data) => api.post('/config/compare/export', data, { responseType: 'blob' })
export const batchUpdateConfigValues = (data) => api.post('/config/batch-update', data)

// ==================== 版本管理 ====================
export const getVersions = (seriesId, params) => api.get('/versions', { params: { series_id: seriesId, ...params } })
export const getVersion = (id) => api.get(`/versions/${id}`)
export const createVersion = (data) => api.post('/versions', data)
export const updateVersion = (id, data) => api.put(`/versions/${id}`, null, { params: data })
export const deleteVersion = (id) => api.delete(`/versions/${id}`)
export const compareVersions = (data) => api.post('/versions/compare', data)
export const rollbackVersion = (id) => api.post(`/versions/${id}/rollback`)
export const exportVersionCompare = (data) => api.post('/versions/compare/export', data, { responseType: 'blob' })
export const getChangeLogs = (params) => api.get('/versions/change-logs', { params })
export const getChangeLog = (id) => api.get(`/versions/change-logs/${id}`)

// ==================== 版本清理 ====================
export const getStorageStatus = () => api.get('/version-cleanup/status')
export const checkVersionPolicy = () => api.get('/version-cleanup/check-policy')
export const cleanupOldVersions = (dryRun = true) => api.post('/version-cleanup/cleanup', null, { params: { dry_run: dryRun } })

// ==================== 草稿管理 ====================
export const getCurrentDraftBatch = (seriesId) => api.get(`/drafts/batch/current/${seriesId}`)
export const getDraftBatch = (batchId) => api.get(`/drafts/batch/${batchId}`)
export const createDraftBatch = (seriesId, filename) => api.post('/drafts/batch', null, { params: { series_id: seriesId, filename } })
export const getDraftStats = (batchId) => api.get(`/drafts/batch/${batchId}/stats`)
export const getDraftList = (batchId) => api.get(`/drafts/batch/${batchId}/drafts`)
export const createDraft = (data) => api.post('/drafts/draft', data)
export const submitDraftBatch = (batchId, data) => api.post(`/drafts/batch/${batchId}/submit`, data)
export const discardDraftBatch = (batchId) => api.delete(`/drafts/batch/${batchId}`)
export const deleteDraft = (draftId) => api.delete(`/drafts/draft/${draftId}`)
export const deleteDraftByKey = (batchId, itemId, modelId, fieldName) =>
  api.delete('/drafts/draft/by-key', { params: { batch_id: batchId, item_id: itemId, model_id: modelId, field_name: fieldName } })
export const batchDiscardDrafts = (data) => api.post('/drafts/batch/discard', data)
export const batchSubmitDrafts = (data) => api.post('/drafts/batch/submit', data)

// ==================== 导入导出 ====================
// 不设置 Content-Type，让 axios 自动处理（包含 boundary）
export const importExcel = (formData, params) => api.post('/import-export/import', formData, { params })
export const previewImport = (formData) => api.post('/import-export/preview', formData)
export const exportExcel = (seriesId, params) => api.get('/import-export/export', {
  params: { series_id: seriesId, ...params },
  responseType: 'blob'
})
export const downloadTemplate = () => api.get('/import-export/template', {
  responseType: 'blob'
})

// ==================== 枚举值 ====================
export const getEnumValues = (params) => api.get('/enums/extract', { params })
export const getSelectionTypes = () => api.get('/enums/selection-types')
export const getRdStatuses = () => api.get('/enums/rd-statuses')
export const getConfigValueOptions = () => api.get('/enums/config-values')