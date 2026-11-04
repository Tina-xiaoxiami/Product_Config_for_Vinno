<template>
  <router-view />
  <FeatureNameReviewDialog ref="nameEditor" global-host />
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import FeatureNameReviewDialog from './components/FeatureNameReviewDialog.vue'
import { registerFeatureNameReview } from './utils/featureNameReviewHost'
const nameEditor = ref(null)
const router = useRouter()
let stopOpening, stopLeaving
onMounted(() => {
  stopOpening = registerFeatureNameReview((id, mode) => nameEditor.value.open(id, mode))
  stopLeaving = router.beforeEach(() => nameEditor.value.requestLeave())
})
onBeforeUnmount(() => { stopOpening?.(); stopLeaving?.() })
</script>

<style>
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
}
</style>