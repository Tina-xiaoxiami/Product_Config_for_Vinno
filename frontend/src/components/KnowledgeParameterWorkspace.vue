<template>
  <section class="parameter-workspace" data-testid="knowledge-parameter-workspace">
    <p class="parameter-hint">维护一次规格参数，再按已发布配置快照匹配各型号。预览不会修改配置，也不会发布正式问答。</p>
    <el-alert v-if="!available" title="参数型答案存储尚未初始化，请更新服务后使用。" type="warning" :closable="false" />
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <div class="parameter-toolbar">
      <el-select v-model="topicId" filterable clearable placeholder="选择参数主题" aria-label="参数主题" @change="onTopicChange" :loading="topicsLoading"><el-option v-for="item in topics" :key="item.id" :label="item.name" :value="item.id" /></el-select>
      <el-button size="small" type="primary" :disabled="!available" @click="openTopic">新建参数主题</el-button>
      <el-button size="small" :disabled="!topic || !available" @click="openSpec()">新增规格与IPN</el-button>
      <el-button size="small" @click="loadTopics">刷新</el-button>
    </div>
    <template v-if="topic">
      <p class="parameter-hint">{{ topic.question }} · {{ topic.fields.map(field => `${field.label}${field.unit ? '（' + field.unit + '）' : ''}`).join('、') }}</p>
      <div class="parameter-specs" v-loading="specsLoading">
        <article v-for="spec in specs" :key="spec.id" class="parameter-spec" :class="{ inactive: !spec.is_active }">
          <div><strong>{{ spec.name }}</strong> <code>{{ spec.ipn }}</code> <el-tag size="small" :type="spec.is_active ? 'success' : 'info'">{{ spec.is_active ? '启用' : '停用' }}</el-tag> <span class="parameter-hint">修订 {{ spec.revision }}</span></div>
          <p>{{ formatParameterValues(topic, spec.values) }}</p><p class="parameter-hint">配置项：{{ spec.current_cn_name || '尚未明确' }}</p><p v-if="spec.identity_issue" class="parameter-issue">{{ spec.identity_issue }}</p>
          <details><summary>依据与核对记录</summary><p>{{ spec.evidence_reference }}</p><p>核对人：{{ spec.confirmed_by }}</p></details>
          <el-button size="small" link type="primary" @click="openSpec(spec)">编辑 / 停用</el-button>
        </article>
        <el-empty v-if="!specsLoading && !specs.length" description="尚无规格。请录入已确认的参数与IPN，不会自动推测容量或关联。" :image-size="50" />
      </div>
      <div class="parameter-toolbar parameter-preview-controls">
        <el-select v-model="seriesId" filterable clearable placeholder="配置系列" aria-label="参数匹配配置系列" @change="onSeriesChange"><el-option v-for="series in seriesList" :key="series.id" :label="series.name" :value="series.id" /></el-select>
        <el-select v-model="versionId" filterable clearable placeholder="已发布配置版本" aria-label="参数匹配配置版本" :disabled="!seriesId" :loading="versionsLoading" @change="onVersionChange"><el-option v-for="version in versions" :key="version.id" :label="`${version.version_number}${version.version_name ? ' · ' + version.version_name : ''}`" :value="version.id" /></el-select>
        <el-select v-model="modelIds" multiple filterable collapse-tags collapse-tags-tooltip placeholder="该快照中的完整型号" aria-label="参数匹配型号" :disabled="!snapshot" :loading="snapshotLoading" @change="invalidatePreview"><el-option v-for="model in snapshot?.models || []" :key="model.id" :label="model.name" :value="model.id" /></el-select>
        <el-button size="small" :disabled="!snapshot" @click="selectAllModels">选择快照全部型号</el-button>
        <el-button size="small" type="primary" :disabled="!versionId || !modelIds.length" :loading="previewLoading" @click="runPreview">按配置匹配参数</el-button>
      </div>
      <template v-if="preview">
        <p class="parameter-hint">配置版本：{{ preview.snapshot.version_number }} · {{ preview.rows.length }} 个型号；匹配以快照IPN和正式选型类别为准。</p>
        <div class="parameter-toolbar">
          <el-input v-model="search" clearable size="small" placeholder="搜索全部匹配结果" aria-label="搜索参数匹配结果" @input="page = 1" />
          <el-button v-if="search || statuses !== null" size="small" @click="clearFilters">清除筛选</el-button>
          <span class="parameter-hint">{{ filteredRows.length }} / {{ preview.rows.length }} 条</span>
          <TableColumnSettings :model-value="columnLayout" :defaults="PARAMETER_PREVIEW_COLUMNS" @update:model-value="applyColumns" />
          <el-button size="small" @click="answerVisible = true">查看 / 复制答案</el-button>
        </div>
        <div ref="tableArea" class="parameter-table-area">
          <el-table :key="columnStructure" :data="pagedRows" border stripe size="small" :height="tableHeight" @header-dragend="resizeColumn" row-key="model_id" data-table-id="knowledge-parameter-preview" empty-text="当前筛选下暂无结果">
            <el-table-column v-for="column in visibleColumns" :key="column.key" :prop="column.key" :label="column.label" :width="column.width" :min-width="30" :fixed="column.fixed ? 'left' : false">
              <template v-if="column.key === 'status_label'" #header>
                <span class="parameter-filter-header">{{ column.label }}<el-popover trigger="click" placement="bottom-end" :width="240">
                  <template #reference><el-button :icon="Filter" text size="small" :class="{ active: statuses !== null }" aria-label="匹配状态筛选" :title="statuses === null ? '匹配状态：不限' : `匹配状态：已选${statuses.length}项`" /></template>
                  <p class="parameter-hint">选择后立即筛选</p><div class="parameter-toolbar"><el-button link size="small" @click="setStatuses(null)">不限</el-button><el-button link size="small" @click="setStatuses([])">清空</el-button></div>
                  <el-checkbox-group :model-value="statuses ?? allStatuses" @update:model-value="setStatuses"><el-checkbox v-for="value in allStatuses" :key="value" :value="value">{{ parameterStatusLabel(value) }}</el-checkbox></el-checkbox-group>
                </el-popover></span>
              </template>
              <template #default="{ row }"><span class="parameter-cell">{{ row[column.key] || '—' }}</span></template>
            </el-table-column>
            <el-table-column label="操作" width="80" fixed="right"><template #default="{ row }"><el-button link type="primary" size="small" @click="detailRow = row">详情</el-button></template></el-table-column>
          </el-table>
        </div>
        <el-pagination v-if="filteredRows.length" v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[20,50,100]" :total="filteredRows.length" layout="total, sizes, prev, pager, next" small @size-change="page = 1" />
      </template>
      <el-empty v-else-if="!previewLoading" description="选择配置快照及型号后预览；缺项和多种可选规格会逐项列出。" :image-size="50" />
    </template>
    <el-dialog v-model="editorState.visible" :title="editorState.kind === 'topic' ? '新建参数主题' : '维护规格与IPN'" width="min(800px, calc(100vw - 32px))" :before-close="closeEditor" destroy-on-close>
      <el-alert v-if="editorState.error" :title="editorState.error" type="error" :closable="false" />
      <el-form v-if="editorState.form" label-position="top" :disabled="editorState.saving">
        <template v-if="editorState.kind === 'topic'">
          <div class="parameter-form-grid"><el-form-item label="主题名称" required><el-input v-model="editorState.form.name" maxlength="100" placeholder="如：电池容量" /></el-form-item><el-form-item label="对应问题" required><el-input v-model="editorState.form.question" maxlength="500" placeholder="如：各型号电池容量是多少？" /></el-form-item></div>
          <el-form-item label="其他问法（每行一个）"><el-input v-model="editorState.form.aliases" type="textarea" :rows="2" /></el-form-item>
          <p class="parameter-hint">填写参数名称、单位和数值/文字类型；创建后保留字段定义，规格参数可另行修订。</p>
          <div v-for="(field,index) in editorState.form.fields" :key="index" class="parameter-field-row"><el-input v-model="field.label" placeholder="中文标签，如 容量" :aria-label="`第${index+1}字段名`" /><el-input v-model="field.unit" placeholder="单位，如 mAh" :aria-label="`第${index+1}字段单位`" /><el-select v-model="field.type"><el-option label="数值" value="number" /><el-option label="文字" value="text" /></el-select><el-button size="small" :disabled="editorState.form.fields.length === 1" @click="editorState.form.fields.splice(index,1)">移除</el-button></div>
          <el-button size="small" @click="editorState.form.fields.push({ key:'', label:'', unit:'', type:'number' })">添加参数字段</el-button>
        </template>
        <template v-else>
          <div class="parameter-form-grid"><el-form-item label="规格名称" required><el-input v-model="editorState.form.name" placeholder="输入已确认的规格名" maxlength="100" /></el-form-item><el-form-item label="对应IPN" required><el-input v-model="editorState.form.ipn" placeholder="配置基础数据中的唯一IPN" maxlength="100" /></el-form-item></div>
          <div class="parameter-form-grid"><el-form-item v-for="field in topic?.fields || []" :key="field.key" :label="`${field.label}${field.unit ? '（'+field.unit+'）' : ''}`" required><el-input v-model="editorState.form.values[field.key]" :placeholder="`输入${field.type === 'number' ? '数值' : '文字'}，不自动换算`" /></el-form-item></div>
          <el-form-item label="依据 / 原始资料定位" required><el-input v-model="editorState.form.evidence_reference" type="textarea" :rows="3" maxlength="5000" /></el-form-item>
          <div class="parameter-form-grid"><el-form-item label="本次核对人" required><el-input v-model="editorState.form.confirmed_by" maxlength="100" placeholder="填写实际核对人" /></el-form-item><el-form-item label="规格状态"><el-switch v-model="editorState.form.is_active" active-text="启用" inactive-text="停用" /></el-form-item></div>
        </template>
      </el-form>
      <template #footer><el-button :disabled="editorState.saving" @click="closeEditor()">取消</el-button><el-button type="primary" :loading="editorState.saving" @click="editor.submit()">保存</el-button></template>
    </el-dialog>
    <el-dialog :model-value="!!detailRow" title="型号匹配详情" width="min(800px, calc(100vw - 32px))" @update:model-value="value => { if (!value) detailRow = null }"><template v-if="detailRow"><h3>{{ detailRow.model_name }}</h3><p v-for="issue in detailRow.issues" :key="String(issue)">{{ issue }}</p><article v-for="match in detailRow.matches" :key="`${match.spec_id}-${match.ipn}`" class="parameter-spec"><strong>{{ match.name || match.spec_name }} · {{ match.ipn }}</strong><p>{{ formatParameterValues(topic, match.values) }}</p><p>配置快照名称：{{ match.snapshot_cn_name || '未记录' }}</p><p v-if="match.current_cn_name && match.current_cn_name !== match.snapshot_cn_name">当前中文描述：{{ match.current_cn_name }}</p><p>{{ match.selection_label || match.selection_config || '选型未明确' }}</p><p v-if="match.current_config_note">研发当前配置（辅助）：{{ match.current_config_note }}</p><p>依据：{{ match.evidence_reference }}</p><p>规格修订：{{ match.revision }}</p></article><pre class="parameter-answer">{{ detailRow.answer_text }}</pre></template></el-dialog>
    <el-dialog v-model="answerVisible" title="参数匹配答案预览" width="min(800px, calc(100vw - 32px))"><p class="parameter-hint">结果依据所选配置快照与当前已保存规格，不代表已发布正式问答。</p><pre class="parameter-answer">{{ preview?.answer_text }}</pre><template #footer><el-button @click="copyAnswer">复制答案</el-button><el-button @click="answerVisible = false">关闭</el-button></template></el-dialog>
  </section>
</template>
<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Filter } from '@element-plus/icons-vue'
import TableColumnSettings from './TableColumnSettings.vue'
import { getSeriesList, getVersions } from '../api/data'
import { getParameterTopics, createParameterTopic, getParameterSpecs, createParameterSpec, updateParameterSpec, getParameterSnapshot, previewParameterTopic } from '../api/knowledgeParameters'
import { PARAMETER_PREVIEW_COLUMNS, parameterStatusLabel, parameterFailure, formatParameterValues, filterParameterRows, parameterTopicPayload, parameterSpecPayload, createLatestParameterRequest, createParameterEditor } from '../utils/knowledgeParameters'
import { loadColumnLayout, normalizeColumnLayout, saveColumnLayout } from '../utils/tableColumnLayout'
const topics = ref([]), topicId = ref(null), specs = ref([]), available = ref(true), error = ref(''), topicsLoading = ref(false), specsLoading = ref(false)
const seriesList = ref([]), seriesId = ref(null), versions = ref([]), versionId = ref(null), versionsLoading = ref(false), snapshot = ref(null), snapshotLoading = ref(false), modelIds = ref([]), preview = ref(null), previewLoading = ref(false)
const topic = computed(() => topics.value.find(item => item.id === topicId.value))
const topicRequests = createLatestParameterRequest(), specRequests = createLatestParameterRequest(), versionRequests = createLatestParameterRequest(), snapshotRequests = createLatestParameterRequest(), previewRequests = createLatestParameterRequest()
const fail = failure => { error.value = parameterFailure(failure) }
const invalidatePreview = () => { previewRequests.invalidate(); preview.value = null; previewLoading.value = false; error.value = ''; page.value = 1; answerVisible.value = false; detailRow.value = null }
const loadTopics = async () => topicRequests.run(getParameterTopics, { start: () => { topicsLoading.value = true; error.value = '' }, success: result => { available.value = result.available !== false; topics.value = result.items || []; if (topicId.value && !topics.value.some(item => item.id === topicId.value)) { topicId.value = null; onTopicChange() } }, error: fail, finish: () => { topicsLoading.value = false } })
const onTopicChange = () => { invalidatePreview(); specs.value = []; specRequests.invalidate(); specsLoading.value = false; if (topicId.value) loadSpecs() }
const loadSpecs = async () => { const id = topicId.value; if (!id) return; await specRequests.run(() => getParameterSpecs(id), { start: () => { specsLoading.value = true; error.value = '' }, success: result => { specs.value = result.items || []; available.value = result.available !== false }, error: fail, finish: () => { specsLoading.value = false } }) }
const onSeriesChange = async () => { versionRequests.invalidate(); snapshotRequests.invalidate(); versions.value = []; versionId.value = null; snapshot.value = null; modelIds.value = []; versionsLoading.value = false; snapshotLoading.value = false; invalidatePreview(); if (!seriesId.value) return; const id = seriesId.value; await versionRequests.run(async () => { const result = []; let skip = 0; while (true) { const data = await getVersions(id, { limit: 200, skip }); result.push(...data.items); skip += data.items.length; if (!data.items.length || skip >= data.total) return result } }, { start: () => { versionsLoading.value = true }, success: result => { versions.value = result }, error: fail, finish: () => { versionsLoading.value = false } }) }
const onVersionChange = async () => { snapshotRequests.invalidate(); snapshot.value = null; modelIds.value = []; snapshotLoading.value = false; invalidatePreview(); if (!versionId.value) return; const id = versionId.value; await snapshotRequests.run(() => getParameterSnapshot(id), { start: () => { snapshotLoading.value = true }, success: result => { snapshot.value = result }, error: fail, finish: () => { snapshotLoading.value = false } }) }
const selectAllModels = () => { modelIds.value = (snapshot.value?.models || []).map(model => model.id); invalidatePreview() }
const runPreview = async () => { if (!topic.value || !versionId.value || !modelIds.value.length) return; const id = topicId.value, payload = { config_version_id: versionId.value, model_ids: [...modelIds.value] }; await previewRequests.run(() => previewParameterTopic(id, payload), { start: () => { previewLoading.value = true; preview.value = null; error.value = ''; page.value = 1 }, success: result => { preview.value = result; clearFilters(); nextTick(updateTableHeight) }, error: fail, finish: () => { previewLoading.value = false } }) }
const editorState = reactive({ visible: false, kind: 'topic', form: null, saving: false, error: '' })
const editor = createParameterEditor({ state: editorState,
  confirmDiscard: () => ElMessageBox.confirm('尚有未保存的参数修改，是否放弃？', '未保存的修改', { confirmButtonText: '放弃修改', cancelButtonText: '继续编辑', type: 'warning' }),
  save: async (kind, form) => { if (kind === 'topic') { const payload = parameterTopicPayload(form); if (!payload.name || !payload.question || !payload.fields.length || payload.fields.some(field => !field.key || !field.label)) throw new Error('请填写主题、问题及完整参数字段'); return createParameterTopic(payload) } if (!form.name.trim() || !form.ipn.trim() || !form.evidence_reference.trim() || !form.confirmed_by.trim()) throw new Error('请填写规格名称、IPN、依据及本次核对人'); const selectedTopic = topics.value.find(item => item.id === form.topic_id); if (!selectedTopic) throw new Error('主题已变化，请重新打开规格'); const payload = parameterSpecPayload(form, selectedTopic); return form.id ? updateParameterSpec(form.topic_id, form.id, payload) : createParameterSpec(form.topic_id, payload) },
  onSaved: async (result, kind, form) => { invalidatePreview(); if (kind === 'topic') { await loadTopics(); topicId.value = result.id; onTopicChange() } else if (topicId.value === form.topic_id) await loadSpecs(); ElMessage.success('参数记录已保存') }
})
const closeEditor = done => editor.close(done)
const openTopic = () => editor.open('topic', { name: '', question: '', aliases: '', fields: [{ key: '', label: '', unit: '', type: 'number' }] })
const openSpec = value => { if (!topic.value) return; editor.open('spec', value ? { ...value, topic_id: topicId.value, confirmed_by: '' } : { topic_id: topicId.value, name: '', ipn: '', values: Object.fromEntries(topic.value.fields.map(field => [field.key, ''])), evidence_reference: '', confirmed_by: '', is_active: true }) }
const search = ref(''), statuses = ref(null), page = ref(1), pageSize = ref(20), answerVisible = ref(false), detailRow = ref(null)
const previewRows = computed(() => (preview.value?.rows || []).map(row => ({ ...row, status_label: parameterStatusLabel(row.status), specs_text: (row.matches || []).map(match => `${match.name || match.spec_name} / ${match.ipn}`).join('；'), values_text: (row.matches || []).map(match => formatParameterValues(topic.value, match.values)).join('\n'), selection_text: (row.matches || []).map(match => match.selection_label || match.selection_config || '未明确').join('；'), issues_text: (row.issues || []).join('；') })))
const allStatuses = computed(() => [...new Set(previewRows.value.map(row => row.status))])
const filteredRows = computed(() => filterParameterRows(previewRows.value, search.value, statuses.value))
const pagedRows = computed(() => filteredRows.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))
const setStatuses = value => { statuses.value = value; page.value = 1 }
const clearFilters = () => { search.value = ''; statuses.value = null; page.value = 1 }
const storageKey = 'knowledge-parameter-preview-columns-v1', storage = { getItem: key => localStorage.getItem(key), setItem: (key,value) => localStorage.setItem(key,value) }
const columnLayout = ref(loadColumnLayout(storage, storageKey, PARAMETER_PREVIEW_COLUMNS, message => ElMessage.warning(message)))
const visibleColumns = computed(() => columnLayout.value.filter(column => column.visible)), columnStructure = computed(() => visibleColumns.value.map(column => `${column.key}:${column.fixed}`).join('|'))
const applyColumns = value => { columnLayout.value = normalizeColumnLayout(PARAMETER_PREVIEW_COLUMNS, value); saveColumnLayout(storage, storageKey, columnLayout.value, message => ElMessage.warning(message)) }
const resizeColumn = (width,_old,column) => applyColumns(columnLayout.value.map(item => item.key === column.property ? { ...item,width } : item))
const tableArea = ref(null), tableHeight = ref(300)
const updateTableHeight = () => { if (tableArea.value) tableHeight.value = Math.max(260, window.innerHeight - Math.max(0, tableArea.value.getBoundingClientRect().top) - 85) }
let resizeObserver
watch(tableArea, (area, previous) => { if (previous) resizeObserver?.unobserve(previous); if (area) { resizeObserver?.observe(area); nextTick(updateTableHeight) } }, { flush: 'post' })
const copyAnswer = async () => { try { await navigator.clipboard.writeText(preview.value?.answer_text || ''); ElMessage.success('答案预览已复制') } catch { ElMessage.error('复制失败，可从预览中选择文字复制') } }
onMounted(async () => { window.addEventListener('resize', updateTableHeight); resizeObserver = new ResizeObserver(updateTableHeight); await Promise.all([loadTopics(), getSeriesList({ limit: 1000 }).then(result => { seriesList.value = result.items || [] }).catch(fail)]); await nextTick(); if (tableArea.value) resizeObserver.observe(tableArea.value) })
onBeforeUnmount(() => { [topicRequests,specRequests,versionRequests,snapshotRequests,previewRequests].forEach(request => request.invalidate()); resizeObserver?.disconnect(); window.removeEventListener('resize', updateTableHeight) })
</script>
<style scoped>
.parameter-workspace { display: grid; gap: 10px; min-width: 0; }
.parameter-hint { color: var(--el-text-color-secondary); font-size: 12px; margin: 3px 0; }
.parameter-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; }
.parameter-toolbar > .el-button + .el-button { margin-left: 0; }
.parameter-toolbar > .el-select { width: 240px; max-width: 100%; }
.parameter-toolbar > .el-input { width: 260px; max-width: 100%; }
.parameter-preview-controls .el-select:last-of-type { flex: 1 1 270px; }
.parameter-specs { display: flex; flex-wrap: wrap; gap: 8px; max-height: 300px; overflow: auto; }
.parameter-spec { border: 1px solid var(--el-border-color-light); border-radius: 5px; padding: 9px 11px; flex: 1 1 270px; min-width: 0; }
.parameter-spec p { margin: 5px 0; overflow-wrap: anywhere; white-space: pre-wrap; }
.parameter-issue { color: var(--el-color-warning-dark-2); font-size: 12px; }
.parameter-spec.inactive { opacity: .7; }
.parameter-spec details { font-size: 12px; }
.parameter-cell { display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 3; overflow: hidden; white-space: pre-wrap; overflow-wrap: anywhere; }
.parameter-table-area { min-width: 0; width: 100%; overflow: hidden; }
.parameter-filter-header { display: inline-flex; align-items: center; gap: 3px; }
.parameter-filter-header .active { color: var(--el-color-primary); }
.parameter-form-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 10px; }
.parameter-field-row { display: grid; grid-template-columns: 1.4fr 1.4fr 1fr 100px auto; gap: 7px; margin-bottom: 8px; }
.parameter-answer { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 60vh; overflow: auto; font: inherit; line-height: 1.65; }
@media (max-width: 650px) { .parameter-form-grid { grid-template-columns: 1fr; } .parameter-field-row { grid-template-columns: repeat(2,minmax(0,1fr)); } }
</style>
