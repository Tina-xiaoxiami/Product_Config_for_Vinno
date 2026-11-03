<template>
  <div class="page">
    <ProbeManagementActions path="/probe-models">
      <span v-if="selectedCategory" class="management-meta">{{ selectedCategory.name }}</span>
      <template v-if="selectedCategory">

              <el-button size="small" @click="exportAllVariants" :loading="exportingAll">导出所有变体</el-button>
              <el-button size="small" type="warning" @click="autoPopulate" :loading="populating">从配置自动填充</el-button>
              <el-upload
                :show-file-list="false"
                :auto-upload="false"
                :on-change="h => importAllVariants(h.raw)"
                accept=".xlsx,.xls"
                style="display:inline-block"
              >
                <el-button size="small" @click="">导入变体</el-button>
              </el-upload>
              <el-button size="small" type="primary" :icon="Plus" @click="addModelToCat(selectedCategory.id)">新增型号</el-button>
      </template>
      <el-button size="small" @click="refreshData">刷新</el-button>
      <el-button size="small" type="primary" plain :icon="Plus" @click="handleCreateCategory">新增类别</el-button>
    </ProbeManagementActions>
    <div class="panel-layout">
      <!-- Left: Category Panel -->
      <div class="panel panel-left">
        <div class="panel-header">
          <span class="panel-title">探头类别</span>
        </div>
        <div class="panel-body" v-loading="loading">
          <div
            v-for="cat in categories"
            :key="cat.id"
            class="category-item"
            :class="{ active: selectedCategory?.id === cat.id }"
            @click="selectCategory(cat)"
          >
            <div class="category-info">
              <span class="category-name">{{ cat.name }}</span>
              <span class="category-count">{{ (modelMap[cat.id] || []).length }} 型 <span class="app-counts">常规 {{ applicationCounts[cat.id]?.regular ?? '—' }} · POC {{ applicationCounts[cat.id]?.poc ?? '—' }}</span></span>
            </div>
            <div class="category-actions" @click.stop>
              <el-button size="small" text @click="handleEditCategory(cat)">编辑</el-button>
              <el-button size="small" text type="danger" @click="handleDeleteCategory(cat)">删除</el-button>
            </div>
          </div>
          <el-empty v-if="!categories.length" description="暂无探头类别" :image-size="80" />
        </div>
      </div>

      <!-- Both sections stay mounted and share the selected category. -->
      <div class="panel panel-right unified-right">
        <section ref="applicationsSection" class="applications-zone" aria-label="类别应用" tabindex="-1">
          <ApplicationsView ref="applicationsPanel" embedded :categories="categories" :category-id="selectedCategory?.id"
            @counts="applicationCounts = $event" @editor-state="applicationState = $event" @changed="onApplicationsChanged" />
        </section>
        <section class="models-zone" aria-label="探头型号">
          <div class="models-heading"><strong>探头型号</strong><span>{{ currentModels.length }} 型</span></div>
          <ProbeDataTable v-if="selectedCategory" :rows="modelRows" :columns="modelColumns" table-id="probe-applications-models"
            fill-height :actions-width="260" auto-apply-filters>
            <template #cell="{row, column}">
              <div v-if="column.key === 'variant_values'" class="variant-tags">
                <el-tag v-for="variant in row._variants" :key="variant.id" size="small" type="info"
                  :title="[variant.notes, variant.history_ids.length > 1 ? `${variant.history_ids.length} 条相同物料历史记录` : ''].filter(Boolean).join(' · ')">
                  {{ variant.internal_model }}<template v-if="variant.ipn"> / {{ variant.ipn }}</template>
                  <small v-if="variant.history_ids.length > 1"> · 历史 {{ variant.history_ids.length }}</small>
                </el-tag><span v-if="!row._variants?.length" class="no-data">无</span>
              </div>
              <span v-else>{{ row[column.key] ?? '—' }}</span>
            </template>
            <template #actions="{row}">
              <el-button size="small" text @click="openVariantDialog(row)">变体</el-button>
              <el-button size="small" text @click="openAppDialog(row)">类别应用</el-button>
              <el-button size="small" text @click="handleEditModel(row, selectedCategory.id)">编辑</el-button>
              <el-button size="small" text type="danger" @click="handleDeleteModel(row)">删除</el-button>
            </template>
          </ProbeDataTable>
          <el-empty v-else description="从左侧选择探头类别" :image-size="50" />
        </section>
      </div>
    </div>

    <!-- Category Dialog -->
    <el-dialog v-model="catDialogVisible" :title="editingCatId ? '编辑类别' : '新增类别'" width="400px">
      <el-form :model="catForm" label-width="80px">
        <el-form-item label="名称"><el-input v-model="catForm.name" placeholder="请输入探头类别名称" /></el-form-item>
        <el-form-item label="排序"><el-input-number v-model="catForm.sort_order" :min="0" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="catDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveCategory" :loading="saving">保存</el-button>
      </template>
    </el-dialog>

    <!-- Model Dialog -->
    <el-dialog v-model="modelDialogVisible" :title="editingModelId ? '编辑型号' : '新增型号'" width="400px">
      <el-form :model="modelForm" label-width="80px">
        <el-form-item label="类别">
          <el-select v-model="modelForm.category_id" style="width:100%">
            <el-option v-for="c in categories" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="型号"><el-input v-model="modelForm.model_number" placeholder="如 F2-5CP" /></el-form-item>
        <el-form-item label="排序"><el-input-number v-model="modelForm.sort_order" :min="0" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="modelDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveModel" :loading="saving">保存</el-button>
      </template>
    </el-dialog>

    <!-- Variant Dialog -->
    <el-dialog v-model="variantDialogVisible" title="管理内部型号变体" width="760px">
      <div class="dialog-info">
        探头型号：<strong>{{ variantTarget?.model_number }}</strong>
        <span style="margin-left:16px;font-size:12px;color:#909399">
          可导出 Excel 表格，批量编辑后导入
        </span>
      </div>

      <div class="variant-actions">
        <el-button size="small" @click="exportModelVariants" :loading="exporting">导出模板</el-button>
        <el-upload
          :show-file-list="false"
          :auto-upload="false"
          :on-change="h => importModelVariants(h.raw)"
          accept=".xlsx,.xls"
          style="display:inline-block"
        >
          <el-button size="small" type="success" :loading="importing">导入Excel</el-button>
        </el-upload>
      </div>

      <el-table :data="variantList" border size="small" max-height="300" style="margin-top:8px">
        <el-table-column type="index" label="#" width="40" />
        <el-table-column prop="internal_model" label="内部型号" min-width="180" />
        <el-table-column prop="ipn" label="IPN" width="150" />
        <el-table-column prop="notes" label="备注" min-width="160">
          <template #default="{ row: v }">
            <span :title="v.notes">{{ v.notes || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80">
          <template #default="{ row: v }">
            <el-button size="small" text type="danger" @click="deleteVariant(v)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!variantList.length" description="暂无变体" :image-size="60" />
      <div class="variant-add-form">
        <el-input v-model="newVariant.internal_model" placeholder="内部型号" style="width:160px" />
        <el-input v-model="newVariant.ipn" placeholder="IPN" style="width:140px" />
        <el-input v-model="newVariant.notes" placeholder="备注（说明差异）" style="width:200px" />
        <el-button size="small" type="primary" @click="addVariant">添加</el-button>
      </div>
      <template #footer>
        <el-button @click="variantDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, nextTick, onBeforeUnmount } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, FolderOpened } from '@element-plus/icons-vue'
import { getProbeCategories, createProbeCategory, updateProbeCategory, deleteProbeCategory, getProbeModels, createProbeModel, updateProbeModel, deleteProbeModel, exportVariantsExcel, importVariantsExcel, exportModelVariantsExcel, importModelVariantsExcel, autoPopulateVariants } from '../api/data'
import api from '../api/index'
import { useRoute, onBeforeRouteLeave } from 'vue-router'
import { useWorkspaceRefresh } from '../utils/useWorkspaceRefresh'
import { groupProbeVariants } from '../utils/probeMatrix'
import ProbeManagementActions from '../components/ProbeManagementActions.vue'

import ApplicationsView from './ApplicationsView.vue'
import ProbeDataTable from '../components/ProbeDataTable.vue'
import { resolveProbeCategory, applicationEditorState, probeContextBlock, probeModelRows } from '../utils/probeApplications'

const route = useRoute()
const loading = ref(false)
const categories = ref([])
const modelMap = ref({})
const selectedCategory = ref(null)
const applicationsPanel = ref(), applicationsSection = ref()
const applicationCounts = ref({}), applicationState = ref(applicationEditorState())
let requestedCategoryId = Number(route.query.category_id) || null
const modelColumns = [
  { key: 'position', label: '#', width: 42, fixed: true, filter: false },
  { key: 'model_number', label: '型号', width: 135, fixed: true },
  { key: 'variant_values', label: '内部型号 / IPN', width: 340, multiValue: true },
  { key: 'application_count', label: '应用', width: 65 },
  { key: 'sort_order', label: '排序', width: 65 }
]

const catDialogVisible = ref(false); const editingCatId = ref(null)
const modelDialogVisible = ref(false); const editingModelId = ref(null); const saving = ref(false)
const catForm = reactive({ name: '', sort_order: 0 })
const modelForm = reactive({ category_id: null, model_number: '', sort_order: 0 })

let dataLoadRequest = 0
const loadData = async () => {
  const request = ++dataLoadRequest
  loading.value = true
  try {
    const [catRes, modelRes] = await Promise.all([
      getProbeCategories({ limit: 200 }),
      getProbeModels({ limit: 2000, include_details: true })
    ])
    if (request !== dataLoadRequest) return
    const nextCategories = catRes.items || []
    const nextMap = {}
    for (const model of modelRes.items || []) {
      const row = { ...model, _appCount: model.application_count || 0, _variants: groupProbeVariants(model.id, model.variant_items) }
      if (!nextMap[model.category_id]) nextMap[model.category_id] = []
      nextMap[model.category_id].push(row)
    }
    categories.value = nextCategories
    modelMap.value = nextMap
    selectedCategory.value = resolveProbeCategory(nextCategories, selectedCategory.value?.id, requestedCategoryId)
    requestedCategoryId = null
  } catch {
    if (request === dataLoadRequest) ElMessage.error('加载失败')
  } finally {
    if (request === dataLoadRequest) loading.value = false
  }
}

const currentModels = computed(() => {
  if (!selectedCategory.value) return []
  return modelMap.value[selectedCategory.value.id] || []
})

const modelRows = computed(() => probeModelRows(currentModels.value))
const metadataOpen = () => catDialogVisible.value || modelDialogVisible.value || variantDialogVisible.value
const selectCategory = cat => {
  if (metadataOpen() || probeContextBlock(applicationState.value)) {
    ElMessage.warning('请先完成当前编辑或提交，再切换探头类别'); return false
  }
  selectedCategory.value = cat
  return true
}
watch(() => route.query.category_id, value => {
  const category = categories.value.find(row => row.id === Number(value))
  if (category) selectCategory(category)
  else if (!categories.value.length) requestedCategoryId = Number(value) || null
})
const focusApplications = async () => {
  await nextTick()
  applicationsSection.value?.scrollIntoView({ block: 'nearest' })
  applicationsSection.value?.focus({ preventScroll: true })
  await applicationsPanel.value?.focusAdd()
}
watch(() => route.query.focus, value => { if (value === 'applications') focusApplications() }, { immediate: true })
const onApplicationsChanged = () => loadData()
const refreshData = async () => {
  if (metadataOpen() || !applicationState.value.canRefresh) { ElMessage.warning('请先提交或撤销当前编辑，再刷新'); return false }
  await loadData()
  return applicationsPanel.value?.refresh()
}

// Category CRUD
const handleCreateCategory = () => { editingCatId.value = null; catForm.name = ''; catForm.sort_order = 0; catDialogVisible.value = true }
const handleEditCategory = (row) => { editingCatId.value = row.id; catForm.name = row.name; catForm.sort_order = row.sort_order; catDialogVisible.value = true }
const saveCategory = async () => {
  if (!catForm.name) return ElMessage.warning('请输入名称')
  saving.value = true
  try {
    editingCatId.value ? await updateProbeCategory(editingCatId.value, catForm) : await createProbeCategory(catForm)
    ElMessage.success('保存成功'); catDialogVisible.value = false; await loadData()
  } catch { ElMessage.error('保存失败') } finally { saving.value = false }
}
const handleDeleteCategory = async (row) => {
  if (probeContextBlock(applicationState.value, true)) return ElMessage.warning('请先提交或撤销应用编辑，再删除类别')
  try {
    await ElMessageBox.confirm(`确认删除"${row.name}"及其所有型号？`, '确认', { type: 'warning' })
    await deleteProbeCategory(row.id); ElMessage.success('删除成功')
    if (selectedCategory.value?.id === row.id) selectedCategory.value = null
    await loadData()
  } catch (e) { if (e !== 'cancel') ElMessage.error('删除失败') }
}

// Model CRUD
const handleCreateModel = () => {
  editingModelId.value = null
  modelForm.category_id = selectedCategory.value?.id || categories.value[0]?.id || null
  modelForm.model_number = ''; modelForm.sort_order = 0
  modelDialogVisible.value = true
}
const addModelToCat = (catId) => { handleCreateModel(); modelForm.category_id = catId }
const handleEditModel = (m, catId) => {
  editingModelId.value = m.id
  modelForm.category_id = catId; modelForm.model_number = m.model_number; modelForm.sort_order = m.sort_order || 0
  modelDialogVisible.value = true
}
const saveModel = async () => {
  if (!modelForm.category_id || !modelForm.model_number) return ElMessage.warning('类别和型号不能为空')
  saving.value = true
  try {
    editingModelId.value ? await updateProbeModel(editingModelId.value, modelForm) : await createProbeModel(modelForm)
    ElMessage.success('保存成功'); modelDialogVisible.value = false; await loadData()
  } catch { ElMessage.error('保存失败') } finally { saving.value = false }
}
const handleDeleteModel = async (row) => {
  try {
    await ElMessageBox.confirm(`确认删除"${row.model_number}"？`, '确认', { type: 'warning' })
    await deleteProbeModel(row.id); ElMessage.success('删除成功'); await loadData()
  } catch (e) { if (e !== 'cancel') ElMessage.error('删除失败') }
}

// Applications are maintained once per category, including regular and POC tracks.
const openAppDialog = async model => {
  const category = categories.value.find(row => row.id === model.category_id)
  if (category && !selectCategory(category)) return false
  await focusApplications()
  return true
}

// Variant management
const variantDialogVisible = ref(false); const variantTarget = ref(null)
const variantList = ref([]); const newVariant = reactive({ internal_model: '', ipn: '', notes: '' })
const exporting = ref(false); const importing = ref(false)
const exportingAll = ref(false)
const populating = ref(false)

const autoPopulate = async () => {
  populating.value = true
  try {
    const res = await autoPopulateVariants()
    ElMessage.success(res.message)
    await loadData()
  } catch { ElMessage.error('自动填充失败') } finally { populating.value = false }
}

const openVariantDialog = async (m) => {
  variantTarget.value = m; newVariant.internal_model = ''; newVariant.ipn = ''; newVariant.notes = ''
  try { variantList.value = await api.get(`/probe-models/${m.id}/variants`) } catch { variantList.value = [] }
  variantDialogVisible.value = true
}
const addVariant = async () => {
  if (!newVariant.internal_model) return ElMessage.warning('请输入内部型号')
  try {
    await api.post(`/probe-models/${variantTarget.value.id}/variants`, { ...newVariant })
    ElMessage.success('添加成功')
    newVariant.internal_model = ''; newVariant.ipn = ''; newVariant.notes = ''
    await openVariantDialog(variantTarget.value); await loadData()
  } catch { ElMessage.error('添加失败') }
}
const deleteVariant = async (v) => {
  try { await api.delete(`/probe-models/${variantTarget.value.id}/variants/${v.id}`); ElMessage.success('删除成功'); await openVariantDialog(variantTarget.value); await loadData() }
  catch { ElMessage.error('删除失败') }
}

const exportModelVariants = async () => {
  if (!variantTarget.value) return
  exporting.value = true
  try {
    const res = await exportModelVariantsExcel(variantTarget.value.id)
    const url = URL.createObjectURL(new Blob([res]))
    const a = document.createElement('a')
    a.href = url; a.download = `${variantTarget.value.model_number}_变体.xlsx`
    a.click(); URL.revokeObjectURL(url)
    ElMessage.success('导出成功')
  } catch { ElMessage.error('导出失败') } finally { exporting.value = false }
}

const importModelVariants = async (file) => {
  if (!variantTarget.value) return
  importing.value = true
  try {
    const fd = new FormData(); fd.append('file', file)
    const res = await importModelVariantsExcel(variantTarget.value.id, fd)
    ElMessage.success(res.message)
    await openVariantDialog(variantTarget.value); await loadData()
  } catch { ElMessage.error('导入失败') } finally { importing.value = false }
}

const exportAllVariants = async () => {
  exportingAll.value = true
  try {
    const res = await exportVariantsExcel()
    const url = URL.createObjectURL(new Blob([res]))
    const a = document.createElement('a')
    a.href = url; a.download = `探头型号变体_${new Date().toISOString().slice(0,10).replace(/-/g,'')}.xlsx`
    a.click(); URL.revokeObjectURL(url)
    ElMessage.success('导出成功')
  } catch { ElMessage.error('导出失败') } finally { exportingAll.value = false }
}

const importAllVariants = async (file) => {
  try {
    const fd = new FormData(); fd.append('file', file)
    const res = await importVariantsExcel(fd)
    ElMessage.success(res.message)
    await loadData()
  } catch { ElMessage.error('导入失败') }
}

const metadataBusy = () => saving.value || importing.value || populating.value
const metadataDirty = () => catDialogVisible.value || modelDialogVisible.value || (variantDialogVisible.value && Boolean(newVariant.internal_model || newVariant.ipn || newVariant.notes))
const requestLeave = async () => {
  if (metadataBusy() || applicationState.value.busy) return false
  if (metadataDirty() || applicationState.value.hasUnsavedChanges) {
    try { await ElMessageBox.confirm('探头或应用编辑尚未保存或提交，是否放弃并离开？', '未保存的修改', { confirmButtonText: '放弃修改', cancelButtonText: '继续编辑', type: 'warning' }) }
    catch { return false }
    applicationsPanel.value?.discardLocal()
  }
  catDialogVisible.value = false; modelDialogVisible.value = false; variantDialogVisible.value = false
  return true
}
const beforeUnload = event => {
  if (metadataBusy() || metadataDirty() || applicationState.value.protected) { event.preventDefault(); event.returnValue = '' }
}
onBeforeRouteLeave(requestLeave)
if (typeof window !== 'undefined') window.addEventListener('beforeunload', beforeUnload)
onBeforeUnmount(() => { dataLoadRequest += 1; window.removeEventListener('beforeunload', beforeUnload) })
useWorkspaceRefresh(loadData, { canRefresh: () => !metadataOpen() && applicationState.value.canRefresh })
</script>

<style scoped>
.page { padding: 0; flex: 1; min-height: 360px; display: flex; flex-direction: column; }

.panel-layout {
  display: flex;
  gap: 8px;
  flex: 1;
  min-height: 0;
}

.panel {
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.panel-left {
  width: 220px;
  min-width: 200px;
  flex-shrink: 0;
}

.panel-right {
  flex: 1;
  min-width: 0;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 10px;
  border-bottom: 1px solid #e4e7ed;
  background: #fafafa;
}

.panel-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
}

.panel-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 6px;
}

/* Category items */
.category-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
  margin-bottom: 2px;
}

.category-item:hover {
  background: #f5f7fa;
}

.category-item.active {
  background: #ecf5ff;
  border-left: 3px solid #409eff;
  padding-left: 7px;
}

.category-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.category-name {
  font-size: 13px;
  font-weight: 500;
  color: #303133;
}

.category-count {
  font-size: 11px;
  color: #909399;
}

.category-actions {
  display: flex;
  gap: 4px;
  opacity: 0;
  transition: opacity 0.15s;
}

.category-item:hover .category-actions {
  opacity: 1;
}

/* Placeholder */
.placeholder-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #c0c4cc;
  gap: 12px;
}

.placeholder-content p {
  font-size: 13px;
  margin: 0;
}

/* Variant tags */
.variant-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
}

.no-data {
  color: #c0c4cc;
  font-size: 12px;
}

/* Dialog styles */
.dialog-info {
  font-size: 13px;
  color: #606266;
}

.variant-actions {
  display: flex;
  gap: 8px;
  margin: 12px 0;
}

.variant-add-form {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #e4e7ed;
}
.unified-right { padding: 8px; gap: 8px; }
.applications-zone { flex-shrink: 0; min-height: 0; max-height: 45%; overflow: auto; outline: none; }
.models-zone { flex: 1; display: flex; flex-direction: column; min-height: 160px; overflow: hidden; }
.models-heading { display: flex; align-items: center; gap: 8px; font-size: 13px; margin-bottom: 3px; }
.models-heading span, .app-counts { color: #909399; font-size: 11px; }
.app-counts { white-space: nowrap; }
@media (max-width: 760px) { .panel-left { width: 160px; min-width: 140px; }.unified-right { padding: 6px; } }
</style>
