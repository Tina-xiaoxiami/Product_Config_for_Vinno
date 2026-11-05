import { nextTick, onActivated, onMounted } from 'vue'

// Layout retains workspaces with KeepAlive. Re-entering a page must read the
// shared source again, while an editor can defer refresh until its draft is safe.
export function useWorkspaceRefresh(refresh, { canRefresh = () => true } = {}) {
  let mounting = true
  const run = () => canRefresh() ? refresh() : undefined
  onMounted(() => {
    nextTick(() => { mounting = false })
    return run()
  })
  onActivated(() => {
    if (mounting) return
    return run()
  })
}
