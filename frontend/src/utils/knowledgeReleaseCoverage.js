import { knowledgeScopePayload, knowledgeScopeLabel } from './knowledgeQueryScope.js'

export function coverageRequestPayload(form) {
  const scope = knowledgeScopePayload(form)
  if (scope && form.country?.trim()) scope.country = form.country.trim().toUpperCase()
  return { scope }
}

export function coverageScopeNotice(payload) {
  return payload.scope
    ? `本次检查范围：${knowledgeScopeLabel(payload.scope)}；适用范围未识别的文件仅列为候选问题。`
    : '本次检查全部已配置来源；当前查询范围未填写完整，不代表已核对某个型号。'
}

export function coverageAssessment(report) {
  if (!report) return '尚未检查资料覆盖'
  if (report.completeness === 'gaps_found') return '发现资料覆盖缺口'
  if (report.completeness === 'no_known_gaps' && report.scan_status === 'checked' && report.roots?.length && report.roots.every(root => root.status === 'scanned')) {
    return '未发现已知缺口（限已配置目录）'
  }
  return '覆盖完整性未验证'
}

export function coverageTraceBoundary(trace, report = null) {
  if (report) return '来源覆盖检查见上方结果；已登记资料的检索数量不能代表全部历史完整，检查结果仅限所列目录及检查时间。'
  return trace?.coverage?.coverage_message || '已登记资料的检索数量不能代表全部历史完整；来源目录尚未完成覆盖检查。'
}

export function coverageItems(report, onlyGaps = true, query = '') {
  const needle = String(query || '').trim().toLocaleLowerCase()
  return (Array.isArray(report?.items) ? report.items : []).filter(item => {
    const isGap = typeof item.is_gap === 'boolean' ? item.is_gap
      : Boolean(item.issues?.length && item.range_status !== 'after_target' && item.applicability_status !== 'not_applicable')
    if (onlyGaps && !isGap) return false
    return !needle || [item.file_name, item.version, ...(item.source_locations || []), ...(item.issues || []).flatMap(issue => [issue.reason, issue.action])]
      .some(value => String(value || '').toLocaleLowerCase().includes(needle))
  })
}

const labels = {
  registration: { registered: '已登记', unregistered: '未登记' },
  extraction: { completed: '提取完成', failed: '提取失败', stale: '提取已过期', pending: '尚未提取', not_registered: '未登记，尚未提取', unsupported: '格式暂不支持提取', unavailable: '原件不可用' },
  applicability: { applicable: '原文适用于当前范围', not_applicable: '当前范围不适用', unrecognized: '适用范围未识别', not_requested: '未指定型号范围' },
  range: { within_target: '目标版本以内', after_target: '晚于目标版本', unknown: '版本范围未识别', not_requested: '未限定目标版本' },
  language: { zh: '中文线索', en: '英文线索', unknown: '语言未识别' },
  version: { source_extract: '正文明确版本', filename_candidate: '文件名或目录候选，发布资格未核验', unknown: '版本来源未识别' },
  root: { scanned: '已扫描', missing: '目录不可用', error: '扫描失败' }
}
export const coverageStatusLabel = (type, value) => labels[type]?.[value] || '未识别'

export function registeredPreviewUrl(item) {
  const match = /^\/api\/knowledge\/documents\/([1-9]\d*)\/preview$/.exec(String(item.preview_url || ''))
  return match && item.document_ids?.some(id => String(id) === match[1]) ? match[0] : ''
}

export function createCoverageState() {
  return { report: null, loading: false, error: '', scopeNotice: '' }
}

function validReport(value) {
  return value && typeof value === 'object' && Array.isArray(value.items) && Array.isArray(value.roots)
    && value.totals && typeof value.totals === 'object'
    && ['checked', 'partial', 'unavailable', 'not_configured'].includes(value.scan_status)
    && ['gaps_found', 'no_known_gaps', 'unverified'].includes(value.completeness)
}

export function createCoverageWorkspace(api, state) {
  let requestId = 0, disposed = false
  const invalidate = () => {
    requestId += 1
    state.report = null; state.loading = false; state.error = ''; state.scopeNotice = ''
  }
  const check = async form => {
    if (disposed) return false
    const request = ++requestId, payload = coverageRequestPayload(form)
    state.report = null; state.error = ''; state.loading = true; state.scopeNotice = coverageScopeNotice(payload)
    try {
      const report = await api.checkReleaseCoverage(payload)
      if (disposed || request !== requestId) return false
      if (!validReport(report)) throw new Error('覆盖检查返回内容不完整，请重试')
      state.report = report
      return true
    } catch (failure) {
      if (disposed || request !== requestId) return false
      state.error = `资料覆盖检查失败：${failure?.response?.data?.detail || failure?.message || '请重试'}`
      return false
    } finally {
      if (!disposed && request === requestId) state.loading = false
    }
  }
  return { check, invalidate, dispose: () => { disposed = true; invalidate() } }
}
