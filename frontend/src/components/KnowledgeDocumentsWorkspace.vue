<template>
  <section class="knowledge-documents-workspace" aria-label="原始资料管理">
    <div class="document-toolbar">
      <el-input
        v-model="state.query"
        clearable
        placeholder="搜索资料名、版本或产品"
        aria-label="搜索原始资料"
        :prefix-icon="Search"
        @keyup.enter="searchDocuments"
        @clear="searchDocuments"
      />
      <el-select v-model="state.documentType" clearable placeholder="全部资料类型" aria-label="原始资料类型" @change="searchDocuments">
        <el-option v-for="option in DOCUMENT_TYPE_OPTIONS" :key="option.value" :label="option.label" :value="option.value" />
      </el-select>
      <el-button type="primary" :icon="Search" :loading="state.loading" @click="searchDocuments">查询</el-button>
    </div>

    <el-alert v-if="state.error" type="error" :closable="false" show-icon data-testid="knowledge-documents-error">
      <template #title>{{ state.error }} <el-button link type="primary" @click="loadDocuments">重试</el-button></template>
    </el-alert>
    <el-alert v-if="state.operationError" :title="state.operationError" type="error" :closable="false" show-icon />

    <div data-testid="knowledge-document-list" class="document-list" v-loading="state.loading">
      <article v-for="document in state.items" :key="document.id" class="document-card">
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
            <span>{{ formatDocumentFileSize(document.file_size) }}</span>
            <span :class="document.available ? 'available' : 'unavailable'">{{ document.available ? '原文已同步' : '原文未同步' }}</span>
          </div>
        </div>
        <div class="document-actions">
          <el-tag v-if="document.extraction_status === 'completed'" type="success" size="small" effect="plain">
            正文已提取 · {{ document.chunk_count }}片段
          </el-tag>
          <el-button :loading="Boolean(state.extractionLoading[document.id])" :disabled="!document.available || Boolean(state.archiveLoading[document.id])" @click="extractDocument(document)">
            {{ document.extraction_status === 'completed' ? '重新提取' : '提取正文' }}
          </el-button>
          <el-button :icon="View" :disabled="!document.available" @click="previewDocument(document)">
            {{ canInlineDocument(document) ? '预览' : '打开原文' }}
          </el-button>
          <el-button link type="primary" :disabled="!document.available" @click="openDocumentLocally(document, 'reveal')">在访达中显示</el-button>
          <el-button link type="primary" :disabled="!document.available" @click="openDocumentLocally(document, 'open')">本机打开</el-button>
          <el-button link type="danger" :loading="Boolean(state.archiveLoading[document.id])" :disabled="Boolean(state.extractionLoading[document.id])" @click="archiveDocument(document)">归档</el-button>
        </div>
      </article>
      <el-empty v-if="!state.loading && !state.error && !state.items.length" description="暂无匹配资料" />
    </div>
    <el-pagination
      v-if="state.total > 0"
      v-model:current-page="state.page"
      v-model:page-size="state.pageSize"
      :total="state.total"
      :page-sizes="[50, 100, 200]"
      layout="total, sizes, prev, pager, next"
      size="small"
      @current-change="loadDocuments"
      @size-change="searchDocuments"
    />
    <el-dialog v-model="previewVisible" data-testid="document-preview-dialog" :title="previewTitle" width="88%" top="4vh" destroy-on-close>
      <iframe v-if="previewVisible" :src="previewUrl" class="preview-frame" :title="previewTitle" />
    </el-dialog>
  </section>
</template>

<script setup>
import { onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Document, Search, View } from '@element-plus/icons-vue'
import {
  archiveKnowledgeDocument,
  extractKnowledgeDocument,
  getKnowledgeDocumentPreviewUrl,
  getKnowledgeDocuments,
  openKnowledgeDocumentLocally
} from '../api/data'
import {
  DOCUMENT_TYPE_OPTIONS,
  canInlineDocument,
  createDocumentState,
  createDocumentWorkspace,
  documentTypeLabel,
  formatDocumentFileSize
} from '../utils/knowledgeDocumentsWorkspace'

const props = defineProps({ active: { type: Boolean, default: true } })
const state = reactive(createDocumentState())
const previewVisible = ref(false), previewTitle = ref(''), previewUrl = ref('')
const controller = createDocumentWorkspace({
  getKnowledgeDocuments, extractKnowledgeDocument, archiveKnowledgeDocument, openKnowledgeDocumentLocally,
  notify: message => ElMessage.success(message),
  confirmArchive: async document => {
    try {
      await ElMessageBox.confirm(
        `归档后「${document.title}」不再出现在资料列表与问答检索中，已提取的正文片段会被清除；受控目录里的原件文件不会被删除。`,
        '归档资料', { type: 'warning', confirmButtonText: '归档', cancelButtonText: '取消' }
      )
      return true
    } catch (error) {
      if (error === 'cancel' || error === 'close') return false
      throw error
    }
  }
}, state)
const { loadDocuments, searchDocuments, extractDocument, archiveDocument, openDocumentLocally } = controller

function previewDocument(document) {
  const url = getKnowledgeDocumentPreviewUrl(document.id)
  if (!canInlineDocument(document)) { window.open(url, '_blank', 'noopener'); return }
  previewTitle.value = document.title; previewUrl.value = url; previewVisible.value = true
}

onMounted(loadDocuments)
onBeforeUnmount(controller.dispose)
watch(() => props.active, active => {
  if (active) loadDocuments()
  else previewVisible.value = false
})
</script>

<style scoped>
.knowledge-documents-workspace { display: flex; flex-direction: column; gap: 12px; min-width: 0; padding: 16px; }
.document-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.document-toolbar .el-input { flex: 1 1 260px; }
.document-toolbar .el-select { width: 180px; }
.document-toolbar .el-button { margin-left: 0; }
.document-list { display: grid; gap: 10px; min-width: 0; }
.document-card { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; min-width: 0; padding: 14px; border: 1px solid #dbe4ef; border-radius: 9px; background: #fff; }
.document-icon { display: grid; place-items: center; width: 42px; height: 48px; color: #2563eb; border-radius: 10px; background: #eff6ff; font-size: 24px; }
.document-info { flex: 1 1 260px; min-width: 0; }
.document-title-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.document-title-row h3 { margin: 0; font-size: 15px; overflow-wrap: anywhere; }
.document-info p { margin: 5px 0; color: #6b7280; font-size: 12px; overflow-wrap: anywhere; }
.document-meta { display: flex; flex-wrap: wrap; gap: 6px 12px; color: #6b7280; font-size: 12px; }
.available { color: #159447; }
.unavailable { color: #b91c1c; }
.document-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.document-actions .el-button { margin-left: 0; }
.el-pagination { justify-content: flex-end; }
.preview-frame { width: 100%; height: 78vh; border: 0; background: #f3f4f6; }
@media (max-width: 720px) { .knowledge-documents-workspace { padding: 10px; } .document-actions { flex: 1 1 100%; } }
</style>
