const integerId = value => Number.isInteger(Number(value)) && Number(value) > 0
const failureMessage = failure => typeof failure?.response?.data?.detail === 'string'
  ? failure.response.data.detail : failure?.message || '请重试'
const copyForm = form => ({ feature_id: form.feature_id, group_id: form.group_id, category_ids: [...form.category_ids] })
const emptyForm = () => ({ feature_id: null, group_id: null, category_ids: [] })

export function catalogFeatureLabel(feature) {
  return [feature.name || feature.primary_cn_name || '未命名功能', feature.primary_en_name, feature.ipn ? `IPN ${feature.ipn}` : 'IPN未填写']
    .filter(Boolean).join(' · ')
}

export function catalogCandidates(catalog, search = '') {
  const query = String(search || '').trim().toLocaleLowerCase()
  return (catalog?.items || []).filter(feature => !query || catalogFeatureLabel(feature).toLocaleLowerCase().includes(query))
}

export function catalogSelectionPayload(form, catalog, categories) {
  const feature = catalog?.items?.find(item => item.id === Number(form.feature_id))
  if (!feature || !integerId(form.feature_id)) throw new Error('请选择功能库中的现有功能')
  if (feature.probe_matrix_enabled || feature.pending) throw new Error('该功能已加入模板或已有待提交记录，不能重复添加')
  const groupId = Number(form.group_id)
  if (!catalog.groups.some(group => group.id === groupId)) throw new Error('请选择现有功能分类')
  const selected = Array.isArray(form.category_ids) ? [...new Set(form.category_ids.map(Number))] : []
  if (!selected.length) throw new Error('至少选择一个探头类别，系统不会默认全部支持')
  const available = new Set(categories.map(category => category.id))
  if (selected.some(id => !integerId(id) || !available.has(id))) throw new Error('探头类别已变化，请重新选择')
  return { feature_id: feature.id, group_id: groupId, category_ids: selected }
}

export function projectTemplateCatalog(catalog, drafts, categories) {
  if (!Array.isArray(catalog?.items) || !Array.isArray(catalog?.groups) || !Array.isArray(catalog?.matrix_items)
    || !Array.isArray(drafts?.drafts) || !Array.isArray(drafts?.catalog_additions)) throw new Error('功能库或草稿数据不完整，请重试')
  const groupIds = new Set(catalog.groups.map(group => group.id))
  const identities = new Map(catalog.items.map(feature => [feature.id, feature]))
  const features = catalog.matrix_items.map(feature => {
    if (!identities.has(feature.id) || (!feature.probe_matrix_enabled && !feature.pending) || !groupIds.has(feature.group_id)) {
      throw new Error('功能库与模板成员数据不一致，请重新读取')
    }
    return { ...feature, name: feature.name || feature.primary_cn_name || feature.primary_en_name || `IPN ${feature.ipn || feature.id}` }
  })
  const pendingFeatureIds = new Set(features.filter(feature => feature.pending).map(feature => feature.id))
  const additions = new Set(drafts.catalog_additions.map(addition => addition.feature_id))
  if (pendingFeatureIds.size !== additions.size || [...pendingFeatureIds].some(id => !additions.has(id))) {
    throw new Error('功能库与待提交成员数据不一致，请重新读取')
  }
  const categoryIds = new Set(categories.map(category => category.id))
  const pendingCells = {}
  for (const draft of drafts.drafts) {
    if (!pendingFeatureIds.has(draft.feature_id)) continue
    if (!categoryIds.has(draft.category_id)) throw new Error('待提交记录中的探头类别已变化，请重新读取')
    pendingCells[`${draft.category_id}_${draft.feature_id}`] = {
      default_support: draft.new_support || 'unsupported', default_excludes: draft.new_excludes ?? null
    }
  }
  const matrixGroups = new Set(features.map(feature => feature.group_id))
  return { features, groups: catalog.groups.filter(group => matrixGroups.has(group.id)), pendingCells, pendingFeatureIds,
    draftTotal: Number(drafts.total) || 0, catalogAdditionsCount: additions.size }
}

export function catalogCellSource(key, liveCells, pendingCells, pendingFeatureIds) {
  if (!pendingFeatureIds.has(Number(key.split('_')[1]))) return liveCells[key]
  return pendingCells[key] || { default_support: 'unsupported', default_excludes: null }
}

export const createTemplateCatalogEditorState = () => ({ visible: false, saving: false, saved: false, error: '', refreshError: '', search: '', form: emptyForm() })

export function createTemplateCatalogEditor({ state, getContext, save, refresh, confirmDiscard }) {
  let session = 0, baseline = '', disposed = false, closing = false, savedPayload = null
  const current = token => !disposed && token === session
  const refreshSaved = async token => {
    try {
      await refresh(savedPayload)
      if (!current(token)) return false
      state.refreshError = ''; state.visible = false
      return true
    } catch (failure) {
      if (current(token)) state.refreshError = `已保存草稿，刷新失败，请重试刷新：${failureMessage(failure)}`
      return false
    }
  }
  return {
    open() {
      if (disposed || state.saving || state.visible) return false
      session += 1; savedPayload = null
      Object.assign(state, { visible: true, saving: false, saved: false, error: '', refreshError: '', search: '', form: emptyForm() })
      baseline = JSON.stringify(state.form)
      return true
    },
    chooseFeature(id) {
      if (state.saving || state.saved) return
      const { catalog } = getContext()
      const feature = catalog?.items?.find(item => item.id === Number(id))
      state.form.feature_id = id == null ? null : Number(id)
      state.form.group_id = feature && catalog.groups.some(group => group.id === feature.group_id) ? feature.group_id : null
      state.form.category_ids = []; state.error = ''
    },
    async close(done) {
      if (state.saving || closing) return false
      const token = session
      closing = true
      try {
        if (!state.saved && JSON.stringify(state.form) !== baseline) await confirmDiscard()
        if (!current(token)) return false
        session += 1; state.visible = false
        if (typeof done === 'function') done()
        return true
      } catch { return false }
      finally { closing = false }
    },
    async submit() {
      if (disposed || state.saving || state.saved || !state.visible) return false
      const token = session
      state.saving = true; state.error = ''; state.refreshError = ''
      try {
        const { catalog, categories } = getContext()
        const payload = catalogSelectionPayload(copyForm(state.form), catalog, categories)
        await save(payload)
        if (!current(token)) return false
        savedPayload = payload; state.saved = true; baseline = JSON.stringify(state.form)
        await refreshSaved(token)
        return true
      } catch (failure) {
        if (current(token)) state.error = `草稿保存失败：${failureMessage(failure)}`
        return false
      } finally { if (current(token)) state.saving = false }
    },
    async retryRefresh() {
      if (disposed || state.saving || !state.saved) return false
      const token = session
      state.saving = true; state.refreshError = ''
      try { return await refreshSaved(token) }
      finally { if (current(token)) state.saving = false }
    },
    dispose() { disposed = true; session += 1; state.visible = false; state.saving = false }
  }
}
