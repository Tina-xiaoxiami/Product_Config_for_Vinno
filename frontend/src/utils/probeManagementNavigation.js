export const PROBE_MANAGEMENT_TABS = [
  { path: '/template-features', label: '模板管理' },
  { path: '/probe-models', label: '探头&应用' }
]

export function probeManagementRoutePath(path) {
  return path === '/feature-manage' ? '/template-features' : path === '/applications' ? '/probe-models' : path
}

export function probeManagementMenuPath(path) {
  const canonical = probeManagementRoutePath(path)
  return PROBE_MANAGEMENT_TABS.some(tab => tab.path === canonical) ? '/template-features' : canonical
}

export const probeApplicationsRedirect = to => ({
  path: '/probe-models', query: { ...to.query, focus: 'applications' }, hash: to.hash
})
