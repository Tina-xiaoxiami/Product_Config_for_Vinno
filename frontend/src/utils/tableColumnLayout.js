export const MODEL_TABLE_COLUMNS = [
  { key: 'name', label: '型号名称', width: 220, fixed: true },
  { key: 'series_id', label: '所属系列', width: 190 },
  { key: 'sub_series', label: '所属子系列', width: 210 },
  { key: 'registration_packages', label: '对应注册证', width: 300 },
  { key: 'description', label: '描述', width: 200 },
  { key: 'status', label: '状态', width: 100 },
  { key: 'created_at', label: '创建时间', width: 180 }
].map(column => ({ visible: true, fixed: false, ...column }))

export function normalizeColumnLayout(defaults, saved) {
  const byKey = new Map(defaults.map(column => [column.key, column]))
  const seen = new Set()
  const result = []
  for (const item of Array.isArray(saved) ? saved : []) {
    const source = byKey.get(item?.key)
    if (!source || seen.has(item.key)) continue
    seen.add(item.key)
    result.push({ ...source, visible: typeof item.visible === 'boolean' ? item.visible : source.visible,
      fixed: typeof item.fixed === 'boolean' ? item.fixed : source.fixed,
      width: Number.isFinite(item.width) ? Math.max(30, item.width) : source.width })
  }
  for (const source of defaults) if (!seen.has(source.key)) result.push({ ...source })
  if (!result.some(column => column.visible) && result.length) result[0].visible = true
  return result
}
export function moveLayoutColumn(columns, fromKey, toKey) {
  const result = columns.map(column => ({ ...column }))
  const from = result.findIndex(column => column.key === fromKey)
  const to = result.findIndex(column => column.key === toKey)
  if (from < 0 || to < 0 || from === to) return result
  result.splice(to, 0, result.splice(from, 1)[0])
  return result
}
export function loadColumnLayout(storage, key, defaults, warn) {
  try {
    const raw = storage.getItem(key)
    if (!raw) return normalizeColumnLayout(defaults)
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) throw new Error('invalid layout')
    return normalizeColumnLayout(defaults, parsed)
  } catch { warn?.('列布局读取失败，已使用默认布局'); return normalizeColumnLayout(defaults) }
}
export function saveColumnLayout(storage, key, columns, warn) {
  try { storage.setItem(key, JSON.stringify(columns)); return true }
  catch { warn?.('列布局未能保存，刷新后可能恢复原设置'); return false }
}

export function buildTemplateMatrixColumns(features) {
  return [
    { key: 'category', label: '探头类别', width: 120, fixed: true },
    { key: 'regular', label: '常规应用', width: 140, fixed: true },
    { key: 'poc', label: 'POC 应用', width: 140, fixed: true },
    ...features.map(feature => ({ key: `feature:${feature.id}`, label: feature.name, width: 110, fixed: false }))
  ].map(column => ({ visible: true, ...column }))
}

// Consecutive columns share a header only when both group and fixed side match.
// This preserves arbitrary personal order without detaching cells from feature IDs.
export function templateMatrixSections(columns, features, groups, options = {}) {
  const byId = new Map(features.map(feature => [`feature:${feature.id}`, feature]))
  const sections = []
  for (const column of columns) {
    if (!column.visible || (column.key === 'regular' && options.showRegular === false)
      || (column.key === 'poc' && options.showPOC === false)) continue
    if (!column.key.startsWith('feature:')) { sections.push({ ...column, kind: 'base' }); continue }
    const feature = byId.get(column.key)
    if (!feature) continue
    const groupKey = `group:${feature.group_id}:${column.fixed ? 'fixed' : 'normal'}`
    let section = sections.at(-1)
    if (section?.groupKey !== groupKey) {
      section = { kind: 'group', groupKey, key: `${groupKey}:${column.key}`, fixed: column.fixed,
        label: groups.find(group => group.id === feature.group_id)?.name || '未分类', columns: [] }
      sections.push(section)
    }
    section.columns.push({ ...column, feature })
  }
  return sections
}
