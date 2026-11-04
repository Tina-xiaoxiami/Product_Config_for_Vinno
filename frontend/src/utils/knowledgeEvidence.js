const STATUSES = new Set(['draft', 'partial', 'no_evidence', 'validation_failed', 'unavailable', 'deterministic_required'])
export const evidenceStatusLabel = status => ({ draft: '资料草稿 · 未发布', partial: '部分资料草稿 · 未发布', no_evidence: '未找到可用原文', validation_failed: '原文核验未通过', unavailable: '资料问答暂不可用', deterministic_required: '请使用确定性查询' }[status] || '资料问答')
export const evidenceErrorMessage = error => typeof error?.response?.data?.detail === 'string' ? error.response.data.detail : '资料问答失败，请重试。'
export function evidenceCitationUrl(citation) {
  const id = citation?.document_id, url = citation?.preview_url
  if (!Number.isSafeInteger(id) || id <= 0 || typeof url !== 'string') return null
  return new RegExp(`^/api/knowledge/documents/${id}/preview(?:\\?version_id=[a-fA-F0-9]{64})?(?:#page=[1-9][0-9]*)?$`).test(url) ? url : null
}

const copy = value => JSON.parse(JSON.stringify(value))
const identity = value => JSON.stringify([String(value?.question || '').trim(), value?.scope || null])
function inputPayload(input) {
  const question = String(input?.question || '').trim(), scope = input?.scope
  if (question.length < 2) throw new Error('请输入至少两个字的问题。')
  if (!scope?.market || !Number.isSafeInteger(scope.product_model_id) || scope.product_model_id <= 0 || !String(scope.software_version || '').trim()) throw new Error('请补齐市场、完整机型和软件版本范围。')
  return { question, scope: copy(scope) }
}
function checkedResult(result) {
  if (!STATUSES.has(result?.status) || !Array.isArray(result.claims)) throw new Error('资料问答返回格式无效，请重试。')
  if (['draft', 'partial'].includes(result.status) && result.claims.some(claim => typeof claim.text !== 'string' || !Array.isArray(claim.citations) || !claim.citations.length || claim.citations.some(citation => !evidenceCitationUrl(citation)))) throw new Error('资料草稿缺少有效原文记录，请重试。')
  return { ...result, claims: ['draft', 'partial'].includes(result.status) ? result.claims : [] }
}

export function createEvidenceAnswerController({ state, getInput, request, capabilities }) {
  Object.assign(state, { loading: false, checking: false, available: null, unavailableReason: '', error: '', result: null, resultInput: null })
  let sequence = 0, capabilitySequence = 0, active = null, availability = null, disposed = false
  const invalidate = () => {
    sequence += 1
    active?.abort()
    active = null
    Object.assign(state, { loading: false, error: '', result: null, resultInput: null })
  }
  return {
    invalidate,
    async checkAvailability() {
      if (disposed) return false
      const current = ++capabilitySequence
      availability?.abort()
      availability = new AbortController()
      state.checking = true
      try {
        const result = await capabilities(availability.signal)
        if (disposed || current !== capabilitySequence) return false
        state.available = result?.available === true
        state.unavailableReason = state.available ? '' : result?.reason || '共享资料问答服务尚未启用。'
        return state.available
      } catch {
        if (!disposed && current === capabilitySequence) {
          state.available = false
          state.unavailableReason = '无法连接资料问答服务，请重试连接。'
        }
        return false
      } finally { if (!disposed && current === capabilitySequence) state.checking = false }
    },
    async run() {
      if (disposed || state.loading) return false
      let payload
      try { payload = inputPayload(getInput()) } catch (error) { state.error = error.message; return false }
      if (state.available !== true) { state.error = state.unavailableReason || '资料问答服务尚未就绪，请稍后重试。'; return false }
      const current = ++sequence, fingerprint = identity(payload)
      active = new AbortController()
      state.loading = true
      state.error = ''
      try {
        const result = await request(payload, active.signal)
        if (disposed || current !== sequence || fingerprint !== identity(getInput())) return false
        state.result = checkedResult(result)
        state.resultInput = payload
        return true
      } catch (error) {
        if (!disposed && current === sequence && fingerprint === identity(getInput())) state.error = error?.response ? evidenceErrorMessage(error) : error?.message || evidenceErrorMessage(error)
        return false
      } finally {
        if (!disposed && current === sequence) {
          state.loading = false
          active = null
        }
      }
    },
    dispose() {
      disposed = true
      capabilitySequence += 1
      availability?.abort()
      invalidate()
    }
  }
}
