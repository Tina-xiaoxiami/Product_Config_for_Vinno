<template>
  <div class="layout">
    <el-container>
      <el-aside :width="sidebarCollapsed ? '64px' : '180px'" :class="{ collapsed: sidebarCollapsed }">
        <div class="logo">
          <span v-if="!sidebarCollapsed">产品配置管理</span>
          <el-button text class="sidebar-toggle" :aria-label="sidebarCollapsed ? '展开导航' : '收起导航'" :title="sidebarCollapsed ? '展开导航' : '收起导航'" @click="toggleSidebar">
            <el-icon><Expand v-if="sidebarCollapsed" /><Fold v-else /></el-icon>
          </el-button>
        </div>
        <el-menu
          :default-active="probeManagementMenuPath($route.path)"
          :collapse="sidebarCollapsed"
          :collapse-transition="false"
          router
          background-color="#304156"
          text-color="#bfcbd9"
          active-text-color="#409EFF"
        >
          <el-menu-item index="/knowledge">
            <el-icon><Collection /></el-icon>
            <template #title>产品知识库</template>
          </el-menu-item>
          <el-menu-item index="/release">
            <el-icon><Promotion /></el-icon>
            <template #title>功能发布</template>
          </el-menu-item>
          <el-sub-menu index="/manage">
            <template #title>
              <el-icon><Setting /></el-icon>
              <span>基础数据管理</span>
            </template>
            <el-menu-item index="/models">
              <span>产品型号</span>
            </el-menu-item>
            <el-menu-item index="/template-features">
              <span>探头&amp;应用管理</span>
            </el-menu-item>
            <el-menu-item index="/registration-manage">
              <span>注册管理</span>
            </el-menu-item>
          </el-sub-menu>
          <el-sub-menu index="/product-config">
            <template #title>
              <el-icon><Document /></el-icon>
              <span>机型配置</span>
            </template>
            <el-menu-item index="/config">
              <span>配置管理</span>
            </el-menu-item>
            <el-menu-item index="/compare">
              <span>配置对比</span>
            </el-menu-item>
            <el-menu-item index="/version-compare">
              <span>版本对比</span>
            </el-menu-item>
            <el-menu-item index="/versions">
              <span>版本历史</span>
            </el-menu-item>
          </el-sub-menu>
          <el-sub-menu index="/probe">
            <template #title>
              <el-icon><DataAnalysis /></el-icon>
              <span>探头配置</span>
            </template>
            <el-menu-item index="/probe-config">
              <span>探头配置管理</span>
            </el-menu-item>
            <el-menu-item index="/probe-versions">
              <span>版本历史</span>
            </el-menu-item>
          </el-sub-menu>
        </el-menu>
      </el-aside>
      <el-main :class="{ 'management-workspace': isProbeManagementPage }">
        <nav v-show="isProbeManagementPage" class="probe-management-navigation" aria-label="探头与应用管理">
          <el-tabs :model-value="$route.path" :before-leave="switchProbeManagementTab" class="probe-management-tabs">
            <el-tab-pane v-for="tab in PROBE_MANAGEMENT_TABS" :key="tab.path" :name="tab.path" :label="tab.label" />
          </el-tabs>
          <div id="probe-management-actions" class="probe-management-actions" />
        </nav>
        <router-view v-slot="{ Component }">
          <keep-alive>
            <component :is="Component" />
          </keep-alive>
        </router-view>
      </el-main>
    </el-container>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { PROBE_MANAGEMENT_TABS, probeManagementMenuPath } from '../utils/probeManagementNavigation'
import { ElMessage } from 'element-plus'
import { Document, DataAnalysis, Setting, Collection, Promotion, Fold, Expand } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const isProbeManagementPage = computed(() => PROBE_MANAGEMENT_TABS.some(tab => tab.path === route.path))
const switchProbeManagementTab = async (path) => {
  if (path === route.path) return true
  try {
    const failure = await router.push(path)
    return !failure
  } catch {
    ElMessage.error('切换页面失败，请重试')
    return false
  }
}

const sidebarCollapsed = ref(false)
try { sidebarCollapsed.value = localStorage.getItem('config_sidebar_collapsed') === 'true' } catch (error) { console.warn('读取导航设置失败', error) }
const toggleSidebar = () => {
  sidebarCollapsed.value = !sidebarCollapsed.value
  try { localStorage.setItem('config_sidebar_collapsed', String(sidebarCollapsed.value)) } catch { ElMessage.warning('导航已切换，但浏览器未能保存设置') }
}
</script>

<style scoped>
.layout {
  height: 100vh;
}

.el-container {
  height: 100%;
}

.el-aside {
  background-color: #304156;
  color: #fff;
  flex-shrink: 0;
  overflow-x: hidden;
  transition: width 0.15s ease;
}

.logo {
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 10px;
  font-size: 15px;
  font-weight: bold;
  white-space: nowrap;
  background-color: #263445;
}
.collapsed .logo { justify-content: center; padding: 0; }
.sidebar-toggle { color: #dce5ef; padding: 8px; }
.sidebar-toggle:hover { color: #fff; background-color: #40546c; }
.el-menu { --el-menu-item-height: 44px; --el-menu-sub-item-height: 38px; }

.el-menu {
  border-right: none;
}

.probe-management-navigation { display: flex; align-items: center; flex-wrap: wrap; gap: 0 12px; flex-shrink: 0; background: #fff; border: 1px solid #e4e7ed; border-radius: 4px; padding: 0 12px; margin-bottom: 6px; }
.probe-management-tabs { flex: 1 1 330px; min-width: 0; }
.probe-management-actions { display: flex; margin-left: auto; padding: 4px 0; }
.probe-management-actions:empty { display: none; }
.probe-management-tabs :deep(.el-tabs__header) { margin: 0; }
.probe-management-tabs :deep(.el-tabs__nav-wrap::after) { display: none; }
.probe-management-tabs :deep(.el-tabs__item) { height: 36px; font-size: 13px; }
.probe-management-tabs :deep(.el-tabs__item.is-active) { font-weight: 600; }
.probe-management-tabs :deep(.el-tabs__content) { display: none; }

.el-main.management-workspace { display: flex; flex-direction: column; }

.el-main {
  padding: 12px;
  min-width: 0;
  background-color: #f0f2f5;
}
</style>
