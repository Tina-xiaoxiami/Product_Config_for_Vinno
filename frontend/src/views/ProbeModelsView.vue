<template>
  <div class="page">
    <div class="panel-layout">
      <!-- Left: Category Panel -->
      <div class="panel panel-left">
        <div class="panel-header">
          <span class="panel-title">探头类别</span>
          <el-button size="small" type="primary" plain :icon="Plus" @click="handleCreateCategory">新增</el-button>
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
              <span class="category-count">{{ (modelMap[cat.id] || []).length }} 型</span>
            </div>
            <div class="category-actions" @click.stop>
              <el-button size="small" text @click="handleEditCategory(cat)">编辑</el-button>
              <el-button size="small" text type="danger" @click="handleDeleteCategory(cat)">删除</el-button>
            </div>
          </div>
          <el-empty v-if="!categories.length" description="暂无探头类别" :image-size="80" />
        </div>
      </div>

      <!-- Right: Models Panel -->
      <div class="panel panel-right">
        <div class="panel-header">
          <template v-if="selectedCategory">
            <span class="panel-title">{{ selectedCategory.name }} — 探头型号</span>
            <div class="panel-header-actions">
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
            </div>
          </template>
          <span v-else class="panel-title placeholder">请选择一个探头类别</span>
        </div>
        <div class="panel-body" v-loading="loading">
          <template v-if="selectedCategory">
            <el-table :data="currentModels" border stripe size="small" style="width:100%" max-height="560" v-if="currentModels.length">
              <el-table-column type="index" label="#" width="40" />
              <el-table-column prop="model_number" label="型号" width="130" />
              <el-table-column label="内部型号 / IPN" min-width="240">
                <template #default="{row:m}">
                  <div v-if="!m._variants?.length" class="no-data">无</div>
                  <div v-else class="variant-tags">
                    <el-tag
                      v-for="v in m._variants"
                      :key="v.id"
                      size="small"
                      type="info"
                      style="margin:2px 4px 2px 0"
                    >
                      {{ v.internal_model }}<template v-if="v.ipn"> / {{ v.ipn }}</template>
                    </el-tag>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="应用" width="60" align="center">
                <template #default="{row:m}">{{ m._appCount ?? '-' }}</template>
              </el-table-column>
              <el-table-column label="排序" width="60" align="center">
                <template #default="{row:m}">{{ m.sort_order ?? 0 }}</template>
              </el-table-column>
              <el-table-column label="操作" width="300" fixed="right">
                <template #default="{ row: m }">
                  <el-button size="small" text @click="openVariantDialog(m)">变体</el-button>
                  <el-button size="small" text @click="openAppDialog(m)">应用</el-button>
                  <el-button size="small" text @click="handleEditModel(m, selectedCategory.id)">编辑</el-button>
                  <el-button size="small" text type="danger" @click="handleDeleteModel(m)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-else description="该类别下暂无探头型号" :image-size="80">
              <el-button size="small" type="primary" :icon="Plus" @click="addModelToCat(selectedCategory.id)">新增型号</el-button>
            </el-empty>
          </template>
          <div v-else class="placeholder-content">
            <el-icon :size="48" color="#c0c4cc"><FolderOpened /></el-icon>
            <p>从左侧选择一个探头类别以查看型号</p>
          </div>
        </div>
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

    <!-- Application Assignment Dialog -->
    <el-dialog v-model="appDialogVisible" title="管理探头应用" width="500px">
      <div class="dialog-info">探头型号：<strong>{{ appTarget?.model_number }}</strong></div>
      <el-checkbox-group v-model="selectedAppIds" style="margin-top:12px">
        <el-checkbox v-for="a in allApps" :key="a.id" :label="a.id" :value="a.id">{{ a.name }}</el-checkbox>
      </el-checkbox-group>
      <template #footer>
        <el-button @click="appDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveApps" :loading="appSaving">保存</el-button>
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
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, FolderOpened } from '@element-plus/icons-vue'
import { getProbeCategories, createProbeCategory, updateProbeCategory, deleteProbeCategory, getProbeModels, createProbeModel, updateProbeModel, deleteProbeModel, getApplications, getProbeModelApps, setProbeModelApps, exportVariantsExcel, importVariantsExcel, exportModelVariantsExcel, importModelVariantsExcel, autoPopulateVariants } from '../api/data'
import api from '../api/index'

const loading = ref(false)
const categories = ref([])
const modelMap = ref({})
const selectedCategory = ref(null)

const catDialogVisible = ref(false); const editingCatId = ref(null)
const modelDialogVisible = ref(false); const editingModelId = ref(null); const saving = ref(false)
const catForm = reactive({ name: '', sort_order: 0 })
const modelForm = reactive({ category_id: null, model_number: '', sort_order: 0 })

const loadData = async () => {
  loading.value = true
  try {
    const [catRes, modelRes] = await Promise.all([
      getProbeCategories({ limit: 200 }),
      getProbeModels({ limit: 2000 })
    ])
    categories.value = catRes.items || []
    const models = modelRes.items || []

    const mm = {}; models.forEach(m => { if (!mm[m.category_id]) mm[m.category_id] = []; mm[m.category_id].push(m) })
    modelMap.value = mm

    // Load app counts and variants for current category's models
    const curModels = selectedCategory.value ? (mm[selectedCategory.value.id] || []) : []
    const appCounts = {};
    const varMap = {};
    await Promise.all(curModels.map(async m => {
      try { appCounts[m.id] = (await getProbeModelApps(m.id)).length } catch { appCounts[m.id] = 0 }
      try { varMap[m.id] = await api.get(`/probe-models/${m.id}/variants`) } catch { varMap[m.id] = [] }
    }))
    // Rebuild modelMap with enriched data
    const enriched = {}
    for (const cid of Object.keys(mm)) {
      enriched[cid] = mm[cid].map(m => ({
        ...m,
        _appCount: appCounts[m.id] || 0,
        _variants: varMap[m.id] || []
      }))
    }
    modelMap.value = enriched
  } catch { ElMessage.error('加载失败') } finally { loading.value = false }
}

const currentModels = computed(() => {
  if (!selectedCategory.value) return []
  return modelMap.value[selectedCategory.value.id] || []
})

const selectCategory = (cat) => {
  selectedCategory.value = cat
  loadData()
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

// App management
const allApps = ref([]); const appDialogVisible = ref(false); const appTarget = ref(null)
const selectedAppIds = ref([]); const appSaving = ref(false)

const openAppDialog = async (m) => {
  appTarget.value = m; selectedAppIds.value = []
  try { selectedAppIds.value = ((await getProbeModelApps(m.id)) || []).map(a => a.id) } catch { selectedAppIds.value = [] }
  appDialogVisible.value = true
}
const saveApps = async () => {
  appSaving.value = true
  try { await setProbeModelApps(appTarget.value.id, selectedAppIds.value); ElMessage.success('保存成功'); appDialogVisible.value = false; await loadData() }
  catch { ElMessage.error('保存失败') } finally { appSaving.value = false }
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

onMounted(async () => {
  allApps.value = ((await getApplications({ limit: 500 })).items || [])
  await loadData()
  if (categories.value.length) selectedCategory.value = categories.value[0]
})
</script>

<style scoped>
.page { padding: 0; height: calc(100vh - 120px); }

.panel-layout {
  display: flex;
  gap: 16px;
  height: 100%;
}

.panel {
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.panel-left {
  width: 280px;
  min-width: 240px;
  flex-shrink: 0;
}

.panel-right {
  flex: 1;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid #e4e7ed;
  background: #fafafa;
}

.panel-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}

.panel-title.placeholder {
  color: #c0c4cc;
  font-weight: 400;
}

.panel-header-actions {
  display: flex;
  gap: 8px;
}

.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

/* Category items */
.category-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
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
  padding-left: 9px;
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
  font-size: 14px;
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
  font-size: 14px;
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
</style>
