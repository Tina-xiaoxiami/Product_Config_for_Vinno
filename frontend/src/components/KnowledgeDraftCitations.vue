<template>
  <div class="draft-citations">
    <p v-if="loading" role="status">正在读取引用的原表行…</p>
    <p v-for="warning in warnings" :key="warning" class="citation-warning">{{ warning }}</p>
    <section v-for="(table, index) in tables" :key="index">
      <header>
        <strong>{{ table.title }}</strong><span>工作表 {{ table.sheet_name }}</span>
        <span>{{ table.header_row ? `表头第 ${table.header_row} 行` : '按原表列字母显示' }}</span>
        <a v-if="table.preview_url" :href="table.preview_url" target="_blank" rel="noopener noreferrer">查看原件</a>
        <span v-else>已按原件哈希核验引用行</span>
      </header>
      <el-table :data="table.rows" size="small" border max-height="300" row-key="row_number" aria-label="引用原表">
        <el-table-column label="原表行" width="112" fixed>
          <template #default="{ row }">
            第 {{ row.row_number }} 行
            <el-tag v-if="row.hidden" type="warning" size="small" effect="plain">原表隐藏行</el-tag>
          </template>
        </el-table-column>
        <el-table-column v-for="(column, i) in table.columns" :key="table.column_letters[i]" :label="column" :min-width="110">
          <template #default="{ row }"><span class="citation-cell">{{ row.cells[i] }}</span></template>
        </el-table-column>
      </el-table>
    </section>
    <ul v-if="unresolved.length">
      <li v-for="citation in unresolved" :key="citation.id">
        {{ citation.document_title }} · {{ citation.source_ref }}
        <a v-if="canViewUnverifiedOriginal(citation)" :href="citation.preview_url" target="_blank" rel="noopener noreferrer">查看原件</a>
      </li>
    </ul>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { getKnowledgeSpreadsheetCitations } from '../api/knowledgeEvidence'
import { canViewUnverifiedOriginal } from '../utils/knowledgeCitation'

const props = defineProps({ questionId: Number, version: Number, draftRevision: Number, citations: { type: Array, required: true } })
const tables = ref([]), warnings = ref([]), loading = ref(false)
const unresolved = computed(() => {
  const displayed = new Set(tables.value.flatMap(table => table.rows.flatMap(row => row.citation_ids)))
  return props.citations.filter(citation => !displayed.has(citation.id))
})
watch(() => [props.questionId, props.version, props.draftRevision], async ([id, version, draftRevision], _, onCleanup) => {
  const controller = new AbortController()
  onCleanup(() => controller.abort())
  tables.value = []
  warnings.value = []
  loading.value = false
  if (!id || !props.citations.some(citation => citation.source_ref?.startsWith('工作表'))) return
  loading.value = true
  try {
    const result = await getKnowledgeSpreadsheetCitations(id, version, controller.signal, draftRevision)
    if (!controller.signal.aborted) {
      tables.value = result.tables
      warnings.value = result.warnings
    }
  } catch (error) {
    if (!controller.signal.aborted) warnings.value = [error?.response?.status === 409
      ? '答案已修订，请重新打开以查看对应引用。' : '暂时无法读取原表行，请查看原件。']
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
}, { immediate: true })
</script>

<style scoped>
.draft-citations { display:grid; gap:8px; width:100%; min-width:0; }
.draft-citations section { min-width:0; }
.draft-citations header { display:flex; align-items:center; flex-wrap:wrap; gap:6px 12px; margin:0 0 4px; }
.draft-citations header span,.citation-warning { color:var(--el-text-color-secondary); font-size:12px; }
.draft-citations p,.draft-citations ul { margin:0; }
.draft-citations a { color:var(--el-color-primary); }
.citation-cell { white-space:pre-wrap; overflow-wrap:anywhere; }
</style>
