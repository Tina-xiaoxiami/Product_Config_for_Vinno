<template>
  <div class="models-page">
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>产品型号管理</span>
          <div class="header-actions">
            <el-select v-model="selectedSeries" :disabled="reordering" placeholder="选择产品系列" @change="changeSeries" style="width: 200px">
              <el-option v-for="s in seriesList" :key="s.id" :label="s.name" :value="s.id" />
            </el-select>
            <SubseriesEditor ref="subseriesEditorRef" button-label="管理子系列与组合" @saved="loadData" />
            <el-button type="primary" :icon="Plus" @click="handleCreate" :disabled="!selectedSeries">新增型号</el-button>
          </div>
        </div>
      </template>

      <div class="group-help">在此统一维护子系列与组合，配置管理和白皮书引用同一份分组关系。</div>
      <el-alert v-if="loadError" :title="loadError" type="error" :closable="false"><el-button link @click="loadData">重新加载</el-button></el-alert>
      <div class="model-workspace">
        <aside class="group-navigation" aria-label="型号分组">
          <el-tree :data="groupNodes" node-key="key" default-expand-all highlight-current :current-node-key="selectedGroup" :expand-on-click-node="false" @node-click="selectGroup">
            <template #default="{ data }"><span class="group-node"><span>{{ data.label }}</span><small>{{ data.ids.length }}</small></span></template>
          </el-tree>
        </aside>
        <section class="model-results">
          <div class="model-toolbar"><span>{{ currentGroup?.label || '全部型号' }} · {{ total }} 个型号</span><el-input v-model="search" clearable placeholder="搜索型号 / 描述" style="width: 240px" aria-label="搜索型号" /></div>
      <el-table ref="tableRef" :data="tableData" border stripe v-loading="loading" row-key="id" max-height="600" size="small">
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="name" label="型号名称" min-width="200" fixed="left" show-overflow-tooltip />
        <el-table-column label="所属子系列" min-width="180">
          <template #default="{ row }"><div class="registration-mappings"><el-tag v-for="name in row.sub_series" :key="name" size="small" effect="plain">{{ name }}</el-tag><span v-if="!row.sub_series?.length" class="unmapped-registration">未分组</span></div></template>
        </el-table-column>
        <el-table-column label="对应注册证" min-width="280">
          <template #default="{ row }">
            <div v-if="row.registration_packages?.length" class="registration-mappings">
              <el-tag
                v-for="mapping in row.registration_packages"
                :key="mapping.registration_package_id"
                :type="mapping.is_enabled ? 'success' : 'info'"
                effect="plain"
              >
                {{ mapping.registration_number }} · {{ mapping.registration_model_name }} ·
                {{ mapping.is_enabled ? '已启用' : '未启用' }}
              </el-tag>
            </div>
            <span v-else class="unmapped-registration">未映射注册证</span>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="描述" width="200" show-overflow-tooltip />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)">{{ row.status || '生产中' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="sort_order" label="排序" width="80" />
        <el-table-column prop="created_at" label="创建时间" width="180">
          <template #default="{ row }">
            {{ formatTime(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="210" fixed="right" class-name="model-actions">
          <template #default="{ row }">
            <el-button size="small" @click="moveRow(row, -1)" :disabled="!canReorder || catalog.findIndex(item => item.id === row.id) === 0" aria-label="上移型号" :icon="ArrowUp" />
            <el-button size="small" @click="moveRow(row, 1)" :disabled="!canReorder || catalog.findIndex(item => item.id === row.id) === catalog.length - 1" aria-label="下移型号" :icon="ArrowDown" />
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
import { Plus, ArrowUp, ArrowDown } from '@element-plus/icons-vue'
import { getSeriesList, getModels, getSubseries, createModel, updateModel, deleteModel } from '../api/data'
import { useRoute, useRouter } from 'vue-router'
import SubseriesEditor from '../components/SubseriesEditor.vue'
import { applySharedMemberships, buildManagementGroups, loadCompleteModelCatalog, createGroupEditorRequest } from '../utils/modelManagementGroups'
import { formatTime } from '../utils/modelHelpers'

const seriesList = ref([])
const selectedSeries = ref(null)
const catalog = ref([])
const sharedGroups = ref({})
const selectedGroup = ref('all')
const search = ref('')
const loadError = ref('')
const groupNodes = computed(() => buildManagementGroups(catalog.value, sharedGroups.value))
const currentGroup = computed(() => groupNodes.value.flatMap(node => [node, ...(node.children || [])]).find(node => node.key === selectedGroup.value))
const filteredModels = computed(() => {
  const ids = new Set(currentGroup.value?.ids || [])
  const query = search.value.trim().toLocaleLowerCase()
  return catalog.value.filter(model => ids.has(String(model.id)) && (!query || [model.name, model.description, ...(model.sub_series || [])].some(value => String(value || '').toLocaleLowerCase().includes(query))))
})
const tableData = computed(() => filteredModels.value.slice((currentPage.value - 1) * pageSize.value, currentPage.value * pageSize.value))
const reordering = ref(false)
const canReorder = computed(() => selectedGroup.value === 'all' && !search.value.trim() && !loading.value && !reordering.value && !loadError.value)
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
const changeSeries = () => { selectedGroup.value = 'all'; currentPage.value = 1; loadData() }
const loading = ref(false)
const total = computed(() => filteredModels.value.length)
const currentPage = ref(1)
const pageSize = ref(20)
const tableRef = ref(null)

// 排序移动
const moveRow = async (row, direction) => {
  if (!canReorder.value) return
  const ordered = [...catalog.value]
  const idx = ordered.findIndex(m => m.id === row.id), next = idx + direction
  if (next < 0 || next >= ordered.length) return
  ;[ordered[idx], ordered[next]] = [ordered[next], ordered[idx]]
  reordering.value = true
  try {
    // Use the complete series order; never renumber only a filtered page.
    for (const [index, model] of ordered.entries()) if (model.sort_order !== index) await updateModel(model.id, { sort_order: index })
  } catch { ElMessage.error('排序保存失败，已重新加载实际顺序') }
  finally { reordering.value = false; await loadData() }
}

const dialogVisible = ref(false)
const editingId = ref(null)
const saving = ref(false)
const form = reactive({
  name: '',
  description: '',
  status: '生产中',
  sort_order: 0
})

const loadSeries = async () => {
  try {
    const res = await getSeriesList()
    seriesList.value = res.items || []
    if (seriesList.value.length > 0) {
      selectedSeries.value = seriesList.value[0].id
      await loadData()
    }
  } catch (error) {
    console.error('加载系列失败:', error)
  }
}

let loadRequest = 0
const loadData = async () => {
  if (!selectedSeries.value) return
  const request = ++loadRequest, seriesId = selectedSeries.value
  const isCurrent = () => request === loadRequest && seriesId === selectedSeries.value
  loading.value = true; loadError.value = ''; catalog.value = []; sharedGroups.value = {}
  try {
    const [models, groups] = await Promise.all([
      loadCompleteModelCatalog(params => getModels(seriesId, params), isCurrent), getSubseries()
    ])
    if (!isCurrent() || !models) return
    sharedGroups.value = groups
    catalog.value = [...applySharedMemberships(new Map(models.map(model => [model.id, model])), groups.groups).values()]
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
  form.name = ''
  form.description = ''
  form.status = '生产中'
  form.sort_order = 0
  dialogVisible.value = true
}

const handleEdit = (row) => {
  editingId.value = row.id
  form.name = row.name
  form.description = row.description || ''
  form.status = row.status || '生产中'
  form.sort_order = row.sort_order || 0
  dialogVisible.value = true
}

const handleSave = async () => {
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
        series_id: selectedSeries.value,
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
      `确认删除型号 "${row.name}"？该操作将同时删除该型号的所有配置数据。`,
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
onDeactivated(() => { pageActive = false; editorRequest.invalidate(); ++loadRequest; loading.value = false })
</script>

<style scoped>
.model-workspace { display: flex; gap: 16px; min-width: 0; }
.group-navigation { width: 240px; flex-shrink: 0; max-height: 640px; overflow: auto; border-right: 1px solid #ebeef5; padding-right: 10px; }
.group-node { display: flex; gap: 8px; align-items: center; width: 100%; min-width: 0; }
.group-node span { white-space: normal; overflow-wrap: anywhere; }
.group-node small { color: #909399; margin-left: auto; padding-right: 6px; }
.group-navigation :deep(.el-tree-node__content) { height: auto; min-height: 32px; padding-top: 3px; padding-bottom: 3px; }
.model-results { min-width: 0; flex: 1; }
.model-toolbar { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 10px; align-items: center; font-size: 13px; }
.group-help { font-size: 12px; color: #909399; margin-bottom: 12px; }
@media (max-width: 900px) { .model-workspace { flex-direction: column; } .group-navigation { width: auto; max-height: 220px; border-right: 0; border-bottom: 1px solid #ebeef5; } .header-actions { flex-wrap: wrap; } }
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
