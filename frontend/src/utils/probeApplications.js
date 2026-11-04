export function resolveProbeCategory(categories, currentId, requestedId = null) {
  return categories.find(category => category.id === Number(requestedId))
    || categories.find(category => category.id === currentId) || categories[0] || null
}

export function applicationEditorState({ pendingCount = 0, editMode = false, submitting = false, saving = false, dialogOpen = false, formDirty = false, draftSaved = false } = {}) {
  const busy = submitting || saving
  return { busy, isSubmitting: submitting, hasPendingChanges: pendingCount > 0, hasUnsavedChanges: (pendingCount > 0 && !draftSaved) || formDirty,
    canSwitch: !busy && !dialogOpen, canRefresh: !busy && (!editMode || draftSaved) && !dialogOpen,
    protected: busy || (pendingCount > 0 && !draftSaved) || formDirty }
}

export function probeContextBlock(state, destructive = false) {
  return Boolean(state && (!state.canSwitch || (destructive && (state.hasPendingChanges || state.hasUnsavedChanges))))
}

export function createCategoryApplicationLoader({ readApps, readAvailable, selectedId, start, loaded, failed, finished }) {
  let request = 0, disposed = false
  return {
    async load(categoryId) {
      if (disposed) return false
      const token = ++request
      const current = () => !disposed && token === request && selectedId() === categoryId
      start(categoryId)
      try {
        const [apps, available] = await Promise.all([readApps(categoryId), readAvailable(categoryId)])
        if (!current()) return false
        loaded(categoryId, apps, available)
        return true
      } catch (error) {
        if (current()) failed(error)
        return false
      } finally { if (current()) finished() }
    },
    invalidate() { request += 1 },
    dispose() { disposed = true; request += 1 }
  }
}

export function probeModelRows(models) {
  return models.map((model, index) => ({ ...model, position: index + 1, application_count: model._appCount,
    variant_values: (model._variants || []).map(variant => [variant.internal_model, variant.ipn].filter(Boolean).join(' / ')) }))
}

export const APPLICATION_DRAFT_KEY = 'probe-application-associations-draft-v1'

export function createApplicationDraftStore(storage, warn = () => {}) {
  let observed = null, blocked = false
  const empty = () => ({ changes: {}, editMode: false, categoryId: null, error: '' })
  const read = () => storage.getItem(APPLICATION_DRAFT_KEY)
  return {
    restore() {
      try {
        observed = read()
        if (!observed) return empty()
        const value = JSON.parse(observed)
        if (value.version !== 1 || !value.changes || Array.isArray(value.changes) || typeof value.changes !== 'object') throw Error('invalid draft')
        const entries = Object.entries(value.changes)
        if (entries.length > 1000 || entries.some(([key, change]) => !change || !['add', 'remove'].includes(change.action)
          || !Number.isInteger(change.catId) || change.catId <= 0 || !Number.isInteger(change.appId) || change.appId <= 0
          || !['regular', 'poc'].includes(change.probeType) || typeof change.appName !== 'string'
          || key !== `${change.catId}_${change.appId}_${change.probeType}`)) throw Error('invalid changes')
        return { changes: Object.fromEntries(entries), editMode: value.editMode === true || entries.length > 0,
          categoryId: Number.isInteger(value.categoryId) && value.categoryId > 0 ? value.categoryId : null, error: '' }
      } catch {
        blocked = true
        const error = '本机草稿读取失败，原记录已保留；请先核对，避免刷新丢失本页修改'
        warn(error)
        return { ...empty(), error }
      }
    },
    save(changes, { categoryId = null, editMode = false } = {}) {
      try {
        if (blocked || read() !== observed) throw Error('draft changed')
        const payload = Object.keys(changes).length || editMode
          ? JSON.stringify({ version: 1, changes, categoryId, editMode, savedAt: new Date().toISOString() }) : null
        if (payload) storage.setItem(APPLICATION_DRAFT_KEY, payload)
        else storage.removeItem(APPLICATION_DRAFT_KEY)
        observed = payload
        return true
      } catch {
        warn('本机草稿未能自动保存（存储不可用或其他页面已更新），本页修改仍保留，请勿直接刷新')
        return false
      }
    },
    clear() { return this.save({}) }
  }
}
