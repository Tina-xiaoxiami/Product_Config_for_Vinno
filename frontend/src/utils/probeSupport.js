export function expandCombinedName(name) {
  const parts = name.split(/[\\/]/)
  if (parts.length <= 1) return [name]
  const last = parts[parts.length - 1].trim()
  const suffix = last.length > 1 ? last.slice(1) : ''
  return [...parts.slice(0, -1).map(part => part.trim()).filter(Boolean).map(part => part + suffix), ...(last ? [last] : [])]
}

export function parseProbeExcludes(value) {
  if (typeof value === 'string') { try { value = JSON.parse(value) } catch { value = null } }
  if (Array.isArray(value)) return { excludes: value, tender: [] }
  return { excludes: value?.excludes || [], tender: value?.tender || [] }
}

export function formatProbeSupport({ status, apps = [], excludes = [], tender = [], mode = 'auto' }) {
  if (status === 'pending') return '待确认'
  if (status === 'mixed') return '存在差异'
  if (status === 'not_applicable') return '不适用'
  if (!status || status === 'unsupported') return '—'
  const excluded = excludes.flatMap(expandCombinedName)
  const tenderApps = tender.flatMap(expandCombinedName)
  const unknown = excluded.filter(name => !apps.includes(name))
  if (unknown.length) return '待核对排除: ' + [...new Set(unknown)].join(', ')
  if (!apps.length) return status === 'supported' ? 'ALL' : '△'
  const supported = apps.filter(name => !excluded.includes(name) && !tenderApps.includes(name))
  if (status === 'conditional' && tenderApps.length) {
    return [...(supported.length ? ['支:' + supported.join(',')] : []), '招:' + tenderApps.join(',')].join(' | ')
  }
  if (!excluded.length && !tenderApps.length) return 'ALL'
  return mode === 'supported' || (mode === 'auto' && supported.length <= excluded.length)
    ? supported.join(', ') : '除: ' + excluded.join(', ')
}

export function probeGroupColors(groups) {
  const backgrounds = ['#e3f2fd', '#e8f5e9', '#fff8e1', '#fce4ec', '#ede7f6', '#e0f2f1', '#fff3e0', '#e8eaf6', '#fbe9e7', '#f3e5f5']
  const borders = ['#1976d2', '#388e3c', '#f57f17', '#c62828', '#5e35b1', '#00796b', '#e65100', '#3949ab', '#d84315', '#7b1fa2']
  return Object.fromEntries(groups.map((group, index) => [group.id, { bg: backgrounds[index % backgrounds.length], border: borders[index % borders.length] }]))
}
