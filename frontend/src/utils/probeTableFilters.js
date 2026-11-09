export const probeFilterValue = value => value == null ? '' : Array.isArray(value) ? value.join('、') : String(value)

export function probeFilterOptions(rows, key, multiValue = false) {
  return [...new Set(rows.flatMap(row => multiValue && Array.isArray(row[key])
    ? row[key].length ? row[key].map(probeFilterValue) : ['']
    : [probeFilterValue(row[key])]))].sort()
}

export function filterProbeRows(rows, filters, multiValueKeys = []) {
  return rows.filter(row => Object.entries(filters).every(([key, values]) =>
    values == null || (multiValueKeys.includes(key) && Array.isArray(row[key])
      ? (row[key].length ? row[key] : ['']).some(value => values.includes(probeFilterValue(value)))
      : values.includes(probeFilterValue(row[key])))))
}

export function selectVisibleFilterValues(selected, visible, checked) {
  const values = new Set(selected)
  for (const value of visible) checked ? values.add(value) : values.delete(value)
  return [...values]
}
