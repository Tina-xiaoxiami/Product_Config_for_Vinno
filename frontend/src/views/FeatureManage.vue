<template>
  <div class="page">
    <!-- 顶部操作栏 -->
    <div class="page-header">
      <div class="header-left">
        <h3 class="page-title">功能管理</h3>
        <span class="page-subtitle">{{ tableData.length }} 个功能组 / {{ totalFeatures }} 项功能</span>
      </div>
      <div class="header-actions">
        <el-button size="small" @click="handleCreateGroup">新增功能组</el-button>
        <el-button size="small" type="primary" :icon="Plus" @click="handleCreateFeature">新增功能</el-button>
      </div>
    </div>

    <!-- 功能组卡片列表 -->
    <div class="group-list" v-loading="loading">
      <div v-for="group in tableData" :key="group.id" class="group-card">
        <div class="group-header">
          <div class="group-info">
            <span class="group-name">{{ group.name }}</span>
            <span class="group-feature-count">{{ (group.features || []).length }} 项功能</span>
            <span v-if="group.sort_order > 0" class="group-order">排序 {{ group.sort_order }}</span>
          </div>
          <div class="group-actions">
            <el-button size="small" text @click="handleCreateFeatureToGroup(group.id)">+ 添加功能</el-button>
            <el-button size="small" text @click="handleEditGroup(group)">编辑组</el-button>
            <el-button size="small" text type="danger" @click="handleDeleteGroup(group)">删除组</el-button>
          </div>
        </div>
        <div class="group-body">
          <div v-if="(group.features || []).length" class="feature-list">
            <div v-for="feature in group.features" :key="feature.id" class="feature-item">
              <div class="feature-main">
                <span class="feature-name">{{ feature.name }}</span>
                <span v-if="feature.ipn" class="feature-ipn">IPN: {{ feature.ipn }}</span>
              </div>
              <div class="feature-meta">
                <span v-if="feature.sort_order > 0" class="feature-order">{{ feature.sort_order }}</span>
              </div>
              <div class="feature-actions">
                <el-button size="small" text @click="handleEditFeature(feature, group.id)">编辑</el-button>
                <el-button size="small" text type="danger" @click="handleDeleteFeature(feature)">删除</el-button>
              </div>
            </div>
          </div>
          <div v-else class="group-empty">
            <el-empty description="暂无功能" :image-size="32" />
          </div>
        </div>
      </div>
    </div>

    <!-- 功能组对话框 -->
    <el-dialog v-model="showGroupForm" :title="editingGroupId ? '编辑功能组' : '新增功能组'" width="420px" destroy-on-close>
      <el-form :model="groupForm" label-width="60px">
        <el-form-item label="名称"><el-input v-model="groupForm.name" placeholder="如 基础功能" /></el-form-item>
        <el-form-item label="排序"><el-input-number v-model="groupForm.sort_order" :min="0" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showGroupForm = false">取消</el-button>
        <el-button type="primary" @click="saveGroup" :loading="saving">保存</el-button>
      </template>
    </el-dialog>

    <!-- 功能对话框 -->
    <el-dialog v-model="showFeatureForm" :title="editingFeatureId ? '编辑功能' : '新增功能'" width="420px" destroy-on-close>
      <el-form :model="featureForm" label-width="60px">
        <el-form-item label="功能组">
          <el-select v-model="featureForm.group_id" style="width:100%" placeholder="选择功能组">
            <el-option v-for="g in tableData" :key="g.id" :label="g.name" :value="g.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="名称"><el-input v-model="featureForm.name" placeholder="如 TView" /></el-form-item>
        <el-form-item label="IPN"><el-input v-model="featureForm.ipn" placeholder="关联配置管理中的 IPN" /></el-form-item>
        <el-form-item label="排序"><el-input-number v-model="featureForm.sort_order" :min="0" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showFeatureForm = false">取消</el-button>
        <el-button type="primary" @click="saveFeature" :loading="saving">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { getFeatureGroups, createFeatureGroup, updateFeatureGroup, deleteFeatureGroup, getFeatures, createFeature, updateFeature, deleteFeature } from '../api/data'

const tableData = ref([])
const loading = ref(false)
const showGroupForm = ref(false)
const editingGroupId = ref(null)
const showFeatureForm = ref(false)
const editingFeatureId = ref(null)
const saving = ref(false)
const groupForm = reactive({ name: '', sort_order: 0 })
const featureForm = reactive({ group_id: null, name: '', ipn: '', sort_order: 0 })

const totalFeatures = computed(() => {
  return tableData.value.reduce((sum, g) => sum + (g.features || []).length, 0)
})

const loadData = async () => {
  loading.value = true
  try {
    const groups = (await getFeatureGroups()).items || []
    const features = (await getFeatures({ limit: 500 })).items || []
    const featMap = {}
    features.forEach(f => {
      const gid = f.group_id
      featMap[gid] = featMap[gid] || []
      featMap[gid].push(f)
    })
    tableData.value = groups.map(g => ({ ...g, features: featMap[g.id] || [] }))
  } catch { ElMessage.error('加载失败') } finally { loading.value = false }
}

// Groups
const handleCreateGroup = () => {
  editingGroupId.value = null
  groupForm.name = ''
  groupForm.sort_order = 0
  showGroupForm.value = true
}
const handleEditGroup = (row) => {
  editingGroupId.value = row.id
  groupForm.name = row.name
  groupForm.sort_order = row.sort_order
  showGroupForm.value = true
}
const saveGroup = async () => {
  if (!groupForm.name) return ElMessage.warning('请输入名称')
  saving.value = true
  try {
    if (editingGroupId.value) {
      await updateFeatureGroup(editingGroupId.value, groupForm)
    } else {
      await createFeatureGroup(groupForm)
    }
    ElMessage.success('保存成功')
    showGroupForm.value = false
    await loadData()
  } catch { ElMessage.error('保存失败') } finally { saving.value = false }
}
const handleDeleteGroup = async (row) => {
  try {
    await ElMessageBox.confirm(`确认删除功能组"${row.name}"？<p style="color:#e6a23c;font-size:12px;margin:4px 0 0">将同时删除组内所有功能。</p>`, '确认删除', { type: 'warning', dangerouslyUseHTMLString: true })
    await deleteFeatureGroup(row.id)
    ElMessage.success('删除成功')
    await loadData()
  } catch (e) { if (e !== 'cancel') ElMessage.error('删除失败') }
}

// Features
const handleCreateFeature = () => {
  editingFeatureId.value = null
  featureForm.group_id = tableData.value[0]?.id || null
  featureForm.name = ''
  featureForm.ipn = ''
  featureForm.sort_order = 0
  showFeatureForm.value = true
}
const handleCreateFeatureToGroup = (groupId) => {
  editingFeatureId.value = null
  featureForm.group_id = groupId
  featureForm.name = ''
  featureForm.ipn = ''
  featureForm.sort_order = 0
  showFeatureForm.value = true
}
const handleEditFeature = (row, groupId) => {
  editingFeatureId.value = row.id
  featureForm.group_id = groupId
  featureForm.name = row.name
  featureForm.ipn = row.ipn || ''
  featureForm.sort_order = row.sort_order
  showFeatureForm.value = true
}
const saveFeature = async () => {
  if (!featureForm.group_id || !featureForm.name) return ElMessage.warning('功能组和名称不能为空')
  saving.value = true
  try {
    if (editingFeatureId.value) {
      await updateFeature(editingFeatureId.value, featureForm)
    } else {
      await createFeature(featureForm)
    }
    ElMessage.success('保存成功')
    showFeatureForm.value = false
    await loadData()
  } catch { ElMessage.error('保存失败') } finally { saving.value = false }
}
const handleDeleteFeature = async (row) => {
  try {
    await ElMessageBox.confirm(`确认删除功能"${row.name}"？`, '确认删除', { type: 'warning' })
    await deleteFeature(row.id)
    ElMessage.success('删除成功')
    await loadData()
  } catch (e) { if (e !== 'cancel') ElMessage.error('删除失败') }
}

onMounted(() => loadData())
</script>

<style scoped>
.page {
  padding: 0;
  max-width: 960px;
}

/* Header */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.header-left {
  display: flex;
  align-items: baseline;
  gap: 12px;
}
.page-title {
  font-size: 16px;
  font-weight: 600;
  margin: 0;
  color: #303133;
}
.page-subtitle {
  font-size: 12px;
  color: #909399;
}
.header-actions {
  display: flex;
  gap: 8px;
}

/* Group Cards */
.group-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.group-card {
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  overflow: hidden;
  transition: box-shadow 0.2s;
  background: #fff;
}
.group-card:hover {
  box-shadow: 0 2px 12px rgba(0,0,0,0.06);
}
.group-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: linear-gradient(135deg, #f0f5ff 0%, #fafcff 100%);
  border-bottom: 1px solid #e4e7ed;
}
.group-info {
  display: flex;
  align-items: center;
  gap: 12px;
}
.group-name {
  font-weight: 600;
  font-size: 14px;
  color: #303133;
}
.group-feature-count {
  font-size: 12px;
  color: #909399;
  background: #f0f2f5;
  padding: 1px 8px;
  border-radius: 10px;
}
.group-order {
  font-size: 11px;
  color: #c0c4cc;
}
.group-actions {
  display: flex;
  gap: 2px;
}

/* Feature List */
.group-body {
  padding: 0;
}
.feature-list {
  display: flex;
  flex-direction: column;
}
.feature-item {
  display: flex;
  align-items: center;
  padding: 10px 16px;
  border-bottom: 1px solid #f0f2f5;
  transition: background 0.15s;
}
.feature-item:last-child {
  border-bottom: none;
}
.feature-item:hover {
  background: #fafafa;
}
.feature-main {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.feature-name {
  font-size: 13px;
  color: #303133;
  font-weight: 500;
}
.feature-ipn {
  font-size: 11px;
  color: #909399;
  background: #f5f7fa;
  padding: 1px 6px;
  border-radius: 3px;
  font-family: 'SF Mono', monospace;
}
.feature-meta {
  margin: 0 12px;
}
.feature-order {
  font-size: 11px;
  color: #c0c4cc;
}
.feature-actions {
  display: flex;
  gap: 2px;
  flex-shrink: 0;
}
.group-empty {
  padding: 16px 0;
}
</style>
