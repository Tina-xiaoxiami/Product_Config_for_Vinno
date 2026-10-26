<template>
  <el-button :disabled="disabled" @click="open">编辑子系列</el-button>
  <el-dialog v-model="visible" title="编辑共用子系列" width="min(760px, calc(100vw - 32px))" :before-close="requestClose" :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving">
    <el-alert type="info" :closable="false" title="配置库包含全部机型，白皮书使用其中已有文档的机型。此处保存的子系列由两个系统共用。" />
    <el-alert v-if="error" type="error" :closable="false" :title="error" style="margin-top: 10px" />
    <div v-loading="loading" style="min-height: 90px; max-height: 55vh; overflow-y: auto; padding: 4px">
      <el-empty v-if="!loading && !groups.length && loaded" description="还没有子系列，点击新增创建" :image-size="44" />
      <section v-for="(group, index) in groups" :key="group.editorKey" class="subseries-card">
        <div class="subseries-heading">
          <el-input v-model="group.name" :disabled="saving" :aria-label="'第 ' + (index + 1) + ' 个子系列名称'" placeholder="子系列名称" maxlength="200" />
          <el-select v-model="group.series" :disabled="saving" placeholder="所属系列" :aria-label="'第 ' + (index + 1) + ' 个子系列所属系列'">
            <el-option label="不限系列" value="" />
            <el-option v-for="series in seriesList" :key="series.id" :label="series.name" :value="series.name" />
            <el-option v-if="group.series && !seriesList.some(series => series.name === group.series)" :label="group.series + '（系列已不存在）'" :value="group.series" />
          </el-select>
          <el-button type="danger" text :disabled="saving" :aria-label="'删除子系列 ' + (group.name || index + 1)" @click="groups.splice(index, 1)">删除</el-button>
        </div>
        <el-select v-model="group.models" multiple filterable collapse-tags collapse-tags-tooltip :max-collapse-tags="3" :disabled="saving" :aria-label="'第 ' + (index + 1) + ' 个子系列成员机型'" placeholder="从配置库选择成员机型，可搜索" style="width:100%">
          <el-option v-for="option in subseriesGroupOptions(group, catalog)" :key="option.value" :label="option.label" :value="option.value" />
        </el-select>
        <div class="subseries-note">{{ group.models.length }} 个成员 · 更换所属系列会保留原选择，请移除不属于新系列的机型后保存。</div>
      </section>
    </div>
    <el-button :disabled="saving || loading || !loaded" @click="add">新增子系列</el-button>
    <span class="subseries-note" style="margin-left: 10px">共 {{ groups.length }} 个子系列，修改后点击保存</span>
    <template #footer>
      <el-button :disabled="saving" @click="requestClose()">关闭</el-button>
      <el-button v-if="error" :disabled="saving || loading" @click="reload">重新加载</el-button>
      <el-button type="primary" :loading="saving" :disabled="!loaded || loading || saving || !dirty" @click="save">保存子系列</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getSubseries, saveSubseries } from '../api/data'
import { cloneSubseriesGroups, subseriesGroupOptions, subseriesPayload, subseriesSnapshot } from '../utils/subseriesEditor'

defineProps({ disabled: Boolean })
const emit = defineEmits(['saved'])
const visible = ref(false), loading = ref(false), saving = ref(false), loaded = ref(false)
const groups = ref([]), catalog = ref([]), seriesList = ref([]), revision = ref(''), baseline = ref('[]'), error = ref('')
let request = 0, nextKey = 0
const dirty = computed(() => subseriesSnapshot(groups.value) !== baseline.value)
const install = data => {
  groups.value = cloneSubseriesGroups(data.groups).map(group => ({ ...group, editorKey: ++nextKey }))
  catalog.value = data.catalog
  seriesList.value = data.series
  revision.value = data.revision
  baseline.value = subseriesSnapshot(groups.value)
  loaded.value = true
}
const load = async () => {
  const token = ++request
  loading.value = true; error.value = ''; loaded.value = false
  try {
    const data = await getSubseries()
    if (token === request && visible.value) install(data)
  } catch (cause) {
    if (token === request) error.value = cause.response?.data?.detail || '子系列加载失败，请重试'
  } finally { if (token === request) loading.value = false }
}
const reload = async () => {
  if (saving.value || loading.value) return
  if (dirty.value) {
    try { await ElMessageBox.confirm('重新加载将放弃当前未保存的修改，确定继续？', '重新加载子系列', { confirmButtonText: '重新加载', cancelButtonText: '继续编辑', type: 'warning' }) }
    catch { return }
  }
  await load()
}
const open = () => { visible.value = true; groups.value = []; baseline.value = '[]'; load() }
const add = () => groups.value.push({ name: '', series: '', models: [], options: [], editorKey: ++nextKey })
const requestClose = async done => {
  if (saving.value) return
  if (dirty.value) {
    try { await ElMessageBox.confirm('子系列修改尚未保存，确定放弃修改并关闭？', '未保存的修改', { confirmButtonText: '放弃修改', cancelButtonText: '继续编辑', type: 'warning' }) }
    catch { return }
  }
  ++request; loading.value = false; visible.value = false
  if (typeof done === 'function') done()
}
const save = async () => {
  if (saving.value || loading.value || !loaded.value || !dirty.value) return
  if (groups.value.some(group => !group.name.trim() || !group.models.length)) {
    ElMessage.warning('请填写每个子系列的名称，并至少选择一个成员机型'); return
  }
  if (new Set(groups.value.map(group => group.name.trim())).size !== groups.value.length) {
    ElMessage.warning('子系列名称不能重复'); return
  }
  saving.value = true; error.value = ''
  try {
    install(await saveSubseries(subseriesPayload(revision.value, groups.value)))
    ElMessage.success('子系列已保存，白皮书与配置管理共用此关系')
    emit('saved')
  } catch (cause) {
    error.value = cause.response?.data?.detail || '子系列保存失败，修改已保留，请重试'
  } finally { saving.value = false }
}
</script>

<style scoped>
.subseries-card { margin: 12px 0; padding: 12px; border: 1px solid var(--el-border-color); border-radius: 5px; }
.subseries-heading { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; }
.subseries-heading .el-input { flex: 1; min-width: 100px; }
.subseries-heading .el-select { width: 230px; }
.subseries-note { font-size: 12px; color: var(--el-text-color-secondary); margin-top: 6px; }
</style>
