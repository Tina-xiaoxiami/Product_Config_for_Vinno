<template>
  <el-popover ref="popover" placement="bottom-start" :width="390" trigger="click" @before-enter="load">
    <template #reference><el-button :disabled="disabled" :loading="applying">子系列组合</el-button></template>
    <div v-loading="loading" style="min-height: 70px">
      <strong>已保存的子系列组合</strong>
      <p style="font-size:12px;color:var(--el-text-color-secondary)">一键选择组合的全部机型，按最新子系列成员去重。</p>
      <el-alert v-if="error" type="error" :closable="false" :title="error" />
      <el-empty v-if="!loading && !error && !combinations.length" description="还没有组合，点击下方创建" :image-size="40" />
      <div style="max-height: 300px; overflow-y: auto">
        <div v-for="combination in combinations" :key="combination.name" style="padding: 8px 0; border-bottom:1px solid var(--el-border-color-lighter)">
          <el-button text type="primary" :disabled="loading || applying || disabled" @click="apply(combination.name)">{{ combination.name }} · {{ combination.model_ids.length }} 个机型</el-button>
          <div style="font-size:12px; overflow-wrap:anywhere; color:var(--el-text-color-secondary)">{{ combination.sub_series.join(' + ') }}</div>
          <div v-if="combination.missing_models.length" style="font-size:12px;color:var(--el-color-warning)">包含未匹配机型，请先编辑核对</div>
        </div>
      </div>
      <div style="display:flex;gap:8px;margin-top:12px">
        <el-button :disabled="loading || applying" @click="load">刷新组合</el-button>
        <el-button type="primary" :disabled="applying || disabled" @click="edit">新建 / 编辑组合</el-button>
      </div>
    </div>
  </el-popover>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getSubseries } from '../api/data'
import { buildSubseriesCombinationSelection } from '../utils/subseriesEditor'
const props = defineProps({ disabled: Boolean, selectionKey: String })
const emit = defineEmits(['apply', 'edit'])
const popover = ref(null), combinations = ref([]), loading = ref(false), applying = ref(false), error = ref('')
let request = 0
const load = async () => {
  if (applying.value) return
  const token = ++request
  loading.value = true; error.value = ''
  try {
    const data = await getSubseries()
    if (token === request) combinations.value = data.combinations || []
  } catch (cause) {
    if (token === request) { combinations.value = []; error.value = cause.response?.data?.detail || '子系列组合加载失败，请刷新重试' }
  } finally { if (token === request) loading.value = false }
}
const apply = async name => {
  if (props.disabled || applying.value || loading.value) return
  const selectionKey = props.selectionKey
  applying.value = true; error.value = ''
  const token = ++request
  try {
    // Resolve current references at each use; never apply a saved model snapshot.
    const data = await getSubseries()
    if (token !== request || props.disabled) return
    if (selectionKey !== props.selectionKey) throw new Error('当前机型选择已变化，请重新选择组合')
    combinations.value = data.combinations || []
    const combination = combinations.value.find(item => item.name === name)
    if (!combination) throw new Error('该组合已被删除或改名，请刷新后重新选择')
    const selection = buildSubseriesCombinationSelection(combination, data.catalog)
    popover.value?.hide()
    emit('apply', selection)
  } catch (cause) {
    error.value = cause.response?.data?.detail || cause.message || '组合应用失败，请重试'
    ElMessage.warning(error.value)
  } finally { applying.value = false }
}
const edit = () => { popover.value?.hide(); emit('edit') }
</script>
