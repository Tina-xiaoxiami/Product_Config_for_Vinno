<template>
  <section class="feature-detail" data-testid="knowledge-feature-detail">
    <h3>功能详情</h3>
    <p class="hint">选择功能与完整机型，按指定配置快照查看选型，并定位同范围资料。软件版本和配置版本分别选择。</p>
    <div class="controls">
      <el-select v-model="featureId" filterable clearable size="small" aria-label="详情功能" placeholder="功能 / IPN" :loading="catalogLoading" @change="workspace.invalidate">
        <el-option v-for="feature in features" :key="feature.id" :value="feature.id" :label="featureLabel(feature)" />
      </el-select>
      <el-select v-model="scope.market" clearable size="small" aria-label="详情市场" placeholder="市场" @change="onMarketChange"><el-option label="国内" value="domestic" /><el-option label="海外" value="overseas" /></el-select>
      <el-select v-model="scope.product_model_id" filterable clearable size="small" aria-label="详情完整机型" placeholder="完整机型" @change="onModelChange"><el-option v-for="model in scopedModels" :key="model.id" :label="`${model.name} · ${model.series_name}`" :value="model.id" /></el-select>
      <el-input v-model="scope.software_version" size="small" aria-label="详情软件版本" placeholder="目标软件版本" maxlength="80" @input="workspace.invalidate" />
      <el-select v-model="versionId" filterable clearable size="small" aria-label="详情配置快照" placeholder="已发布配置快照" :loading="versionsLoading" :disabled="!scope.product_model_id" @change="workspace.invalidate"><el-option v-for="version in versions" :key="version.id" :value="version.id" :label="`${version.version_number}${version.version_name ? ' · ' + version.version_name : ''}`" /></el-select>
      <el-button size="small" type="primary" :disabled="!featureId" :loading="state.loading" @click="loadDetail">查看详情</el-button>
      <el-button size="small" :disabled="catalogLoading" @click="loadCatalog">刷新功能目录</el-button>
    </div>
    <el-alert v-if="catalogError" :title="catalogError" type="error" :closable="false" />
    <el-alert v-if="versionsError" :title="versionsError" type="error" :closable="false"><el-button size="small" @click="onModelChange">重试配置列表</el-button></el-alert>
    <el-alert v-if="state.error" :title="state.error" type="error" :closable="false" />
    <article v-if="state.result" class="detail-result">
      <h3>{{ featureLabel(state.result.feature) }}</h3>
      <p class="hint">身份状态：{{ state.result.feature.identity_status }} · {{ state.result.feature.group_name }}</p>
      <p v-if="state.result.scope">{{ knowledgeScopeLabel(state.result.scope) }}</p>
      <el-alert v-if="state.result.status === 'needs_scope'" title="请补充市场、完整机型和目标软件版本后查看适用范围及资料。" type="info" :closable="false" />
      <ul v-if="state.result.issues.length" class="issues"><li v-for="issue in state.result.issues" :key="issue">{{ issue }}</li></ul>
      <section v-if="state.result.configuration" class="detail-section">
        <h4>配置与适用范围</h4>
        <p>已发布配置 {{ state.result.configuration.snapshot.version_number }} · {{ state.result.configuration.model.name }}</p>
        <div class="config-cards">
          <article v-for="(item, index) in state.result.configuration.items" :key="`${item.ipn}-${item.relation_type}-${index}`" class="config-card">
            <strong>{{ item.snapshot_name || '快照中无该IPN' }} · {{ item.ipn }}</strong>
            <p>{{ relationLabel(item.relation_type) }} · {{ item.selection_label }}<span v-if="item.selection_config">（{{ item.selection_config }}）</span></p>
            <p v-if="item.current_config_note" class="hint">研发当前配置（辅助）：{{ item.current_config_note }}</p>
          </article>
        </div>
        <p class="hint">关联版本、参数或组合成员分别展示，不自动继承为主功能支持结论。配置选型不能替代注册资料核验。</p>
      </section>
      <section v-if="state.result.scope" class="detail-section">
        <h4>当前范围的候选原文</h4>
        <p class="hint">保留各份来源与限制，未合并为统一正文；打开原文时核验文件摘要及位置。</p>
        <button v-for="citation in state.result.citations" :key="citation.chunk_id" type="button" class="source-card" @click="emit('citation', citation)">
          <strong>{{ citation.document_title }} · {{ citation.source_ref }}</strong><p>{{ citation.excerpt }}</p>
        </button>
      </section>
      <KnowledgeHistoryTrace v-if="state.result.history" :trace="state.result.history" />
    </article>
  </section>
</template>
<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import KnowledgeHistoryTrace from './KnowledgeHistoryTrace.vue'
import { getKnowledgeFeatures, getKnowledgeFeatureDetail, getVersions } from '../api/data'
import { createFeatureDetailWorkspace } from '../utils/knowledgeFeatureDetail'
import { createLatestParameterRequest, parameterFailure } from '../utils/knowledgeParameters'
import { knowledgeScopeLabel } from '../utils/knowledgeQueryScope'
const props = defineProps({ models: { type: Array, default: () => [] } })
const emit = defineEmits(['citation'])
const featureId = ref(null), features = ref([]), catalogLoading = ref(false), catalogError = ref('')
const scope = reactive({ market: '', product_model_id: null, software_version: '' })
const versions = ref([]), versionId = ref(null), versionsLoading = ref(false), versionsError = ref('')
const state = reactive({}), workspace = createFeatureDetailWorkspace({ load: getKnowledgeFeatureDetail }, state)
const catalogRequest = createLatestParameterRequest(), versionsRequest = createLatestParameterRequest()
const scopedModels = computed(() => props.models.filter(model => !scope.market || model.series_name?.endsWith(scope.market === 'domestic' ? '-China' : '-Oversea')))
const featureLabel = feature => `${feature.legacy_name} · ${feature.display_cn_name || feature.primary_cn_name || feature.primary_en_name || '名称待核'}${feature.ipns?.length ? ' · ' + feature.ipns.map(item => item.ipn).join(' / ') : ''}`
const relationLabel = value => ({ primary: '主功能', version_variant: '关联版本', related: '关联功能', parameter: '参数', component: '组合成员' }[value] || value)
async function allPages(fetchPage) {
  const items = []
  while (true) {
    const page = await fetchPage({ skip: items.length, limit: 200 })
    if (!page.items?.length && items.length < page.total) throw new Error('目录分页不完整，请重试')
    items.push(...(page.items || []))
    if (items.length >= page.total) return items
  }
}
const loadCatalog = () => catalogRequest.run(() => allPages(getKnowledgeFeatures), {
  start: () => { catalogLoading.value = true; catalogError.value = '' },
  success: items => { features.value = items; if (featureId.value && !items.some(item => item.id === featureId.value)) { featureId.value = null; workspace.invalidate() } },
  error: error => { catalogError.value = parameterFailure(error) },
  finish: () => { catalogLoading.value = false }
})
const onModelChange = async () => {
  workspace.invalidate(); versionsRequest.invalidate(); versions.value = []; versionId.value = null; versionsLoading.value = false; versionsError.value = ''
  const model = props.models.find(item => item.id === scope.product_model_id)
  if (!model) return
  await versionsRequest.run(() => allPages(params => getVersions(model.series_id, params)), {
    start: () => { versionsLoading.value = true }, success: items => { versions.value = items },
    error: error => { versionsError.value = parameterFailure(error) }, finish: () => { versionsLoading.value = false }
  })
}
const onMarketChange = () => { scope.product_model_id = null; onModelChange() }
const loadDetail = () => workspace.load(featureId.value, { ...scope, product_model_id: scope.product_model_id || null, market: scope.market || null, software_version: scope.software_version || null }, versionId.value || null)
onMounted(loadCatalog)
onBeforeUnmount(() => { workspace.invalidate(); catalogRequest.invalidate(); versionsRequest.invalidate() })
</script>
<style scoped>
.feature-detail h3,.detail-section h4 { margin: 8px 0; }
.controls { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin:12px 0; }
.controls .el-select,.controls .el-input { width:200px; }
.controls .el-button+.el-button { margin-left:0; }
.hint { color:var(--el-text-color-secondary); font-size:13px; }
.detail-section { margin-top:16px; border-top:1px solid var(--el-border-color-lighter); padding-top:8px; }
.config-cards { display:flex; flex-wrap:wrap; gap:8px; }
.config-card { border:1px solid var(--el-border-color); border-radius:6px; padding:10px; flex:1 1 260px; min-width:0; overflow-wrap:anywhere; }
.source-card { display:block; width:100%; margin:8px 0; padding:10px; border:1px solid var(--el-border-color); background:var(--el-bg-color); color:inherit; border-radius:6px; text-align:left; cursor:pointer; font:inherit; overflow-wrap:anywhere; }
.source-card p { white-space:pre-wrap; margin:8px 0 0; }
.issues { color:var(--el-color-warning-dark-2); padding-left:20px; }
</style>
