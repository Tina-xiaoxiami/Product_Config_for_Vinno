<template>
  <div class="models-page">
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>产品型号管理</span>
          <div class="header-actions">
            <el-select v-model="selectedSeries" placeholder="选择产品系列" @change="loadData" style="width: 200px">
              <el-option v-for="s in seriesList" :key="s.id" :label="s.name" :value="s.id" />
            </el-select>
            <el-button type="primary" :icon="Plus" @click="handleCreate" :disabled="!selectedSeries">新增型号</el-button>
          </div>
        </div>
      </template>

      <el-table ref="tableRef" :data="tableData" border stripe v-loading="loading" row-key="id">
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="name" label="型号名称" min-width="200" />
        <el-table-column label="对应注册证" min-width="280">
          <template #default="{ row }">
            <div v-if="row.registration_packages?.length" class="registration-mappings">
              <el-tag
                v-for="mapping in row.registration_packages"
                :key="mapping.registration_package_id"
                type="info"
                effect="plain"
              >
                {{ mapping.registration_number }} · {{ mapping.registration_model_name }}
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
        <el-table-column label="操作" width="210" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="moveRow(row, -1)" :disabled="tableData.indexOf(row) === 0" :icon="ArrowUp" />
            <el-button size="small" @click="moveRow(row, 1)" :disabled="tableData.indexOf(row) === tableData.length - 1" :icon="ArrowDown" />
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
          @size-change="loadData"
          @current-change="loadData"
        />
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
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, ArrowUp, ArrowDown } from '@element-plus/icons-vue'
import { getSeriesList, getModels, createModel, updateModel, deleteModel } from '../api/data'
import { formatTime } from '../utils/modelHelpers'

const seriesList = ref([])
const selectedSeries = ref(null)
const tableData = ref([])
const loading = ref(false)
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const tableRef = ref(null)

// 排序移动
const moveRow = async (row, direction) => {
  const idx = tableData.value.findIndex(m => m.id === row.id)
  const newIdx = idx + direction
  if (newIdx < 0 || newIdx >= tableData.value.length) return
  const moved = tableData.value.splice(idx, 1)[0]
  tableData.value.splice(newIdx, 0, moved)
  const updates = tableData.value.map((m, i) => ({ id: m.id, sort_order: i }))
  await Promise.all(updates.map(u => updateModel(u.id, { sort_order: u.sort_order })))
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

const loadData = async () => {
  if (!selectedSeries.value) return

  loading.value = true
  try {
    const res = await getModels(selectedSeries.value, {
      skip: (currentPage.value - 1) * pageSize.value,
      limit: pageSize.value
    })
    tableData.value = res.items || []
    total.value = res.total || 0
  } catch (error) {
    console.error('加载失败:', error)
    ElMessage.error('加载失败')
  } finally {
    loading.value = false
  }
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

onMounted(() => {
  loadSeries()
})
</script>

<style scoped>
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

.registration-mappings { display: flex; flex-wrap: wrap; gap: 6px; }
.unmapped-registration { color: #94a3b8; font-size: 12px; }

.pagination-wrapper {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
</style>
