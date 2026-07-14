<template>
  <div class="page">
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>探头类别管理</span>
          <el-button type="primary" :icon="Plus" @click="handleCreate">新增类别</el-button>
        </div>
      </template>
      <el-table :data="tableData" border stripe v-loading="loading">
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="name" label="类别名称" min-width="200" />
        <el-table-column prop="sort_order" label="排序" width="80" />
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="handleEdit(row)">编辑</el-button>
            <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑类别' : '新增类别'" width="450px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="类别名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="排序"><el-input-number v-model="form.sort_order" :min="0" /></el-form-item>
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
import { Plus } from '@element-plus/icons-vue'
import { getProbeCategories, createProbeCategory, updateProbeCategory, deleteProbeCategory } from '../api/data'

const tableData = ref([]); const loading = ref(false)
const dialogVisible = ref(false); const editingId = ref(null); const saving = ref(false)
const form = reactive({ name: '', sort_order: 0 })

const loadData = async () => {
  loading.value = true
  try { tableData.value = (await getProbeCategories()).items || [] } catch (e) { ElMessage.error('加载失败') } finally { loading.value = false }
}
const handleCreate = () => { editingId.value = null; form.name = ''; form.sort_order = 0; dialogVisible.value = true }
const handleEdit = (row) => { editingId.value = row.id; form.name = row.name; form.sort_order = row.sort_order || 0; dialogVisible.value = true }
const handleSave = async () => {
  if (!form.name) return ElMessage.warning('请输入名称')
  saving.value = true
  try { editingId.value ? await updateProbeCategory(editingId.value, form) : await createProbeCategory(form); ElMessage.success(editingId.value ? '更新成功' : '创建成功'); dialogVisible.value = false; await loadData() } catch (e) { ElMessage.error(e.response?.data?.detail || '保存失败') } finally { saving.value = false }
}
const handleDelete = async (row) => { try { await ElMessageBox.confirm(`确认删除"${row.name}"？`, '确认', { type: 'warning' }); await deleteProbeCategory(row.id); ElMessage.success('删除成功'); await loadData() } catch (e) { if (e !== 'cancel') ElMessage.error('删除失败') } }
onMounted(() => loadData())
</script>
<style scoped>.page { padding: 0 } .card-header { display: flex; justify-content: space-between; align-items: center }</style>
