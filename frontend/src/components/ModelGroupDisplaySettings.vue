<template>
  <el-button size="small" text :icon="Setting" @click="open">显示分组</el-button>
  <el-dialog v-model="visible" title="显示分组" width="min(440px, calc(100vw - 32px))" :before-close="requestClose">
    <p class="group-display-note">选择左侧显示的组合和子系列，仅影响当前浏览器。全部型号始终保留。</p>
    <div class="group-display-list">
      <template v-for="node in nodes.filter(node => node.key !== 'all')" :key="node.key">
        <el-checkbox :model-value="!draft.includes(node.key)" @update:model-value="toggle(node.key, $event)">{{ node.label }}</el-checkbox>
        <div v-if="node.children" class="group-display-children">
          <el-checkbox v-for="child in node.children" :key="child.key" :disabled="draft.includes(node.key)" :model-value="!draft.includes(child.key)" @update:model-value="toggle(child.key, $event)">{{ child.label }}</el-checkbox>
        </div>
      </template>
    </div>
    <template #footer><div class="group-display-footer"><el-button size="small" @click="draft = []">恢复默认</el-button><span><el-button size="small" @click="requestClose()">取消</el-button><el-button type="primary" size="small" @click="apply">应用</el-button></span></div></template>
  </el-dialog>
</template>
<script setup>
import { ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import { Setting } from '@element-plus/icons-vue'
const props = defineProps({ nodes: {type:Array, required:true}, modelValue: {type:Array, required:true} })
const emit = defineEmits(['update:modelValue'])
const visible = ref(false), draft = ref([]), baseline = ref('')
const open = () => { draft.value = [...props.modelValue]; baseline.value = JSON.stringify(draft.value); visible.value = true }
const toggle = (key, checked) => { draft.value = checked ? draft.value.filter(value => value !== key) : [...new Set([...draft.value, key])] }
const apply = () => { emit('update:modelValue', [...draft.value]); visible.value = false }
const requestClose = async done => {
  if (JSON.stringify(draft.value) !== baseline.value) {
    try { await ElMessageBox.confirm('分组显示设置尚未应用，确定放弃修改？', '未应用的显示设置', {confirmButtonText:'放弃修改',cancelButtonText:'继续设置',type:'warning'}) }
    catch { return }
  }
  visible.value = false
  if (typeof done === 'function') done()
}
</script>
<style scoped>
.group-display-note { font-size: 12px; color: var(--el-text-color-secondary); margin: 0 0 10px; }
.group-display-list { display: flex; flex-direction: column; max-height: 55vh; overflow: auto; }
.group-display-children { display: flex; flex-direction: column; padding-left: 20px; }
.group-display-list .el-checkbox { height: auto; min-height: 32px; margin-right: 0; }
.group-display-list :deep(.el-checkbox__label) { white-space: normal; overflow-wrap: anywhere; }
.group-display-footer { display: flex; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
</style>
