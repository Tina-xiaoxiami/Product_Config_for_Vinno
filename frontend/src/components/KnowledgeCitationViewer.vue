<template>
  <el-dialog class="knowledge-citation-dialog" top="4vh" :model-value="state.visible" title="原文定位与核验" width="min(1000px, 94vw)" append-to-body @update:model-value="value => { if (!value) controller.close() }">
    <p v-if="state.loading" role="status">正在核对原件版本和引用位置…</p>
    <el-alert v-if="state.error" :title="state.error" type="error" :closable="false" />
    <article v-if="state.result" class="citation-viewer" data-testid="verified-citation">
      <header><strong>{{ state.result.title }}</strong><span>{{ state.result.source_ref }}</span><el-tag size="small" type="success">原件与提取摘要一致</el-tag><el-tag size="small" type="info">{{ state.result.verification.quote === 'matched' ? '引文已匹配' : '定位到资料片段' }}</el-tag></header>
      <p class="citation-version">原件版本（SHA-256文件指纹）{{ state.result.version_id }} · 程序核验不代表人工确认</p>
      <section v-if="structure" class="citation-structure" data-testid="office-location" aria-label="Office结构位置">
        <header><el-tag size="small" type="info">{{ structure.format }}</el-tag><strong>{{ structure.label }}</strong><small>{{ structure.detail }}</small></header>
        <p class="citation-boundary">结构已匹配 · 未进行原页视觉核验 · 未人工确认；不用于正式生产问答。</p>
        <dl v-if="structure.cells.length" class="citation-cells">
          <div v-for="cell in structure.cells" :key="cell.position"><dt>{{ cell.position }}</dt><dd>{{ cell.text }}<small v-if="cell.note">{{ cell.note }}</small></dd></div>
        </dl>
      </section>
      <details v-if="state.result.quote" :key="state.result.quote" class="citation-quote"><summary>查看引用原句（{{ state.result.quote.length }}字）</summary><p>{{ state.result.quote }}</p></details>
      <div class="citation-context"><template v-for="(part,index) in citationTextParts(state.result.text,state.result.quote)" :key="index"><mark v-if="part.highlight">{{ part.text }}</mark><template v-else>{{ part.text }}</template></template></div>
      <div class="citation-actions"><a :href="state.result.preview_url" target="_blank" rel="noopener noreferrer">{{ structure ? '打开或下载核验版本原件' : '打开核验版本原件' }}<span v-if="state.result.page"> · PDF第{{ state.result.page }}页</span></a><el-button v-if="state.result.page" size="small" @click="showOriginal = !showOriginal">{{ showOriginal ? '收起原页' : '查看原页' }}</el-button></div>
      <iframe v-if="showOriginal && state.result.page" :src="state.result.preview_url" title="引用的PDF原页" class="citation-original" />
    </article>
    <template #footer><el-button size="small" @click="controller.close()">关闭</el-button></template>
  </el-dialog>
</template>
<script setup>
import { computed, reactive, ref, onBeforeUnmount } from 'vue'
import { getKnowledgeCitation } from '../api/knowledgeEvidence'
import { createCitationController, citationStructure, citationTextParts } from '../utils/knowledgeCitation'
const state = reactive({}), showOriginal = ref(false)
const controller = createCitationController({ state, request: getKnowledgeCitation })
const structure = computed(() => citationStructure(state.result))
onBeforeUnmount(() => controller.dispose())
defineExpose({ open(citation) { showOriginal.value = false; return controller.open(citation) }, close: controller.close })
</script>
<style scoped>
:global(.knowledge-citation-dialog) { display:flex;flex-direction:column;max-height:92vh;margin-bottom:4vh; }
:global(.knowledge-citation-dialog .el-dialog__header), :global(.knowledge-citation-dialog .el-dialog__footer) { flex-shrink:0; }
:global(.knowledge-citation-dialog .el-dialog__body) { flex:1;min-height:0;overflow:auto;padding-top:8px;padding-bottom:12px; }
.citation-viewer { display:grid; gap:10px; min-width:0; }
.citation-viewer header,.citation-actions { display:flex;flex-wrap:wrap;align-items:center;gap:8px; }
.citation-version { margin:0;font-size:12px;color:var(--el-text-color-secondary);overflow-wrap:anywhere; }
.citation-structure { min-width:0;border:1px solid var(--el-border-color-light);border-radius:4px;padding:8px; }
.citation-structure small,.citation-boundary { color:var(--el-text-color-secondary);font-size:12px;overflow-wrap:anywhere; }
.citation-boundary { margin:6px 0; }
.citation-cells { margin:0;max-height:24vh;overflow:auto;font-size:12px; }
.citation-cells > div { display:flex;gap:8px;padding:4px 0;border-top:1px solid var(--el-border-color-lighter); }
.citation-cells dt { flex:0 0 100px;overflow-wrap:anywhere;font-weight:600; }
.citation-cells dd { min-width:0;margin:0;white-space:pre-wrap;overflow-wrap:anywhere; }
.citation-cells small { display:block;margin-top:2px; }
.citation-quote { margin:0;border-left:2px solid var(--el-color-primary);padding-left:10px;overflow-wrap:anywhere; }
.citation-quote summary { cursor:pointer;color:var(--el-color-primary);font-size:12px; }
.citation-quote p { margin:8px 0 0;white-space:pre-wrap;line-height:1.6; }
.citation-context { white-space:pre-wrap;overflow-wrap:anywhere;max-height:38vh;overflow:auto;border:1px solid var(--el-border-color-light);padding:12px;line-height:1.7; }
.citation-context mark { background:#fff2ad;color:inherit; }
.citation-actions a { color:var(--el-color-primary); }
.citation-original { width:100%;height:50vh;border:1px solid var(--el-border-color-light); }
</style>
