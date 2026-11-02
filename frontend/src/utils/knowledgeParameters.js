export const PARAMETER_PREVIEW_COLUMNS = [
  { key: 'model_name', label: '型号', width: 190, fixed: true },
  { key: 'status_label', label: '匹配状态', width: 140 },
  { key: 'specs_text', label: '规格 / IPN', width: 230 },
  { key: 'values_text', label: '参数值', width: 270 },
  { key: 'selection_text', label: '正式选型', width: 160 },
  { key: 'issues_text', label: '缺项 / 说明', width: 280 }
].map(column => ({ visible: true, fixed: false, ...column }))
export const parameterStatusLabel = status => ({ matched: '已匹配', missing_spec: '未匹配规格', needs_review: '需核对', multiple: '多种规格', missing: '缺少数据', ambiguous: '匹配有歧义', unsupported: '不允许支持', incomplete: '待补充', no_match: '未匹配' }[status] || status || '未明确')
export const parameterFailure = error => {
  const detail = error?.response?.data?.detail
  return typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map(item => item.msg || String(item)).join('；') : error?.message || '操作失败，请重试'
}
export function formatParameterValues(topic, values = {}) {
  return (topic?.fields || []).map(field => `${field.label}：${values[field.key] == null || values[field.key] === '' ? '未填写' : `${values[field.key]}${field.unit ? ' ' + field.unit : ''}`}`).join('；')
}
export function filterParameterRows(rows, search, statuses) {
  const needle = String(search || '').trim().toLowerCase()
  return rows.filter(row => (statuses == null || statuses.includes(row.status)) && (!needle || JSON.stringify(row).toLowerCase().includes(needle)))
}
export const parameterTopicPayload = form => ({ name: form.name.trim(), question: form.question.trim(),
  aliases: String(form.aliases || '').split('\n').map(value => value.trim()).filter(Boolean),
  fields: form.fields.map((field,index) => ({ key: field.key.trim() || `parameter_${index+1}`, label: field.label.trim(), unit: field.unit.trim(), type: field.type })) })
export const parameterSpecPayload = (form, topic) => ({ name: form.name.trim(), ipn: form.ipn.trim(),
  values: Object.fromEntries(topic.fields.map(field => [field.key, form.values[field.key]])),
  evidence_reference: form.evidence_reference.trim(), confirmed_by: form.confirmed_by.trim(), is_active: form.is_active,
  ...(form.id ? { expected_revision: form.revision } : {}) })
export function createLatestParameterRequest() {
  let sequence = 0
  return {
    invalidate() { sequence += 1 },
    async run(request, handlers) {
      const current = ++sequence
      handlers.start?.()
      try { const result = await request(); if (current === sequence) handlers.success?.(result) }
      catch (error) { if (current === sequence) handlers.error?.(error) }
      finally { if (current === sequence) handlers.finish?.() }
    }
  }
}
export function createParameterEditor({ state, save, confirmDiscard, onSaved }) {
  let session = 0, baseline = ''
  return {
    open(kind, value) {
      session += 1
      Object.assign(state, { kind, form: JSON.parse(JSON.stringify(value)), visible: true, saving: false, error: '' })
      baseline = JSON.stringify(state.form)
    },
    async close(done) {
      if (state.saving) return
      if (JSON.stringify(state.form) !== baseline) { try { await confirmDiscard() } catch { return } }
      session += 1; state.visible = false
      if (typeof done === 'function') done()
    },
    async submit() {
      if (state.saving) return
      const current = session, kind = state.kind, source = JSON.parse(JSON.stringify(state.form))
      state.saving = true; state.error = ''
      try {
        const result = await save(kind, source)
        if (current !== session) return
        baseline = JSON.stringify(state.form); state.visible = false
        await onSaved?.(result, kind, source)
      } catch (error) { if (current === session) state.error = parameterFailure(error) }
      finally { if (current === session) state.saving = false }
    }
  }
}
