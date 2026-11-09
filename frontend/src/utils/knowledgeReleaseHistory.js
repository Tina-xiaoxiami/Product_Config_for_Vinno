import { knowledgeScopePayload } from './knowledgeQueryScope.js'

export function historyTracePayload(form) {
  const scope = knowledgeScopePayload(form), query = String(form.query || '').trim()
  if (!scope || query.length < 2) return null
  if (form.country?.trim()) scope.country = form.country.trim().toUpperCase()
  return { query, scope, ...(form.release_line?.trim() ? { release_line: form.release_line.trim() } : {}) }
}
export const historyAssessmentLabel = status => ({ unavailable: '追溯尚未初始化', scope_unconfirmed: '资料适用范围待核对',
  no_applicable_documents: '缺少适用资料', no_record: '未检索到明确记录', conflicting_evidence: '版本证据存在冲突', conditional_evidence: '存在分支或条件限制', evidence_found: '找到历史原文记录' }[status] || '历史证据')
