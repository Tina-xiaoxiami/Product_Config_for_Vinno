import { draftBaseline, draftWorkingValue } from './configDraftHelpers.js'

// Managed names, assignments and evidence already belong to this workspace revision.
// Only suggestion-origin assignments respond to the optional pending view toggle.
export function projectManagedMeasurement(row, includePending = true) {
  const hideSuggestion = !includePending && row.assignment_origin === 'suggestion'
  return {
    ...row,
    mode: [...(hideSuggestion ? row.official_mode || [] : row.mode || [])],
    categories: [...(hideSuggestion ? row.official_categories || [] : row.categories || [])],
    ...(hideSuggestion ? { classification_basis: row.enrichment?.confirmed_payload ? '已核对补充' : '原表' } : {})
  }
}

export function dictionaryLabel(document, dimension, code) {
  return document?.[dimension]?.find(entry => entry.code === code)?.name || code || '(空白)'
}

export function identityRows(document, row) {
  return (document?.entries || []).filter(entry => entry.kind === row.kind && entry.item_id === row.item_id)
}

export function readableChange(value) {
  if (value == null || value === '') return '(空白)'
  return typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value)
}

export function workspaceChangeRows(changes = []) {
  return changes.map(change => ({
    ...change,
    label: change.label?.replace(/^measurement · /, '测量项 · ').replace(/^calculation · /, '计算项 · ').replace(/^applications · /, '应用 · ').replace(/^modes · /, '模式 · '),
    type_label: ({ create: '新增', update: '修改', delete: '移除' })[change.change_type] || change.change_type,
    field_label: ({ names: 'UI 名称', assignments: '应用与模式', name: '字典名称', evidence: '核对资料', record: '整条关系', applications: '应用字典', modes: '模式字典' })[change.field] || change.field,
    before_label: readableChange(draftBaseline(change, change.before)),
    after_label: readableChange(draftWorkingValue(change, change.after))
  }))
}

const joined = values => values?.length ? values.join('；') : '(空白)'
const statusLabel = value => ({ pending: '待核对', confirmed: '已核对', rejected: '未采用', deferred: '暂缓核对', unresolved: '待补充', stale_source: '来源已变化' })[value] || value || '未补充'
export function formatManagedChange(change, value, document) {
  if (value == null) return '(空白)'
  const applications = row => joined((row.categories || []).map(code => dictionaryLabel(document, 'applications', code)))
  const modes = row => joined((row.mode || row.modes || []).map(code => dictionaryLabel(document, 'modes', code)))
  if (change.field === 'names') {
    const counts = new Map()
    for (const row of value) {
      const label = `中文：${row.cn_name || '(空白)'}\n英文：${row.description || row.en_name || '(使用 Id)'}`
      counts.set(label, (counts.get(label) || 0) + 1)
    }
    return [...counts].map(([label, count]) => `${label}\n适用 ${count} 条关系`).join('\n\n')
  }
  if (change.field === 'assignments') return `应用：${applications(value)}\n模式：${modes(value)}`
  if (change.entity === 'dictionary') return `${value.code} · ${value.name}`
  if (change.field === 'evidence') {
    const evidence = value.enrichment
    const history = evidence?.history || []
    return `核对状态：${value.enrichment_status || statusLabel(evidence?.status)}\n候选修订：${evidence?.candidate?.revision ?? '(无)'}\n审核记录：${history.length} 条\n确认应用：${joined((value.official_categories || []).map(code => dictionaryLabel(document, 'applications', code)))}\n确认模式：${joined((value.official_mode || []).map(code => dictionaryLabel(document, 'modes', code)))}` + (Object.hasOwn(value, 'categories') ? `\n当前显示应用：${applications(value)}\n当前显示模式：${modes(value)}\n分类依据：${value.classification_basis || '(空白)'}` : '')
  }
  if (change.field === 'record') return `${value.kind === 'calculation' ? '计算项' : '测量项'} · ${value.item_id}\n中文：${value.cn_name || '(空白)'}\n英文：${value.description || value.item_id}\n应用：${applications(value)}\n模式：${modes(value)}`
  return readableChange(value)
}

// The unmanaged source response arrives before workspace initialization/loading.
// Keep its mode shape compatible with the managed table during that async gap.
export function normalizeMeasurementModes(row) {
  return { ...row, mode: Array.isArray(row.mode) ? [...row.mode] : row.mode ? [row.mode] : [] }
}

function evidenceIdentity(enrichment) {
  return JSON.stringify([
    enrichment?.review_revision ?? 0,
    enrichment?.status ?? null,
    enrichment?.source_fingerprint ?? null,
    enrichment?.source_stale ?? false,
    enrichment?.candidate?.fingerprint ?? null,
    enrichment?.candidate?.revision ?? null,
    enrichment?.has_pending_update ?? false
  ])
}

// Compare live review/candidate identities, never managed names, assignments or
// frozen audit-history metadata. Historical documents remain unchanged.
export function sourceEvidenceHasDrift(sourceEntries, document) {
  const sources = new Map((sourceEntries || []).map(row => [row.id, row]))
  return (document?.entries || []).some(row => {
    if (row.source_entry_id == null) return false
    const source = sources.get(row.source_entry_id)
    return !source || evidenceIdentity(source.enrichment) !== evidenceIdentity(row.enrichment)
  })
}
