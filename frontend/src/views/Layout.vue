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
          :default-active="$route.path"
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
            <el-menu-item index="/series">
              <span>产品系列</span>
            </el-menu-item>
            <el-menu-item index="/models">
              <span>产品型号</span>
            </el-menu-item>
            <el-menu-item index="/probe-models">
              <span>探头管理</span>
            </el-menu-item>
            <el-menu-item index="/applications">
              <span>应用管理</span>
            </el-menu-item>
            <el-menu-item index="/template-features">
              <span>模板管理</span>
            </el-menu-item>
            <el-menu-item index="/feature-manage">
              <span>功能管理</span>
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
      <el-main>
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
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Document, DataAnalysis, Setting, Collection, Promotion, Fold, Expand } from '@element-plus/icons-vue'

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

.el-main {
  padding: 12px;
  min-width: 0;
  background-color: #f0f2f5;
}
</style>
