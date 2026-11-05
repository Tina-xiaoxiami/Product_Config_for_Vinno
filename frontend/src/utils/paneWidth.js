export const DEFAULT_PANE_WIDTH = 440
export const PANE_MIN = 280
export const PANE_MAX = 640
export const CONTENT_MIN = 520
export const SPLITTER_WIDTH = 12

export function paneLayout(containerWidth, preferred = DEFAULT_PANE_WIDTH) {
  const stacked = containerWidth < PANE_MIN + CONTENT_MIN + SPLITTER_WIDTH
  const max = Math.max(PANE_MIN, Math.min(PANE_MAX, containerWidth - CONTENT_MIN - SPLITTER_WIDTH))
  const safe = Number.isFinite(preferred) ? preferred : DEFAULT_PANE_WIDTH
  return { stacked, min: PANE_MIN, max, width: Math.round(Math.min(max, Math.max(PANE_MIN, safe))) }
}

export function loadPaneWidth(storage, key) {
  try {
    const value = storage.getItem(key)
    const width = value == null || value.trim() === '' ? NaN : Number(value)
    return Number.isFinite(width) && width >= PANE_MIN && width <= PANE_MAX ? width : DEFAULT_PANE_WIDTH
  } catch { return DEFAULT_PANE_WIDTH }
}

export function savePaneWidth(storage, key, width) {
  try { storage.setItem(key, String(width)) } catch { /* A view preference must not block the workspace. */ }
}
