<template>
  <div class="models-page">
    <el-card shadow="never" class="models-card">
      <template #header>
        <div class="card-header">
          <span>产品型号管理</span>
          <div class="header-actions">
            <SubseriesEditor ref="subseriesEditorRef" button-label="管理子系列与组合" @saved="loadData" />
            <el-button type="primary" :icon="Plus" @click="handleCreate" :disabled="loading || !!loadError">新增型号</el-button>
          </div>
        </div>
      </template>

      <el-alert v-if="loadError" :title="loadError" type="error" :closable="false"><el-button link @click="loadData">重新加载</el-button></el-alert>
      <div class="model-workspace">
        <aside class="group-navigation" aria-label="型号分组">
          <div class="group-navigation-header"><span>型号分组</span><ModelGroupDisplaySettings :nodes="allGroupNodes" :model-value="hiddenGroupKeys" @update:model-value="applyGroupDisplay" /><el-tooltip content="在此统一维护分组，配置管理和白皮书共用"><el-icon class="group-info" tabindex="0" aria-label="分组说明"><InfoFilled /></el-icon></el-tooltip></div>
          <el-tree :indent="14" :data="groupNodes" node-key="key" default-expand-all highlight-current :current-node-key="selectedGroup" :expand-on-click-node="false" @node-click="selectGroup">
            <template #default="{ data }">
              <span class="group-node" :class="{ 'group-combination': data.children }">
                <el-icon class="group-node-icon"><component :is="data.children ? Collection : data.key === 'all' ? Grid : Folder" /></el-icon>
                <span class="group-node-label">{{ data.label }}</span>
                <small class="group-count">{{ data.ids.length }}</small>
              </span>
            </template>
          </el-tree>
        </aside>
        <section class="model-results">
          <div class="model-toolbar"><div class="model-result-heading"><span>{{ currentGroup?.label || '全部型号' }}</span><span class="model-result-count">{{ total }} 个型号</span></div><div class="model-toolbar-actions"><el-input v-model="search" clearable placeholder="搜索型号 / 描述" style="width: 240px" aria-label="搜索型号" /><TableColumnSettings :model-value="columnLayout" :defaults="MODEL_TABLE_COLUMNS" @update:model-value="applyColumnLayout" /></div></div>
      <el-table :key="columnStructureKey" @dragover.prevent="rowDragOver" @drop.prevent="dropModelRow" :row-class-name="({ row }) => String(row.id) === dragOverId ? 'model-drop-target' : ''" @header-dragend="resizeColumn" ref="tableRef" :data="tableData" border stripe v-loading="loading" row-key="id" max-height="600" size="small">
        <el-table-column width="36" fixed="left" class-name="model-drag-column">
          <template #default="{ row }"><span class="model-row-drag" tabindex="0" :data-model-id="row.id" :draggable="!loading" :aria-label="'拖动排序型号 ' + row.name" title="拖动调整个人显示顺序，自动保存；也可按 Alt + ↑ / ↓" @keydown.alt.up.prevent="moveModelByKeyboard(row.id, -1)" @keydown.alt.down.prevent="moveModelByKeyboard(row.id, 1)" @dragstart="startModelDrag($event, row.id)" @dragend="clearModelDrag">⠿</span></template>
        </el-table-column>
        <el-table-column v-for="column in displayedColumns" :key="column.key" :prop="column.key" :label="column.label" :width="column.width" :min-width="30" :fixed="column.fixed ? 'left' : false" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="column.key === 'series_id'">{{ seriesList.find(series => series.id === row.series_id)?.name || row.series_id }}</span>
            <div v-else-if="column.key === 'sub_series'" class="registration-mappings"><el-tag v-for="name in row.sub_series" :key="name" size="small" effect="plain">{{ name }}</el-tag><span v-if="!row.sub_series?.length" class="unmapped-registration">未分组</span></div>
            <template v-else-if="column.key === 'registration_packages'">
              <div v-if="row.registration_packages?.length" class="registration-mappings">
                <el-tag v-for="mapping in row.registration_packages" :key="mapping.registration_package_id" :type="mapping.is_enabled ? 'success' : 'info'" effect="plain">{{ mapping.registration_number }} · {{ mapping.registration_model_name }} · {{ mapping.is_enabled ? '已启用' : '未启用' }}</el-tag>
              </div>
              <span v-else class="unmapped-registration">未映射注册证</span>
            </template>
            <el-tag v-else-if="column.key === 'status'" :type="getStatusType(row.status)">{{ row.status || '生产中' }}</el-tag>
            <span v-else-if="column.key === 'created_at'">{{ formatTime(row.created_at) }}</span>
            <span v-else>{{ row[column.key] }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right" class-name="model-actions">
          <template #default="{ row }">
            <el-button size="small" @click="handleEdit(row)">编辑</el-button>
            <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-wrapper" v-if="total > 0">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          @size-change="currentPage = 1"
        />
      </div>
        </section>
      </div>
    </el-card>

    <!-- 新增/编辑对话框 -->
    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑型号' : '新增型号'" width="500px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="所属系列">
          <el-select v-model="form.series_id" :disabled="!!editingId" placeholder="请选择所属系列">
            <el-option v-for="series in seriesList" :key="series.id" :label="series.name" :value="series.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="型号名称">
          <el-input v-model="form.name" placeholder="请输入型号名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" placeholder="可选" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.status" placeholder="选择状态">
            <el-option label="生产中" value="生产中" />
            <el-option label="研发中" value="研发中" />
            <el-option label="停产" value="停产" />
          </el-select>
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="form.sort_order" :min="0" :max="999" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSave" :loading="saving">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onActivated, onDeactivated, watch, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Collection, Grid, Folder, InfoFilled } from '@element-plus/icons-vue'
import { getSeriesList, getModels, getSubseries, createModel, updateModel, deleteModel } from '../api/data'
import { useRoute, useRouter } from 'vue-router'
import SubseriesEditor from '../components/SubseriesEditor.vue'
import TableColumnSettings from '../components/TableColumnSettings.vue'
import ModelGroupDisplaySettings from '../components/ModelGroupDisplaySettings.vue'
import { orderModelCatalog, moveModelToTarget, visibleManagementGroups, loadPersonalList, savePersonalList } from '../utils/modelPersonalLayout'
import { MODEL_TABLE_COLUMNS, loadColumnLayout, saveColumnLayout, normalizeColumnLayout } from '../utils/tableColumnLayout'
import { applySharedMemberships, buildManagementGroups, loadCompleteModelCatalog, createGroupEditorRequest } from '../utils/modelManagementGroups'
import { formatTime } from '../utils/modelHelpers'

const columnStorageKey = 'models-table-column-layout-v1'
const columnStorage = { getItem: key => localStorage.getItem(key), setItem: (key, value) => localStorage.setItem(key, value) }
const columnLayout = ref(loadColumnLayout(columnStorage, columnStorageKey, MODEL_TABLE_COLUMNS, message => ElMessage.warning(message)))
const displayedColumns = computed(() => columnLayout.value.filter(column => column.visible))
const columnStructureKey = computed(() => displayedColumns.value.map(column => `${column.key}:${column.fixed}`).join('|'))
const applyColumnLayout = columns => {
  columnLayout.value = normalizeColumnLayout(MODEL_TABLE_COLUMNS, columns)
  saveColumnLayout(columnStorage, columnStorageKey, columnLayout.value, message => ElMessage.warning(message))
}
const resizeColumn = (width, _oldWidth, column) => {
  if (!columnLayout.value.some(item => item.key === column.property)) return
  applyColumnLayout(columnLayout.value.map(item => item.key === column.property ? { ...item, width: Math.max(30, width) } : item))
}

const seriesList = ref([])
const catalog = ref([])
const sharedGroups = ref({})
const selectedGroup = ref('all')
const search = ref('')
const loadError = ref('')
const rowOrderKey = 'models-personal-row-order-v1'
const groupDisplayKey = 'models-personal-group-display-v1'
const savedRowOrder = ref(loadPersonalList(columnStorage, rowOrderKey, message => ElMessage.warning(message)))
const hiddenGroupKeys = ref(loadPersonalList(columnStorage, groupDisplayKey, message => ElMessage.warning(message)))
const allGroupNodes = computed(() => buildManagementGroups(catalog.value, sharedGroups.value))
const groupNodes = computed(() => visibleManagementGroups(allGroupNodes.value, hiddenGroupKeys.value))
const applyGroupDisplay = hidden => {
  hiddenGroupKeys.value = hidden
  savePersonalList(columnStorage, groupDisplayKey, hidden, message => ElMessage.warning(message))
  if (!currentGroup.value) selectedGroup.value = 'all'
}
const currentGroup = computed(() => groupNodes.value.flatMap(node => [node, ...(node.children || [])]).find(node => node.key === selectedGroup.value))
const filteredModels = computed(() => {
  const ids = new Set(currentGroup.value?.ids || [])
  const query = search.value.trim().toLocaleLowerCase()
  return catalog.value.filter(model => ids.has(String(model.id)) && (!query || [model.name, model.description, ...(model.sub_series || [])].some(value => String(value || '').toLocaleLowerCase().includes(query))))
})
const tableData = computed(() => filteredModels.value.slice((currentPage.value - 1) * pageSize.value, currentPage.value * pageSize.value))
const subseriesEditorRef = ref(null)
const route = useRoute(), router = useRouter()
let pageActive = true
const editorRequest = createGroupEditorRequest({
  isRequested: () => route.query.editSubseries === '1',
  isActive: () => pageActive && route.path === '/models',
  consume: () => {
    const query = { ...route.query }; delete query.editSubseries
    return router.replace({ path: route.path, query })
  },
  nextTick,
  open: () => subseriesEditorRef.value?.open()
})
const openRequestedEditor = () => editorRequest.run()
watch(() => route.query.editSubseries, openRequestedEditor)
watch([search, selectedGroup], () => { currentPage.value = 1 })
const selectGroup = node => { selectedGroup.value = node.key }
const loading = ref(false)
const total = computed(() => filteredModels.value.length)
const currentPage = ref(1)
const pageSize = ref(20)
const tableRef = ref(null)

// Personal ordering never rewrites the shared catalog's business sort_order.
const draggedModelId = ref(null), dragOverId = ref(null)
const modelIdAtEvent = event => event.target.closest('tr')?.querySelector('[data-model-id]')?.dataset.modelId
const startModelDrag = (event, id) => {
  draggedModelId.value = String(id)
  event.dataTransfer.effectAllowed = 'move'
  event.dataTransfer.setData('text/plain', String(id))
}
const clearModelDrag = () => { draggedModelId.value = null; dragOverId.value = null }
const rowDragOver = event => { if (draggedModelId.value) dragOverId.value = modelIdAtEvent(event) || null }
const moveModelByKeyboard = (id, direction) => {
  if (loading.value) return
  const index = filteredModels.value.findIndex(model => model.id === id)
  const target = filteredModels.value[index + direction]
  if (!target) return
  catalog.value = moveModelToTarget(catalog.value, id, target.id)
  savedRowOrder.value = catalog.value.map(model => String(model.id))
  savePersonalList(columnStorage, rowOrderKey, savedRowOrder.value, message => ElMessage.warning(message))
}
const dropModelRow = event => {
  const target = modelIdAtEvent(event)
  if (draggedModelId.value && target && !loading.value) {
    catalog.value = moveModelToTarget(catalog.value, draggedModelId.value, target)
    savedRowOrder.value = catalog.value.map(model => String(model.id))
    savePersonalList(columnStorage, rowOrderKey, savedRowOrder.value, message => ElMessage.warning(message))
  }
  clearModelDrag()
}

const dialogVisible = ref(false)
const editingId = ref(null)
const saving = ref(false)
const form = reactive({
  series_id: null,
  name: '',
  description: '',
  status: '生产中',
  sort_order: 0
})

const loadSeries = async () => {
  try {
    const res = await getSeriesList()
    seriesList.value = res.items || []
    await loadData()
  } catch (error) {
    console.error('加载系列失败:', error)
  }
}

let loadRequest = 0
const loadData = async () => {
  const request = ++loadRequest
  const isCurrent = () => request === loadRequest
  clearModelDrag()
  loading.value = true; loadError.value = ''; catalog.value = []; sharedGroups.value = {}
  try {
    const [models, groups] = await Promise.all([
      loadCompleteModelCatalog(params => getModels(null, params), isCurrent), getSubseries()
    ])
    if (!isCurrent() || !models) return
    sharedGroups.value = groups
    catalog.value = orderModelCatalog([...applySharedMemberships(new Map(models.map(model => [model.id, model])), groups.groups).values()], savedRowOrder.value)
    if (!currentGroup.value) selectedGroup.value = 'all'
    currentPage.value = Math.min(currentPage.value, Math.max(1, Math.ceil(total.value / pageSize.value)))
  } catch (error) {
    if (isCurrent()) loadError.value = error.response?.data?.detail || error.message || '加载失败，请重试'
  } finally { if (isCurrent()) loading.value = false }
}

const getStatusType = (status) => {
  const types = {
    '生产中': 'success',
    '研发中': 'warning',
    '停产': 'danger'
  }
  return types[status] || 'info'
}

const handleCreate = () => {
  editingId.value = null
  form.series_id = null
  form.name = ''
  form.description = ''
  form.status = '生产中'
  form.sort_order = 0
  dialogVisible.value = true
}

const handleEdit = (row) => {
  editingId.value = row.id
  form.series_id = row.series_id
  form.name = row.name
  form.description = row.description || ''
  form.status = row.status || '生产中'
  form.sort_order = row.sort_order || 0
  dialogVisible.value = true
}

const handleSave = async () => {
  if (!editingId.value && !form.series_id) { ElMessage.warning('请选择所属系列'); return }
  if (!form.name) {
    ElMessage.warning('请输入型号名称')
    return
  }

  saving.value = true
  try {
    if (editingId.value) {
      await updateModel(editingId.value, {
        name: form.name,
        description: form.description,
        status: form.status,
        sort_order: form.sort_order
      })
      ElMessage.success('更新成功')
    } else {
      await createModel({
        series_id: form.series_id,
        name: form.name,
        description: form.description,
        status: form.status,
        sort_order: form.sort_order
      })
      ElMessage.success('创建成功')
    }
    dialogVisible.value = false
    await loadData()
  } catch (error) {
    console.error('保存失败:', error)
    ElMessage.error(error.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

const handleDelete = async (row) => {
  try {
    await ElMessageBox.confirm(
      `确认删除型号 "${row.name}"（${seriesList.value.find(series => series.id === row.series_id)?.name || row.series_id}）？该操作将同时删除该型号的所有配置数据。`,
      '确认删除',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )

    await deleteModel(row.id)
    ElMessage.success('删除成功')
    await loadData()
  } catch (error) {
    if (error !== 'cancel') {
      console.error('删除失败:', error)
      ElMessage.error(error.response?.data?.detail || '删除失败')
    }
  }
}

let initialized = false
onMounted(async () => { await loadSeries(); initialized = true; openRequestedEditor() })
onActivated(() => { pageActive = true; if (initialized) { loadData(); openRequestedEditor() } })
onDeactivated(() => { clearModelDrag(); pageActive = false; editorRequest.invalidate(); ++loadRequest; loading.value = false })
</script>

<style scoped>
.models-card > :deep(.el-card__header) { padding: 12px 16px; }
.models-card > :deep(.el-card__body) { padding: 16px; }
.model-workspace { display: flex; gap: 16px; min-width: 0; align-items: flex-start; }
.group-navigation { width: 256px; flex-shrink: 0; border: 1px solid var(--el-border-color-light); border-radius: 4px; overflow: hidden; }
.group-navigation-header { display: flex; justify-content: space-between; align-items: center; padding: 10px 12px; background: var(--el-fill-color-light); border-bottom: 1px solid var(--el-border-color-lighter); font-size: 13px; font-weight: 600; color: var(--el-text-color-primary); }
.group-info { color: var(--el-text-color-placeholder); font-size: 14px; }
.group-navigation :deep(.el-tree) { padding: 6px; max-height: 590px; overflow: auto; font-size: 13px; }
.group-node { display: flex; gap: 7px; align-items: center; width: 100%; min-width: 0; padding: 3px 8px 3px 0; }
.group-node-label { white-space: normal; overflow-wrap: anywhere; line-height: 20px; flex: 1; }
.group-node-icon { color: var(--el-text-color-placeholder); flex-shrink: 0; font-size: 14px; }
.group-combination .group-node-label { font-weight: 500; }
.group-count { flex-shrink: 0; min-width: 22px; padding: 0 5px; border-radius: 3px; text-align: center; font-size: 11px; line-height: 18px; color: var(--el-text-color-secondary); background: var(--el-fill-color-light); font-variant-numeric: tabular-nums; }
.group-navigation :deep(.el-tree-node__content) { height: auto; min-height: 34px; margin: 2px 0; border-radius: 3px; border-left: 2px solid transparent; }
.group-navigation :deep(.el-tree-node.is-current > .el-tree-node__content) { background: var(--el-color-primary-light-9); border-left-color: var(--el-color-primary); color: var(--el-color-primary); }
.group-navigation :deep(.el-tree-node.is-current > .el-tree-node__content) .group-node-icon,
.group-navigation :deep(.el-tree-node.is-current > .el-tree-node__content) .group-count { color: var(--el-color-primary); }
.group-navigation :deep(.el-tree-node.is-current > .el-tree-node__content) .group-count { background: var(--el-color-primary-light-8); }
.model-results { min-width: 0; flex: 1; }
.model-toolbar { display: flex; justify-content: space-between; gap: 12px; min-height: 32px; margin-bottom: 12px; align-items: center; font-size: 13px; }
.model-toolbar-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.model-result-heading { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; color: var(--el-text-color-primary); font-weight: 500; }
.model-result-count { color: var(--el-text-color-secondary); font-size: 12px; font-weight: 400; }
@media (max-width: 900px) { .model-workspace { flex-direction: column; } .group-navigation { width: 100%; } .group-navigation :deep(.el-tree) { max-height: 200px; } .card-header { flex-wrap: wrap; gap: 12px; } .header-actions { flex-wrap: wrap; } .model-results { width: 100%; } }
.model-row-drag { display: inline-block; cursor: grab; color: var(--el-text-color-placeholder); padding: 2px 4px; }
.model-results :deep(.model-drop-target td) { box-shadow: inset 0 2px 0 var(--el-color-primary); }
.models-page {
  padding: 0;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-actions {
  display: flex;
  gap: 12px;
}

.model-results :deep(.model-actions .cell) { display: flex; align-items: center; gap: 5px; flex-wrap: nowrap; }
.model-results :deep(.model-actions .el-button + .el-button) { margin-left: 0; }
.registration-mappings { display: flex; flex-wrap: wrap; gap: 6px; }
.unmapped-registration { color: #94a3b8; font-size: 12px; }

.pagination-wrapper {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
</style>
