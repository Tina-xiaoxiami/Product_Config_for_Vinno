export function sourceApplicabilityDisplay(source) {
  const facts = source.source_applicability || {}
  return {
    id: source.document_id, title: source.title, preview_url: source.preview_url,
    version: facts.version?.value || source.version || '版本尚不明确',
    models: (facts.models || []).map(model => typeof model === 'string' ? model : `${model.name}${model.scope === 'series' ? '系列' : ''}`).join('、') || '原文未明确',
    country: facts.country?.value || '原文未声明', market: facts.market?.value || '原文未声明',
    status: ({ extracted: '原文直接提取', incomplete: '原文部分字段待补充', conflict: '存在字段冲突' })[facts.status] || '原文信息',
    fields: facts.field_evidence || []
  }
}
export const confirmationQuestion = item => item.question || item.reason || '请核对所列具体字段'
