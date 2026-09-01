<template>
  <div class="knowledge-page">
    <header class="knowledge-header">
      <div>
        <h2>产品知识库</h2>
        <p>以 IPN 为功能唯一身份，统一查询主名称、备用名、版本关系和原始资料。</p>
      </div>
      <el-tag :type="stats.pending === 0 ? 'success' : 'danger'" effect="plain">
        {{ stats.pending === 0 ? '无待确认功能' : `${stats.pending} 个功能待确认` }}
      </el-tag>
    </header>

    <section class="stats-grid" v-loading="statsLoading">
      <div class="stat-card primary">
        <span class="stat-value">{{ stats.total_features }}</span>
        <span class="stat-label">功能总数</span>
      </div>
      <div class="stat-card">
        <span class="stat-value">{{ stats.auto_matched }}</span>
        <span class="stat-label">自动匹配</span>
      </div>
      <div class="stat-card">
        <span class="stat-value">{{ stats.confirmed }}</span>
        <span class="stat-label">人工确认</span>
      </div>
      <div class="stat-card">
        <span class="stat-value">{{ stats.related }}</span>
        <span class="stat-label">关系型功能</span>
      </div>
    </section>

    <el-tabs v-model="activeTab" class="knowledge-tabs">
      <el-tab-pane label="功能主数据" name="features">
        <section class="toolbar">
          <el-input
            v-model="featureQuery"
            data-testid="knowledge-search"
            clearable
            placeholder="搜索 IPN、中英文名称或备用名"
            :prefix-icon="Search"
            @keyup.enter="searchFeatures"
            @clear="searchFeatures"
          />
          <el-select
            v-model="identityStatus"
            data-testid="knowledge-status-filter"
            clearable
            placeholder="全部身份状态"
            @change="searchFeatures"
          >
            <el-option label="自动匹配" value="auto_matched" />
            <el-option label="人工确认" value="confirmed" />
            <el-option label="关系型功能" value="related" />
          </el-select>
          <el-button type="primary" :icon="Search" @click="searchFeatures">查询</el-button>
        </section>

        <div data-testid="feature-knowledge-list" class="feature-list" v-loading="featureLoading">
          <article v-for="feature in features" :key="feature.id" class="feature-card">
            <div class="feature-heading">
              <div>
                <div class="feature-title-row">
                  <h3>{{ feature.primary_cn_name || feature.legacy_name }}</h3>
                  <el-tag :type="statusType(feature.identity_status)" size="small" effect="plain">
                    {{ statusLabel(feature.identity_status) }}
                  </el-tag>
                </div>
                <p class="english-name">{{ feature.primary_en_name || '暂无英文主名' }}</p>
              </div>
              <span class="group-name">{{ feature.group_name }}</span>
            </div>

            <div class="ipn-list">
              <div v-for="entry in feature.ipns" :key="`${entry.ipn}-${entry.relation_type}`" class="ipn-item">
                <code>{{ entry.ipn }}</code>
                <span>{{ relationLabel(entry.relation_type) }}</span>
                <span v-if="entry.zh_desc && entry.zh_desc !== feature.primary_cn_name" class="ipn-description">
                  {{ entry.zh_desc }}
                </span>
              </div>
            </div>

            <div class="name-section">
              <span class="section-label">备用名</span>
              <div class="alias-list">
                <el-tag
                  v-for="name in aliases(feature)"
                  :key="`${name.language}-${name.name}`"
                  size="small"
                  type="info"
                  effect="plain"
                >
                  {{ name.name }}
                </el-tag>
                <span v-if="aliases(feature).length === 0" class="empty-text">无</span>
              </div>
            </div>

            <div v-if="feature.identity_status === 'related'" class="relation-note">
              <el-icon><Link /></el-icon>
              <span>{{ relationNote(feature) }}</span>
            </div>
          </article>
          <el-empty v-if="!featureLoading && features.length === 0" description="未找到匹配功能" />
        </div>

        <el-pagination
          v-if="featureTotal > featureLimit"
          v-model:current-page="featurePage"
          :page-size="featureLimit"
          :total="featureTotal"
          layout="prev, pager, next, total"
          @current-change="loadFeatures"
        />
      </el-tab-pane>

      <el-tab-pane label="国内注册与策略" name="registration">
        <section class="registration-intro">
          <div>
            <div class="registration-title-row">
              <h3>国内注册探头判定</h3>
              <el-tag type="success" effect="plain">国内 / CN</el-tag>
            </div>
            <p>先执行注册红线，再读取正式选型；研发当前配置仅在没有正式选型时作为辅助信息。</p>
          </div>
          <el-button :icon="View" :disabled="!registrationSourceDocumentId" @click="openRegistrationSource">
            注册差异表原文
          </el-button>
        </section>

        <section class="status-legend" aria-label="配置状态图例">
          <span><strong class="status-x">X</strong> X 标配</span>
          <span><strong class="status-o">O</strong> O 选配</span>
          <span><strong class="status-tender">Δ</strong> Δ 招标支持</span>
          <span><strong class="status-blocked">#</strong> # 未注册</span>
        </section>

        <section class="registration-toolbar">
          <el-select
            v-model="selectedProductModelId"
            data-testid="registration-model-select"
            filterable
            placeholder="选择国内产品型号"
            @change="searchRegistrationProbes"
          >
            <el-option
              v-for="model in registrationModels"
              :key="model.product_model_id"
              :label="registrationModelLabel(model)"
              :value="model.product_model_id"
            />
          </el-select>
          <el-input
            v-model="registrationQuery"
            data-testid="registration-probe-search"
            clearable
            placeholder="搜索探头型号、IPN 或配置名称"
            :prefix-icon="Search"
            @keyup.enter="searchRegistrationProbes"
            @clear="searchRegistrationProbes"
          />
          <el-select
            v-model="registrationStatus"
            data-testid="registration-status-filter"
            clearable
            placeholder="全部注册状态"
            @change="searchRegistrationProbes"
          >
            <el-option label="已注册" value="registered" />
            <el-option label="# 未注册" value="unregistered" />
          </el-select>
          <el-select
            v-model="effectiveStatus"
            data-testid="effective-status-filter"
            clearable
            placeholder="全部最终判定"
            @change="searchRegistrationProbes"
          >
            <el-option label="X 标配" value="X" />
            <el-option label="O 选配" value="O" />
            <el-option label="Δ 招标支持" value="Δ" />
            <el-option label="# 未注册" value="#" />
            <el-option label="未定义" value="未定义" />
          </el-select>
          <el-button type="primary" :icon="Search" @click="searchRegistrationProbes">查询</el-button>
        </section>

        <section v-if="selectedProductModelId" class="registration-context">
          <span>产品型号：<strong>{{ registrationMeta.product_model_name || '-' }}</strong></span>
          <span v-if="registrationMeta.registration_model_name">
            注册基础型号：<strong>{{ registrationMeta.registration_model_name }}</strong>
          </span>
          <el-tag v-if="isDerivedRegistrationModel" type="warning" size="small" effect="plain">
            衍生型号沿用基础型号注册
          </el-tag>
        </section>

        <section class="registration-summary" v-loading="registrationLoading">
          <div><strong>{{ registrationSummary.registered }}</strong><span>已注册</span></div>
          <div class="danger"><strong>{{ registrationSummary.unregistered }}</strong><span>未注册</span></div>
          <div><strong>{{ registrationSummary.standard }}</strong><span>标配</span></div>
          <div><strong>{{ registrationSummary.optional }}</strong><span>选配</span></div>
          <div><strong>{{ registrationSummary.tender }}</strong><span>招标支持</span></div>
          <div><strong>{{ registrationSummary.undefined }}</strong><span>策略未定义</span></div>
        </section>

        <el-table
          data-testid="registration-strategy-table"
          :data="registrationItems"
          v-loading="registrationLoading"
          border
          stripe
          empty-text="请选择型号或调整筛选条件"
          class="registration-table"
        >
          <el-table-column prop="probe_model" label="探头型号" min-width="130" fixed="left" />
          <el-table-column prop="ipn" label="IPN" min-width="115" />
          <el-table-column prop="config_name" label="配置名称" min-width="180">
            <template #default="scope">{{ scope.row.config_name || '配置系统暂无对应项' }}</template>
          </el-table-column>
          <el-table-column label="注册状态" min-width="105" align="center">
            <template #default="scope">
              <el-tag :type="scope.row.registration_status === 'registered' ? 'success' : 'danger'" effect="plain">
                {{ scope.row.registration_status === 'registered' ? '已注册' : '# 未注册' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="选型类别（正式）" min-width="135" align="center">
            <template #default="scope">{{ displayConfigStatus(scope.row.selection_config) }}</template>
          </el-table-column>
          <el-table-column label="当前配置（辅助）" min-width="135" align="center">
            <template #default="scope">{{ displayConfigStatus(scope.row.current_config) }}</template>
          </el-table-column>
          <el-table-column label="最终判定" min-width="120" align="center" fixed="right">
            <template #default="scope">
              <el-tag :type="effectiveStatusType(scope.row.effective_status)" effect="dark">
                {{ displayConfigStatus(scope.row.effective_status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="判定依据" min-width="165">
            <template #default="scope">
              <span :class="{ 'auxiliary-source': scope.row.status_source === 'current_config_aux' }">
                {{ statusSourceLabel(scope.row.status_source) }}
              </span>
              <el-tag v-if="scope.row.conflict" type="danger" size="small" class="conflict-tag">存在冲突</el-tag>
            </template>
          </el-table-column>
        </el-table>

        <el-pagination
          v-if="registrationTotal > registrationLimit"
          v-model:current-page="registrationPage"
          :page-size="registrationLimit"
          :total="registrationTotal"
          layout="prev, pager, next, total"
          @current-change="loadRegistrationProbes"
        />
      </el-tab-pane>

      <el-tab-pane label="原始资料" name="documents">
        <section class="toolbar document-toolbar">
          <el-input
            v-model="documentQuery"
            clearable
            placeholder="搜索资料名、版本或产品"
            :prefix-icon="Search"
            @keyup.enter="searchDocuments"
            @clear="searchDocuments"
          />
          <el-select v-model="documentType" clearable placeholder="全部资料类型" @change="searchDocuments">
            <el-option label="注册证/注册变更" value="registration_certificate" />
            <el-option label="注册差异表" value="registration_difference" />
            <el-option label="产品说明书" value="manual" />
            <el-option label="产品白皮书" value="whitepaper" />
            <el-option label="Release Note" value="release_note" />
          </el-select>
          <el-button type="primary" :icon="Search" @click="searchDocuments">查询</el-button>
        </section>

        <div data-testid="knowledge-document-list" class="document-list" v-loading="documentLoading">
          <article v-for="document in documents" :key="document.id" class="document-card">
            <div class="document-icon"><el-icon><Document /></el-icon></div>
            <div class="document-info">
              <div class="document-title-row">
                <h3>{{ document.title }}</h3>
                <el-tag size="small" effect="plain">{{ documentTypeLabel(document.document_type) }}</el-tag>
              </div>
              <p>{{ document.file_name }}</p>
              <div class="document-meta">
                <span v-if="document.product_series">{{ document.product_series }}</span>
                <span v-if="document.version">版本 {{ document.version }}</span>
                <span>{{ formatFileSize(document.file_size) }}</span>
                <span :class="document.available ? 'available' : 'unavailable'">
                  {{ document.available ? '原文已同步' : '原文未同步' }}
                </span>
              </div>
            </div>
            <el-button :icon="View" :disabled="!document.available" @click="previewDocument(document)">
              {{ canInline(document) ? '预览' : '打开原文' }}
            </el-button>
          </article>
          <el-empty v-if="!documentLoading && documents.length === 0" description="暂无已登记资料" />
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-dialog
      v-model="previewVisible"
      data-testid="document-preview-dialog"
      :title="previewTitle"
      width="88%"
      top="4vh"
      destroy-on-close
    >
      <iframe v-if="previewVisible" :src="previewUrl" class="preview-frame" :title="previewTitle" />
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Document, Link, Search, View } from '@element-plus/icons-vue'
import {
  getKnowledgeDocuments,
  getKnowledgeDocumentPreviewUrl,
  getKnowledgeFeatures,
  getKnowledgeStats,
  getConfiguredRegistrationModels,
  getRegistrationProbes
} from '../api/data'

const activeTab = ref('features')
const stats = ref({ total_features: 0, auto_matched: 0, confirmed: 0, related: 0, pending: 0 })
const statsLoading = ref(false)

const featureQuery = ref('')
const identityStatus = ref('')
const featureLoading = ref(false)
const features = ref([])
const featureTotal = ref(0)
const featurePage = ref(1)
const featureLimit = 20

const documentQuery = ref('')
const documentType = ref('')
const documentLoading = ref(false)
const documents = ref([])

const registrationModels = ref([])
const selectedProductModelId = ref(null)
const registrationQuery = ref('')
const registrationStatus = ref('')
const effectiveStatus = ref('')
const registrationLoading = ref(false)
const registrationItems = ref([])
const registrationTotal = ref(0)
const registrationPage = ref(1)
const registrationLimit = 100
const registrationMeta = ref({})
const registrationSummary = ref({
  registered: 0,
  unregistered: 0,
  standard: 0,
  optional: 0,
  tender: 0,
  undefined: 0,
  auxiliary: 0,
  conflicts: 0
})

const previewVisible = ref(false)
const previewUrl = ref('')
const previewTitle = ref('')

const isDerivedRegistrationModel = computed(() => (
  registrationMeta.value.mapping_type
  && registrationMeta.value.mapping_type !== 'direct'
))
const registrationSourceDocumentId = computed(() => (
  registrationItems.value.find(item => item.source_document_id)?.source_document_id || null
))

const statusLabel = (status) => ({
  auto_matched: '自动匹配',
  confirmed: '人工确认',
  related: '关系型功能',
  pending: '待确认'
}[status] || status)

const statusType = (status) => ({
  auto_matched: 'success',
  confirmed: 'primary',
  related: 'warning',
  pending: 'danger'
}[status] || 'info')

const relationLabel = (relation) => ({
  primary: '主 IPN',
  related: '相关功能',
  version_variant: '版本 IPN'
}[relation] || relation)

const documentTypeLabel = (type) => ({
  registration_certificate: '注册证/变更',
  registration_difference: '注册差异表',
  manual: '产品说明书',
  whitepaper: '产品白皮书',
  release_note: 'Release Note'
}[type] || type)

const registrationModelLabel = (model) => model.product_model_name === model.registration_model_name
  ? model.product_model_name
  : `${model.product_model_name} → ${model.registration_model_name}`
const displayConfigStatus = (status) => ({
  X: 'X 标配',
  O: 'O 选配',
  '∆': 'Δ 招标支持',
  'Δ': 'Δ 招标支持',
  '#': '# 未注册',
  未定义: '未定义'
}[status] || status || '—')
const effectiveStatusType = (status) => ({
  X: 'success',
  O: 'primary',
  'Δ': 'warning',
  '#': 'danger',
  未定义: 'info'
}[status] || 'info')
const statusSourceLabel = (source) => ({
  registration_redline: '注册红线',
  selection_config: '正式选型类别',
  current_config_aux: '研发当前配置（辅助）',
  missing: '尚无正式策略'
}[source] || source || '—')

const aliases = (feature) => (feature.names || []).filter(name => name.name_type === 'alias')
const relationNote = (feature) => (feature.ipns || []).some(entry => entry.relation_type === 'version_variant')
  ? '版本关系：保留各组 IPN 独立身份，当前名称作为关系入口。'
  : '关联功能：保留关联 IPN 的独立身份，当前名称作为查询入口。'
const canInline = (document) => document.mime_type === 'application/pdf' || document.mime_type?.startsWith('image/')
const formatFileSize = (size) => {
  if (!size) return '0 KB'
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

const loadStats = async () => {
  statsLoading.value = true
  try {
    stats.value = await getKnowledgeStats()
  } catch {
    ElMessage.error('统计信息加载失败')
  } finally {
    statsLoading.value = false
  }
}

const loadFeatures = async () => {
  featureLoading.value = true
  try {
    const result = await getKnowledgeFeatures({
      q: featureQuery.value || undefined,
      identity_status: identityStatus.value || undefined,
      skip: (featurePage.value - 1) * featureLimit,
      limit: featureLimit
    })
    features.value = result.items || []
    featureTotal.value = result.total || 0
  } catch {
    ElMessage.error('功能知识加载失败')
  } finally {
    featureLoading.value = false
  }
}

const searchFeatures = () => {
  featurePage.value = 1
  loadFeatures()
}

const loadDocuments = async () => {
  documentLoading.value = true
  try {
    const result = await getKnowledgeDocuments({
      q: documentQuery.value || undefined,
      document_type: documentType.value || undefined,
      limit: 100
    })
    documents.value = result.items || []
  } catch {
    ElMessage.error('原始资料加载失败')
  } finally {
    documentLoading.value = false
  }
}

const searchDocuments = () => loadDocuments()

const loadRegistrationModels = async () => {
  try {
    const result = await getConfiguredRegistrationModels({ country_code: 'CN' })
    registrationModels.value = result.items || []
    if (!selectedProductModelId.value && registrationModels.value.length > 0) {
      const preferred = registrationModels.value.find(model => model.product_model_name === 'VINNO 10')
      selectedProductModelId.value = (preferred || registrationModels.value[0]).product_model_id
    }
    if (selectedProductModelId.value) await loadRegistrationProbes()
  } catch {
    ElMessage.error('国内注册型号加载失败')
  }
}

const loadRegistrationProbes = async () => {
  if (!selectedProductModelId.value) return
  registrationLoading.value = true
  try {
    const result = await getRegistrationProbes({
      product_model_id: selectedProductModelId.value,
      q: registrationQuery.value || undefined,
      registration_status: registrationStatus.value || undefined,
      effective_status: effectiveStatus.value || undefined,
      skip: (registrationPage.value - 1) * registrationLimit,
      limit: registrationLimit
    })
    registrationItems.value = result.items || []
    registrationTotal.value = result.total || 0
    registrationSummary.value = result.summary || {}
    registrationMeta.value = {
      product_model_name: result.product_model_name,
      registration_model_name: result.registration_model_name,
      mapping_type: result.mapping_type
    }
  } catch {
    ElMessage.error('注册与策略数据加载失败')
  } finally {
    registrationLoading.value = false
  }
}

const searchRegistrationProbes = () => {
  registrationPage.value = 1
  loadRegistrationProbes()
}

const openRegistrationSource = () => {
  if (!registrationSourceDocumentId.value) return
  window.open(
    getKnowledgeDocumentPreviewUrl(registrationSourceDocumentId.value),
    '_blank',
    'noopener'
  )
}

const previewDocument = (document) => {
  const url = getKnowledgeDocumentPreviewUrl(document.id)
  if (!canInline(document)) {
    window.open(url, '_blank', 'noopener')
    return
  }
  previewTitle.value = document.title
  previewUrl.value = url
  previewVisible.value = true
}

onMounted(() => {
  loadStats()
  loadFeatures()
  loadDocuments()
  loadRegistrationModels()
})
</script>

<style scoped>
.knowledge-page { max-width: 1180px; margin: 0 auto; }
.knowledge-header { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 18px; }
.knowledge-header h2 { margin: 0 0 6px; font-size: 22px; color: #1f2937; }
.knowledge-header p { margin: 0; color: #6b7280; font-size: 13px; }
.stats-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 18px; }
.stat-card { background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; padding: 15px 18px; display: flex; flex-direction: column; }
.stat-card.primary { background: linear-gradient(135deg, #ecf5ff, #fff); border-color: #bfdbfe; }
.stat-value { color: #111827; font-size: 24px; font-weight: 700; }
.stat-label { margin-top: 3px; color: #6b7280; font-size: 12px; }
.knowledge-tabs { background: #fff; border-radius: 12px; padding: 0 18px 18px; border: 1px solid #e5e7eb; }
.toolbar { display: grid; grid-template-columns: minmax(320px, 1fr) 190px auto; gap: 10px; margin: 10px 0 16px; }
.feature-list, .document-list { display: flex; flex-direction: column; gap: 10px; min-height: 180px; }
.feature-card, .document-card { border: 1px solid #e5e7eb; border-radius: 9px; padding: 15px 16px; background: #fff; }
.feature-card:hover, .document-card:hover { border-color: #bfdbfe; box-shadow: 0 3px 14px rgba(30, 64, 175, 0.06); }
.feature-heading, .feature-title-row, .document-title-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.feature-title-row, .document-title-row { justify-content: flex-start; }
.feature-card h3, .document-card h3 { margin: 0; font-size: 15px; color: #1f2937; }
.english-name, .document-info p { margin: 4px 0 0; color: #6b7280; font-size: 12px; }
.group-name { color: #6b7280; background: #f3f4f6; border-radius: 12px; padding: 3px 9px; font-size: 12px; }
.ipn-list { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 13px; }
.ipn-item { display: flex; align-items: center; gap: 7px; background: #f8fafc; border-radius: 6px; padding: 6px 9px; font-size: 12px; color: #64748b; }
.ipn-item code { color: #1d4ed8; font-weight: 600; }
.ipn-description { border-left: 1px solid #dbe3ef; padding-left: 7px; }
.name-section { display: flex; align-items: flex-start; gap: 12px; margin-top: 12px; }
.section-label { min-width: 48px; padding-top: 3px; color: #6b7280; font-size: 12px; }
.alias-list { display: flex; flex-wrap: wrap; gap: 6px; }
.empty-text { color: #9ca3af; font-size: 12px; }
.relation-note { display: flex; align-items: center; gap: 6px; margin-top: 11px; color: #92400e; font-size: 12px; }
.document-card { display: flex; align-items: center; gap: 14px; }
.document-icon { width: 42px; height: 42px; border-radius: 9px; display: grid; place-items: center; background: #eff6ff; color: #2563eb; font-size: 20px; }
.document-info { flex: 1; min-width: 0; }
.document-meta { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 7px; color: #6b7280; font-size: 11px; }
.available { color: #15803d; }
.unavailable { color: #b91c1c; }
.registration-intro { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; margin: 12px 0; padding: 14px 16px; border: 1px solid #dbeafe; border-radius: 9px; background: #f8fbff; }
.registration-title-row { display: flex; align-items: center; gap: 9px; }
.registration-title-row h3 { margin: 0; color: #1f2937; font-size: 15px; }
.registration-intro p { margin: 6px 0 0; color: #64748b; font-size: 12px; }
.status-legend { display: flex; flex-wrap: wrap; gap: 8px 18px; margin-bottom: 12px; color: #475569; font-size: 12px; }
.status-legend span { display: flex; align-items: center; gap: 5px; }
.status-legend strong { display: inline-grid; place-items: center; width: 20px; height: 20px; border-radius: 5px; color: #fff; }
.status-x { background: #16a34a; }
.status-o { background: #2563eb; }
.status-tender { background: #d97706; }
.status-blocked { background: #dc2626; }
.registration-toolbar { display: grid; grid-template-columns: minmax(190px, 1.1fr) minmax(220px, 1.4fr) 150px 150px auto; gap: 9px; margin-bottom: 12px; }
.registration-context { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 18px; margin-bottom: 12px; color: #64748b; font-size: 12px; }
.registration-context strong { color: #1f2937; }
.registration-summary { display: grid; grid-template-columns: repeat(6, minmax(90px, 1fr)); gap: 8px; margin-bottom: 12px; }
.registration-summary div { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; padding: 10px 12px; border: 1px solid #e5e7eb; border-radius: 8px; background: #fff; }
.registration-summary strong { color: #1f2937; font-size: 19px; }
.registration-summary span { color: #64748b; font-size: 11px; }
.registration-summary .danger strong { color: #dc2626; }
.registration-table { width: 100%; }
.auxiliary-source { color: #b45309; }
.conflict-tag { display: block; width: fit-content; margin-top: 4px; }
.preview-frame { width: 100%; height: 78vh; border: 0; background: #f3f4f6; }
.el-pagination { justify-content: flex-end; margin-top: 16px; }
@media (max-width: 850px) {
  .stats-grid { grid-template-columns: repeat(2, 1fr); }
  .toolbar, .registration-toolbar { grid-template-columns: 1fr; }
  .registration-summary { grid-template-columns: repeat(2, 1fr); }
  .registration-intro { flex-direction: column; }
  .knowledge-header { flex-direction: column; gap: 10px; }
}
</style>
