// Personal view preferences use canonical IDs and group occurrence keys, not labels.
export function orderModelCatalog(models, savedOrder = []) {
  const byId = new Map(models.map(model => [String(model.id), model]))
  const ordered = []
  for (const id of savedOrder) {
    const model = byId.get(String(id))
    if (model) { ordered.push(model); byId.delete(String(id)) }
  }
  return [...ordered, ...byId.values()]
}
export function moveModelToTarget(models, sourceId, targetId) {
  const ordered = [...models]
  const source = ordered.findIndex(model => String(model.id) === String(sourceId))
  const target = ordered.findIndex(model => String(model.id) === String(targetId))
  if (source < 0 || target < 0 || source === target) return ordered
  ordered.splice(target, 0, ordered.splice(source, 1)[0])
  return ordered
}
export function visibleManagementGroups(nodes, hiddenKeys = []) {
  const hidden = new Set(hiddenKeys)
  return nodes.filter(node => node.key === 'all' || !hidden.has(node.key)).map(node => ({
    ...node, ...(node.children ? { children: node.children.filter(child => !hidden.has(child.key)) } : {})
  }))
}
export function loadPersonalList(storage, key, warn) {
  try {
    const raw = storage.getItem(key)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed) || parsed.some(value => typeof value !== 'string' && typeof value !== 'number')) throw Error('invalid preference')
    return [...new Set(parsed.map(String))]
  } catch { warn?.('个人布局读取失败，已使用默认布局'); return [] }
}
export function savePersonalList(storage, key, values, warn) {
  try { storage.setItem(key, JSON.stringify(values)); return true }
  catch { warn?.('个人布局未能保存，刷新后可能恢复原设置'); return false }
}

export function orderManagementGroups(nodes, saved = []) {
  const ranks = new Map(saved.map((key, index) => [key, index]))
  return nodes.map(node => ({ ...node, ...(node.children ? { children: orderManagementGroups(node.children, saved) } : {}) }))
    .sort((a, b) => a.key === 'all' ? -1 : b.key === 'all' ? 1 : (ranks.get(a.key) ?? Infinity) - (ranks.get(b.key) ?? Infinity))
}
export function rememberGroupSiblingOrder(nodes, siblingKeys) {
  const keys = nodes.flatMap(node => [node.key, ...(node.children || []).map(child => child.key)])
  const changed = new Set(siblingKeys)
  let index = 0
  return keys.map(key => changed.has(key) ? siblingKeys[index++] : key)
}
