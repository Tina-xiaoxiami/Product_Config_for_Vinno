<template>
  <div class="knowledge-evidence" data-testid="knowledge-evidence-answer" aria-live="polite">
    <div v-if="state.available === false" class="evidence-connection"><span>{{ state.unavailableReason }}</span><el-button size="small" link :loading="state.checking" @click="controller.checkAvailability()">重试连接</el-button></div>
    <el-alert v-if="state.error" :title="state.error" type="error" :closable="false"><span v-if="state.result">本次未更新，以下保留上次相同问题与范围的草稿。</span></el-alert>
    <p v-if="state.loading" class="evidence-note">正在检索原文并核验引用，结果不会自动发布。<el-button size="small" link @click="controller.invalidate()">取消等待</el-button></p>
    <article v-if="state.result" class="evidence-result" :class="state.result.status">
      <header class="evidence-result-heading"><el-tag :type="state.result.status === 'draft' ? 'info' : 'warning'" size="small">{{ evidenceStatusLabel(state.result.status) }}</el-tag><span>{{ knowledgeScopeLabel(state.result.scope || state.resultInput?.scope) }}</span><span v-if="state.result.metrics?.model_calls != null">模型调用 {{ state.result.metrics.model_calls }} 次</span></header>
      <p v-if="state.result.message" class="evidence-message">{{ state.result.message }}</p>
      <p v-if="state.result.claims.length" class="evidence-note">以下为有原文依据的资料草稿，需人工确认；配置、注册与参数结论以对应确定性查询为准。</p>
      <section v-for="(claim,index) in state.result.claims" :key="index" class="evidence-claim">
        <p class="evidence-claim-text">{{ claim.text }}</p>
        <div class="evidence-citations"><details v-for="(citation,citeIndex) in claim.citations" :key="`${citation.document_id}-${citation.page}-${citeIndex}`"><summary><span>[{{ index + 1 }}.{{ citeIndex + 1 }}] {{ citation.title }}<span v-if="citation.page"> · PDF第{{ citation.page }}页</span></span></summary><blockquote>{{ citation.quote }}</blockquote><el-button v-if="evidenceCitationUrl(citation)" size="small" link type="primary" @click="citationViewer?.open(citation)">定位并核验原文</el-button><small>{{ citationVisualLabel(citation) }}</small></details></div>
      </section>
      <p v-if="state.result.coverage" class="evidence-note">本次读取 {{ state.result.coverage.document_count ?? 0 }} 份资料<span v-if="state.result.coverage.page_count != null">、{{ state.result.coverage.page_count }} 页</span>；范围以本次已登记可用资料为限。</p>
      <div v-if="state.result.gaps?.length" class="evidence-gaps"><strong>缺口与边界</strong><ul><li v-for="(gap,index) in state.result.gaps" :key="index">{{ gap }}</li></ul></div>
    </article>
    <KnowledgeCitationViewer ref="citationViewer" />
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { getKnowledgeEvidenceCapabilities, generateKnowledgeEvidenceAnswer } from '../api/knowledgeEvidence'
import { createEvidenceAnswerController, evidenceCitationUrl, evidenceStatusLabel } from '../utils/knowledgeEvidence'
import KnowledgeCitationViewer from './KnowledgeCitationViewer.vue'
import { citationVisualLabel } from '../utils/knowledgeCitation'
import { knowledgeScopeLabel } from '../utils/knowledgeQueryScope'

const props = defineProps({ question: { type: String, default: '' }, scope: { type: Object, default: null } })
const state = reactive({})
const citationViewer = ref(null)
const controller = createEvidenceAnswerController({ state, getInput: () => ({ question: props.question, scope: props.scope }), request: generateKnowledgeEvidenceAnswer, capabilities: getKnowledgeEvidenceCapabilities })
watch(() => JSON.stringify([props.question, props.scope]), () => { controller.invalidate(); citationViewer.value?.close() }, { flush: 'sync' })
watch(() => state.result, () => citationViewer.value?.close(), { flush: 'sync' })
onMounted(() => controller.checkAvailability())
onBeforeUnmount(() => controller.dispose())
defineExpose({ run: () => controller.run(), state })
</script>

<style scoped>
.knowledge-evidence { display: grid; gap: 8px; min-width: 0; }
.knowledge-evidence:empty { display: none; }
.evidence-connection, .evidence-result-heading { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; color: var(--el-text-color-secondary); font-size: 12px; }
.evidence-connection { margin: 6px 0 12px; }
.evidence-result { margin-bottom: 12px; border: 1px solid var(--el-border-color-light); border-radius: 6px; padding: 12px; background: var(--el-bg-color); }
.evidence-note { margin: 7px 0; color: var(--el-text-color-secondary); font-size: 12px; }
.evidence-message, .evidence-claim-text { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.65; margin: 10px 0 7px; }
.evidence-citations { display: flex; flex-wrap: wrap; gap: 6px 12px; }
.evidence-citations details { max-width: 100%; font-size: 12px; }
.evidence-citations summary { cursor: pointer; color: var(--el-color-primary); overflow-wrap: anywhere; }
.evidence-citations blockquote { margin: 7px 0; padding: 5px 10px; border-left: 2px solid var(--el-border-color); white-space: pre-wrap; overflow-wrap: anywhere; color: var(--el-text-color-secondary); }
.evidence-citations a { color: var(--el-color-primary); }
.evidence-gaps { border-top: 1px solid var(--el-border-color-lighter); margin-top: 10px; padding-top: 8px; font-size: 12px; color: var(--el-text-color-secondary); }
.evidence-gaps ul { margin: 5px 0; padding-left: 20px; }
</style>
