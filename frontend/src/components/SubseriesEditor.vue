<template>
  <el-button :disabled="disabled" @click="open">{{ buttonLabel }}</el-button>
  <el-dialog v-model="visible" title="管理子系列与组合" width="min(760px, calc(100vw - 32px))" :before-close="requestClose" :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving">
    <el-alert type="info" :closable="false" title="配置库包含全部机型，白皮书使用其中已有文档的机型。此处保存的子系列由两个系统共用。" />
    <el-alert v-if="error" type="error" :closable="false" :title="error" style="margin-top: 10px" />
    <div ref="editorContent" v-loading="loading" style="min-height: 90px; max-height: 55vh; overflow-y: auto; padding: 4px">
      <el-empty v-if="!loading && !groups.length && loaded" description="还没有子系列，点击新增创建" :image-size="44" />
      <section v-for="(group, index) in groups" :key="group.editorKey" class="subseries-card" :data-editor-key="group.editorKey" :class="{ 'is-new': highlightedKey === group.editorKey }">
        <div class="subseries-heading">
          <el-input v-model="group.name" :disabled="saving" :aria-label="'第 ' + (index + 1) + ' 个子系列名称'" placeholder="子系列名称" maxlength="200" />
          <el-select v-model="group.series_names" multiple clearable :disabled="saving" placeholder="所属系列（可多选，不选为全部）" :aria-label="'第 ' + (index + 1) + ' 个子系列所属系列'">
            <el-option v-for="series in seriesList" :key="series.id" :label="series.name" :value="series.name" />
            <el-option v-for="name in group.series_names.filter(name => !seriesList.some(series => series.name === name))" :key="name" :label="name + '（系列已不存在）'" :value="name" />
          </el-select>
          <el-button type="danger" text :disabled="saving" :aria-label="'删除子系列 ' + (group.name || index + 1)" @click="removeGroup(group)">删除</el-button>
        </div>
        <el-select v-model="group.models" class="subseries-members" multiple filterable :disabled="saving" :aria-label="'第 ' + (index + 1) + ' 个子系列成员机型'" placeholder="从配置库选择成员机型，可搜索" style="width:100%">
          <el-option v-for="option in subseriesGroupOptions(group, catalog)" :key="option.value" :label="option.label" :value="option.value" />
        </el-select>
        <div class="subseries-note">{{ group.models.length }} 个成员 · 更换所属系列会保留原选择，请移除不属于新系列的机型后保存。</div>
      </section>
      <h4 style="margin:16px 0 4px">子系列组合</h4>
      <p class="subseries-note">组合引用子系列，成员调整后自动更新；重叠机型会自动去重。</p>
      <section v-for="(combination, index) in combinations" :key="combination.editorKey" class="subseries-card" :data-editor-key="combination.editorKey" :class="{ 'is-new': highlightedKey === combination.editorKey }">
        <div class="subseries-heading">
          <el-input v-model="combination.name" :disabled="saving" :aria-label="'第 ' + (index + 1) + ' 个组合名称'" placeholder="例如：科研机型组合" maxlength="200" />
          <el-button text type="danger" :disabled="saving" :aria-label="'删除组合 ' + (combination.name || index + 1)" @click="combinations.splice(index, 1)">删除组合</el-button>
        </div>
        <el-select v-model="combination.groupKeys" class="subseries-members" multiple filterable :disabled="saving" :aria-label="'第 ' + (index + 1) + ' 个组合包含的子系列'" placeholder="选择一个或多个子系列" style="width:100%">
          <el-option v-for="group in groups" :key="group.editorKey" :value="group.editorKey" :label="(group.name || '未命名子系列') + '（' + (group.series_names?.join('、') || '不限系列') + '）'" />
        </el-select>
      </section>
    </div>
    <el-button :disabled="saving || loading || !loaded" @click="add">新增子系列</el-button>
    <el-button :disabled="saving || loading || !loaded || !groups.length" @click="addCombination">新增组合</el-button>
    <span class="subseries-note" style="margin-left: 10px">{{ groups.length }} 个子系列 · {{ combinations.length }} 个组合，修改后点击保存</span>
    <template #footer>
      <el-button :disabled="saving" @click="requestClose()">关闭</el-button>
      <el-button v-if="error" :disabled="saving || loading" @click="reload">重新加载</el-button>
      <el-button type="primary" :loading="saving" :disabled="!loaded || loading || saving || !dirty" @click="save">保存子系列</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getSubseries, saveSubseries } from '../api/data'
import { cloneSubseriesGroups, cloneSubseriesCombinations, subseriesGroupOptions, subseriesPayload, subseriesSnapshot } from '../utils/subseriesEditor'

defineProps({ disabled: Boolean, buttonLabel: { type: String, default: '编辑子系列' } })
const emit = defineEmits(['saved'])
const visible = ref(false), loading = ref(false), saving = ref(false), loaded = ref(false)
const combinations = ref([])
const groups = ref([]), catalog = ref([]), seriesList = ref([]), revision = ref(''), baseline = ref(subseriesSnapshot([], [])), error = ref('')
let request = 0, nextKey = 0
const dirty = computed(() => subseriesSnapshot(groups.value, combinations.value) !== baseline.value)
const install = data => {
  groups.value = cloneSubseriesGroups(data.groups).map(group => ({ ...group, editorKey: ++nextKey }))
  combinations.value = cloneSubseriesCombinations(data.combinations || [], groups.value).map(combination => ({ ...combination, editorKey: ++nextKey }))
  catalog.value = data.catalog
  seriesList.value = data.series
  revision.value = data.revision
  baseline.value = subseriesSnapshot(groups.value, combinations.value)
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
const open = () => { visible.value = true; groups.value = []; combinations.value = []; baseline.value = subseriesSnapshot([], []); load() }
const highlightedKey = ref(null)
const revealNew = async key => {
  highlightedKey.value = key
  await nextTick()
  if (!visible.value) return
  const card = editorContent.value?.querySelector(`[data-editor-key="${key}"]`)
  card?.scrollIntoView({ block: 'nearest', behavior: 'instant' })
  card?.querySelector('input')?.focus({ preventScroll: true })
}
const editorContent = ref(null)
const add = () => {
  const key = ++nextKey
  groups.value.push({ name: '', series_names: [], models: [], options: [], editorKey: key })
  revealNew(key)
}
const addCombination = () => {
  const key = ++nextKey
  combinations.value.push({ name: '', groupKeys: [], editorKey: key })
  revealNew(key)
}
const removeGroup = group => {
  if (combinations.value.some(combination => combination.groupKeys.includes(group.editorKey))) {
    ElMessage.warning('该子系列正在被组合使用，请先从组合中移除后再删除'); return
  }
  groups.value = groups.value.filter(item => item.editorKey !== group.editorKey)
}
defineExpose({ open })
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
  if (combinations.value.some(combination => !combination.name.trim() || !combination.groupKeys.length)) {
    ElMessage.warning('请填写组合名称，并至少选择一个子系列'); return
  }
  if (new Set(combinations.value.map(combination => combination.name.trim())).size !== combinations.value.length) {
    ElMessage.warning('组合名称不能重复'); return
  }
  saving.value = true; error.value = ''
  try {
    install(await saveSubseries(subseriesPayload(revision.value, groups.value, combinations.value)))
    ElMessage.success('子系列已保存，白皮书与配置管理共用此关系')
    emit('saved')
  } catch (cause) {
    error.value = cause.response?.data?.detail || '子系列保存失败，修改已保留，请重试'
  } finally { saving.value = false }
}
</script>

<style scoped>
.subseries-card { margin: 12px 0; padding: 12px; border: 1px solid var(--el-border-color); border-radius: 5px; }
.subseries-card.is-new { border-color: var(--el-color-primary); background: var(--el-color-primary-light-9); box-shadow: 0 0 0 1px var(--el-color-primary-light-7); }
.subseries-heading { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; }
.subseries-heading .el-input { flex: 1; min-width: 100px; }
.subseries-heading .el-select { width: 230px; }
.subseries-members :deep(.el-tag) { height: auto; min-height: 20px; }
.subseries-members :deep(.el-select__tags-text) { white-space: normal; overflow-wrap: anywhere; }
.subseries-note { font-size: 12px; color: var(--el-text-color-secondary); margin-top: 6px; }
</style>
