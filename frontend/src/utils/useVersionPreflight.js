import { reactive, watch, onScopeDispose } from 'vue'

// Invalidate synchronously so a changed input cannot submit an older validation.
export function useVersionPreflight(getInput, check, delay = 300) {
  let request = 0
  let timer
  const state = reactive({ pending: false, error: '', recheck: () => schedule(getInput()) })
  function schedule(input) {
    const current = ++request
    clearTimeout(timer)
    state.error = ''
    const seriesIds = [...new Set(input.seriesIds)]
    state.pending = input.enabled && seriesIds.length > 0
    if (!state.pending) return
    const versionNumber = input.versionNumber
    timer = setTimeout(async () => {
      try {
        const response = await check({ seriesIds, versionNumber })
        if (current !== request) return
        const results = new Map((response.results || []).map(result => [result.series_id, result]))
        state.error = seriesIds.map(id => {
          const result = results.get(id)
          return result?.valid === true ? '' : result?.message || '版本号校验结果不完整，请重新校验'
        }).filter(Boolean).join('\n')
      } catch {
        if (current === request) state.error = '版本号校验失败，请检查连接后重新校验'
      } finally {
        if (current === request) state.pending = false
      }
    }, delay)
  }
  watch(() => JSON.stringify(getInput()), () => schedule(getInput()), { immediate: true, flush: 'sync' })
  onScopeDispose(() => { request++; clearTimeout(timer) })
  return state
}
