export const cloneSubseriesGroups = groups => groups.map(group => ({
  ...group,
  series_names: [...(group.series_names || (group.series ? [group.series] : []))],
  models: group.model_ids ? [...group.model_ids.map(id => `id:${id}`), ...(group.missing_models || [])] : [...group.models],
  options: (group.options || []).map(option => ({ ...option }))
}))
export const subseriesGroupOptions = (group, catalog) => {
  const series = group.series_names || (group.series ? [group.series] : [])
  const options = catalog.filter(model => !series.length || series.includes(model.series)).map(model => ({
    id: model.id, value: `id:${model.id}`, label: `${model.name}（${model.series}）`, series: model.series
  }))
  const values = new Set(options.map(option => option.value))
  for (const value of group.models) {
    if (!values.has(value)) {
      const model = catalog.find(model => `id:${model.id}` === value)
      options.push({ value, label: model ? `${model.name}（${model.series}，不属于当前系列）` : `${value}（未匹配，保留）` })
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
    revision, groups: groups.map(group => ({ name: group.name.trim(), ...(group.unresolved_refs ? { unresolved_refs: group.unresolved_refs.filter(ref => group.models.includes(ref.name)) } : {}), series_names: [...(group.series_names || (group.series ? [group.series] : []))], model_ids: [...new Set(group.models.filter(value => /^id:\d+$/.test(value)).map(value => Number(value.slice(3))))], models: [...new Set(group.models.filter(value => !/^id:\d+$/.test(value)))] }))
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
