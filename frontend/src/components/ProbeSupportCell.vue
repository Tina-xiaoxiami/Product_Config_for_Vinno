<template><span class="probe-support-cell" :class="status || 'unsupported'" :title="text">{{ text }}</span></template>
<script setup>
import { computed } from 'vue'
import { formatProbeSupport } from '../utils/probeSupport'
const props = defineProps({ status: String, apps: {type:Array,default:()=>[]}, excludes:{type:Array,default:()=>[]}, tender:{type:Array,default:()=>[]}, mode:{type:String,default:'auto'} })
const text = computed(() => formatProbeSupport(props))
</script>
<style scoped>
.probe-support-cell{display:block;min-height:28px;padding:3px 5px;white-space:normal;overflow-wrap:anywhere;font-size:11px;line-height:1.35;background:#f1f5f9;color:#94a3b8;text-align:center}.supported{background:#dcfce7;color:#166534;font-weight:600}.conditional{background:#fef3c7;color:#92400e}.pending,.mixed{background:#fff7ed;color:#9a3412}.not_applicable{color:#64748b}
</style>
