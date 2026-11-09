<template>
  <el-popover :visible="visible" trigger="click" :width="220" placement="bottom-start" @update:visible="requestVisibility">
    <template #reference><el-button size="small" text :type="modelValue == null ? 'info' : 'primary'" :icon="Filter" :aria-label="'筛选' + label" class="column-filter" /></template>
    <el-input v-model="search" placeholder="搜索候选值" size="small" clearable />
    <div class="filter-tools"><el-button link size="small" @click="selectVisible(true)">全选搜索结果</el-button><el-button link size="small" @click="selectVisible(false)">清空搜索结果</el-button></div>
    <el-checkbox-group v-model="draft" class="filter-options"><el-checkbox v-for="value in candidates" :key="value" :value="value" :label="value">{{ value || '(空白)' }}</el-checkbox></el-checkbox-group>
    <div class="filter-tools"><el-button size="small" @click="apply(null)">不限</el-button><el-button size="small" type="primary" @click="apply([...draft])">应用</el-button></div>
  </el-popover>
</template>
<script setup>
import { ref, computed } from 'vue'
import { Filter } from '@element-plus/icons-vue'
import { ElMessageBox } from 'element-plus'
import { selectVisibleFilterValues } from '../utils/probeTableFilters'
const props=defineProps({label:String,values:{type:Array,required:true},modelValue:{default:null}})
const emit=defineEmits(['update:modelValue'])
const visible=ref(false),search=ref(''),draft=ref([]),baseline=ref('')
const signature=values=>JSON.stringify([...values].sort())
const candidates=computed(()=>props.values.filter(v=>(v||'(空白)').toLowerCase().includes(search.value.toLowerCase())))
function selectVisible(checked){draft.value=selectVisibleFilterValues(draft.value,candidates.value,checked)}
async function requestVisibility(value){
  if(value){draft.value=[...(props.modelValue??props.values)];baseline.value=signature(draft.value);search.value='';visible.value=true;return}
  if(signature(draft.value)!==baseline.value){try{await ElMessageBox.confirm('筛选尚未应用，确定放弃这些选择？','未应用的筛选',{confirmButtonText:'放弃选择',cancelButtonText:'继续筛选',type:'warning'})}catch{return}}
  visible.value=false
}
function apply(value){emit('update:modelValue',value);visible.value=false}
</script>
<style scoped>.column-filter{width:24px;height:24px;padding:3px}.filter-tools{display:flex;gap:6px;margin-top:7px}.filter-options{display:flex;flex-direction:column;align-items:flex-start;max-height:220px;overflow:auto;margin-top:8px}.filter-options .el-checkbox{height:auto;min-height:26px;margin:0;white-space:normal}</style>
