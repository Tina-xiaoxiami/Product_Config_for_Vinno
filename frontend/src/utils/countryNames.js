const regionNames = typeof Intl.DisplayNames === 'function'
  ? new Intl.DisplayNames(['zh-CN'], { type: 'region' })
  : null

// Preserve the source code when it has no recognized Chinese region name.
export function formatCountryCode(value) {
  const code = String(value ?? '').trim()
  if (!/^[A-Za-z]{2}$/.test(code) || !regionNames) return code
  const normalized = code.toUpperCase()
  if (normalized === 'ZZ') return code
  const name = regionNames.of(normalized)
  return name && name !== normalized ? `${name}（${code}）` : code
}
