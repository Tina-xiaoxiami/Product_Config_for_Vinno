export const probeRuleKey = row => `${row.probe_model_id}:${row.variant_id || 0}:${row.feature_id}`
export const probeStatusLabel = status => ({ supported: '支持', conditional: '条件支持', unsupported: '不支持', pending: '待确认', not_applicable: '不适用' }[status] || status)
const copy = value => JSON.parse(JSON.stringify(value))

export function applyProbeRule(document, key, patch, modelIds) {
  const result = copy(document)
  const row = result.rows.find(row => probeRuleKey(row) === key)
  if (!row) throw new Error('条目已变化，请刷新')
  const ids = [...new Set(modelIds)]
  if (!ids.length) Object.assign(row, patch)
  for (const id of ids) {
    if (!document.scope.model_ids.includes(id)) throw new Error('机型不在当前总集范围内')
    const rules = result.overrides[id] ||= {}
    rules[key] = { ...rules[key], ...patch }
  }
  return result
}

export function removeProbeRule(document, key) {
  const result = copy(document)
  result.rows = result.rows.filter(row => probeRuleKey(row) !== key)
  for (const rules of Object.values(result.overrides)) delete rules[key]
  return result
}
