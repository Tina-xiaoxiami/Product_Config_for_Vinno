<template>
  <div class="layout">
    <el-container>
      <el-aside width="200px">
        <div class="logo">产品配置管理</div>
        <el-menu
          :default-active="$route.path"
          router
          background-color="#304156"
          text-color="#bfcbd9"
          active-text-color="#409EFF"
        >
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
import { Document, DataAnalysis, Clock, Setting } from '@element-plus/icons-vue'
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
}

.logo {
  height: 60px;
  line-height: 60px;
  text-align: center;
  font-size: 18px;
  font-weight: bold;
  color: #fff;
  background-color: #263445;
}

.el-menu {
  border-right: none;
}

.el-main {
  padding: 20px;
  background-color: #f0f2f5;
}
</style>