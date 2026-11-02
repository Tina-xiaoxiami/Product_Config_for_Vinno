<template>
  <header class="workspace-page-header">
    <div class="workspace-page-heading">
      <div class="workspace-page-identity">
        <span v-if="workspace.tabs.length" class="workspace-section-label">{{ workspace.groupTitle }}</span>
        <h1>{{ workspace.title }}</h1>
      </div>
      <p>{{ workspace.description }}</p>
    </div>
    <nav v-if="workspace.tabs.length" :aria-label="workspace.groupTitle + '模块导航'" class="workspace-module-navigation">
      <el-tabs :model-value="workspace.activeTab" :before-leave="beforeLeave">
        <el-tab-pane v-for="tab in workspace.tabs" :key="tab.path" :name="tab.path" :label="tab.label" />
      </el-tabs>
    </nav>
  </header>
</template>

<script setup>
defineProps({ workspace: { type: Object, required: true }, beforeLeave: { type: Function, required: true } })
</script>

<style scoped>
.workspace-page-header{flex:0 0 auto;min-width:0;padding:12px 16px 0;border:1px solid var(--workspace-border);border-radius:10px;background:var(--workspace-surface);color:var(--workspace-text)}
.workspace-page-heading{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:6px 20px;padding-bottom:10px}
.workspace-page-identity{display:flex;align-items:center;gap:10px;min-width:0}
.workspace-section-label{font-size:12px;color:var(--workspace-muted);border-right:1px solid var(--workspace-border);padding-right:10px;white-space:nowrap}
h1{margin:0;font-size:19px;line-height:28px;font-weight:650;letter-spacing:.2px}
p{margin:0;color:var(--workspace-muted);font-size:12px;line-height:1.6;max-width:680px}
.workspace-module-navigation :deep(.el-tabs__header){margin:0}
.workspace-module-navigation :deep(.el-tabs__nav-wrap::after){height:1px;background:var(--workspace-border)}
.workspace-module-navigation :deep(.el-tabs__item){height:36px;font-size:13px;color:var(--workspace-muted)}
.workspace-module-navigation :deep(.el-tabs__item.is-active){color:var(--workspace-primary);font-weight:600}
.workspace-module-navigation :deep(.el-tabs__active-bar){height:3px;border-radius:3px;background:var(--workspace-primary)}
.workspace-module-navigation :deep(.el-tabs__content){display:none}
@media(max-width:900px){.workspace-page-header{padding-inline:12px}.workspace-page-heading{gap:4px}.workspace-page-heading p{flex:1 0 100%}h1{font-size:18px}}
</style>
