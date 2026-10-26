<template>
  <div class="release-workspace">
    <header class="workspace-header">
      <div>
        <h2>功能发布</h2>
        <p>在一个入口中查资料、做文件同步、查版本并管理已确认的功能版本记录。</p>
      </div>
    </header>

    <el-tabs v-model="activeTab" class="workspace-tabs">
      <el-tab-pane label="发布资料检索" name="search" />
      <el-tab-pane label="文件同步" name="review" />
      <el-tab-pane label="发布版本" name="releases" />
      <el-tab-pane label="发布对比" name="compare" />
      <el-tab-pane label="功能版本管理" name="feature-versions" />
    </el-tabs>

    <section v-show="isWorkbenchTab(activeTab)" class="workspace-body">
      <div class="workspace-guide">
        <div>
          <strong>{{ activeTabInfo.title }}</strong>
          <span>{{ activeTabInfo.description }}</span>
        </div>
        <a
          :href="releaseWorkbenchStandaloneUrl(activeTab)"
          class="standalone-link"
          target="_blank"
          rel="noopener noreferrer"
        >在新窗口打开</a>
      </div>

      <div class="workbench-stack">
        <div
          v-for="tab in mountedWorkbenchTabs"
          :key="tab"
          v-show="activeTab === tab"
          class="workbench-frame-shell"
        >
          <div v-if="workbenchState[tab].status === 'checking'" class="workbench-status">
            <el-icon class="is-loading"><Loading /></el-icon>
            <strong>正在连接发布工作台…</strong>
            <span>工作台由当前产品配置服务同进程提供。</span>
          </div>

          <el-result
            v-else-if="workbenchState[tab].status === 'error'"
            icon="warning"
            title="发布工作台暂时无法加载"
            :sub-title="workbenchState[tab].message"
          >
            <template #extra>
              <el-button
                type="primary"
                data-testid="release-workbench-retry"
                @click="checkWorkbenchAvailability(tab, true)"
              >重试</el-button>
              <el-button
                tag="a"
                :href="releaseWorkbenchStandaloneUrl(tab)"
                target="_blank"
                rel="noopener noreferrer"
                data-testid="release-workbench-standalone"
              >在新窗口打开</el-button>
            </template>
          </el-result>

          <iframe
            v-else-if="workbenchState[tab].status === 'ready'"
            :key="workbenchState[tab].frameKey"
            ref="workbenchFrames"
            class="workbench-frame"
            :data-view="tab"
            :src="releaseWorkbenchUrl(tab)"
            :title="`${tabInfo[tab].title}工作台`"
            @load="markWorkbenchLoaded(tab, $event)"
            @error="markWorkbenchError(tab)"
          />
        </div>
      </div>
    </section>

    <section
      v-if="nativeReleaseMounted"
      v-show="activeTab === 'feature-versions'"
      class="workspace-body native-release-pane"
    >
      <div class="workspace-guide">
        <div>
          <strong>功能版本与首发记录</strong>
          <span>这里保留已有的功能版本、候选复核、发布介绍与模板管理。</span>
        </div>
      </div>
      <FeatureRelease />
    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
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

const tabInfo = {
  search: {
    title: '发布资料检索',
    description: '按产品、版本或关键词定位 Release Note、白皮书等发布来源。'
  },
  review: {
    title: '文件同步与扫描',
    description: '管理发布资料目录并扫描变化，确认后再进入发布数据。'
  },
  releases: {
    title: '发布版本',
    description: '查看已组织的发布版本和其资料覆盖情况。'
  },
  compare: {
    title: '发布对比',
    description: '对比不同发布版本的资料与功能变化。'
  }
}

const activeTab = ref(normalizeReleaseTab(route.query.tab))
const visitedWorkbenchTabs = ref([])
const nativeReleaseMounted = ref(activeTab.value === 'feature-versions')
const workbenchFrames = ref([])
const workbenchState = reactive(Object.fromEntries(
  RELEASE_WORKBENCH_VIEWS.map(tab => [tab, {
    status: 'idle',
    message: '',
    frameKey: 0
  }])
))

const isWorkbenchTab = tab => RELEASE_WORKBENCH_VIEWS.includes(tab)
const activeTabInfo = computed(() => tabInfo[activeTab.value] || tabInfo.search)
const mountedWorkbenchTabs = computed(() => RELEASE_WORKBENCH_VIEWS.filter(
  tab => visitedWorkbenchTabs.value.includes(tab)
))

async function checkWorkbenchAvailability(tab, force = false) {
  if (!isWorkbenchTab(tab)) return
  const state = workbenchState[tab]
  if (!force && (state.status === 'checking' || state.status === 'ready')) return

  state.status = 'checking'
  state.message = ''
  try {
    const response = await fetch(releaseWorkbenchHealthUrl(), {
      cache: 'no-store',
      headers: { Accept: 'application/json' }
    })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    state.frameKey += 1
    state.status = 'ready'
  } catch (error) {
    state.status = 'error'
    state.message = `请确认产品配置后端已启动，然后重试（${error.message || '连接失败'}）。`
  }
}

function mountWorkbenchTab(tab) {
  if (!isWorkbenchTab(tab)) return
  if (!visitedWorkbenchTabs.value.includes(tab)) {
    visitedWorkbenchTabs.value = [...visitedWorkbenchTabs.value, tab]
  }
  checkWorkbenchAvailability(tab)
}

function markWorkbenchLoaded(tab, event) {
  event.currentTarget?.contentWindow?.postMessage({
    type: 'release-workspace:activate',
    view: tab
  }, window.location.origin)
}

function markWorkbenchError(tab) {
  workbenchState[tab].status = 'error'
  workbenchState[tab].message = '嵌入页面加载失败，请重试或在新窗口打开。'
}

function handleWorkbenchMessage(event) {
  if (!isWorkbenchNavigationMessage(event, window.location.origin)) return
  if (!workbenchFrames.value.some(frame => frame?.contentWindow === event.source)) return
  activeTab.value = event.data.view
}

watch(() => route.query.tab, value => {
  const tab = normalizeReleaseTab(value)
  if (tab !== activeTab.value) activeTab.value = tab
})

watch(activeTab, tab => {
  mountWorkbenchTab(tab)
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
  min-height: 620px;
  display: flex;
  flex-direction: column;
  color: #1f2937;
}

.workspace-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 4px 4px 10px;
}

.workspace-header h2 { margin: 0 0 6px; font-size: 22px; }
.workspace-header p { margin: 0; color: #64748b; font-size: 13px; }
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

.workspace-guide {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 14px;
  border-bottom: 1px solid #e5e7eb;
  background: #f8fafc;
}

.workspace-guide div { display: flex; align-items: baseline; gap: 12px; min-width: 0; }
.workspace-guide strong { white-space: nowrap; font-size: 14px; }
.workspace-guide span { color: #64748b; font-size: 12px; }
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
  .release-workspace { min-height: 560px; }
  .workspace-guide div { align-items: flex-start; flex-direction: column; gap: 4px; }
  .workspace-header { flex-direction: column; }
}
</style>
