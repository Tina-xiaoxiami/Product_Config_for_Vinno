<template>
  <div class="compare-page">
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>配置对比</span>
        </div>
      </template>

      <!-- 选择区域 -->
      <div class="select-area">
        <div class="select-row">
          <div class="select-item">
            <label>产品系列：</label>
            <el-select v-model="selectedSeries" placeholder="选择产品系列" @change="loadModels" style="width: 200px">
              <el-option v-for="s in seriesList" :key="s.id" :label="s.name" :value="s.id" />
            </el-select>
          </div>

          <div class="select-item">
            <label>对比型号：</label>
            <el-select
              v-model="selectedModels"
              multiple
              collapse-tags
              collapse-tags-tooltip
              placeholder="选择要对比的型号（至少2个）"
              style="width: 500px"
            >
              <el-option v-for="m in modelList" :key="m.id" :label="m.name" :value="m.id" />
            </el-select>
          </div>
        </div>

        <div class="select-row">
          <div class="select-item">
            <label>对比字段：</label>
            <el-checkbox-group v-model="compareFields">
              <el-checkbox label="final_config">最终配置</el-checkbox>
              <el-checkbox label="current_config">当前配置</el-checkbox>
              <el-checkbox label="selection_config">选型类别</el-checkbox>
              <el-checkbox label="rd_status">研发状态</el-checkbox>
            </el-checkbox-group>
          </div>

          <div class="select-item">
            <el-checkbox v-model="showOnlyDiff" border>仅显示差异项</el-checkbox>
          </div>

          <el-button type="primary" :icon="DataAnalysis" @click="handleCompare" :loading="loading">
            开始对比
          </el-button>
        </div>
      </div>

      <!-- 草稿状态栏 -->
      <transition name="el-zoom-in-top">
        <el-card v-if="draftStats.total > 0" class="draft-bar" shadow="never">
          <div class="draft-info">
            <el-icon><EditPen /></el-icon>
            <span>当前有 <strong>{{ draftStats.total }}</strong> 条草稿：</span>
            <el-tag v-if="draftStats.create > 0" type="success" size="small">
              新增 {{ draftStats.create }}
            </el-tag>
            <el-tag v-if="draftStats.update > 0" type="warning" size="small">
              修改 {{ draftStats.update }}
            </el-tag>
            <el-tag v-if="draftStats.delete > 0" type="danger" size="small">
              删除 {{ draftStats.delete }}
            </el-tag>
            <div class="draft-actions">
              <el-button type="primary" size="small" @click="handleSubmitDraft">提交发布</el-button>
              <el-button size="small" @click="handleDiscardDraft">废弃全部</el-button>
            </div>
          </div>
        </el-card>
      </transition>
    </el-card>

    <!-- 对比结果 -->
    <el-card v-if="compareResult" shadow="never" class="result-card">
      <template #header>
        <div class="result-header">
          <div class="result-summary">
            <el-statistic title="总配置项" :value="compareResult.total" />
            <el-statistic title="差异项" :value="compareResult.diff_count" :value-style="{ color: '#E6A23C' }" />
          </div>
          <div class="result-actions">
            <el-button :icon="Download" @click="handleExportResult">导出结果</el-button>
          </div>
        </div>
      </template>

      <el-table
        :data="filteredTableData"
        border
        stripe
        :max-height="500"
        @filter-change="handleFilterChange"
      >
        <el-table-column prop="rd_name" label="研发名称" width="280" fixed show-overflow-tooltip />
        <el-table-column prop="ipn" label="IPN号" width="120" show-overflow-tooltip />
        <el-table-column
          prop="field_name"
          label="对比字段"
          width="100"
          :filters="fieldFilters"
          :filter-method="filterField"
        >
          <template #default="{ row }">
            <el-tag size="small" :type="getFieldTagType(row.field_name)">
              {{ getFieldLabel(row.field_name) }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column
          v-for="modelId in selectedModels"
          :key="modelId"
          :label="getModelName(modelId)"
          min-width="120"
        >
          <template #default="{ row }">
            <div
              class="value-cell"
              :class="[
                getValueClass(row, modelId),
                { 'cell-changed': isFieldChanged(row.item_id, modelId, row.field_name) }
              ]"
              @click="startEdit(row, modelId)"
            >
              <template v-if="editingCell?.itemId === row.item_id && editingCell?.modelId === modelId && editingCell?.field === row.field_name">
                <el-select
                  ref="editSelectRef"
                  v-model="row.values[modelId]"
                  size="small"
                  placeholder="-"
                  clearable
                  filterable
                  allow-create
                  @change="finishEdit(row, modelId, row.values[modelId])"
                  @blur="editingCell = null"
                  style="width: 100%"
                >
                  <el-option v-for="v in getEnumOptions(row.field_name)" :key="v" :label="v" :value="v" />
                </el-select>
              </template>
              <template v-else>
                <span>{{ row.values[modelId] || '-' }}</span>
                <span v-if="isFieldChanged(row.item_id, modelId, row.field_name)" class="original-hint">
                  ({{ getOriginalValue(row.item_id, modelId, row.field_name) || '-' }})
                </span>
              </template>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="差异" width="80" fixed="right">
          <template #default="{ row }">
            <el-tag v-if="hasDiff(row)" type="warning" size="small">差异</el-tag>
            <el-tag v-else type="info" size="small">相同</el-tag>
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页 -->
      <div class="pagination-wrapper" v-if="compareResult.items.length > pageSize">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :total="compareResult.items.length"
          :page-sizes="[50, 100, 200]"
          layout="total, sizes, prev, pager, next"
        />
      </div>
    </el-card>

    <!-- 空状态 -->
    <el-card v-else shadow="never">
      <el-empty description="请选择型号进行对比">
        <template #image>
          <el-icon :size="60" color="#C0C4CC"><DataAnalysis /></el-icon>
        </template>
      </el-empty>
    </el-card>

    <!-- 提交对话框 -->
    <el-dialog v-model="submitDialogVisible" title="提交发布" width="400px">
      <el-form label-width="100px">
        <el-form-item label="版本号">
          <el-input v-model="submitForm.version_number" placeholder="自动生成版本号（如 v1.0.1）" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="submitForm.description" type="textarea" placeholder="本次变更的描述" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="submitDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmSubmitDraft">确认提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { DataAnalysis, Download, EditPen } from '@element-plus/icons-vue'
import {
  getSeriesList, getModels, compareConfigs, exportCompareResult,
  createDraftBatch, getDraftStats, createDraft,
  submitDraftBatch, discardDraftBatch, deleteDraftByKey,
  getEnumValues
} from '../api/data'

// 数据
const seriesList = ref([])
const modelList = ref([])
const loading = ref(false)

// 枚举值
const enumValues = ref({
  selectionTypes: [],
  rdStatuses: [],
  configValues: []
})

// 草稿
const draftBatchId = ref(null)
const draftStats = ref({ total: 0, create: 0, update: 0, delete: 0 })
const draftChanges = ref(new Map())

// 编辑状态
const editingCell = ref(null)
const editSelectRef = ref(null)  // 编辑时的select组件引用
const originalValues = ref(new Map())  // 存储原始值

// 提交对话框
const submitDialogVisible = ref(false)
const submitForm = {
  version_number: '',
  description: ''
}

// 筛选条件
const selectedSeries = ref(null)
const selectedModels = ref([])
const compareFields = ref(['current_config', 'final_config'])
const showOnlyDiff = ref(true)  // 默认只显示差异项

// 对比结果
const compareResult = ref(null)

// 分页
const currentPage = ref(1)
const pageSize = ref(100)

// 字段过滤器
const fieldFilters = [
  { text: '最终配置', value: 'final_config' },
  { text: '当前配置', value: 'current_config' },
  { text: '选型类别', value: 'selection_config' },
  { text: '研发状态', value: 'rd_status' }
]

// 当前过滤的字段
const currentFieldFilter = ref([])

// 过滤后的表格数据
const filteredTableData = computed(() => {
  if (!compareResult.value) return []

  let data = compareResult.value.items

  // 按字段过滤
  if (currentFieldFilter.value.length > 0) {
    data = data.filter(item => currentFieldFilter.value.includes(item.field_name))
  }

  // 仅显示差异项
  if (showOnlyDiff.value) {
    data = data.filter(item => hasDiff(item))
  }

  return data
})

// 加载产品系列
const loadSeries = async () => {
  try {
    const res = await getSeriesList()
    seriesList.value = res.items || []
    if (seriesList.value.length > 0) {
      selectedSeries.value = seriesList.value[0].id
      await loadModels()
    }
  } catch (error) {
    console.error('加载产品系列失败:', error)
  }
}

// 加载产品型号
const loadModels = async () => {
  if (!selectedSeries.value) return

  try {
    const res = await getModels(selectedSeries.value)
    modelList.value = res.items || []
  } catch (error) {
    console.error('加载产品型号失败:', error)
  }
}

// 获取型号名称
const getModelName = (modelId) => {
  const model = modelList.value.find(m => m.id === modelId)
  return model ? model.name : ''
}

// 执行对比
const handleCompare = async () => {
  if (selectedModels.value.length < 2) {
    ElMessage.warning('请至少选择2个型号进行对比')
    return
  }

  if (compareFields.value.length === 0) {
    ElMessage.warning('请至少选择1个对比字段')
    return
  }

  loading.value = true
  try {
    const res = await compareConfigs({
      model_ids: selectedModels.value,
      compare_fields: compareFields.value,
      show_only_diff: showOnlyDiff.value
    })

    compareResult.value = res
    currentPage.value = 1

    // 保存原始值
    originalValues.value.clear()
    for (const item of res.items) {
      for (const modelId of Object.keys(item.values)) {
        const key = `${item.item_id}_${modelId}_${item.field_name}`
        originalValues.value.set(key, item.values[modelId])
      }
    }

    // 初始化草稿批次
    if (selectedSeries.value) {
      try {
        const batchRes = await createDraftBatch(selectedSeries.value)
        draftBatchId.value = batchRes.id
      } catch (error) {
        console.error('初始化草稿失败:', error)
      }
    }

    // 加载枚举值
    await loadEnumValues()

    if (res.diff_count === 0) {
      ElMessage.success('所选型号配置完全相同')
    } else {
      ElMessage.info(`发现 ${res.diff_count} 项差异`)
    }
  } catch (error) {
    console.error('对比失败:', error)
    ElMessage.error('对比失败')
  } finally {
    loading.value = false
  }
}

// 加载枚举值
const loadEnumValues = async () => {
  try {
    const res = await getEnumValues()
    // 选型类别：排除"已完成"
    enumValues.value.selectionTypes = (res.selection_types || []).filter(v => v !== '已完成')
    // 研发状态：包含未定义、未完成、招标完成、已完成
    enumValues.value.rdStatuses = (res.rd_statuses || []).filter(v =>
      ['未定义', '未完成', '招标完成', '已完成'].includes(v)
    )
    // 最终配置和当前配置：合并后排除"已完成"
    const allValues = [...new Set([...res.selection_types || [], ...res.rd_statuses || []])]
    enumValues.value.configValues = allValues.filter(v => v !== '已完成')
  } catch (error) {
    console.error('加载枚举值失败:', error)
  }
}

// 获取枚举选项
const getEnumOptions = (fieldName) => {
  if (fieldName === 'selection_config') return enumValues.value.selectionTypes
  if (fieldName === 'rd_status') return enumValues.value.rdStatuses
  return enumValues.value.configValues
}

// 开始编辑
const startEdit = (row, modelId) => {
  editingCell.value = { itemId: row.item_id, modelId, field: row.field_name }
  // 自动展开下拉框
  nextTick(() => {
    if (editSelectRef.value) {
      const select = Array.isArray(editSelectRef.value) ? editSelectRef.value[0] : editSelectRef.value
      if (select) {
        select.focus()
        setTimeout(() => {
          if (select.toggleMenu) {
            select.toggleMenu()
          }
        }, 50)
      }
    }
  })
}

// 结束编辑
const finishEdit = async (row, modelId, newValue) => {
  editingCell.value = null

  const key = `${row.item_id}_${modelId}_${row.field_name}`
  const oldValue = originalValues.value.get(key)

  // 检查值是否真正变化
  if (!isValueChanged(oldValue, newValue)) {
    // 改回原值，删除草稿
    if (draftChanges.value.has(key)) {
      await removeDraftChange(row.item_id, modelId, row.field_name, key)
    }
    return
  }

  await saveDraft(row, modelId, newValue, oldValue)
}

// 检查值是否变化
const isValueChanged = (oldVal, newVal) => {
  if (oldVal == null && newVal == null) return false
  if (oldVal === '' && newVal == null) return false
  if (oldVal == null && newVal === '') return false
  return String(oldVal || '') !== String(newVal || '')
}

// 保存草稿
const saveDraft = async (row, modelId, newValue, oldValue) => {
  if (!draftBatchId.value || !selectedSeries.value) return

  const key = `${row.item_id}_${modelId}_${row.field_name}`

  try {
    const res = await createDraft({
      series_id: selectedSeries.value,
      batch_id: draftBatchId.value,
      change_type: 'update',
      item_id: row.item_id,
      model_id: parseInt(modelId),
      field_name: row.field_name,
      new_value: newValue,
      old_value: oldValue
    })

    draftChanges.value.set(key, { oldValue, newValue, draftId: res.draft_id })
    await loadDraftStats()
  } catch (error) {
    console.error('保存草稿失败:', error)
    ElMessage.error('保存失败')
  }
}

// 删除草稿变更
const removeDraftChange = async (itemId, modelId, fieldName, key) => {
  if (!draftBatchId.value) return

  try {
    await deleteDraftByKey(draftBatchId.value, itemId, parseInt(modelId), fieldName)
    draftChanges.value.delete(key)
    await loadDraftStats()
  } catch (error) {
    console.error('删除草稿失败:', error)
  }
}

// 加载草稿统计
const loadDraftStats = async () => {
  if (!draftBatchId.value) return

  try {
    const res = await getDraftStats(draftBatchId.value)
    draftStats.value = res
  } catch (error) {
    console.error('加载草稿统计失败:', error)
  }
}

// 检查字段是否被修改（基于实际值与原始值的比较）
const isFieldChanged = (itemId, modelId, fieldName) => {
  // 获取当前显示的值
  const currentItem = compareResult.value?.items?.find(item =>
    item.item_id === itemId && item.field_name === fieldName
  )
  const currentValue = currentItem?.values?.[modelId]

  // 获取原始值
  const key = `${itemId}_${modelId}_${fieldName}`
  const originalValue = originalValues.value.get(key)

  // 比较是否真正不同
  return isValueChanged(originalValue, currentValue)
}

// 获取原始值
const getOriginalValue = (itemId, modelId, fieldName) => {
  const key = `${itemId}_${modelId}_${fieldName}`
  return originalValues.value.get(key)
}

// 字段过滤
const filterField = (value, row) => {
  return row.field_name === value
}

const handleFilterChange = (filters) => {
  currentFieldFilter.value = filters.field_name || []
}

// 获取字段标签
const getFieldLabel = (field) => {
  const labels = {
    'final_config': '最终配置',
    'current_config': '当前配置',
    'selection_config': '选型类别',
    'rd_status': '研发状态'
  }
  return labels[field] || field
}

// 获取字段标签类型
const getFieldTagType = (field) => {
  const types = {
    'final_config': 'primary',
    'current_config': 'success',
    'selection_config': 'warning',
    'rd_status': 'info'
  }
  return types[field] || ''
}

// 判断是否有差异
const hasDiff = (row) => {
  const values = Object.values(row.values)
    .filter(v => v !== null && v !== undefined && v !== '' && v !== 'N/A')

  if (values.length === 0) return false
  return new Set(values).size > 1
}

// 获取值的样式类
const getValueClass = (row, modelId) => {
  const values = Object.values(row.values)
    .filter(v => v !== null && v !== undefined && v !== '' && v !== 'N/A')

  if (values.length === 0) return ''

  const uniqueValues = new Set(values)
  if (uniqueValues.size === 1) return ''

  // 检查当前值是否与其他值不同
  const currentValue = row.values[modelId]
  const otherValues = Object.entries(row.values)
    .filter(([id]) => parseInt(id) !== modelId)
    .map(([, v]) => v)

  if (currentValue && otherValues.some(v => v !== currentValue)) {
    return 'value-diff'
  }

  return ''
}

// 导出结果
const handleExportResult = async () => {
  if (!compareResult.value) return

  try {
    const response = await exportCompareResult({
      model_ids: selectedModels.value,
      compare_fields: compareFields.value,
      show_only_diff: showOnlyDiff.value
    })

    const blob = new Blob([response], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', `配置对比_${Date.now()}.xlsx`)
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)

    ElMessage.success('导出成功')
  } catch (error) {
    console.error('导出失败:', error)
    ElMessage.error('导出失败')
  }
}

// 提交草稿
const handleSubmitDraft = () => {
  submitForm.version_number = ''
  submitForm.description = ''
  submitDialogVisible.value = true
}

// 确认提交草稿
const confirmSubmitDraft = async () => {
  if (!draftBatchId.value) return

  try {
    await submitDraftBatch(draftBatchId.value, {
      version_number: submitForm.version_number || undefined,
      description: submitForm.description || undefined
    })

    ElMessage.success('提交成功')
    submitDialogVisible.value = false

    // 清空草稿状态
    draftStats.total = 0
    draftStats.create = 0
    draftStats.update = 0
    draftStats.delete = 0
    draftChanges.value.clear()

    // 重新对比
    await handleCompare()
  } catch (error) {
    console.error('提交失败:', error)
    ElMessage.error('提交失败')
  }
}

// 废弃草稿
const handleDiscardDraft = async () => {
  if (!draftBatchId.value) return

  try {
    await ElMessageBox.confirm('确认废弃所有草稿？此操作不可恢复。', '确认', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    })

    await discardDraftBatch(draftBatchId.value)
    ElMessage.success('已废弃')

    // 清空草稿状态
    draftStats.total = 0
    draftStats.create = 0
    draftStats.update = 0
    draftStats.delete = 0
    draftChanges.value.clear()

    // 重新对比
    await handleCompare()
  } catch (error) {
    if (error !== 'cancel') {
      console.error('废弃失败:', error)
      ElMessage.error('废弃失败')
    }
  }
}

onMounted(() => {
  loadSeries()
})
</script>

<style scoped>
.compare-page {
  padding: 0;
}

.card-header {
  font-size: 16px;
  font-weight: 500;
}

.select-area {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.select-row {
  display: flex;
  align-items: center;
  gap: 24px;
  flex-wrap: wrap;
}

.select-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.select-item label {
  color: #606266;
  white-space: nowrap;
}

.result-card {
  margin-top: 16px;
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.result-summary {
  display: flex;
  gap: 40px;
}

.value-cell {
  padding: 4px 8px;
  border-radius: 4px;
}

.value-diff {
  background-color: #fdf6ec;
  color: #E6A23C;
  font-weight: 500;
}

.pagination-wrapper {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}

:deep(.el-checkbox-group) {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

/* 草稿状态栏 */
.draft-bar {
  margin-top: 16px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

.draft-bar :deep(.el-card__body) {
  padding: 12px 20px;
}

.draft-info {
  color: white;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.draft-info .el-icon {
  font-size: 18px;
}

.draft-info strong {
  font-size: 16px;
}

.draft-info .el-tag {
  margin-left: 4px;
}

.draft-actions {
  margin-left: auto;
  display: flex;
  gap: 8px;
}

/* 已修改的单元格高亮 */
.cell-changed {
  background-color: #fdf6ec;
  border-radius: 4px;
}

.cell-changed span:first-child {
  color: #e6a23c;
  font-weight: 500;
}

/* 原值提示 */
.original-hint {
  color: #909399;
  font-size: 11px;
  margin-left: 4px;
}
</style>