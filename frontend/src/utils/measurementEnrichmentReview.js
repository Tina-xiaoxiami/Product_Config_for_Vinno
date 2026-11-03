export const REVIEW_CATEGORIES = ['Common', 'ABD', 'CARD', 'GYN', 'OB', 'VAS']
export const REVIEW_MODES = ['Tissue', 'Flow', 'TissueTM', 'Doppler', 'EI', 'PWVTM', 'STRAINRATETM', 'VShear', 'pVShear', 'URM', 'VATT', 'SMF']
export const REVIEW_RELATIONS = [
  { value: 'input', label: '候选输入' },
  { value: 'alternative', label: '可能替代输入' },
  { value: 'context', label: '分类上下文' },
  { value: 'unresolved', label: '待核对关联' }
]
export function reviewStatusLabel(status) {
  return { pending: '待人工核对', proposed: '候选建议', unresolved: '待补依据', confirmed: '已确认', rejected: '已拒绝', deferred: '已暂缓', revoked: '已撤销确认', stale_source: '原始资料已变化', needs_review: '待人工核对', available: '可核对', unreviewed: '尚未核对' }[status] || '状态待核对'
}
export function reviewCategoryLabel(category) {
  return { Common: '通用', ABD: '腹部', CARD: '心脏', GYN: '妇科', OB: '产科', VAS: '血管' }[category] || category
}
const clone = value => JSON.parse(JSON.stringify(value))
const text = value => typeof value === 'string' ? value.trim() : ''

export function safeSourceUrl(value) {
  const urlText = text(value)
  if (!/^https?:\/\//i.test(urlText) || /[\u0000-\u0020\u007f]/.test(urlText)) return ''
  try {
    const url = new URL(urlText)
    return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : ''
  } catch { return '' }
}

export function dependencyKey(value) {
  return JSON.stringify([value.kind, value.item_id])
}

export function parseDependencyKey(value) {
  try {
    const pair = JSON.parse(value)
    return Array.isArray(pair) && pair.length === 2 && ['measurement', 'calculation'].includes(pair[0]) && typeof pair[1] === 'string' && pair[1].length
      ? { kind: pair[0], item_id: pair[1] } : null
  } catch { return null }
}

export function dependencyOptions(records, batchId) {
  const options = new Map()
  for (const row of records) {
    if (row.batch_id !== batchId || !['measurement', 'calculation'].includes(row.kind) || typeof row.item_id !== 'string') continue
    const key = dependencyKey(row)
    if (!options.has(key)) options.set(key, { key, label: `${row.kind === 'calculation' ? '计算' : '测量'} · ${row.item_id}${row.cn_name ? ` · ${row.cn_name}` : ''}` })
  }
  return [...options.values()]
}

export function visibleDependencyOptions(options, query, selectedKeys = [], limit = 80) {
  const selected = new Set(selectedKeys)
  const needle = text(query).toLocaleLowerCase()
  const matches = options.filter(option => !selected.has(option.key) && (!needle || option.label.toLocaleLowerCase().includes(needle))).slice(0, limit)
  return [...options.filter(option => selected.has(option.key)), ...matches]
}

export function cloneReviewPayload(detail) {
  const payload = clone(detail?.enrichment?.candidate?.payload || {})
  return { ...payload, categories: payload.categories || [], modes: payload.modes || [], input_terms: (payload.input_terms || []).map(term => ({ ...term, relation_kind: term.relation_kind || 'input' })), formula_reference: payload.formula_reference || '', sources: payload.sources || [], uncertainties: payload.uncertainties || [], research_status: payload.research_status || 'unresolved' }
}

export function reviewSnapshot(value) {
  const canonical = entry => Array.isArray(entry) ? entry.map(canonical) : entry && typeof entry === 'object'
    ? Object.fromEntries(Object.keys(entry).sort().map(key => [key, canonical(entry[key])])) : entry
  return JSON.stringify(canonical(value))
}

export function validateReviewForm(form, action, detail) {
  if (detail?.enrichment?.status === 'stale_source') return '原始资料已变化，请等待更新后的候选资料再核对'
  if (!['confirm', 'reject', 'defer', 'revoke'].includes(action)) return '请选择有效的核对操作'
  if (!text(form.confirmed_by)) return '请填写本次核对人'
  if (action !== 'confirm') return text(form.note) ? '' : '请填写处理说明或理由'
  const payload = form.payload
  if (!Array.isArray(payload?.categories) || !payload.categories.length || payload.categories.some(value => !REVIEW_CATEGORIES.includes(value))) return '请至少选择一个有效分类'
  if (!Array.isArray(payload.modes) || payload.modes.some(value => !REVIEW_MODES.includes(value))) return '请核对成像模式'
  if (payload.research_status !== 'proposed') return '待补依据的研究状态不能直接确认，请补充依据后明确改为候选建议'
  if (detail?.enrichment?.candidate?.payload?.research_status === 'unresolved' && !text(form.note)) return '请填写待补依据项转为可确认建议的说明'
  if (!Array.isArray(payload.sources) || !payload.sources.length || payload.sources.some(source => !safeSourceUrl(source.url) || !text(source.title) || !text(source.locator) || !Array.isArray(source.supports) || !source.supports.some(text))) return '请补全至少一条有效来源（HTTP(S)链接、标题、定位和支持内容）'
  if (!Array.isArray(payload.input_terms)) return '请核对输入术语与候选依赖'
  if (payload.input_terms.some(term => !REVIEW_RELATIONS.some(option => option.value === term.relation_kind))) return '请核对术语关联类型'
  if (!Array.isArray(payload.input_terms) || payload.input_terms.some(term => !text(term.term) || !Array.isArray(term.possible_dependencies) || term.possible_dependencies.some(dependency => !parseDependencyKey(dependencyKey(dependency))))) return '请核对输入术语与候选依赖'
  return ''
}

export function buildReviewRequest(detail, form, action) {
  const enrichment = detail.enrichment
  return {
    action,
    expected_candidate_fingerprint: enrichment.candidate.fingerprint,
    expected_source_fingerprint: enrichment.source_fingerprint,
    expected_review_revision: enrichment.review_revision,
    confirmed_by: text(form.confirmed_by),
    note: text(form.note),
    ...(action === 'confirm' ? { confirmed_payload: clone(form.payload) } : {})
  }
}
