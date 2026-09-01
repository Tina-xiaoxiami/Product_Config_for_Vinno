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
                <div class="feature-names">
                  <span class="feature-name">{{ feature.primary_cn_name || feature.name }}</span>
                  <span v-if="feature.primary_en_name" class="feature-en-name">{{ feature.primary_en_name }}</span>
                </div>
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
    <el-dialog v-model="showFeatureForm" :title="editingFeatureId ? '编辑功能主数据' : '新增功能主数据'" width="680px" destroy-on-close>
      <el-form :model="featureForm" label-width="100px">
        <el-form-item label="功能组">
          <el-select v-model="featureForm.group_id" style="width:100%" placeholder="选择功能组">
            <el-option v-for="g in tableData" :key="g.id" :label="g.name" :value="g.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="中文主名称">
          <el-input v-model="featureForm.primary_cn_name" placeholder="以配置项中文描述为准" />
        </el-form-item>
        <el-form-item label="英文主名称">
          <el-input v-model="featureForm.primary_en_name" placeholder="以配置项英文描述为准" />
        </el-form-item>
        <el-form-item label="中文曾用名">
          <el-input
            v-model="featureForm.alias_cn_text"
            type="textarea"
            :rows="2"
            placeholder="每行一个中文曾用名"
          />
        </el-form-item>
        <el-form-item label="英文曾用名">
          <el-input
            v-model="featureForm.alias_en_text"
            type="textarea"
            :rows="2"
            placeholder="每行一个英文曾用名"
          />
        </el-form-item>
        <el-form-item label="IPN关系">
          <div class="ipn-editor">
            <div v-for="(entry, index) in featureForm.ipns" :key="index" class="ipn-editor-row">
              <el-input v-model="entry.ipn" placeholder="配置项IPN" />
              <el-select v-model="entry.relation_type" aria-label="IPN关系类型">
                <el-option label="主IPN" value="primary" />
                <el-option label="相关功能" value="related" />
                <el-option label="版本IPN" value="version_variant" />
              </el-select>
              <el-button type="danger" text @click="removeIpn(index)">移除</el-button>
            </div>
            <el-button size="small" @click="addIpn">+ 添加IPN</el-button>
          </div>
        </el-form-item>
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
import {
  getFeatureGroups,
  createFeatureGroup,
  updateFeatureGroup,
  deleteFeatureGroup,
  getFeatures,
  createFeature,
  updateFeature,
  deleteFeature,
  getFeatureMasterData,
  updateFeatureMasterData
} from '../api/data'

const tableData = ref([])
const loading = ref(false)
const showGroupForm = ref(false)
const editingGroupId = ref(null)
const showFeatureForm = ref(false)
const editingFeatureId = ref(null)
const saving = ref(false)
const groupForm = reactive({ name: '', sort_order: 0 })
const featureForm = reactive({
  group_id: null,
  primary_cn_name: '',
  primary_en_name: '',
  alias_cn_text: '',
  alias_en_text: '',
  ipns: [],
  sort_order: 0
})

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
const resetFeatureForm = (groupId = null) => {
  featureForm.group_id = groupId || tableData.value[0]?.id || null
  featureForm.primary_cn_name = ''
  featureForm.primary_en_name = ''
  featureForm.alias_cn_text = ''
  featureForm.alias_en_text = ''
  featureForm.ipns = []
  featureForm.sort_order = 0
}
const parseAliases = (value) => value
  .split(/\r?\n/)
  .map(name => name.trim())
  .filter(Boolean)
const masterPayload = () => ({
  primary_cn_name: featureForm.primary_cn_name,
  primary_en_name: featureForm.primary_en_name,
  alias_cn_names: parseAliases(featureForm.alias_cn_text),
  alias_en_names: parseAliases(featureForm.alias_en_text),
  ipns: featureForm.ipns
    .map(entry => ({ ipn: entry.ipn.trim(), relation_type: entry.relation_type }))
    .filter(entry => entry.ipn)
})
const addIpn = () => featureForm.ipns.push({ ipn: '', relation_type: 'related' })
const removeIpn = (index) => featureForm.ipns.splice(index, 1)

const handleCreateFeature = () => {
  editingFeatureId.value = null
  resetFeatureForm()
  showFeatureForm.value = true
}
const handleCreateFeatureToGroup = (groupId) => {
  editingFeatureId.value = null
  resetFeatureForm(groupId)
  showFeatureForm.value = true
}
const handleEditFeature = async (row, groupId) => {
  editingFeatureId.value = row.id
  resetFeatureForm(groupId)
  featureForm.sort_order = row.sort_order
  try {
    const master = await getFeatureMasterData(row.id)
    featureForm.primary_cn_name = master.primary_cn_name || ''
    featureForm.primary_en_name = master.primary_en_name || ''
    featureForm.alias_cn_text = (master.alias_cn_names || []).join('\n')
    featureForm.alias_en_text = (master.alias_en_names || []).join('\n')
    featureForm.ipns = (master.ipns || []).map(entry => ({
      ipn: entry.ipn,
      relation_type: entry.relation_type
    }))
    showFeatureForm.value = true
  } catch {
    ElMessage.error('功能主数据加载失败')
  }
}
const saveFeature = async () => {
  if (!featureForm.group_id || !featureForm.primary_cn_name || !featureForm.primary_en_name) {
    return ElMessage.warning('功能组、中英文主名称不能为空')
  }
  saving.value = true
  try {
    const payload = masterPayload()
    if (editingFeatureId.value) {
      const primaryIpn = payload.ipns.find(entry => entry.relation_type === 'primary')?.ipn || ''
      await updateFeature(editingFeatureId.value, {
        group_id: featureForm.group_id,
        name: featureForm.primary_cn_name,
        ipn: primaryIpn,
        sort_order: featureForm.sort_order
      })
      await updateFeatureMasterData(editingFeatureId.value, payload)
    } else {
      const primaryIpn = payload.ipns.find(entry => entry.relation_type === 'primary')?.ipn || ''
      const created = await createFeature({
        group_id: featureForm.group_id,
        name: featureForm.primary_cn_name,
        ipn: primaryIpn,
        sort_order: featureForm.sort_order
      })
      await updateFeatureMasterData(created.id, payload)
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
.feature-names { display: flex; flex-direction: column; gap: 2px; }
.feature-name {
  font-size: 13px;
  color: #303133;
  font-weight: 500;
}
.feature-en-name { color: #909399; font-size: 11px; }
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
.ipn-editor { width: 100%; display: flex; flex-direction: column; gap: 8px; }
.ipn-editor-row { display: grid; grid-template-columns: 1fr 130px auto; gap: 8px; }
</style>
