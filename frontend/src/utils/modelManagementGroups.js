// Shared memberships are resolved by canonical model ID, never display name.
export function applySharedMemberships(models, groups = []) {
  const memberships = new Map()
  for (const group of groups) for (const id of group.model_ids || []) {
    const names = memberships.get(String(id)) || []
    if (!names.includes(group.name)) names.push(group.name)
    memberships.set(String(id), names)
  }
  return new Map([...models].map(([id, model]) => [id, { ...model, sub_series: memberships.get(String(id)) || [] }]))
}

export function buildManagementGroups(models, data = {}) {
  const ids = new Set(models.map(model => String(model.id)))
  const restrict = values => [...new Set((values || []).map(String))].filter(id => ids.has(id))
  const groups = (data.groups || []).map(group => ({
    key: JSON.stringify(['group', group.series || '', group.name]), label: group.name,
    ids: restrict(group.model_ids), series: group.series || ''
  })).filter(group => group.ids.length)
  const used = new Set()
  const combinations = (data.combinations || []).map(combo => {
    const children = groups.filter(group => (combo.sub_series || []).includes(group.label))
    children.forEach(group => used.add(group.key))
    return { key: JSON.stringify(['combination', combo.name]), label: combo.name,
      ids: [...new Set(children.flatMap(group => group.ids))],
      children: children.map(group => ({ ...group, key: JSON.stringify([combo.name, group.key]) })) }
  }).filter(combo => combo.ids.length)
  const grouped = new Set(groups.flatMap(group => group.ids))
  return [{ key: 'all', label: '全部型号', ids: [...ids] }, ...combinations,
    ...groups.filter(group => !used.has(group.key)),
    { key: 'ungrouped', label: '未分组', ids: [...ids].filter(id => !grouped.has(id)) }]
}

// Reject incomplete/changing pages rather than showing misleading group counts.
export async function loadCompleteModelCatalog(fetchPage, isCurrent = () => true) {
  const models = [], seen = new Set()
  let total = null
  for (let page = 0; page < 100; page++) {
    const response = await fetchPage({ skip: models.length, limit: 100 })
    if (!isCurrent()) return null
    if (!Array.isArray(response.items) || !Number.isInteger(response.total) || response.total < 0 ||
        (total !== null && total !== response.total)) throw new Error('型号列表已变化，请重新加载')
    total = response.total
    for (const model of response.items) {
      if (seen.has(String(model.id))) throw new Error('型号列表已变化，请重新加载')
      seen.add(String(model.id)); models.push(model)
    }
    if (models.length === total) return models
    if (!response.items.length || models.length > total) break
  }
  throw new Error('型号列表未完整加载，请重试')
}

export function createGroupEditorRequest({ isRequested, consume, nextTick, isActive, open }) {
  let pending = false, generation = 0
  return {
    invalidate() { generation++ },
    async run() {
      if (pending || !isActive() || !isRequested()) return
      pending = true
      const token = generation
      try {
        await consume()
        await nextTick()
        if (token === generation && isActive()) open()
      } finally { pending = false }
    }
  }
}
