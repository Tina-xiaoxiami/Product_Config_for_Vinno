<template>
  <div class="page">
    <!-- Draft bar -->
    <div v-if="editMode" class="draft-bar">
      <el-tag type="warning">编辑中</el-tag>
      <span><strong>{{ pendingCount }}</strong> 项待提交变更</span>
      <div class="draft-actions">
        <el-button size="small" @click="cancelEdit">撤销</el-button>
        <el-button size="small" type="primary" @click="submitChanges" :loading="submitting">提交并创建版本</el-button>
        <el-button size="small" type="danger" @click="discardChanges">废弃全部</el-button>
      </div>
    </div>

    <div class="card-header">
      <span>应用管理（按探头类别）</span>
      <div style="display:flex;gap:12px;align-items:center">
        <template v-if="!editMode">
          <el-button size="small" @click="showAllApps = true">全部应用列表</el-button>
          <el-button size="small" type="primary" @click="enterEditMode">编辑模式</el-button>
          <el-button size="small" @click="openVersions">版本历史</el-button>
          <el-button size="small" :icon="Plus" @click="handleCreateApp">新增应用</el-button>
        </template>
        <template v-else>
          <el-button size="small" @click="showAllApps = true">全部应用列表</el-button>
          <el-button size="small" :icon="Plus" @click="handleCreateApp">新增应用</el-button>
        </template>
      </div>
    </div>
    <div class="panel-layout">
      <!-- Left: Category Panel -->
      <div class="panel panel-left">
        <div class="panel-header">
          <span class="panel-title">探头类别</span>
          <span class="count-hint"><em>常规</em> <em>POC</em></span>
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
              <span class="category-count">
                <span class="count-regular">{{ categoryAppCounts[cat.id]?.regular || 0 }}</span>
                <span class="count-poc">{{ categoryAppCounts[cat.id]?.poc || 0 }}</span>
              </span>
            </div>
          </div>
          <el-empty v-if="!categories.length" description="暂无探头类别" :image-size="60" />
        </div>
      </div>

      <!-- Right: Apps Panel -->
      <div class="panel panel-right">
        <template v-if="selectedCategory">
          <div class="panel-header">
            <span class="panel-title">{{ selectedCategory.name }} — 应用</span>
          </div>
          <div class="panel-body" v-loading="loadingApps">
            <!-- Regular Apps -->
            <div class="app-group">
              <div class="app-group-header">
                <span>常规应用</span>
                <span class="app-count">{{ regularApps.length }} 项</span>
              </div>
              <div v-if="regularApps.length" class="app-list">
                <div v-for="app in regularApps" :key="app.id" class="app-tag">
                  <span>{{ app.name }}<em v-if="app.en_name" class="en-name">{{ app.en_name }}</em></span>
                  <el-button v-if="editMode" size="small" text type="danger" @click="stageRemove(app, 'regular')">移除</el-button>
                </div>
              </div>
              <el-empty v-else description="暂无常规应用" :image-size="40" />
            </div>

            <!-- POC Apps -->
            <div class="app-group">
              <div class="app-group-header">
                <span>POC 应用</span>
                <span class="app-count">{{ pocApps.length }} 项</span>
              </div>
              <div v-if="pocApps.length" class="app-list">
                <div v-for="app in pocApps" :key="app.id" class="app-tag poc">
                  <span>{{ app.name }}<em v-if="app.en_name" class="en-name">{{ app.en_name }}</em></span>
                  <el-button v-if="editMode" size="small" text type="danger" @click="stageRemove(app, 'poc')">移除</el-button>
                </div>
              </div>
              <el-empty v-else description="暂无 POC 应用" :image-size="40" />
            </div>

            <!-- Quick Add -->
            <div class="add-section">
              <div class="add-section-title">{{ editMode ? '暂存添加（需提交后生效）' : '添加应用到本类别' }}</div>
              <div class="add-section-row">
                <el-select v-model="addAppId" placeholder="选择应用" filterable style="width:200px" size="small">
                  <el-option v-for="a in availableApps" :key="a.id" :label="a.name" :value="a.id" />
                </el-select>
                <el-radio-group v-model="addAppType" size="small" style="margin:0 8px">
                  <el-radio value="regular">常规</el-radio>
                  <el-radio value="poc">POC</el-radio>
                </el-radio-group>
                <el-button size="small" type="primary" @click="stageAdd" :disabled="!addAppId">{{ editMode ? '暂存' : '添加' }}</el-button>
              </div>
              <!-- Pending changes for current category -->
              <div v-if="editMode && pendingForCurrentCat.length" class="pending-list">
                <div class="pending-title">待提交变更：</div>
                <div v-for="ch in pendingForCurrentCat" :key="ch.key" class="pending-item" :class="ch.action">
                  <span>{{ ch.action === 'add' ? '+' : '-' }} {{ ch.appName }}（{{ ch.probeType === 'regular' ? '常规' : 'POC' }}）</span>
                  <el-button size="small" text @click="undoPending(ch.key)">撤销</el-button>
                </div>
              </div>
            </div>
          </div>
        </template>
        <div v-else class="empty-state">
          <el-empty description="请从左侧选择一个探头类别" :image-size="80" />
        </div>
      </div>
    </div>

    <!-- Create Application Dialog -->
    <el-dialog v-model="dialogVisible" title="新增应用定义" width="450px">
      <el-form :model="form" label-width="70px">
        <el-form-item label="中文名"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="英文名"><el-input v-model="form.en_name" placeholder="如 Abdomen" /></el-form-item>
        <el-form-item label="排序"><el-input-number v-model="form.sort_order" :min="0" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveApp" :loading="saving">保存</el-button>
      </template>
    </el-dialog>

    <!-- All Apps Dialog -->
    <el-dialog v-model="showAllApps" title="全部应用列表" width="600px">
      <div style="margin-bottom:12px">
        <el-radio-group v-model="typeFilter" size="small">
          <el-radio value="">全部 ({{ allAppsFlat.length }})</el-radio>
          <el-radio value="regular">仅常规</el-radio>
          <el-radio value="poc">仅 POC</el-radio>
          <el-radio value="both">跨类型</el-radio>
        </el-radio-group>
      </div>
      <el-table :data="filteredAllApps" border stripe size="small" max-height="400">
        <el-table-column prop="name" label="中文名" min-width="120" />
        <el-table-column prop="en_name" label="英文名" min-width="140">
          <template #default="{ row }"><span v-if="row.en_name" style="color:#606266">{{ row.en_name }}</span><span v-else style="color:#c0c4cc">-</span></template>
        </el-table-column>
        <el-table-column label="类型" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.probe_types?.includes('regular')" size="small" style="margin-right:4px">常规</el-tag>
            <el-tag v-if="row.probe_types?.includes('poc')" size="small" type="warning">POC</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="usage_count" label="探头使用" width="80" align="center">
          <template #default="{ row }">
            <span v-if="row.usage_count">{{ row.usage_count }}</span>
            <span v-else style="color:#c0c4cc">-</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80" align="center">
          <template #default="{ row }">
            <el-button size="small" text type="danger" @click="deleteApp(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <!-- Versions Dialog -->
    <el-dialog v-model="showVersions" title="应用版本历史" width="500px">
      <el-table :data="versions" border stripe size="small" max-height="400">
        <el-table-column prop="version_number" label="版本号" width="180" />
        <el-table-column prop="created_at" label="时间" width="200" />
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button size="small" type="warning" @click="rollback(row)">回滚</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!versions.length" description="暂无版本" />
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { getProbeCategories, getApplications, createApplication, deleteApplication } from '../api/data'
import api from '../api/index'

const loading = ref(false)
const categories = ref([])
const selectedCategory = ref(null)

// Category apps
const loadingApps = ref(false)
const categoryApps = ref({ regular: [], poc: [] })
const categoryAppCounts = ref({})

// Add app
const addAppId = ref(null)
const addAppType = ref('regular')
const availableApps = ref([])

// Create app
const dialogVisible = ref(false)
const saving = ref(false)
const form = reactive({ name: '', en_name: '', sort_order: 0 })

// All apps dialog
const showAllApps = ref(false)
const allAppsFlat = ref([])
const typeFilter = ref('')

// Edit mode & draft management
const editMode = ref(false)
const submitting = ref(false)
// pendingChanges: { key -> { action: 'add'|'remove', catId, appId, appName, probeType } }
const pendingChanges = reactive({})

// Version management
const showVersions = ref(false)
const versions = ref([])

// Computed: apps for current category (merged with pending changes in edit mode)
const regularApps = computed(() => {
  const base = categoryApps.value.regular || []
  if (!editMode.value) return base
  const catId = selectedCategory.value?.id
  if (!catId) return base
  // Apply pending changes
  const removed = new Set()
  const added = []
  for (const ch of Object.values(pendingChanges)) {
    if (ch.catId !== catId || ch.probeType !== 'regular') continue
    if (ch.action === 'remove') removed.add(ch.appId)
    if (ch.action === 'add') added.push({ id: ch.appId, name: ch.appName, en_name: '', _pending: true })
  }
  return [...base.filter(a => !removed.has(a.id)), ...added]
})

const pocApps = computed(() => {
  const base = categoryApps.value.poc || []
  if (!editMode.value) return base
  const catId = selectedCategory.value?.id
  if (!catId) return base
  const removed = new Set()
  const added = []
  for (const ch of Object.values(pendingChanges)) {
    if (ch.catId !== catId || ch.probeType !== 'poc') continue
    if (ch.action === 'remove') removed.add(ch.appId)
    if (ch.action === 'add') added.push({ id: ch.appId, name: ch.appName, en_name: '', _pending: true })
  }
  return [...base.filter(a => !removed.has(a.id)), ...added]
})

// Pending changes for current category (for display)
const pendingForCurrentCat = computed(() => {
  const catId = selectedCategory.value?.id
  if (!catId) return []
  return Object.entries(pendingChanges)
    .filter(([, ch]) => ch.catId === catId)
    .map(([key, ch]) => ({ key, ...ch }))
})

const pendingCount = computed(() => Object.keys(pendingChanges).length)

const filteredAllApps = computed(() => {
  const f = typeFilter.value
  if (!f) return allAppsFlat.value
  return allAppsFlat.value.filter(row => {
    const types = row.probe_types || []
    if (f === 'regular') return types.includes('regular') && !types.includes('poc')
    if (f === 'poc') return types.includes('poc') && !types.includes('regular')
    if (f === 'both') return types.includes('regular') && types.includes('poc')
    return true
  })
})

const loadCategories = async () => {
  loading.value = true
  try {
    const res = await getProbeCategories({ limit: 200 })
    categories.value = res.items || []
    if (!selectedCategory.value && categories.value.length) {
      selectCategory(categories.value[0])
    }
  } catch { ElMessage.error('加载探头类别失败') } finally { loading.value = false }
}

const selectCategory = async (cat) => {
  selectedCategory.value = cat
  await loadCategoryApps(cat.id)
  await loadAvailableApps(cat.id)
}

const loadCategoryApps = async (catId) => {
  loadingApps.value = true
  try {
    categoryApps.value = await api.get(`/probe-categories/${catId}/apps`)
  } catch { categoryApps.value = { regular: [], poc: [] } } finally { loadingApps.value = false }
}

const loadAvailableApps = async (catId) => {
  try {
    availableApps.value = await api.get(`/probe-categories/${catId}/available-apps`)
  } catch { availableApps.value = [] }
}

// ========= Edit mode =========
const enterEditMode = () => {
  editMode.value = true
  Object.keys(pendingChanges).forEach(k => delete pendingChanges[k])
}

const cancelEdit = () => {
  editMode.value = false
  Object.keys(pendingChanges).forEach(k => delete pendingChanges[k])
}

const discardChanges = () => {
  Object.keys(pendingChanges).forEach(k => delete pendingChanges[k])
  editMode.value = false
  ElMessage.success('已废弃所有变更')
}

const stageAdd = () => {
  if (!addAppId.value || !selectedCategory.value) return
  const app = availableApps.value.find(a => a.id === addAppId.value)
  if (!app) return
  const key = `${selectedCategory.value.id}_${app.id}_${addAppType.value}`
  // If there's a pending remove for this same combo, just remove the pending
  if (pendingChanges[key]?.action === 'remove') {
    delete pendingChanges[key]
  } else {
    pendingChanges[key] = { action: 'add', catId: selectedCategory.value.id, appId: app.id, appName: app.name, probeType: addAppType.value }
  }
  addAppId.value = null
}

const stageRemove = (app, probeType) => {
  if (!selectedCategory.value) return
  const key = `${selectedCategory.value.id}_${app.id}_${probeType}`
  // If there's a pending add for this same combo, just remove the pending
  if (pendingChanges[key]?.action === 'add') {
    delete pendingChanges[key]
  } else {
    pendingChanges[key] = { action: 'remove', catId: selectedCategory.value.id, appId: app.id, appName: app.name, probeType }
  }
}

const undoPending = (key) => {
  delete pendingChanges[key]
}

const submitChanges = async () => {
  const entries = Object.entries(pendingChanges)
  if (!entries.length) return ElMessage.warning('没有待提交的变更')
  submitting.value = true
  let ok = 0; let fail = 0
  try {
    for (const [, ch] of entries) {
      try {
        if (ch.action === 'add') {
          await api.post(`/probe-categories/${ch.catId}/apps`, {
            application_id: ch.appId,
            probe_type: ch.probeType
          })
        } else {
          await api.delete(`/probe-categories/${ch.catId}/apps/${ch.appId}?probe_type=${ch.probeType}`)
        }
        ok++
      } catch { fail++ }
    }
    if (ok > 0) {
      ElMessage.success(`提交完成：${ok} 项成功${fail ? `，${fail} 项失败` : ''}`)
      // Create an application version snapshot
      try {
        await api.post('/applications/version', { version_number: `v${Date.now()}`, description: '应用关联变更' })
      } catch {}
    } else {
      ElMessage.error('全部提交失败')
    }
    Object.keys(pendingChanges).forEach(k => delete pendingChanges[k])
    editMode.value = false
    if (selectedCategory.value) {
      await loadCategoryApps(selectedCategory.value.id)
      await loadAvailableApps(selectedCategory.value.id)
    }
    await updateCounts()
    await loadAllApps()
  } catch { ElMessage.error('提交失败') } finally { submitting.value = false }
}

// ========= CRUD for app definitions =========
const handleCreateApp = () => {
  form.name = ''; form.en_name = ''; form.sort_order = 0; dialogVisible.value = true
}

const saveApp = async () => {
  if (!form.name) return ElMessage.warning('请输入名称')
  saving.value = true
  try {
    await createApplication({ ...form })
    ElMessage.success('保存成功')
    dialogVisible.value = false
    if (selectedCategory.value) {
      await loadAvailableApps(selectedCategory.value.id)
    }
    await updateCounts()
    await loadAllApps()
  } catch { ElMessage.error('保存失败') } finally { saving.value = false }
}

const updateCounts = async () => {
  for (const cat of categories.value) {
    try {
      const apps = await api.get(`/probe-categories/${cat.id}/apps`)
      categoryAppCounts.value[cat.id] = {
        regular: apps.regular?.length || 0,
        poc: apps.poc?.length || 0,
        total: (apps.regular?.length || 0) + (apps.poc?.length || 0)
      }
    } catch { categoryAppCounts.value[cat.id] = { regular: 0, poc: 0, total: 0 } }
  }
}

const deleteApp = async (row) => {
  try {
    await ElMessageBox.confirm(`确认删除应用"${row.name}"？此操作不可恢复。`, '确认删除', { type: 'warning' })
    await deleteApplication(row.id)
    ElMessage.success('删除成功')
    await loadAllApps()
    if (selectedCategory.value) {
      await loadCategoryApps(selectedCategory.value.id)
      await loadAvailableApps(selectedCategory.value.id)
    }
    await updateCounts()
  } catch (e) { if (e !== 'cancel') ElMessage.error('删除失败') }
}

const loadAllApps = async () => {
  try {
    allAppsFlat.value = (await getApplications()).items || []
  } catch { allAppsFlat.value = [] }
}

// Version management
const loadVersions = async () => {
  try { versions.value = await api.get('/applications/versions') || [] } catch { versions.value = [] }
}
const openVersions = async () => {
  await loadVersions()
  showVersions.value = true
}
const rollback = async (row) => {
  try {
    await api.post(`/applications/rollback/${row.id}`)
    ElMessage.success('回滚成功')
    await loadVersions()
  } catch { ElMessage.error('回滚失败') }
}

onMounted(async () => {
  await loadCategories()
  await updateCounts()
  await loadAllApps()
})
</script>

<style scoped>
.page { padding: 0; height: calc(100vh - 120px); display: flex; flex-direction: column; }

/* Draft bar */
.draft-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 16px;
  background: #fef3c7;
  border: 1px solid #fde68a;
  border-radius: 6px;
  margin-bottom: 12px;
  font-size: 13px;
}
.draft-actions {
  margin-left: auto;
  display: flex;
  gap: 8px;
}

.card-header { display: flex; justify-content: space-between; align-items: center; flex-shrink: 0; padding: 0 0 12px; gap: 12px; }

.panel-layout {
  display: flex;
  gap: 16px;
  flex: 1;
  min-height: 0;
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
.category-item:hover { background: #f5f7fa }
.category-item.active {
  background: #ecf5ff;
  border-left: 3px solid #409eff;
  padding-left: 9px;
}

.category-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: 100%;
}

.category-name {
  font-size: 13px;
  font-weight: 500;
  color: #303133;
}

.count-hint { font-size: 11px; color: #909399; display: flex; gap: 6px }
.count-hint em { font-style: normal; color: #409eff }
.count-hint em:last-child { color: #e6a23c }
.category-count { font-size: 11px; color: #909399; display: flex; gap: 6px }
.count-regular { color: #409eff; font-weight: 500 }
.count-poc { color: #e6a23c; font-weight: 500 }

/* App groups */
.app-group { padding: 12px 16px; border-bottom: 1px solid #f0f0f0 }
.app-group-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; font-weight: 500; font-size: 13px }
.app-count { font-weight: 400; font-size: 12px; color: #909399 }
.app-list { display: flex; flex-wrap: wrap; gap: 6px }
.app-tag { display: inline-flex; align-items: center; gap: 4px; padding: 4px 8px; background: #ecf5ff; border: 1px solid #d9ecff; border-radius: 4px; font-size: 12px }
.app-tag.poc { background: #fdf6ec; border-color: #faecd8 }
.en-name { font-style: normal; font-size: 11px; color: #909399; margin-left: 4px }

/* Quick add */
.add-section { padding: 12px 16px }
.add-section-title { font-size: 12px; color: #909399; margin-bottom: 8px }
.add-section-row { display: flex; align-items: center; gap: 4px }

/* Pending changes list */
.pending-list {
  margin-top: 8px;
  padding: 8px;
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 6px;
}
.pending-title { font-size: 12px; color: #92400e; margin-bottom: 4px; font-weight: 500 }
.pending-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 8px;
  font-size: 12px;
  border-radius: 4px;
  margin-bottom: 2px;
}
.pending-item.add { color: #059669 }
.pending-item.remove { color: #dc2626 }

.empty-state { display: flex; align-items: center; justify-content: center; flex: 1; }
</style>
