// The editor belongs to the app, so filtering or renaming a column cannot destroy it.
let openEditor = null
export function registerFeatureNameReview(opener) {
  openEditor = opener
  return () => { if (openEditor === opener) openEditor = null }
}
export function openFeatureNameReview(featureId, displayMode = false) {
  return openEditor?.(featureId, displayMode)
}
