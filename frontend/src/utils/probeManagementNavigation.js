export const PROBE_MANAGEMENT_TABS = [
  { path: '/template-features', label: '模板管理' },
  { path: '/probe-models', label: '探头管理' },
  { path: '/applications', label: '应用管理' }
]

export function probeManagementMenuPath(path) {
  return path === '/feature-manage' || PROBE_MANAGEMENT_TABS.some(tab => tab.path === path) ? '/template-features' : path
}
