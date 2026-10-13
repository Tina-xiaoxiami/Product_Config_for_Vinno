// Working values may already include drafts after a reload; keep their baseline.
export function draftBaseline(change, fallback) {
  return change && Object.hasOwn(change, 'oldValue') ? change.oldValue : fallback
}

export function draftWorkingValue(change, fallback) {
  return change && Object.hasOwn(change, 'newValue') ? change.newValue : fallback
}

export function updateDraftStats(stats, previousType, nextType) {
  const result = { ...stats }
  if (previousType) {
    result.total = Math.max(0, result.total - 1)
    result[previousType] = Math.max(0, (result[previousType] || 0) - 1)
  }
  if (nextType) {
    result.total += 1
    result[nextType] = (result[nextType] || 0) + 1
  }
  return result
}
