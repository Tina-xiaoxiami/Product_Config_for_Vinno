export const cloneSubseriesGroups = groups => groups.map(group => ({
  ...group, models: [...group.models], options: (group.options || []).map(option => ({ ...option }))
}))
export const subseriesGroupOptions = (group, catalog) => {
  const originalById = new Map((group.options || []).filter(option => option.id != null).map(option => [option.id, option]))
  const candidates = catalog.filter(model => !group.series || model.series === group.series).map(model => ({
    id: model.id, value: originalById.get(model.id)?.value || model.name,
    label: model.name, series: model.series
  }))
  const options = [...new Map(candidates.map(option => [option.value, option])).values()]
  const values = new Set(options.map(option => option.value))
  for (const value of group.models) {
    if (!values.has(value)) {
      const known = (group.options || []).find(option => option.value === value)
      options.push({ value, label: known?.label || `${value}（未匹配或不属于当前系列，请核对）` })
      values.add(value)
    }
  }
  return options
}
export const subseriesPayload = (revision, groups) => ({
  revision, groups: groups.map(group => ({ name: group.name.trim(), series: group.series || '', models: [...new Set(group.models)] }))
})
export const subseriesSnapshot = groups => JSON.stringify(subseriesPayload('', groups).groups)
