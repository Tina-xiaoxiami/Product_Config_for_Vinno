<template>
  <div class="frozen-evidence">
    <el-descriptions :column="1" border size="small"><el-descriptions-item label="核对状态">{{ statusLabel(enrichment?.status) }}</el-descriptions-item><el-descriptions-item label="候选修订">{{ enrichment?.candidate?.revision ?? '(无)' }}</el-descriptions-item></el-descriptions>
    <section v-for="section in sections" :key="section.label"><h4>{{ section.label }}</h4><Payload :payload="section.payload" :document="document" /></section>
    <details v-if="enrichment?.candidate_history?.length"><summary>冻结候选资料历史（{{ enrichment.candidate_history.length }} 次修订）</summary><section v-for="candidate in enrichment.candidate_history" :key="candidate.id"><h4>候选修订 {{ candidate.revision }} · {{ candidate.created_at }}</h4><Payload :payload="candidate.payload" :document="document" /></section></details>
    <h4>冻结审核历史（{{ enrichment?.history?.length || 0 }} 条）</h4>
    <section v-for="(record, index) in enrichment?.history || []" :key="record.id || index" class="history-card"><p>{{ actionLabel(record.action) }} · {{ record.actor || record.confirmed_by }} · {{ record.created_at || record.reviewed_at }}</p><p>{{ record.note || '(无说明)' }}</p><details v-if="record.confirmed_payload"><summary>查看当时确认内容</summary><Payload :payload="record.confirmed_payload" :document="document" /></details></section>
    <p v-if="!enrichment">当时尚无补充资料。</p>
  </div>
</template>
<script setup>
import { computed, h } from 'vue'
import { dictionaryLabel } from '../utils/measurementWorkspace'
import { safeSourceUrl, REVIEW_RELATIONS, reviewStatusLabel } from '../utils/measurementEnrichmentReview'
const props = defineProps({ enrichment: Object, document: Object })
const statusLabel = reviewStatusLabel
const actionLabel = value => ({ confirm: '确认', reject: '拒绝', defer: '暂缓', revoke: '撤销确认' })[value] || value
const sections = computed(() => [{ label: '已核对内容', payload: props.enrichment?.confirmed_payload }, { label: '候选资料', payload: props.enrichment?.candidate?.payload }].filter(section => section.payload))
function Payload({ payload, document }) {
  const value = payload || {}
  const line = (name, text) => h('p', [h('strong', `${name}：`), text || '(空白)'])
  const labels = (values, dimension) => (values || []).map(code => dictionaryLabel(document, dimension, code)).join('；')
  return h('div', { class: 'frozen-payload' }, [
    line('应用', labels(value.categories, 'applications')), line('相关输入模式', labels(value.modes, 'modes')), line('研究状态', statusLabel(value.research_status)),
    line('参考公式与依赖说明', value.formula_reference),
    h('strong', '术语与关联：'), h('ul', (value.input_terms || []).map(term => h('li', [
      line(term.term, REVIEW_RELATIONS.find(option => option.value === term.relation_kind)?.label || term.relation_kind),
      line('候选关联', (term.possible_dependencies || []).map(item => `${item.kind === 'calculation' ? '计算项' : '测量项'} ${item.item_id}`).join('；')),
      line('不确定性', term.uncertainty)
    ]))), h('strong', '公开来源：'), h('ul', (value.sources || []).map(source => h('li', [
      safeSourceUrl(source.url) ? h('a', { href: safeSourceUrl(source.url), target: '_blank', rel: 'noopener noreferrer' }, source.title || source.url) : source.title,
      line('发布机构 / 定位', [source.publisher, source.locator].filter(Boolean).join(' · ')),
      ...(source.supports || []).map(support => h('p', support))
    ]))), h('strong', '保留的不确定性：'), h('ul', (value.uncertainties || []).map(text => h('li', text)))
  ])
}
Payload.props = { payload: Object, document: Object }
</script>
<style scoped>
.frozen-evidence{font-size:12px;line-height:1.7;overflow-wrap:anywhere}.frozen-evidence h4{margin:12px 0 6px}.history-card{border-top:1px solid var(--el-border-color-lighter);padding:6px 0}.frozen-evidence :deep(p){white-space:pre-wrap;margin:5px 0}.frozen-evidence :deep(ul){padding-left:20px}
</style>
