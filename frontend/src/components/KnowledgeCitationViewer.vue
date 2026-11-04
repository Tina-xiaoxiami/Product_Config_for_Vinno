<template>
  <el-dialog :model-value="state.visible" title="原文定位与核验" width="min(1000px, 94vw)" append-to-body @update:model-value="value => { if (!value) controller.close() }">
    <p v-if="state.loading" role="status">正在核对原件版本和引用位置…</p>
    <el-alert v-if="state.error" :title="state.error" type="error" :closable="false" />
    <article v-if="state.result" class="citation-viewer" data-testid="verified-citation">
      <header><strong>{{ state.result.title }}</strong><span>{{ state.result.source_ref }}</span><el-tag size="small" type="success">原件与提取摘要一致</el-tag><el-tag size="small" type="info">{{ state.result.verification.quote === 'matched' ? '引文已匹配' : '定位到资料片段' }}</el-tag></header>
      <p class="citation-version">版本摘要 {{ state.result.version_id }} · 程序核验不代表人工确认</p>
      <p v-if="state.result.quote" class="citation-quote">引用：{{ state.result.quote }}</p>
      <div class="citation-context"><template v-for="(part,index) in citationTextParts(state.result.text,state.result.quote)" :key="index"><mark v-if="part.highlight">{{ part.text }}</mark><template v-else>{{ part.text }}</template></template></div>
      <div class="citation-actions"><a :href="state.result.preview_url" target="_blank" rel="noopener noreferrer">打开核验版本原件<span v-if="state.result.page"> · PDF第{{ state.result.page }}页</span></a><el-button v-if="state.result.page" size="small" @click="showOriginal = !showOriginal">{{ showOriginal ? '收起原页' : '查看原页' }}</el-button></div>
      <iframe v-if="showOriginal && state.result.page" :src="state.result.preview_url" title="引用的PDF原页" class="citation-original" />
    </article>
    <template #footer><el-button size="small" @click="controller.close()">关闭</el-button></template>
  </el-dialog>
</template>
<script setup>
import { reactive, ref, onBeforeUnmount } from 'vue'
import { getKnowledgeCitation } from '../api/knowledgeEvidence'
import { createCitationController, citationTextParts } from '../utils/knowledgeCitation'
const state = reactive({}), showOriginal = ref(false)
const controller = createCitationController({ state, request: getKnowledgeCitation })
onBeforeUnmount(() => controller.dispose())
defineExpose({ open(citation) { showOriginal.value = false; return controller.open(citation) }, close: controller.close })
</script>
<style scoped>
.citation-viewer { display:grid; gap:10px; min-width:0; }
.citation-viewer header,.citation-actions { display:flex;flex-wrap:wrap;align-items:center;gap:8px; }
.citation-version { margin:0;font-size:12px;color:var(--el-text-color-secondary);overflow-wrap:anywhere; }
.citation-quote { margin:0;border-left:2px solid var(--el-color-primary);padding-left:10px;white-space:pre-wrap; }
.citation-context { white-space:pre-wrap;overflow-wrap:anywhere;max-height:38vh;overflow:auto;border:1px solid var(--el-border-color-light);padding:12px;line-height:1.7; }
.citation-context mark { background:#fff2ad;color:inherit; }
.citation-actions a { color:var(--el-color-primary); }
.citation-original { width:100%;height:50vh;border:1px solid var(--el-border-color-light); }
</style>
