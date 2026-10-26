export const cloneSubseriesGroups = groups => groups.map(group => ({
  ...group, models: [...group.models], options: (group.options || []).map(option => ({ ...option }))
}))
export const subseriesGroupOptions = (group, catalog) => {
  const originalById = new Map((group.options || []).filter(option => option.id != null).map(option => [option.id, option]))
  const candidates = catalog.filter(model => !group.series || model.series === group.series).map(model => ({
    id: model.id, value: originalById.get(model.id)?.value || model.name,
    label: model.name, series: model.series
  }))
  const byValue = new Map()
  for (const option of candidates) {
    const existing = byValue.get(option.value)
    if (existing) {
      if (option.series && !existing.seriesNames.includes(option.series)) existing.seriesNames.push(option.series)
    } else {
      byValue.set(option.value, { ...option, seriesNames: option.series ? [option.series] : [] })
    }
  }
  const options = [...byValue.values()].map(option => ({
    ...option,
    label: !group.series && option.seriesNames.length ? `${option.label}（${option.seriesNames.join('、')}）` : option.label
  }))
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
export const cloneSubseriesCombinations = (combinations, groups) => combinations.map(combination => ({
  name: combination.name,
  groupKeys: combination.sub_series.map(name => {
    const group = groups.find(group => group.name === name)
    if (!group) throw new Error(`组合引用的子系列不存在：${name}`)
    return group.editorKey
  })
}))
export const subseriesPayload = (revision, groups, combinations) => {
  const payload = {
    revision, groups: groups.map(group => ({ name: group.name.trim(), series: group.series || '', models: [...new Set(group.models)] }))
  }
  if (combinations !== undefined) payload.combinations = combinations.map(combination => ({
    name: combination.name.trim(),
    sub_series: [...new Set(combination.groupKeys)].map(key => {
      const group = groups.find(group => group.editorKey === key)
      if (!group) throw new Error('组合引用的子系列已删除，请先调整组合')
      return group.name.trim()
    })
  }))
  return payload
}
export const subseriesSnapshot = (groups, combinations) => {
  const payload = subseriesPayload('', groups, combinations)
  return JSON.stringify(combinations === undefined ? payload.groups : payload)
}
export const buildSubseriesCombinationSelection = (combination, catalog) => {
  if (combination.missing_models?.length) throw new Error('组合中有未匹配机型，请先在编辑子系列中核对：' + combination.missing_models.join('、'))
  const modelsById = new Map(catalog.map(model => [model.id, model]))
  const models = [...new Set(combination.model_ids)].map(id => {
    const model = modelsById.get(id)
    if (!model || !model.series) throw new Error('组合机型不存在或所属系列已变化，请重新加载')
    return { id: model.id, name: model.name, seriesId: model.series_id, seriesName: model.series }
  })
  if (!models.length) throw new Error('组合中没有可用机型，请先调整子系列')
  return { name: combination.name, models, exactModelIds: models.map(model => model.id) }
}
