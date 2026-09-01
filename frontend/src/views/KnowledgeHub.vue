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
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Document, Link, Search, View } from '@element-plus/icons-vue'
import {
  getKnowledgeDocuments,
  getKnowledgeDocumentPreviewUrl,
  getKnowledgeFeatures,
  getKnowledgeStats
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

const previewVisible = ref(false)
const previewUrl = ref('')
const previewTitle = ref('')

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
.preview-frame { width: 100%; height: 78vh; border: 0; background: #f3f4f6; }
.el-pagination { justify-content: flex-end; margin-top: 16px; }
@media (max-width: 850px) {
  .stats-grid { grid-template-columns: repeat(2, 1fr); }
  .toolbar { grid-template-columns: 1fr; }
  .knowledge-header { flex-direction: column; gap: 10px; }
}
</style>
