<template>
  <div class="versions-page">
    <el-card shadow="never" class="history-card">
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
          hide-timestamp
          type="primary"
        >
          <el-card shadow="hover" class="version-card">
            <div class="version-header">
              <div class="version-info">
                <el-tag type="primary" size="small">{{ version.version_number }}</el-tag>
                <span v-if="version.version_name" class="version-name">{{ version.version_name }}</span>
                <span class="version-time">{{ formatTime(version.published_at) }}</span>
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
import { getSeriesList, getVersions, rollbackVersion, updateVersion } from '../api/data'
import { formatTime } from '../utils/modelHelpers'

// 路由
const router = useRouter()

// 数据
const seriesList = ref([])
const selectedSeries = ref(null)
const versions = ref([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)

// 详情对话框
const detailDialogVisible = ref(false)
const currentVersion = ref(null)
const versionDetail = ref(null)

let versionLoadRequest = 0

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
  total.value = 0

  try {
    const res = await getVersions(selectedSeries.value, {
      skip: (currentPage.value - 1) * pageSize.value,
      limit: pageSize.value
    })
    if (request !== versionLoadRequest || selectedSeries.value !== seriesId) return
    versions.value = res.items || []
    total.value = res.total || 0
  } catch (error) {
    if (request !== versionLoadRequest || selectedSeries.value !== seriesId) return
    versions.value = []
    total.value = 0
    console.error('加载版本列表失败:', error)
    ElMessage.error('加载版本列表失败')
  }
}

const handleSeriesChange = () => {
  currentPage.value = 1
  return loadVersions()
}

const handlePageSizeChange = () => {
  currentPage.value = 1
  loadVersions()
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

// 历史记录保留入口，进入独立对比页并带上当前系列与版本。
const openCompareDialog = version => router.push({
  name: 'VersionCompare', query: { series: String(selectedSeries.value), version: String(version.id) }
})

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

.series-tabs { min-width: 0; margin-top: 10px; }
.series-tabs :deep(.el-tabs__header) { margin-bottom: 0; }
.series-tabs :deep(.el-tabs__content) { display: none; }

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.history-card { width: 100%; max-width: 1120px; box-sizing: border-box; }
.history-card > :deep(.el-card__header) { padding: 12px 16px 8px; }
.history-card > :deep(.el-card__body) { padding: 14px 16px; }
.history-card :deep(.el-timeline) { padding-left: 8px; }
.history-card :deep(.el-timeline-item) { padding-bottom: 12px; }
.history-card :deep(.el-timeline-item__wrapper) { padding-left: 22px; top: -3px; }
.version-card :deep(.el-card__body) { padding: 10px 12px; }

.version-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px 16px;
  flex-wrap: wrap;
}

.version-info {
  display: flex;
  align-items: center;
  gap: 8px 12px;
  flex-wrap: wrap;
  min-width: 0;
}

.version-name {
  font-size: 14px;
  overflow-wrap: anywhere;
  font-weight: 500;
}

.version-time, .version-stats {
  color: #909399;
  font-size: 13px;
}

.version-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.version-actions .el-button + .el-button { margin-left: 0; }

.version-desc {
  color: #606266;
  margin: 6px 0 0;
  line-height: 1.5;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  padding-left: 8px;
  border-left: 3px solid #409EFF;
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

</style>
