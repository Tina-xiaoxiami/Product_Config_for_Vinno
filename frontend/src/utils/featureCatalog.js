export function catalogCoverageLabel(coverage) {
  return coverage ? `配置覆盖 ${coverage.covered_items}/${coverage.configured_items}` : '配置覆盖待加载'
}

export function catalogCoverageType(coverage) {
  if (!coverage?.configured_items) return 'info'
  return coverage.unlinked_count === 0 && coverage.covered_items === coverage.configured_items ? 'success' : 'warning'
}
