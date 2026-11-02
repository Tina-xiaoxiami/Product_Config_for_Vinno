<template>
  <section v-if="trace" class="history-trace" data-testid="knowledge-history-trace">
    <div class="trace-heading"><strong>{{ historyAssessmentLabel(trace.assessment) }}</strong><small>资料证据 · 尚未发布为正式答案</small></div>
    <p>{{ trace.conclusion }}</p>
    <p class="coverage">已按原文和登记关系检索 {{ trace.coverage?.document_count || 0 }} 份资料；版本：{{ trace.coverage?.versions?.join('、') || '暂无' }}</p>
    <p v-for="gap in trace.coverage?.gaps || []" :key="String(gap)" class="warning">{{ text(gap) }}</p>
    <section v-if="Array.isArray(trace.confirmation_items)" class="trace-confirmations" data-testid="history-confirmation-items">
      <strong>需要补充确认的信息：{{ trace.confirmation_items.length }}项</strong>
      <p v-if="!trace.confirmation_items.length">本次没有需要你重复确认的资料事实。</p>
      <article v-for="(item,index) in trace.confirmation_items" :key="`${item.field}-${index}`">
        <strong>{{ confirmationQuestion(item) }}</strong><p>{{ item.reason }}</p>
        <p v-if="item.options?.length">可选信息：{{ item.options.join('、') }}</p>
        <details v-if="item.evidence_refs?.length"><summary>查看与本问题有关的原文</summary><div v-for="(evidence,i) in item.evidence_refs" :key="i"><pre>{{ evidence.excerpt }}</pre><a v-if="evidence.preview_url" :href="evidence.preview_url" target="_blank" rel="noopener noreferrer">{{ evidence.source_ref || '查看原文' }}</a></div></details>
      </article>
    </section>
    <section v-if="sourceDocuments.length" class="trace-source-facts" data-testid="history-source-facts">
      <strong>原文已明确的信息</strong>
      <article v-for="document in sourceDocuments" :key="document.id" class="source-fact-card">
        <div><a :href="document.preview_url" target="_blank" rel="noopener noreferrer">{{ document.title }} · {{ document.version }}</a> <small>{{ document.status }}</small></div>
        <p>适用型号：{{ document.models }}</p>
        <p v-for="(fact,index) in document.fields" :key="index"><strong>{{ fact.label }}：</strong>{{ fact.value }}</p>
        <small>来源国家：{{ document.country }}；来源市场：{{ document.market }}。原文未声明的字段保留为空，不阻止软件变化原文检索。</small>
        <details><summary>查看逐字段原文依据</summary><div v-for="(fact,index) in document.fields" :key="index"><strong>{{ fact.label }} · {{ fact.source_ref }}</strong><pre>{{ fact.excerpt }}</pre><a :href="fact.preview_url || document.preview_url" target="_blank" rel="noopener noreferrer">查看原件</a></div></details>
      </article>
    </section>
    <article v-for="chain in trace.chains || []" :key="`${chain.country || ''}:${chain.release_line}`" class="trace-chain">
      <strong>版本链：{{ chain.release_line }}<span v-if="chain.country"> · 来源国家 {{ chain.country }}</span></strong>
      <p v-if="chain.conditions?.length" class="warning">{{ Array.isArray(chain.conditions) ? chain.conditions.join('；') : chain.conditions }}</p>
      <div v-for="(condition,index) in chain.detected_conditions || []" :key="`condition-${index}`" class="warning"><strong>资料中的平台/升级限制</strong><pre>{{ condition.excerpt }}</pre><a :href="condition.preview_url" target="_blank" rel="noopener noreferrer">查看限制原文 · {{ condition.source_ref }}</a></div>
      <div v-for="event in chain.events || []" :key="`${event.document_id}-${event.source_ref}-${event.excerpt}`" class="trace-event">
        <span>{{ event.event_version || '所属事件版本待核实' }} · {{ changeLabel(event.change_type) }} · {{ event.document_title }}</span>
        <pre>{{ event.excerpt }}</pre>
        <a :href="event.preview_url" target="_blank" rel="noopener noreferrer">查看原文 · {{ event.source_ref || '资料位置' }}</a>
      </div>
      <small v-if="!chain.events?.length">该版本链中未检索到本次主题的明确记录。</small>
    </article>
    <details v-if="trace.coverage?.unresolved_documents?.length" open class="trace-unresolved">
      <summary>相关资料，未确认适用范围（{{ trace.coverage.unresolved_documents.length }}）</summary>
      <article v-for="doc in trace.coverage.unresolved_documents" :key="doc.document_id">
        <a :href="doc.preview_url" target="_blank" rel="noopener noreferrer">{{ doc.title }} · {{ doc.version }}<span v-if="doc.country"> · 来源国家 {{ doc.country }}</span></a>
        <p class="warning">{{ doc.reasons?.join('；') }}</p>
        <div v-for="(condition,index) in doc.detected_conditions || []" :key="`condition-${index}`" class="warning"><strong>资料中的平台/升级限制</strong><pre>{{ condition.excerpt }}</pre><a :href="condition.preview_url" target="_blank" rel="noopener noreferrer">查看限制原文 · {{ condition.source_ref }}</a></div>
        <pre v-for="(event,index) in doc.candidate_events || []" :key="index">{{ event.excerpt }}</pre>
        <small v-if="!doc.candidate_events?.length">没有可展示的相关原文命中；资料范围或可检索状态仍需核对。</small>
      </article>
    </details>
    <details v-if="trace.coverage?.excluded_documents?.length"><summary>排除的资料与原因（{{ trace.coverage.excluded_documents.length }}）</summary><p v-for="(doc,index) in trace.coverage.excluded_documents" :key="index">{{ doc.title || doc.document_title || doc.document_id }}：{{ doc.reasons?.join('；') || doc.reason }}</p></details>
  </section>
</template>
<script setup>
import { computed } from 'vue'
import { sourceApplicabilityDisplay, confirmationQuestion } from '../utils/knowledgeSourceApplicability'
import { historyAssessmentLabel } from '../utils/knowledgeReleaseHistory'
const props = defineProps({ trace: { type: Object, default: null } })
const sourceDocuments = computed(() => (props.trace?.source_documents || []).map(sourceApplicabilityDisplay))
const changeLabel = value => ({ added: '新增记录', optimized: '优化记录', removed: '移除记录', changed: '变化记录', fixed: '修复记录', narrative: '相关描述' }[value] || value || '相关描述')
const text = value => typeof value === 'string' ? value : value.reason || value.message || '资料覆盖待核实'
</script>
<style scoped>
.history-trace { margin-top: 12px; padding: 12px; background: var(--el-fill-color-light); border: 1px solid var(--el-border-color); border-radius: 6px; }
.trace-heading { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }.coverage, small { color: var(--el-text-color-secondary); }.warning { color: var(--el-color-warning-dark-2); }
.source-fact-card, .trace-confirmations article, .trace-chain, .trace-unresolved article { padding: 10px 0; border-top: 1px solid var(--el-border-color-lighter); }.trace-event { margin: 8px 0; }pre { white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; max-height: 280px; overflow: auto; }summary { cursor: pointer; padding: 6px 0; }a { color: var(--el-color-primary); }
</style>
