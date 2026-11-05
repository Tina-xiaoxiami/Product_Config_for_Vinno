import { cloneSubseriesGroups, subseriesPayload } from './subseriesEditor.js'

export function modelFitsSubseries(group, series) {
  const parents = group.series_names || (group.series ? [group.series] : [])
  return !parents.length || parents.includes(series)
}

export function assignModelSubseriesPayload(data, modelId, name) {
  const model = data.catalog.find(model => model.id === modelId)
  if (!model) throw new Error('型号已变化，请刷新后重试')
  name = name.trim()
  if (!name || name.length > 200) throw new Error('子系列名称需为 1–200 个字符')
  const groups = cloneSubseriesGroups(data.groups)
  let group = groups.find(group => group.name.trim() === name)
  if (group && !modelFitsSubseries(group, model.series)) throw new Error('此子系列不包含该型号所属系列，请选择其他子系列或在管理中调整')
  if (!group) {
    group = { name, series_names: [model.series], models: [] }
    groups.push(group)
  }
  group.models = [...new Set([...group.models, `id:${model.id}`])]
  // Omit combinations: the shared API preserves and validates existing references.
  return subseriesPayload(data.revision, groups)
}
