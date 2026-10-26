import { getFieldLabel } from './modelHelpers.js'

export const VERSION_COMPARE_FIELDS = ['final_config', 'current_config', 'selection_config', 'rd_status'].map(key => ({ key, label: getFieldLabel(key) }))
export const VERSION_NAME_COLUMNS = [
  { key: 'rd_name', label: '研发名称', width: 200 },
  { key: 'zh_desc', label: '中文描述', width: 220 },
  { key: 'en_desc', label: '英文名称', width: 220 },
  { key: 'v_code', label: 'V代码', width: 100 },
  { key: 'ipn', label: 'IPN号', width: 110 }
]

export function versionCellChanged(row, modelId, field) {
  return (row.old_values?.[modelId]?.[field] ?? null) !== (row.new_values?.[modelId]?.[field] ?? null)
}

export function versionRowChanged(row, modelIds, fields) {
  return modelIds.some(id => fields.some(field => versionCellChanged(row, id, field)))
}

// Mirror the server's semantic model pruning before applying visible-field filters.
export function scopeVersionRows(rows, modelIds) {
  return rows.filter(row => modelIds.some(id => ['old_values', 'new_values'].some(side =>
    VERSION_COMPARE_FIELDS.some(({ key }) => row[side]?.[id]?.[key] != null)
  )))
}

export function filterVersionRows(rows, modelIds, fields, onlyDiff) {
  const scoped = scopeVersionRows(rows, modelIds)
  return onlyDiff ? scoped.filter(row => versionRowChanged(row, modelIds, fields)) : scoped
}

export function versionExportPayload(result, modelIds, fields, nameColumns, onlyDiff) {
  return {
    version_id_1: result.version_1.id,
    version_id_2: result.version_2.id,
    model_ids: [...modelIds],
    compare_fields: [...fields],
    name_columns: [...nameColumns],
    only_diff: onlyDiff
  }
}

export function reconcileVersionModelSelection(selected, previousAvailable, available, samePair) {
  if (!samePair) return [...available]
  const wasAll = previousAvailable.length > 0 && previousAvailable.every(id => selected.includes(id))
  return wasAll ? [...available] : selected.filter(id => available.includes(id))
}
