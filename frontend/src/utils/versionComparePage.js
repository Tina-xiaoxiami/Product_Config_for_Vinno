export const VERSION_OPTION_PAGE_SIZE = 100

export function positiveQueryId(value) {
  return typeof value === 'string' && /^[1-9]\d*$/.test(value) && Number.isSafeInteger(Number(value)) ? Number(value) : null
}

export function createVersionCompareState() {
  return { series: [], selectedSeries: null, versions: [], version1: null, version2: null, result: null, optionsLoading: false, loading: false, error: '' }
}

// One controller owns the complete historical catalog and request lifecycle.
// The matrix component keeps local model/field selections and exports canonical IDs.
export function createVersionCompareController(state, api, isActive) {
  let catalogRequest = 0, comparisonRequest = 0
  function invalidateComparison() {
    comparisonRequest++
    state.loading = false
    state.result = null
  }
  function deactivate() {
    catalogRequest++
    invalidateComparison()
    state.optionsLoading = false
  }
  async function load(query = {}) {
    const request = ++catalogRequest
    invalidateComparison()
    state.error = ''
    state.optionsLoading = true
    state.versions = []
    state.version1 = null
    state.version2 = null
    const current = () => isActive() && request === catalogRequest
    try {
      if (!state.series.length) {
        const response = await api.getSeriesList()
        if (!current()) return
        state.series = response.items || []
      }
      const requestedSeries = positiveQueryId(query.series)
      state.selectedSeries = state.series.find(series => series.id === requestedSeries)?.id
        ?? state.series.find(series => series.id === state.selectedSeries)?.id ?? state.series[0]?.id ?? null
      if (!state.selectedSeries) return
      const seriesId = state.selectedSeries, versions = []
      let skip = 0, total = Infinity
      while (skip < total) {
        const response = await api.getVersions(seriesId, { skip, limit: VERSION_OPTION_PAGE_SIZE })
        if (!current()) return
        const items = response.items || []
        versions.push(...items)
        total = response.total || 0
        if (!items.length) break
        skip += items.length
      }
      state.versions = versions
      const requestedVersion = positiveQueryId(query.version)
      const index = Math.max(0, versions.findIndex(version => version.id === requestedVersion))
      state.version1 = versions[index]?.id ?? null
      state.version2 = (versions[index + 1] || versions[index - 1])?.id ?? null
    } catch (error) {
      if (current()) state.error = '加载版本失败，请重试'
    } finally {
      if (current()) state.optionsLoading = false
    }
  }
  async function compare() {
    invalidateComparison()
    if (!isActive() || state.optionsLoading || !state.version1 || !state.version2 || state.version1 === state.version2) return
    if (![state.version1, state.version2].every(id => state.versions.some(version => version.id === id))) return
    const request = comparisonRequest, seriesId = state.selectedSeries, first = state.version1, second = state.version2
    const current = () => isActive() && request === comparisonRequest && seriesId === state.selectedSeries && first === state.version1 && second === state.version2
    state.loading = true
    state.error = ''
    try {
      const result = await api.compareVersions({ version_id_1: first, version_id_2: second })
      if (current()) state.result = result
    } catch (error) {
      if (current()) state.error = '版本对比失败，请重试'
    } finally {
      if (current()) state.loading = false
    }
  }
  return { load, compare, invalidateComparison, deactivate }
}
