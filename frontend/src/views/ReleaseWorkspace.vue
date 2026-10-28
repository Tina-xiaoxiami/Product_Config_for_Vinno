<template>
  <div class="release-workspace">
    <header class="workspace-header">
      <div>
        <h2>功能发布</h2>
      </div>
      <a v-if="isWorkbenchTab(activeTab)" :href="releaseWorkbenchStandaloneUrl(activeTab)" class="standalone-link" target="_blank" rel="noopener noreferrer">独立窗口 ↗</a>
    </header>

    <el-tabs v-model="activeTab" class="workspace-tabs">
      <el-tab-pane label="发布资料检索" name="search" />
      <el-tab-pane label="文件同步" name="review" />
      <el-tab-pane label="发布版本" name="releases" />
      <el-tab-pane label="发布对比" name="compare" />
      <el-tab-pane label="功能版本管理" name="feature-versions" />
    </el-tabs>

    <section v-show="isWorkbenchTab(activeTab)" class="workspace-body">
      <div class="workbench-stack">
        <div class="workbench-frame-shell">
          <div v-if="workbenchState.status === 'checking'" class="workbench-status">
            <el-icon class="is-loading"><Loading /></el-icon>
            <strong>正在连接发布工作台…</strong>
            <span>正在准备发布资料视图，请稍候。</span>
          </div>

          <el-result
            v-else-if="workbenchState.status === 'error'"
            icon="warning"
            title="发布工作台暂时无法加载"
            :sub-title="workbenchState.message"
          >
            <template #extra>
              <el-button
                type="primary"
                data-testid="release-workbench-retry"
                @click="checkWorkbenchAvailability(true)"
              >重试</el-button>
              <el-button
                tag="a"
                :href="releaseWorkbenchStandaloneUrl(lastWorkbenchView)"
                target="_blank"
                rel="noopener noreferrer"
                data-testid="release-workbench-standalone"
              >在新窗口打开</el-button>
            </template>
          </el-result>

          <iframe
            v-else-if="workbenchState.status === 'ready' && workbenchFrameUrl"
            :key="workbenchState.frameKey"
            ref="workbenchFrame"
            class="workbench-frame"
            :src="workbenchFrameUrl"
            title="发布资料工作台"
            @load="markWorkbenchLoaded"
            @error="markWorkbenchError"
          />
        </div>
      </div>
    </section>

    <section
      v-if="nativeReleaseMounted"
      v-show="activeTab === 'feature-versions'"
      class="workspace-body native-release-pane"
    >
      <FeatureRelease />
    </section>
  </div>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Loading } from '@element-plus/icons-vue'

import FeatureRelease from './FeatureRelease.vue'
import {
  RELEASE_WORKBENCH_VIEWS,
  isWorkbenchNavigationMessage,
  normalizeReleaseTab,
  releaseWorkbenchHealthUrl,
  releaseWorkbenchStandaloneUrl,
  releaseWorkbenchUrl
} from '../utils/releaseWorkspace'

const route = useRoute()
const router = useRouter()

const isWorkbenchTab = tab => RELEASE_WORKBENCH_VIEWS.includes(tab)
const activeTab = ref(normalizeReleaseTab(route.query.tab))
const nativeReleaseMounted = ref(activeTab.value === 'feature-versions')
const initialWorkbenchView = isWorkbenchTab(activeTab.value) ? activeTab.value : 'search'
const lastWorkbenchView = ref(initialWorkbenchView)
const workbenchFrame = ref(null)
const workbenchFrameUrl = ref('')
const workbenchState = reactive({
  status: 'idle',
  message: '',
  frameKey: 0
})

async function checkWorkbenchAvailability(force = false) {
  if (!force && (workbenchState.status === 'checking' || workbenchState.status === 'ready')) return

  workbenchState.status = 'checking'
  workbenchState.message = ''
  try {
    const response = await fetch(releaseWorkbenchHealthUrl(), {
      cache: 'no-store',
      headers: { Accept: 'application/json' }
    })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    if (force) workbenchState.frameKey += 1
    workbenchState.status = 'ready'
  } catch (error) {
    workbenchState.status = 'error'
    workbenchState.message = `请确认产品配置后端已启动，然后重试（${error.message || '连接失败'}）。`
  }
}

function mountWorkbench(tab) {
  if (!isWorkbenchTab(tab)) return
  if (!workbenchFrameUrl.value) workbenchFrameUrl.value = releaseWorkbenchUrl(tab)
  checkWorkbenchAvailability()
}

function postWorkbenchActivation(tab) {
  if (!isWorkbenchTab(tab)) return
  workbenchFrame.value?.contentWindow?.postMessage({
    type: 'release-workspace:activate',
    view: tab
  }, window.location.origin)
}

function markWorkbenchLoaded() {
  postWorkbenchActivation(lastWorkbenchView.value)
}

function markWorkbenchError() {
  workbenchState.status = 'error'
  workbenchState.message = '嵌入页面加载失败，请重试或在新窗口打开。'
}

function handleWorkbenchMessage(event) {
  if (!isWorkbenchNavigationMessage(event, window.location.origin)) return
  if (workbenchFrame.value?.contentWindow !== event.source) return
  activeTab.value = event.data.view
}

watch(() => route.query.tab, value => {
  const tab = normalizeReleaseTab(value)
  if (tab !== activeTab.value) activeTab.value = tab
})

watch(activeTab, tab => {
  if (isWorkbenchTab(tab)) {
    lastWorkbenchView.value = tab
    mountWorkbench(tab)
    nextTick(() => postWorkbenchActivation(tab))
  }
  if (tab === 'feature-versions') nativeReleaseMounted.value = true
  const routeTab = Array.isArray(route.query.tab) ? route.query.tab[0] : route.query.tab
  if (routeTab !== tab) {
    router.replace({ query: { ...route.query, tab } })
  }
}, { immediate: true })

onMounted(() => window.addEventListener('message', handleWorkbenchMessage))
onBeforeUnmount(() => window.removeEventListener('message', handleWorkbenchMessage))
</script>

<style scoped>
.release-workspace {
  height: calc(100vh - 24px);
  min-height: 420px;
  display: flex;
  flex-direction: column;
  color: #1f2937;
}

.workspace-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 4px 2px 12px;
}

.workspace-header h2 { margin: 0 0 4px; font-size: 20px; }
.workspace-header > .standalone-link { margin-top: 6px; }
.workspace-tabs { flex: 0 0 auto; }
.workspace-tabs :deep(.el-tabs__header) { margin-bottom: 10px; }
.workspace-tabs :deep(.el-tabs__content) { display: none; }

.workspace-body {
  min-height: 0;
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #fff;
  border: 1px solid #dbe3ec;
  border-radius: 8px;
}

.standalone-link { color: #2563eb; font-size: 12px; white-space: nowrap; text-decoration: none; }
.standalone-link:hover { text-decoration: underline; }

.workbench-stack,
.workbench-frame-shell { min-height: 0; flex: 1 1 auto; }
.workbench-frame-shell { height: 100%; }
.workbench-frame { display: block; width: 100%; height: 100%; border: 0; background: #fff; }
.workbench-status {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #64748b;
}
.workbench-status .el-icon { font-size: 28px; color: #409eff; }
.workbench-status strong { color: #334155; }
.workbench-status span { font-size: 12px; }

.native-release-pane { overflow: auto; }
.native-release-pane > :deep(.feature-release) { padding: 14px; }

@media (max-width: 900px) {
  .release-workspace { min-height: 420px; }
  .workspace-header { flex-wrap: wrap; }
}
</style>
