// Keep the same subseries in each saved combination; selection identity is always model.id.
export function buildModelSelectionTree(groups, combinations = []) {
  const included = new Set()
  const sections = combinations.flatMap(combination => {
    const members = groups.filter(group => group.subseriesName && combination.sub_series.includes(group.subseriesName))
    if (!members.length) return []
    members.forEach(group => included.add(group.key))
    return [{ key: JSON.stringify(['combination', combination.name]), label: combination.name, combination: true, subseriesCount: new Set(members.map(group => group.subseriesName)).size, groups: members.map(group => ({ ...group, key: JSON.stringify([combination.name, group.key]) })) }]
  })
  const remaining = groups.filter(group => !included.has(group.key))
  if (remaining.length) sections.push({ key: 'standalone', groups: remaining })
  return sections
}

export function filterModelSelectionTree(sections, query) {
  const q = query.trim().toLowerCase()
  if (!q) return sections
  return sections.map(section => ({ ...section, groups: section.groups.map(group => ({
    ...group,
    models: group.models.filter(model => section.label?.toLowerCase().includes(q) || group.label.toLowerCase().includes(q) || model.name.toLowerCase().includes(q))
  })).filter(group => group.models.length) })).filter(section => section.groups.length)
}

// Element Plus registers options by value. Register each model exactly once even
// when it belongs to overlapping combinations; other occurrences share its selection.
export function primaryModelOccurrences(sections, isExpanded) {
  const fallback = new Map(), visible = new Map()
  for (const section of sections) for (const group of section.groups) for (const model of group.models) {
    if (!fallback.has(model.id)) fallback.set(model.id, group.key)
    if ((!section.combination || isExpanded(section)) && isExpanded(group) && !visible.has(model.id)) visible.set(model.id, group.key)
  }
  return new Map([...fallback].map(([id, key]) => [id, visible.get(id) ?? key]))
}
