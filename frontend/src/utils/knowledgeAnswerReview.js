export const QA_COLUMNS = [
  { key: 'question_text', label: '问题', width: 300, fixed: true },
  { key: 'answer', label: '答案', width: 430 },
  { key: 'evidence_review', label: '核对状态', width: 115 },
  { key: 'asked_count', label: '询问次数', width: 85 },
  { key: 'version', label: '答案版本', width: 85 }
].map(column => ({ visible: true, fixed: false, ...column }))

export function answerReviewLabel(question) {
  if (question.answer?.review_status && question.answer.review_status !== 'published') return '依据已变化'
  const status = question.evidence_review?.status
  if (status === 'reviewed') return '已核对'
  if (status === 'needs_review') return question.evidence_review?.latest?.action === 'defer' ? '暂缓核对' : '待核对'
  return question.answer?.citations?.length ? '已有文档依据' : question.answer ? '核对状态未知' : '尚无答案'
}

export function answerReviewError(form) {
  if (!String(form.confirmed_by || '').trim()) return '请填写本次核对人'
  if (form.action === 'defer') return String(form.note || '').trim() ? '' : '请填写暂缓理由'
  if (!String(form.evidence_reference || '').trim()) return '请填写确认记录或文档依据'
  if (form.action === 'confirm_scope' && (
    !form.country?.trim() || !form.market || !form.product_model_ids?.length ||
    form.version_applicability !== 'specific' || !form.software_version?.trim()
  )) return '请明确国家、市场、完整机型及具体软件版本范围'
  return ''
}

export function answerReviewPayload(question, form) {
  return {
    expected_answer_version: question.answer.version,
    expected_fingerprint: question.evidence_review.fingerprint,
    expected_review_revision: question.evidence_review.review_revision,
    action: form.action,
    country: String(form.country || '').trim().toUpperCase() || null,
    market: form.market || null,
    product_model_ids: [...form.product_model_ids],
    software_version: form.version_applicability === 'specific' ? String(form.software_version || '').trim() || null : null,
    version_applicability: form.version_applicability,
    evidence_reference: String(form.evidence_reference || '').trim(),
    note: String(form.note || '').trim(),
    confirmed_by: String(form.confirmed_by || '').trim()
  }
}
