export const probeFilterValue = value => value == null ? '' : Array.isArray(value) ? value.join('、') : String(value)

export function filterProbeRows(rows, filters) {
  return rows.filter(row => Object.entries(filters).every(([key, values]) =>
    values == null || values.includes(probeFilterValue(row[key]))))
}

export function selectVisibleFilterValues(selected, visible, checked) {
  const values = new Set(selected)
  for (const value of visible) checked ? values.add(value) : values.delete(value)
  return [...values]
}
