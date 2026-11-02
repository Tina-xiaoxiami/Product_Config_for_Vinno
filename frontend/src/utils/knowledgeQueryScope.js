export function knowledgeScopePayload(form) {
  const payload = {
    country: String(form.country || '').trim().toUpperCase(),
    market: form.market || '',
    product_model_id: form.product_model_id || null,
    software_version: String(form.software_version || '').trim()
  }
  return Object.values(payload).every(Boolean) ? payload : null
}

export function knowledgeScopeFingerprint(form) {
  return JSON.stringify([form.country, form.market, form.product_model_id, form.software_version])
}

export function knowledgeScopeLabel(scope) {
  if (!scope) return '历史范围待核实'
  return `${scope.country} · ${scope.market === 'domestic' ? '国内' : '海外'} · ${scope.model_name || scope.product_model_id} · ${scope.software_version}`
}
