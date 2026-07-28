<template>
  <div class="versions-page">
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>版本历史</span>
          <el-select v-model="selectedSeries" placeholder="选择产品系列" @change="loadVersions" style="width: 200px">
            <el-option v-for="s in seriesList" :key="s.id" :label="s.name" :value="s.id" />
          </el-select>
        </div>
      </template>

      <el-timeline v-if="versions.length > 0">
        <el-timeline-item
          v-for="version in versions"
          :key="version.id"
          :timestamp="formatTime(version.published_at)"
          placement="top"
          type="primary"
        >
          <el-card shadow="hover" class="version-card">
            <div class="version-header">
              <div class="version-info">
                <el-tag type="primary" size="large">{{ version.version_number }}</el-tag>
                <span v-if="version.version_name" class="version-name">{{ version.version_name }}</span>
                <span class="version-stats">共 {{ version.row_count }} 项配置</span>
              </div>
              <div class="version-actions">
                <el-button size="small" @click="viewVersion(version)">查看详情</el-button>
                <el-button size="small" @click="openCompareDialog(version)">版本对比</el-button>
                <el-button size="small" type="warning" @click="handleRollback(version)">回滚</el-button>
                <el-button size="small" type="primary" link @click="handleEditVersion(version)">编辑</el-button>
              </div>
            </div>

            <p v-if="version.description" class="version-desc">{{ version.description }}</p>

            <div class="version-footer">
              <span class="publisher">发布人：{{ version.published_by || '系统' }}</span>
            </div>
          </el-card>
        </el-timeline-item>
      </el-timeline>

      <el-empty v-else description="暂无版本记录" />
    </el-card>

    <!-- 版本详情对话框 -->
    <el-dialog v-model="detailDialogVisible" :title="`版本详情 - ${currentVersion?.version_number}`" width="80%">
      <div v-if="versionDetail" class="version-detail">
        <el-table :data="versionDetail.items" border stripe max-height="500">
          <el-table-column prop="rd_name" label="研发名称" width="250" show-overflow-tooltip />
          <el-table-column prop="ipn" label="IPN号" width="120" />
          <el-table-column prop="v_code" label="V代码" width="100" />
          <el-table-column label="配置值">
            <el-table-column
              v-for="model in versionDetail.models"
              :key="model.id"
              :label="model.name"
            >
              <template #default="{ row }">
                <div v-if="row.values[model.id]" class="config-values">
                  <div class="config-item">
                    <span class="label">最终：</span>
                    <span>{{ row.values[model.id].final_config || '-' }}</span>
                  </div>
                  <div class="config-item">
                    <span class="label">当前：</span>
                    <span>{{ row.values[model.id].current_config || '-' }}</span>
                  </div>
                  <div class="config-item">
                    <span class="label">选型：</span>
                    <span>{{ row.values[model.id].selection_config || '-' }}</span>
                  </div>
                  <div class="config-item">
                    <span class="label">研发：</span>
                    <span>{{ row.values[model.id].rd_status || '-' }}</span>
                  </div>
                </div>
              </template>
            </el-table-column>
          </el-table-column>
        </el-table>
      </div>
    </el-dialog>

    <!-- 版本对比对话框 -->
    <el-dialog v-model="compareDialogVisible" title="版本对比" width="90%" top="5vh">
      <div class="compare-select" v-if="versions.length > 1">
        <el-select v-model="compareVersion1" placeholder="选择版本1" style="width: 200px">
          <el-option v-for="v in versions" :key="v.id" :label="v.version_number" :value="v.id" />
        </el-select>
        <span class="compare-vs">VS</span>
        <el-select v-model="compareVersion2" placeholder="选择版本2" style="width: 200px">
          <el-option v-for="v in versions" :key="v.id" :label="v.version_number" :value="v.id" />
        </el-select>
        <el-select
          v-model="selectedModels"
          multiple
          collapse-tags
          collapse-tags-tooltip
          placeholder="选择机型（可选，默认全部）"
          style="width: 280px; margin-left: 16px;"
        >
          <el-option v-for="m in modelList" :key="m.id" :label="m.name" :value="m.id" />
        </el-select>
        <el-button type="primary" @click="executeCompare" :loading="compareLoading" style="margin-left: 16px;">对比</el-button>
      </div>

      <div v-if="compareResult" class="compare-result">
        <el-alert
          :title="`差异统计：新增 ${compareResult.summary.added} 项，修改 ${compareResult.summary.modified} 项，删除 ${compareResult.summary.deleted} 项`"
          type="info"
          show-icon
          :closable="false"
          style="margin-bottom: 16px"
        />

        <el-tabs v-model="activeTab">
          <el-tab-pane :label="`新增 (${compareResult.added.length})`" name="added">
            <el-table :data="compareResult.added" border stripe max-height="400">
              <el-table-column prop="rd_name" label="研发名称" width="300" />
              <el-table-column prop="ipn" label="IPN号" width="150" />
            </el-table>
          </el-tab-pane>

          <el-tab-pane :label="`修改 (${compareResult.modified.length})`" name="modified">
            <el-table :data="compareResult.modified" border stripe max-height="400">
              <el-table-column prop="rd_name" label="研发名称" width="250" />
              <el-table-column prop="ipn" label="IPN号" width="120" />
              <el-table-column prop="model_name" label="型号" width="150" />
              <el-table-column prop="field_name" label="字段" width="100">
                <template #default="{ row }">
                  {{ getFieldLabel(row.field_name) }}
                </template>
              </el-table-column>
              <el-table-column prop="old_value" label="原值" width="150">
                <template #default="{ row }">
                  <span class="old-value">{{ row.old_value || '-' }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="new_value" label="新值" width="150">
                <template #default="{ row }">
                  <span class="new-value">{{ row.new_value || '-' }}</span>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <el-tab-pane :label="`删除 (${compareResult.deleted.length})`" name="deleted">
            <el-table :data="compareResult.deleted" border stripe max-height="400">
              <el-table-column prop="rd_name" label="研发名称" width="300" />
              <el-table-column prop="ipn" label="IPN号" width="150" />
            </el-table>
          </el-tab-pane>
        </el-tabs>
      </div>

      <el-empty v-else-if="!compareLoading" description="请选择两个版本进行对比" />
    </el-dialog>

    <!-- 编辑版本对话框 -->
    <el-dialog v-model="editDialogVisible" title="编辑版本信息" width="500px">
      <el-form :model="editVersionForm" label-width="100px">
        <el-form-item label="版本号">
          <el-input v-model="editVersionForm.version_number" placeholder="版本号" />
        </el-form-item>
        <el-form-item label="版本名称">
          <el-input v-model="editVersionForm.version_name" placeholder="可选" />
        </el-form-item>
        <el-form-item label="版本说明">
          <el-input v-model="editVersionForm.description" type="textarea" :rows="3" placeholder="可选" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveVersionEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getSeriesList, getVersions, compareVersions, rollbackVersion, updateVersion, getModels } from '../api/data'
import { formatTime, getFieldLabel } from '../utils/modelHelpers'

// 路由
const router = useRouter()

// 数据
const seriesList = ref([])
const selectedSeries = ref(null)
const versions = ref([])
const modelList = ref([])  // 机型列表
const selectedModels = ref([])  // 选中的机型

// 详情对话框
const detailDialogVisible = ref(false)
const currentVersion = ref(null)
const versionDetail = ref(null)

// 对比对话框
const compareDialogVisible = ref(false)
const compareVersion1 = ref(null)
const compareVersion2 = ref(null)
const compareResult = ref(null)
const compareLoading = ref(false)
const activeTab = ref('modified')

// 编辑版本对话框
const editDialogVisible = ref(false)
const editVersionForm = ref({
  id: null,
  version_number: '',
  version_name: '',
  description: ''
})

// 加载产品系列
const loadSeries = async () => {
  try {
    const res = await getSeriesList()
    seriesList.value = res.items || []
    if (seriesList.value.length > 0) {
      selectedSeries.value = seriesList.value[0].id
      await loadVersions()
    }
  } catch (error) {
    console.error('加载产品系列失败:', error)
  }
}

// 加载版本列表
const loadVersions = async () => {
  if (!selectedSeries.value) return

  // 切换筛选时先重置数据，避免显示旧数据
  versions.value = []
  modelList.value = []

  try {
    const res = await getVersions(selectedSeries.value)
    versions.value = res.items || []

    // 加载机型列表
    const modelRes = await getModels(selectedSeries.value)
    modelList.value = modelRes.items || []
  } catch (error) {
    console.error('加载版本列表失败:', error)
    ElMessage.error('加载版本列表失败')
  }
}

// 查看版本详情
const viewVersion = async (version) => {
  currentVersion.value = version

  try {
    // 解析快照数据
    const snapshot = version.snapshot_data

    versionDetail.value = {
      models: snapshot.models || [],
      items: (snapshot.items || []).map(item => ({
        ...item,
        values: item.values || {}
      }))
    }

    detailDialogVisible.value = true
  } catch (error) {
    console.error('解析版本数据失败:', error)
    ElMessage.error('解析版本数据失败')
  }
}

// 打开对比对话框
const openCompareDialog = (version) => {
  const idx = versions.value.findIndex(v => v.id === version.id)

  compareVersion1.value = version.id
  compareVersion2.value = idx < versions.value.length - 1 ? versions.value[idx + 1].id : null

  compareResult.value = null
  activeTab.value = 'modified'
  selectedModels.value = []  // 重置机型选择
  compareDialogVisible.value = true
}

// 执行版本对比
const executeCompare = async () => {
  if (!compareVersion1.value || !compareVersion2.value) {
    ElMessage.warning('请选择两个版本进行对比')
    return
  }

  if (compareVersion1.value === compareVersion2.value) {
    ElMessage.warning('请选择不同的版本进行对比')
    return
  }

  compareLoading.value = true
  try {
    const res = await compareVersions({
      version_id_1: compareVersion1.value,
      version_id_2: compareVersion2.value,
      model_ids: selectedModels.value.length > 0 ? selectedModels.value : undefined
    })

    compareResult.value = res

    // 自动选择有数据的标签页
    if (res.modified.length > 0) {
      activeTab.value = 'modified'
    } else if (res.added.length > 0) {
      activeTab.value = 'added'
    } else if (res.deleted.length > 0) {
      activeTab.value = 'deleted'
    }
  } catch (error) {
    console.error('对比失败:', error)
    ElMessage.error('对比失败')
  } finally {
    compareLoading.value = false
  }
}

// 回滚版本
const handleRollback = async (version) => {
  try {
    await ElMessageBox.confirm(
      `确认回滚到版本 ${version.version_number}？将创建一个新版本，内容为该版本的快照。`,
      '确认回滚',
      {
        confirmButtonText: '确定回滚',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )

    const res = await rollbackVersion(version.id)
    ElMessage.success(`回滚成功，新版本: ${res.new_version.version_number}`)
    await loadVersions()

    ElMessageBox.confirm(
      '回滚后的数据已恢复，是否跳转到配置管理页面查看？',
      '回滚完成',
      {
        confirmButtonText: '跳转查看',
        cancelButtonText: '留在此页',
        type: 'success'
      }
    ).then(() => {
      router.push('/config')
    }).catch(() => {})
  } catch (error) {
    if (error !== 'cancel') {
      console.error('回滚失败:', error)
      ElMessage.error('回滚失败')
    }
  }
}

// 编辑版本信息
const handleEditVersion = (version) => {
  editVersionForm.value = {
    id: version.id,
    version_number: version.version_number,
    version_name: version.version_name || '',
    description: version.description || ''
  }
  editDialogVisible.value = true
}

// 保存版本编辑
const saveVersionEdit = async () => {
  try {
    await updateVersion(editVersionForm.value.id, {
      version_number: editVersionForm.value.version_number,
      version_name: editVersionForm.value.version_name,
      description: editVersionForm.value.description
    })
    ElMessage.success('保存成功')
    editDialogVisible.value = false
    await loadVersions()
  } catch (error) {
    console.error('保存失败:', error)
    ElMessage.error(error.response?.data?.detail || '保存失败')
  }
}

onMounted(() => {
  loadSeries()
})
</script>

<style scoped>
.versions-page {
  padding: 0;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.version-card {
  cursor: pointer;
  transition: all 0.3s;
}

.version-card:hover {
  transform: translateX(5px);
}

.version-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.version-info {
  display: flex;
  align-items: center;
  gap: 12px;
}

.version-name {
  font-size: 16px;
  font-weight: 500;
}

.version-stats {
  color: #909399;
  font-size: 13px;
}

.version-actions {
  display: flex;
  gap: 8px;
}

.version-desc {
  color: #606266;
  margin: 12px 0;
  padding-left: 12px;
  border-left: 3px solid #409EFF;
}

.version-footer {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #EBEEF5;
}

.publisher {
  color: #909399;
  font-size: 13px;
}

.version-detail {
  max-height: 70vh;
  overflow-y: auto;
}

.config-values {
  font-size: 12px;
}

.config-item {
  margin: 2px 0;
}

.config-item .label {
  color: #909399;
}

.compare-select {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 20px;
}

.compare-vs {
  font-size: 18px;
  font-weight: bold;
  color: #409EFF;
}

.compare-result {
  margin-top: 16px;
}

.old-value {
  color: #F56C6C;
  text-decoration: line-through;
}

.new-value {
  color: #67C23A;
  font-weight: 500;
}
</style>