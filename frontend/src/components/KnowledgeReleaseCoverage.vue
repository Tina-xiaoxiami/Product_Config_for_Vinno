<template>
  <section v-if="loading || error || report" class="release-coverage" data-testid="release-coverage" :aria-busy="loading">
    <div class="coverage-heading"><strong>{{ loading ? '正在检查资料覆盖…' : coverageAssessment(report) }}</strong><small v-if="report">检查时间：{{ report.checked_at || '未返回' }}</small></div>
    <p v-if="scopeNotice">{{ scopeNotice }}</p>
    <div v-if="error" role="alert" class="coverage-error">{{ error }} <el-button size="small" link @click="$emit('retry')">重新检查</el-button></div>
    <template v-if="report">
      <p>{{ coverageBoundaryLabel(report.boundary) }}</p>
      <p v-if="report.message">{{ report.message }}</p>
      <div class="coverage-counts"><span>文件 {{ report.totals?.files || 0 }}</span><span>已登记 {{ report.totals?.registered || 0 }}</span><span>可检索 {{ report.totals?.ready || 0 }}</span><span>缺口 {{ report.totals?.gaps || 0 }}</span><span>候选待核查 {{ report.totals?.unresolved || 0 }}</span><span>晚于目标 {{ report.totals?.later || 0 }}</span></div>
      <details class="coverage-roots"><summary>本次检查的来源目录（{{ report.roots?.length || 0 }}）</summary><div v-for="(root,index) in report.roots || []" :key="`${root.path}-${index}`"><strong>{{ coverageRootLabel(root.label) }} · {{ coverageStatusLabel('root', root.status) }}</strong><pre>{{ root.path }}</pre><p v-if="root.error" class="coverage-error">{{ root.error }}</p></div><p v-if="!report.roots?.length">尚未配置可检查的来源目录。</p></details>
      <div class="coverage-controls"><el-checkbox v-model="onlyGaps" size="small">只看资料缺口</el-checkbox><el-input v-model="query" clearable size="small" placeholder="筛选文件名、版本或问题" aria-label="筛选资料覆盖条目" /><small>显示 {{ rows.length }} / {{ report.items?.length || 0 }} 条</small></div>
      <p class="coverage-note">未识别型号或版本的文件仅是候选问题，不据文件夹或语言断定适用型号、国家。晚于目标或明确不适用的资料可取消“只看资料缺口”查看，不计作当前确定缺项。</p>
      <div class="coverage-items">
        <details v-for="(item,index) in rows" :key="item.key || index" class="coverage-item">
          <summary><strong>{{ item.file_name || '未命名资料' }}</strong><span>{{ item.version || '版本未识别' }} · {{ coverageStatusLabel('language', item.language) }}</span><span>{{ coverageStatusLabel('registration', item.registration_status) }} · {{ coverageStatusLabel('extraction', item.extraction_status) }}</span></summary>
          <p>版本：{{ item.version || '未识别' }}（{{ coverageStatusLabel('version', item.version_basis) }}）；{{ coverageStatusLabel('range', item.range_status) }}；{{ coverageStatusLabel('applicability', item.applicability_status) }}</p>
          <p v-if="item.document_ids?.length">登记资料编号：{{ item.document_ids.join('、') }} <a v-if="registeredPreviewUrl(item)" :href="registeredPreviewUrl(item)" target="_blank" rel="noopener noreferrer">预览已登记原件</a></p>
          <ul v-if="item.issues?.length" class="coverage-issues"><li v-for="(issue,i) in item.issues" :key="`${issue.code}-${i}`"><strong>{{ issue.reason }}</strong><p v-if="issue.action">处理建议：{{ issue.action }}</p></li></ul>
          <p v-else>未发现该条目的已知问题，仍受本次目录及范围边界限制。</p>
          <div class="coverage-path-heading"><strong>来源位置</strong><el-button v-if="item.source_locations?.length" size="small" link @click="copySources(item)">复制全部来源位置</el-button></div><pre v-for="(location,i) in item.source_locations || []" :key="i">{{ location }}</pre>
        </details>
        <p v-if="!rows.length">{{ onlyGaps ? '当前筛选下没有资料缺口；取消筛选可查看全部候选问题及范围外资料。' : '当前筛选下没有资料条目。' }}</p>
      </div>
      <p v-if="copyError" role="alert" class="coverage-error">{{ copyError }}</p>
    </template>
  </section>
</template>
<script setup>
import { computed, ref } from 'vue'
import { coverageAssessment, coverageBoundaryLabel, coverageRootLabel, coverageItems, coverageStatusLabel, registeredPreviewUrl } from '../utils/knowledgeReleaseCoverage'
const props = defineProps({ report: { type: Object, default: null }, loading: Boolean, error: { type: String, default: '' }, scopeNotice: { type: String, default: '' } })
defineEmits(['retry'])
const onlyGaps = ref(true), query = ref(''), copyError = ref('')
const rows = computed(() => coverageItems(props.report, onlyGaps.value, query.value))
const copySources = async item => {
  copyError.value = ''
  try { await navigator.clipboard.writeText((item.source_locations || []).join('\n')) }
  catch { copyError.value = '复制失败，请在展开的来源位置中选择并复制完整文字。' }
}
</script>
<style scoped>
.release-coverage { margin: 12px 0; padding: 10px 12px; border: 1px solid var(--el-border-color); border-radius: 6px; }
.coverage-heading,.coverage-counts,.coverage-controls,.coverage-path-heading { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 14px; }.coverage-heading small,.coverage-note,small { color: var(--el-text-color-secondary); }.coverage-counts { margin: 8px 0; }.coverage-controls { margin-top: 10px; }.coverage-controls .el-input { width: 250px; max-width: 100%; }.coverage-error { color: var(--el-color-danger); }.coverage-note { font-size: 12px; }
.coverage-roots,.coverage-item { padding: 8px 0; border-top: 1px solid var(--el-border-color-lighter); }summary { cursor: pointer; overflow-wrap: anywhere; }.coverage-item summary span { margin-left: 12px; color: var(--el-text-color-secondary); }.coverage-items { max-height: 55vh; overflow: auto; }.coverage-issues { padding-left: 20px; }.coverage-issues p { margin: 4px 0; }pre { white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; margin: 6px 0; }a { color: var(--el-color-primary); }
</style>
