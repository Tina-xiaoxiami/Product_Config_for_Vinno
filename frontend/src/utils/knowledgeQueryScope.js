export function knowledgeScopePayload(form) {
  const payload = {
    market: form.market || '',
    product_model_id: form.product_model_id || null,
    software_version: String(form.software_version || '').trim()
  }
  return Object.values(payload).every(Boolean) ? payload : null
}

export function knowledgeScopeFingerprint(form) {
  return JSON.stringify([form.market, form.product_model_id, form.software_version])
}

export function knowledgeScopeLabel(scope) {
  if (!scope) return '历史范围待核实'
  return [scope.country ? `来源国家 ${scope.country}` : '', { domestic: '国内', overseas: '海外' }[scope.market], scope.model_name || scope.product_model_id, scope.software_version].filter(Boolean).join(' · ')
}
