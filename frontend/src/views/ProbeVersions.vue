<template>
  <div class="page">
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>探头配置 - 版本历史</span>
          <el-select v-model="selectedProductModel" placeholder="选择产品型号" style="width:220px" @change="loadVersions">
            <el-option v-for="m in productModels" :key="m.id" :label="m.name" :value="m.id" />
          </el-select>
        </div>
      </template>

      <el-table v-if="versions.length" :data="versions" border stripe v-loading="loading">
        <el-table-column prop="version_number" label="版本号" width="180" />
        <el-table-column prop="description" label="描述" min-width="200" />
        <el-table-column prop="created_at" label="创建时间" width="200" />
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="warning" @click="handleRollback(row)">回滚</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-else-if="selectedProductModel && !loading" description="暂无版本记录" />
      <el-empty v-else-if="!selectedProductModel" description="请先选择产品型号" />
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getSeriesList, getModels, getProbeVersions, rollbackProbeVersion } from '../api/data'

const productModels = ref([]); const selectedProductModel = ref(null)
const versions = ref([]); const loading = ref(false)

const loadProductModels = async () => {
  try {
    const sl = (await getSeriesList()).items || []
    const all = []; for (const s of sl) { (await getModels(s.id, { limit: 200 })).items?.forEach(m => all.push({ ...m, seriesName: s.name })) }
    productModels.value = all
  } catch {}
}
const loadVersions = async () => {
  if (!selectedProductModel.value) { versions.value = []; return }
  loading.value = true
  try { versions.value = await getProbeVersions(selectedProductModel.value) || [] } catch { versions.value = [] } finally { loading.value = false }
}
const handleRollback = async (row) => {
  try {
    await ElMessageBox.confirm(`确认回滚到版本 ${row.version_number}？当前数据将被覆盖。`, '确认回滚', { type: 'warning' })
    const r = await rollbackProbeVersion(selectedProductModel.value, row.id)
    ElMessage.success(r.message)
    await loadVersions()
  } catch (e) { if (e !== 'cancel') ElMessage.error('回滚失败') }
}

onMounted(loadProductModels)
</script>
<style scoped>.page{padding:0}.card-header{display:flex;justify-content:space-between;align-items:center}</style>
