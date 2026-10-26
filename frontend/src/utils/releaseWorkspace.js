export const RELEASE_WORKSPACE_TABS = [
  'search',
  'review',
  'releases',
  'compare',
  'feature-versions'
]

export const RELEASE_WORKBENCH_VIEWS = RELEASE_WORKSPACE_TABS.filter(
  tab => tab !== 'feature-versions'
)

export function normalizeReleaseTab(value) {
  const candidate = Array.isArray(value) ? value[0] : value
  return RELEASE_WORKSPACE_TABS.includes(candidate) ? candidate : 'search'
}

export function releaseWorkbenchUrl(tab) {
  return RELEASE_WORKBENCH_VIEWS.includes(tab)
    ? `/release-workbench/?embedded=1#${tab}`
    : ''
}

export function releaseWorkbenchStandaloneUrl(tab) {
  return RELEASE_WORKBENCH_VIEWS.includes(tab)
    ? `/release-workbench/#${tab}`
    : ''
}

export function releaseWorkbenchHealthUrl() {
  return '/release-workbench/api/v1/health'
}

export function isWorkbenchNavigationMessage(event, expectedOrigin) {
  return event?.origin === expectedOrigin
    && event?.data?.type === 'release-workbench:navigate'
    && RELEASE_WORKBENCH_VIEWS.includes(event.data.view)
}
