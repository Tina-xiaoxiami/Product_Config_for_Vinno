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
export const exportExcel = (seriesId, params) => api.post('/import-export/export', {
  series_id: seriesId,
  ...params
}, {
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

// ==================== 探头配置 ====================
// 探头类别
export const getProbeCategories = (params) => api.get('/probe-categories', { params })
export const createProbeCategory = (data) => api.post('/probe-categories', data)
export const updateProbeCategory = (id, data) => api.put(`/probe-categories/${id}`, data)
export const deleteProbeCategory = (id) => api.delete(`/probe-categories/${id}`)

// 探头型号
export const getProbeModels = (params) => api.get('/probe-models', { params })
export const createProbeModel = (data) => api.post('/probe-models', data)
export const updateProbeModel = (id, data) => api.put(`/probe-models/${id}`, data)
export const deleteProbeModel = (id) => api.delete(`/probe-models/${id}`)
export const getProbeModelApps = (modelId) => api.get(`/probe-models/${modelId}/apps`)
export const exportVariantsExcel = () => api.get('/probe-models/variants/export', { responseType: 'blob' })
export const importVariantsExcel = (formData) => api.post('/probe-models/variants/import', formData)
export const exportModelVariantsExcel = (modelId) => api.get(`/probe-models/${modelId}/variants/export`, { responseType: 'blob' })
export const importModelVariantsExcel = (modelId, formData) => api.post(`/probe-models/${modelId}/variants/import`, formData)
export const autoPopulateVariants = () => api.post('/probe-models/variants/auto-populate')
export const setProbeModelApps = (modelId, appIds) => api.post(`/probe-models/${modelId}/apps`, { app_ids: appIds })

// 应用定义
export const getApplications = (params) => api.get('/applications', { params })
export const createApplication = (data) => api.post('/applications', data)
export const updateApplication = (id, data) => api.put(`/applications/${id}`, data)
export const deleteApplication = (id) => api.delete(`/applications/${id}`)

// 功能组 & 功能
export const getFeatureGroups = (params) => api.get('/features/groups', { params })
export const createFeatureGroup = (data) => api.post('/features/groups', data)
export const updateFeatureGroup = (id, data) => api.put(`/features/groups/${id}`, data)
export const deleteFeatureGroup = (id) => api.delete(`/features/groups/${id}`)
export const getFeatures = (params) => api.get('/features', { params })
export const createFeature = (data) => api.post('/features', data)
export const updateFeature = (id, data) => api.put(`/features/${id}`, data)
export const deleteFeature = (id) => api.delete(`/features/${id}`)
export const getFeatureMasterData = (id) => api.get(`/features/${id}/master-data`)
export const createFeatureMasterData = (data) => api.post('/features/master-data', data)
export const updateFeatureMasterData = (id, data) => api.put(`/features/${id}/master-data`, data)

// 模板配置
export const getTemplateFeatures = (categoryId) => api.get('/template-features/by-category/' + categoryId)
export const saveTemplateFeature = (data) => api.post('/template-features', data)
export const deleteTemplateFeature = (id) => api.delete(`/template-features/${id}`)

// 产品探头配置
export const getProbeConfig = (productModelId) => api.get(`/probes/config/${productModelId}`)
export const initProbeConfig = (productModelId, data) => api.post(`/probes/config/${productModelId}/init`, data)
export const updateProbeFeature = (productModelId, data) => api.put(`/probes/config/${productModelId}/feature`, data)
export const getProbeDrafts = (productModelId) => api.get(`/probes/config/${productModelId}/drafts`)
export const submitProbeDrafts = (productModelId, data) => api.post(`/probes/config/${productModelId}/submit`, data)
export const discardProbeDrafts = (productModelId) => api.post(`/probes/config/${productModelId}/discard`)
export const getProbeVersions = (productModelId) => api.get(`/probes/config/${productModelId}/versions`)
export const rollbackProbeVersion = (productModelId, versionId) => api.post(`/probes/config/${productModelId}/rollback/${versionId}`)
export const exportProbeConfig = (productModelId) => api.get(`/probes/config/${productModelId}/export`, { responseType: 'blob' })
export const applyTemplateToProduct = (productModelId) => api.post(`/probes/config/${productModelId}/apply-template`)
export const batchSetStatus = (productModelId, data) => api.post(`/probes/config/${productModelId}/batch-set`, data)
export const getProductProbes = (productModelId) => api.get(`/probes/config/${productModelId}/probes`)
export const setProductProbes = (productModelId, data) => api.post(`/probes/config/${productModelId}/probes`, data)
export const batchFromTemplate = (productModelId, data) => api.post(`/probes/config/${productModelId}/batch-from-template`, data)
export const getSeriesProbes = (seriesIds) => api.get('/probes/config/by-series', { params: { series_ids: seriesIds.join(',') } })

// ==================== 系列级探头配置 ====================
export const getSeriesMatrix = (params) => api.get('/probes/config/series-matrix', { params })
export const updateSeriesFeature = (data) => api.put('/probes/config/series-feature', data)
export const getSeriesDrafts = (modelIds) => api.get('/probes/config/series-drafts', { params: { model_ids: modelIds.join(',') } })
export const discardSeriesDrafts = (data) => api.post('/probes/config/series-discard', data)
export const submitSeriesDrafts = (data) => api.post('/probes/config/series-submit', data)
export const getSeriesProbeVersions = (seriesIds) => api.get('/probes/config/series-versions', { params: seriesIds?.length ? { series_ids: seriesIds.join(',') } : {} })
export const rollbackSeriesVersion = (versionId) => api.post(`/probes/config/series-rollback/${versionId}`)
export const getAllProbesByCategory = () => api.get('/probes/config/all-probes')
export const setSeriesProbes = (data) => api.post('/probes/config/series-probes', data)

// ==================== 机型分组 ====================
export const getModelGroups = () => api.get('/model-groups')

// ==================== 产品知识库 ====================
export const getKnowledgeFeatures = (params) => api.get('/knowledge/features', { params })
export const getKnowledgeFeature = (id) => api.get(`/knowledge/features/${id}`)
export const getKnowledgeStats = () => api.get('/knowledge/stats')
export const getKnowledgeDocuments = (params) => api.get('/knowledge/documents', { params })
export const getKnowledgeDocumentPreviewUrl = (id) => `/api/knowledge/documents/${id}/preview`
export const askKnowledgeQuestion = (data) => api.post('/knowledge/questions/ask', data)
export const getKnowledgeQuestions = (params) => api.get('/knowledge/questions', { params })
export const getKnowledgeQuestion = (id) => api.get(`/knowledge/questions/${id}`)
export const publishKnowledgeAnswer = (id, data) => api.put(`/knowledge/questions/${id}/answer`, data)
export const getKnowledgeAnswerHistory = (id) => api.get(`/knowledge/questions/${id}/history`)

// ==================== 注册红线与产品策略 ====================
export const getConfiguredRegistrationModels = (params) =>
  api.get('/registrations/configured-models', { params })
export const getRegistrationModels = (params) =>
  api.get('/registrations/models', { params })
export const getRegistrationProbes = (params) =>
  api.get('/registrations/probes', { params })
export const getRegistrationModelProbes = (registrationModelId) =>
  api.get(`/registrations/models/${registrationModelId}/probes`)
