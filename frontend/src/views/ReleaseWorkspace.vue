<template>
  <div class="release-workspace">
    <header class="workspace-header">
      <div>
        <h2>功能发布</h2>
      </div>
      <a v-if="isWorkbenchTab(activeTab)" :href="standaloneUrl(activeTab)" class="standalone-link" target="_blank" rel="noopener noreferrer">独立窗口 ↗</a>
    </header>

    <el-tabs v-model="workspaceMode" :before-leave="beforeWorkspaceModeLeave" class="workspace-tabs">
      <el-tab-pane label="查询" name="query" />
      <el-tab-pane label="资料管理" name="manage" />
    </el-tabs>
    <details v-if="activeTab !== 'search'" class="workspace-management-tools" :open="activeTab !== 'review'">
      <summary>版本记录与维护工具</summary>
    <el-tabs v-model="activeTab" :before-leave="beforeWorkspaceTabLeave" class="workspace-tabs workspace-management-tabs">
      <el-tab-pane label="文件同步" name="review" />
      <el-tab-pane label="发布版本" name="releases" />
      <el-tab-pane label="发布对比" name="compare" />
      <el-tab-pane label="功能版本管理" name="feature-versions" />
    </el-tabs>
    </details>

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
      <FeatureRelease ref="nativeRelease" />
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute, useRouter } from 'vue-router'
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
const lastManagementTab = ref(activeTab.value === 'search' ? 'review' : activeTab.value)
const workspaceMode = computed({
  get: () => activeTab.value === 'search' ? 'query' : 'manage',
  set: mode => { activeTab.value = mode === 'query' ? 'search' : lastManagementTab.value }
})
const nativeReleaseMounted = ref(activeTab.value === 'feature-versions')
const initialWorkbenchView = isWorkbenchTab(activeTab.value) ? activeTab.value : 'search'
const lastWorkbenchView = ref(initialWorkbenchView)
const workbenchFrame = ref(null)
const nativeRelease = ref(null)
const workbenchLocations = reactive({})
const standaloneUrl = tab => releaseWorkbenchStandaloneUrl(tab, workbenchLocations[tab], window.location.origin)

async function beforeWorkspaceTabLeave(next, current) {
  if (current !== 'feature-versions' || next === current) return true
  return await nativeRelease.value?.requestWorkspaceLeave() ?? true
}

function beforeWorkspaceModeLeave(next) {
  return beforeWorkspaceTabLeave(next === 'query' ? 'search' : lastManagementTab.value, activeTab.value)
}

onBeforeRouteLeave(() => beforeWorkspaceTabLeave('', activeTab.value))
onBeforeRouteUpdate((to, from) => {
  const next = normalizeReleaseTab(to.query.tab)
  const current = normalizeReleaseTab(from.query.tab)
  return beforeWorkspaceTabLeave(next, current)
})
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
  if (event.origin !== window.location.origin || workbenchFrame.value?.contentWindow !== event.source) return
  if (event.data?.type === 'release-workbench:location') {
    try {
      const url = new URL(event.data.url)
      const tab = url.hash.slice(1).split('?')[0]
      const safe = releaseWorkbenchStandaloneUrl(tab, url.href, window.location.origin)
      if (isWorkbenchTab(tab) && safe !== `/release-workbench/#${tab}`) workbenchLocations[tab] = url.href
      else if (safe === `/release-workbench/#${tab}` && url.origin === window.location.origin && url.pathname === '/release-workbench/' && url.hash === `#${tab}`) workbenchLocations[tab] = url.href
    } catch { /* Ignore invalid or untrusted locations. */ }
    return
  }
  if (activeTab.value !== 'feature-versions' && isWorkbenchNavigationMessage(event, window.location.origin)) activeTab.value = event.data.view
}

watch(() => route.query.tab, value => {
  const tab = normalizeReleaseTab(value)
  if (tab !== activeTab.value) activeTab.value = tab
})

watch(activeTab, tab => {
  if (tab !== 'search') lastManagementTab.value = tab
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
  color: #20334e;
  background: #eef3f9;
}
.workspace-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 8px 6px 14px;
}
.workspace-header h2 { margin: 0; font-size: 22px; font-weight: 650; color: #20334e; }
.workspace-tabs { flex: 0 0 auto; }
.workspace-tabs :deep(.el-tabs__header) { margin: 0 0 12px; }
.workspace-tabs :deep(.el-tabs__nav-wrap::after) { background-color: #dbe4ef; height: 1px; }
.workspace-tabs :deep(.el-tabs__item) { height: 42px; color: #52657e; font-size: 14px; }
.workspace-tabs :deep(.el-tabs__item.is-active) { color: #174ca2; font-weight: 600; }
.workspace-tabs :deep(.el-tabs__active-bar) { height: 3px; background: #2563c9; border-radius: 3px; }
.workspace-tabs :deep(.el-tabs__content) { display: none; }
.workspace-management-tools { flex: 0 0 auto; margin-bottom: 12px; padding: 10px 14px; border: 1px solid #dbe4ef; border-radius: 8px; background: #e6eef9; }
.workspace-management-tools > summary { cursor: pointer; color: #52657e; font-size: 13px; }
.workspace-management-tools[open] > summary { margin-bottom: 8px; }
.workspace-management-tabs :deep(.el-tabs__header) { margin-bottom: 0; }
.workspace-management-tabs :deep(.el-tabs__item) { height: 36px; font-size: 13px; }
.workspace-body {
  min-height: 0;
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #eef3f9;
  border: 1px solid #dbe4ef;
  border-radius: 12px;
}
.standalone-link { color: #52657e; font-size: 12px; white-space: nowrap; text-decoration: none; }
.standalone-link:hover { color: #174ca2; text-decoration: underline; }
.standalone-link:focus-visible { outline: 2px solid #2563c9; outline-offset: 4px; }
.workbench-stack,
.workbench-frame-shell { min-height: 0; flex: 1 1 auto; }
.workbench-frame-shell { height: 100%; }
.workbench-frame { display: block; width: 100%; height: 100%; border: 0; background: #eef3f9; }
.workbench-status { height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; color: #667a94; }
.workbench-status .el-icon { font-size: 28px; color: #2563c9; }
.workbench-status strong { color: #20334e; }
.workbench-status span { font-size: 12px; }
.native-release-pane { overflow: auto; }
.native-release-pane > :deep(.feature-release) { padding: 18px; background: #eef3f9; color: #20334e; }
.native-release-pane :deep(.el-card) { border-color: #dbe4ef; border-radius: 9px; box-shadow: none; }
.native-release-pane :deep(.el-card__header) { background: #e8f0fd; color: #20334e; }
.native-release-pane :deep(.el-button) { min-height: 36px; border-radius: 7px; }
.native-release-pane :deep(.el-input__wrapper),
.native-release-pane :deep(.el-select__wrapper) { min-height: 38px; border-radius: 7px; }
.native-release-pane :deep(.el-table th.el-table__cell) { background: #edf3fb; color: #52657e; }
@media (max-width: 900px) {
  .release-workspace { min-height: 420px; }
  .workspace-header { flex-wrap: wrap; padding-inline: 2px; }
  .workspace-header h2 { font-size: 20px; }
}
</style>
