<template>
  <el-card shadow="never" class="version-compare-page">
    <template #header><span>版本对比</span></template>
    <el-tabs :model-value="state.selectedSeries" class="series-tabs" aria-label="对比产品系列" @tab-change="selectSeries">
      <el-tab-pane v-for="series in state.series" :key="series.id" :label="series.name" :name="series.id" />
    </el-tabs>
    <el-alert v-if="state.error" :title="state.error" type="error" :closable="false" show-icon class="load-error">
      <el-button size="small" @click="retry">重试</el-button>
    </el-alert>
    <VersionComparison v-if="active" :key="state.selectedSeries"
      v-model:version1="state.version1" v-model:version2="state.version2"
      :versions="state.versions" :options-loading="state.optionsLoading" :result="state.result" :loading="state.loading"
      @compare="controller.compare" />
    <el-alert v-if="!state.optionsLoading && !state.error && state.versions.length < 2" type="info" :closable="false" title="该系列不足两个版本，暂时无法对比。" />
  </el-card>
</template>

<script setup>
import { reactive, ref, watch, onActivated, onDeactivated, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import VersionComparison from '../components/VersionComparison.vue'
import { getSeriesList, getVersions, compareVersions } from '../api/data'
import { createVersionCompareState, createVersionCompareController } from '../utils/versionComparePage'

const route = useRoute(), router = useRouter(), active = ref(false)
const state = reactive(createVersionCompareState())
const controller = createVersionCompareController(state, { getSeriesList, getVersions, compareVersions }, () => active.value && route.name === 'VersionCompare')
const selectSeries = id => {
  if (id === state.selectedSeries) return
  controller.deactivate()
  router.replace({ name: 'VersionCompare', query: { series: String(id) } })
}
const retry = () => state.versions.length >= 2 ? controller.compare() : controller.load(route.query)
watch(() => [state.version1, state.version2], controller.invalidateComparison, { flush: 'sync' })
watch(() => [route.query.series, route.query.version], () => {
  if (active.value && route.name === 'VersionCompare') controller.load(route.query)
}, { flush: 'sync' })
onActivated(() => { active.value = true; controller.load(route.query) })
const deactivate = () => { active.value = false; controller.deactivate() }
onDeactivated(deactivate)
onBeforeUnmount(deactivate)
</script>

<style scoped>
.version-compare-page { min-width: 0; }
.series-tabs { margin-bottom: 16px; }
.series-tabs :deep(.el-tabs__header) { margin-bottom: 0; }
.series-tabs :deep(.el-tabs__content) { display: none; }
.load-error { margin-bottom: 12px; }
</style>
