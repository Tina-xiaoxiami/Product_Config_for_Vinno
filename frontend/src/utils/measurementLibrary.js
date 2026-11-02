// Preserve punctuation: E, E' and E/A are distinct measurement identities.
const searchKey = value => String(value ?? '').normalize('NFKC').trim().toLocaleLowerCase()
const selected = (selection, values) => selection == null || selection.some(value => values.includes(value))

export function measurementScope(row) {
  if (row.kind !== 'measurement') return []
  if (!row.categories?.length) return ['unclassified']
  return [...(row.categories.includes('Common') ? ['common'] : []), ...(row.categories.some(value => value !== 'Common') ? ['application'] : [])]
}

export function filterMeasurements(rows, filters = {}) {
  const query = searchKey(filters.q)
  return rows.flatMap(row => {
    if (filters.kind && row.kind !== filters.kind) return []
    if (filters.scope && !measurementScope(row).includes(filters.scope)) return []
    for (const field of ['mode', 'group', 'unit', 'enabled']) {
      if (!selected(filters[field], [row[field] ?? ''])) return []
    }
    if (!selected(filters.category, row.categories?.length ? row.categories : [''])) return []
    const names = [row.item_id, row.en_name, row.cn_name].map(searchKey).filter(Boolean)
    if (query && !names.some(value => value.includes(query))) return []
    return [{ ...row, match: !query ? '' : names.includes(query) ? 'exact' : 'partial' }]
  }).sort((left, right) => Number(right.match === 'exact') - Number(left.match === 'exact'))
}

export function measurementOptions(rows, field) {
  return [...new Set(rows.flatMap(row => field === 'categories' ? row.categories?.length ? row.categories : [''] : [row[field] ?? '']))].sort()
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
