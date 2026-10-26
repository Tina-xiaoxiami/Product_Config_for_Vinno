<template>
  <div class="versions-page">
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>版本历史</span>
        </div>
        <el-tabs v-model="selectedSeries" class="series-tabs" aria-label="产品系列" @tab-change="handleSeriesChange">
          <el-tab-pane v-for="series in seriesList" :key="series.id" :label="series.name" :name="series.id" />
        </el-tabs>
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

      <div class="pagination-wrapper" v-if="total > 0">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          @size-change="handlePageSizeChange"
          @current-change="loadVersions"
        />
      </div>
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
      <el-tabs v-model="selectedSeries" class="series-tabs compare-series-tabs" aria-label="对比产品系列" @tab-change="handleCompareSeriesChange">
        <el-tab-pane v-for="series in seriesList" :key="series.id" :label="series.name" :name="series.id" />
      </el-tabs>
      <VersionComparison v-if="compareDialogVisible" :key="selectedSeries"
        v-model:version1="compareVersion1" v-model:version2="compareVersion2"
        :versions="versionOptions" :options-loading="versionOptionsLoading" :result="compareResult" :loading="compareLoading"
        @compare="executeCompare" />
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
import { ref, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import VersionComparison from '../components/VersionComparison.vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getSeriesList, getVersions, compareVersions, rollbackVersion, updateVersion, getModels } from '../api/data'
import { formatTime, getFieldLabel } from '../utils/modelHelpers'

// 路由
const router = useRouter()

// 数据
const seriesList = ref([])
const selectedSeries = ref(null)
const versions = ref([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
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
const versionOptions = ref([])
const versionOptionsLoading = ref(false)
const activeTab = ref('modified')
const VERSION_OPTION_PAGE_SIZE = 100
let versionLoadRequest = 0
let versionOptionLoadRequest = 0
let compareRequest = 0

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
  const request = ++versionLoadRequest
  const seriesId = selectedSeries.value

  // 切换筛选时先重置数据，避免显示旧数据
  versions.value = []
  modelList.value = []
  total.value = 0

  try {
    const res = await getVersions(selectedSeries.value, {
      skip: (currentPage.value - 1) * pageSize.value,
      limit: pageSize.value
    })
    if (request !== versionLoadRequest || selectedSeries.value !== seriesId) return
    versions.value = res.items || []
    total.value = res.total || 0
    versionOptions.value = []

    // 加载机型列表
    const modelRes = await getModels(seriesId)
    if (request !== versionLoadRequest || selectedSeries.value !== seriesId) return
    modelList.value = modelRes.items || []
  } catch (error) {
    if (request !== versionLoadRequest || selectedSeries.value !== seriesId) return
    versions.value = []
    modelList.value = []
    total.value = 0
    console.error('加载版本列表失败:', error)
    ElMessage.error('加载版本列表失败')
  }
}

const handleSeriesChange = () => {
  compareRequest++
  compareLoading.value = false
  compareResult.value = null
  currentPage.value = 1
  versionOptions.value = []
  versionOptionLoadRequest++
  return loadVersions()
}

const handleCompareSeriesChange = async () => {
  compareVersion1.value = null
  compareVersion2.value = null
  selectedModels.value = []
  const loadingHistory = handleSeriesChange()
  const request = compareRequest
  const seriesId = selectedSeries.value
  const isCurrent = () => request === compareRequest && selectedSeries.value === seriesId && compareDialogVisible.value
  try {
    await loadingHistory
    if (!isCurrent()) return
    const options = await loadAllVersionOptions(seriesId)
    if (!isCurrent()) return
    compareVersion1.value = options[0]?.id ?? null
    compareVersion2.value = options[1]?.id ?? null
  } catch (error) {
    if (isCurrent()) ElMessage.error('加载该系列的版本失败，请重新切换系列重试')
  }
}

const handlePageSizeChange = () => {
  currentPage.value = 1
  loadVersions()
}

const loadAllVersionOptions = async (seriesId) => {
  const request = ++versionOptionLoadRequest
  let skip = 0
  let total = Number.MAX_SAFE_INTEGER
  const items = []
  versionOptionsLoading.value = true
  try {
    while (skip < total) {
      const res = await getVersions(seriesId, { skip, limit: VERSION_OPTION_PAGE_SIZE })
      if (request !== versionOptionLoadRequest || selectedSeries.value !== seriesId) return []
      const pageItems = res.items || []
      items.push(...pageItems)
      total = res.total || 0
      if (pageItems.length === 0) break
      skip += pageItems.length
    }
    versionOptions.value = items
    return items
  } finally {
    if (request === versionOptionLoadRequest) versionOptionsLoading.value = false
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
const openCompareDialog = async (version) => {
  const seriesId = selectedSeries.value
  compareLoading.value = false
  compareVersion1.value = version.id
  compareVersion2.value = null
  compareResult.value = null
  activeTab.value = 'modified'
  selectedModels.value = []  // 重置机型选择
  versionOptions.value = [...versions.value]
  compareDialogVisible.value = true
  const request = ++compareRequest

  try {
    const options = await loadAllVersionOptions(seriesId)
    if (request !== compareRequest || selectedSeries.value !== seriesId) return
    const idx = options.findIndex(v => v.id === version.id)
    compareVersion2.value = idx >= 0 && idx < options.length - 1 ? options[idx + 1].id : null
  } catch (error) {
    if (request !== compareRequest || selectedSeries.value !== seriesId) return
    console.error('加载完整版本列表失败:', error)
    ElMessage.error('加载完整版本列表失败')
  }
}

// 执行版本对比
const executeCompare = async () => {
  compareResult.value = null
  if (!compareVersion1.value || !compareVersion2.value) {
    ElMessage.warning('请选择两个版本进行对比')
    return
  }

  if (compareVersion1.value === compareVersion2.value) {
    ElMessage.warning('请选择不同的版本进行对比')
    return
  }

  const request = ++compareRequest
  const seriesId = selectedSeries.value
  const version1 = compareVersion1.value
  const version2 = compareVersion2.value
  const modelIds = [...selectedModels.value]
  const isCurrent = () => (
    request === compareRequest &&
    compareDialogVisible.value &&
    selectedSeries.value === seriesId &&
    compareVersion1.value === version1 &&
    compareVersion2.value === version2 &&
    modelIds.length === selectedModels.value.length &&
    modelIds.every((id, index) => id === selectedModels.value[index])
  )

  compareLoading.value = true
  try {
    const res = await compareVersions({
      version_id_1: version1,
      version_id_2: version2,
      model_ids: modelIds.length > 0 ? modelIds : undefined
    })

    if (!isCurrent()) return
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
    if (!isCurrent()) return
    console.error('对比失败:', error)
    ElMessage.error('对比失败')
  } finally {
    if (request === compareRequest) compareLoading.value = false
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

// 版本对比条件生命周期
watch([compareVersion1, compareVersion2, selectedModels, compareDialogVisible], () => {
  compareRequest++
  compareLoading.value = false
  compareResult.value = null
}, { deep: true, flush: 'sync' })
// 版本对比条件生命周期结束

onMounted(() => {
  loadSeries()
})
</script>

<style scoped>
.versions-page {
  padding: 0;
}

.series-tabs { min-width: 0; margin-top: 10px; }
.series-tabs :deep(.el-tabs__header) { margin-bottom: 0; }
.series-tabs :deep(.el-tabs__content) { display: none; }

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

.pagination-wrapper {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
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
