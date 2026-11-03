export function resolveProbeCategory(categories, currentId, requestedId = null) {
  return categories.find(category => category.id === Number(requestedId))
    || categories.find(category => category.id === currentId) || categories[0] || null
}

export function applicationEditorState({ pendingCount = 0, editMode = false, submitting = false, saving = false, dialogOpen = false, formDirty = false } = {}) {
  const busy = submitting || saving
  return { busy, isSubmitting: submitting, hasPendingChanges: pendingCount > 0, hasUnsavedChanges: pendingCount > 0 || formDirty,
    canSwitch: !busy && !dialogOpen, canRefresh: !busy && !editMode && !dialogOpen,
    protected: busy || pendingCount > 0 || formDirty }
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
