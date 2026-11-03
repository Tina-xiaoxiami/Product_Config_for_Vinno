// Preserve punctuation: E, E' and E/A are distinct measurement identities.
const searchKey = value => String(value ?? '').normalize('NFKC').trim().toLocaleLowerCase()
const selected = (selection, values) => selection == null || selection.some(value => values.includes(value))

export function measurementScope(row) {
  if (!row.categories?.length) return ['unclassified']
  return [...(row.categories.includes('Common') ? ['common'] : []), ...(row.categories.some(value => value !== 'Common') ? ['application'] : [])]
}

export function filterMeasurements(rows, filters = {}) {
  const query = searchKey(filters.q)
  return rows.flatMap(row => {
    if (filters.kind && row.kind !== filters.kind) return []
    if (filters.scope && !measurementScope(row).includes(filters.scope)) return []
    for (const field of ['mode', 'group', 'unit', 'enabled']) {
      const value = row[field]
      if (!selected(filters[field], Array.isArray(value) ? value.length ? value : [''] : [value ?? ''])) return []
    }
    if (!selected(filters.category, row.categories?.length ? row.categories : [''])) return []
    const names = [row.item_id, row.en_name, row.cn_name].map(searchKey).filter(Boolean)
    if (query && !names.some(value => value.includes(query))) return []
    return [{ ...row, match: !query ? '' : names.includes(query) ? 'exact' : 'partial' }]
  }).sort((left, right) => Number(right.match === 'exact') - Number(left.match === 'exact'))
}

export function measurementOptions(rows, field) {
  return [...new Set(rows.flatMap(row => {
    const value = row[field]
    return Array.isArray(value) ? value.length ? value : [''] : [value ?? '']
  }))].sort()
}

export function measurementCounts(rows) {
  return {
    rows: rows.length,
    measurements: new Set(rows.filter(row => row.kind === 'measurement').map(row => row.item_id)).size,
    calculations: new Set(rows.filter(row => row.kind === 'calculation').map(row => row.item_id)).size,
    common: rows.filter(row => measurementScope(row).includes('common')).length,
    application: rows.filter(row => measurementScope(row).includes('application')).length,
    unclassified: rows.filter(row => measurementScope(row).includes('unclassified')).length
  }
}

// Facets use the full projected batch, before pagination or table-column filters.
// Ignore a facet's own selection so multi-select siblings remain discoverable.
export function measurementFacets(rows, filters = {}) {
  const scopes = measurementCounts(filterMeasurements(rows, { q: filters.q, kind: filters.kind, mode: filters.mode }))
  const countOptions = (field, candidates, selection) => {
    const counts = new Map()
    for (const row of candidates) {
      const raw = row[field]
      const values = Array.isArray(raw) ? raw.length ? raw : [''] : [raw ?? '']
      for (const value of new Set(values)) counts.set(value, (counts.get(value) || 0) + 1)
    }
    return [...new Set([...measurementOptions(rows, field), ...(selection || [])])].sort()
      .map(value => ({ value, count: counts.get(value) || 0 }))
  }
  return {
    scopes: { all: scopes.rows, common: scopes.common, application: scopes.application, unclassified: scopes.unclassified },
    categories: countOptions('categories', filterMeasurements(rows, { ...filters, scope: 'application', category: null }), filters.category)
      .filter(option => option.value && option.value !== 'Common'),
    modes: countOptions('mode', filterMeasurements(rows, { ...filters, mode: null }), filters.mode)
  }
}

export function projectMeasurementRow(row, includePending = true) {
  const enrichment = row.enrichment
  const confirmed = enrichment?.status === 'stale_source' ? null : enrichment?.confirmed_payload
  const pending = includePending && ['pending', 'deferred', 'unresolved'].includes(enrichment?.status)
    ? enrichment.candidate?.payload : null
  const payload = confirmed || pending
  const labels = { pending: '待核对', confirmed: '已核对', rejected: '未采用', deferred: '暂缓核对', unresolved: '待补充', stale_source: '来源已变化' }
  const status = row.kind === 'measurement' ? '原表' : enrichment
    ? confirmed ? enrichment.has_pending_update ? '已核对（有新建议）' : '已核对' : labels[enrichment.status] || '待补充'
    : '未补充'
  return {
    ...row,
    source_mode: row.mode ?? '',
    source_categories: [...(row.categories || [])],
    mode: payload ? [...payload.modes] : row.mode ?? '',
    categories: [...(payload ? payload.categories : row.categories || [])],
    classification_basis: payload ? confirmed ? '已核对补充' : '待核对建议' : '原表',
    enrichment_status: status
  }
}
