<template>
  <Teleport v-if="ready && route.path === path" to="#probe-management-actions">
    <div class="management-actions"><slot /></div>
  </Teleport>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'

defineProps({ path: { type: String, required: true } })
const route = useRoute()
const ready = ref(false)
onMounted(() => { ready.value = true })
</script>

<style scoped>
.management-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }
.management-actions :deep(.el-button + .el-button) { margin-left: 0; }
.management-actions :deep(.management-meta) { color: #909399; font-size: 12px; white-space: nowrap; }
</style>
