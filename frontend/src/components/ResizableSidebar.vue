<template>
  <div ref="container" class="resizable-sidebar" :class="{ 'is-stacked': layout.stacked, 'is-dragging': drag }" :style="{ '--sidebar-width': `${preview ?? layout.width}px` }">
    <div :id="paneId" class="resizable-sidebar-pane"><slot name="sidebar" /></div>
    <div v-if="!layout.stacked" ref="separator" class="sidebar-separator" role="separator" tabindex="0" aria-orientation="vertical" :aria-label="separatorLabel" :aria-controls="paneId" :aria-valuemin="layout.min" :aria-valuemax="layout.max" :aria-valuenow="preview ?? layout.width" title="拖动调节宽度；双击恢复默认；方向键微调" @pointerdown="start" @pointermove="move" @pointerup="finish" @pointercancel="cancel" @lostpointercapture="cancel" @keydown="keyboard" @dblclick="reset"><span /></div>
    <div class="resizable-sidebar-content"><slot /></div>
  </div>
</template>
<script setup>
import { computed, getCurrentInstance, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'
import { DEFAULT_PANE_WIDTH, loadPaneWidth, paneLayout, savePaneWidth } from '../utils/paneWidth'

const props = defineProps({ storageKey: { type: String, required: true }, separatorLabel: { type: String, default: '调整侧栏宽度' } })
const storage = { getItem: key => localStorage.getItem(key), setItem: (key, value) => localStorage.setItem(key, value) }
const preferred = ref(loadPaneWidth(storage, props.storageKey))
const container = ref(null), separator = ref(null), width = ref(0), preview = ref(null), drag = ref(null)
const paneId = `resizable-sidebar-${getCurrentInstance().uid}`
const layout = computed(() => paneLayout(width.value, preferred.value))
let observer
function clamp(value) { return paneLayout(width.value, value).width }
function commit(value) { preferred.value = clamp(value); savePaneWidth(storage, props.storageKey, preferred.value) }
function start(event) {
  if (event.button !== 0 || layout.value.stacked) return
  event.preventDefault()
  separator.value.focus()
  drag.value = { pointerId: event.pointerId, x: event.clientX, width: layout.value.width }
  preview.value = layout.value.width
  event.currentTarget.setPointerCapture(event.pointerId)
}
function move(event) { if (drag.value?.pointerId === event.pointerId) preview.value = clamp(drag.value.width + event.clientX - drag.value.x) }
function cancel() {
  const pointerId = drag.value?.pointerId
  drag.value = null; preview.value = null
  if (pointerId != null && separator.value?.hasPointerCapture(pointerId)) separator.value.releasePointerCapture(pointerId)
}
function finish(event) { if (drag.value?.pointerId !== event.pointerId) return; commit(preview.value); cancel() }
function reset() { cancel(); preferred.value = DEFAULT_PANE_WIDTH; savePaneWidth(storage, props.storageKey, DEFAULT_PANE_WIDTH) }
function keyboard(event) {
  if (event.key === 'Escape' && drag.value) { event.preventDefault(); cancel(); return }
  const values = { ArrowLeft: layout.value.width - (event.shiftKey ? 48 : 16), ArrowRight: layout.value.width + (event.shiftKey ? 48 : 16), Home: layout.value.min, End: layout.value.max }
  if (event.key in values) { event.preventDefault(); cancel(); commit(values[event.key]) }
}
onMounted(() => {
  observer = new ResizeObserver(entries => {
    const next = entries[0].contentRect.width
    if (next !== width.value) { cancel(); width.value = next }
  })
  observer.observe(container.value)
})
onDeactivated(cancel)
onBeforeUnmount(() => { cancel(); observer?.disconnect() })
</script>
<style scoped>
.resizable-sidebar{display:grid;grid-template-columns:var(--sidebar-width) 12px minmax(0,1fr);min-width:0;min-height:0;flex:1}
.resizable-sidebar-pane,.resizable-sidebar-content{display:flex;flex-direction:column;min-width:0;min-height:0}
.sidebar-separator{display:flex;align-items:center;justify-content:center;cursor:col-resize;touch-action:none;outline:none;border-radius:5px}
.sidebar-separator span{height:40px;width:3px;border-radius:3px;background:var(--el-border-color)}
.sidebar-separator:hover,.sidebar-separator:focus-visible,.is-dragging .sidebar-separator{background:var(--el-color-primary-light-9)}
.sidebar-separator:hover span,.sidebar-separator:focus-visible span,.is-dragging .sidebar-separator span{background:var(--el-color-primary)}
.sidebar-separator:focus-visible{outline:2px solid var(--el-color-primary-light-5);outline-offset:-2px}
.is-dragging{user-select:none}
.is-stacked{grid-template-columns:minmax(0,1fr);grid-template-rows:auto minmax(260px,1fr);gap:10px}
</style>
