const STORAGE_KEY = 'config_model_selection_groups_v1'

export function buildModelSelectionGroup(name, selectedIds, models, id = crypto.randomUUID()) {
  const trimmed = name.trim()
  if (!trimmed || trimmed.length > 60) throw new Error('分组名称须为 1–60 个字符')
  const selected = [...new Set(selectedIds)].map(key => models.get(key)).filter(Boolean)
  if (!selected.length) throw new Error('请先选择至少一个机型')
  return { id, name: trimmed, models: selected.map(({ id, name, seriesId, seriesName, source_uuid }) => ({ id, name, seriesId, seriesName, ...(source_uuid ? { source_uuid } : {}) })) }
}

export function resolveGroupSeries(group, series) {
  const names = [...new Set(group.models.map(model => model.seriesName))]
  const ids = []
  let missing = 0
  for (const name of names) {
    const matches = series.filter(item => item.name === name)
    if (matches.length === 1) ids.push(matches[0].id)
    else missing++
  }
  return { ids, missing }
}

export function resolveGroupModels(group, models) {
  const ids = []
  let missing = 0
  for (const saved of group.models) {
    const matches = [...models.values()].filter(model => model.seriesName === saved.seriesName && (saved.source_uuid ? model.source_uuid === saved.source_uuid : (model.name === saved.name || model.aliases?.includes(saved.name))))
    if (matches.length === 1) ids.push(matches[0].id)
    else missing++
  }
  return { ids: [...new Set(ids)], missing }
}

function validateGroups(groups) {
  if (!Array.isArray(groups)) throw new Error('保存的机型分组格式无效')
  const ids = new Set(), names = new Set()
  for (const group of groups) {
    if (!group || typeof group.id !== 'string' || !group.id || typeof group.name !== 'string' || !group.name.trim() || group.name.length > 60 || !Array.isArray(group.models) || !group.models.length || ids.has(group.id) || names.has(group.name)) {
      throw new Error('保存的机型分组格式无效')
    }
    for (const model of group.models) {
      if (!model || typeof model.name !== 'string' || !model.name || typeof model.seriesName !== 'string' || !model.seriesName) throw new Error('保存的机型分组格式无效')
    }
    ids.add(group.id)
    names.add(group.name)
  }
  return groups
}

export function loadModelSelectionGroups(storage = localStorage) {
  const saved = storage.getItem(STORAGE_KEY)
  return saved === null ? [] : validateGroups(JSON.parse(saved))
}

export function saveModelSelectionGroups(groups, storage = localStorage) {
  storage.setItem(STORAGE_KEY, JSON.stringify(validateGroups(groups)))
}
