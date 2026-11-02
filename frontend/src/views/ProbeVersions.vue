<template>
  <el-card shadow="never" v-loading="busy">
    <template #header><div class="toolbar"><strong>探头配置 · 版本历史</strong>
      <el-select :disabled="busy" v-model="workspaceId" placeholder="选择共同总集" style="width:230px" @change="load"><el-option v-for="w in workspaces" :key="w.id" :value="w.id" :label="w.name" /></el-select>
      <el-button size="small" @click="$router.push('/probe-config')">返回配置</el-button>
    </div></template>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-empty v-if="!releases.length" description="暂无已发布总集。原有数据未自动归入任何发布版本。" />
    <template v-else>
      <div class="toolbar"><el-select v-model="before" placeholder="对比起始版本"><el-option v-for="r in releases" :key="r.id" :value="r.id" :label="r.version_number" /></el-select><el-select v-model="after" placeholder="对比目标版本"><el-option v-for="r in releases" :key="r.id" :value="r.id" :label="r.version_number" /></el-select><el-button size="small" :disabled="!before || !after" @click="compare">对比版本</el-button></div>
      <ProbeDataTable :rows="releases" :columns="releaseColumns" table-id="release-history" :actions-width="260"><template #actions="{row}"><el-button size="small" link @click="inspect(row)">查看快照</el-button><el-button size="small" link @click="download(row)">导出</el-button><el-button size="small" link type="warning" @click="restore(row)">恢复为新草稿</el-button></template></ProbeDataTable>
    </template>
    <template v-if="detail"><p>发布时总集和机型范围：{{ [...detail.snapshot.data.scope.groups, ...detail.snapshot.data.scope.combinations].join(' + ') }}；{{ detail.snapshot.data.scope.model_ids.length }} 个机型。配置版本：{{ JSON.stringify(detail.snapshot.config_version_ids) }}</p>
      <el-select v-model="modelId" placeholder="选择历史机型" style="width:260px"><el-option v-for="m in historicalModels" :key="m.id" :value="m.id" :label="m.name + ' (#' + m.id + ')'" /></el-select>
      <ProbeDataTable :rows="historicalRows" :columns="snapshotColumns" table-id="release-snapshot" />
    </template>
    <template v-if="comparison"><p>总集变更：{{ JSON.stringify(comparison.diff) }}；机型结果变化 {{ comparison.changes.length }} 条。</p>
      <ProbeDataTable :rows="comparisonRows" :columns="comparisonColumns" table-id="release-comparison" />
    </template>
  </el-card>
</template>
<script setup>
import { ref, computed, onMounted, onActivated } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as api from '../api/probeWorkspace'
import { probeStatusLabel } from '../utils/probeWorkspace'
import ProbeDataTable from '../components/ProbeDataTable.vue'
const columns = definitions => definitions.map(([key, label, width = 180, fixed = false]) => ({key, label, width, fixed, visible:true}))
const releaseColumns = columns([['version_number','版本号',180,true],['description','说明',260],['created_at','发布时间',220]])
const snapshotColumns = columns([['probe_name','探头',180,true],['ipn','IPN',140],['feature_name','功能',180],['defined_status','定义'],['current_status','现状'],['defined_excludes','定义排除应用'],['current_excludes','现状排除应用'],['priority','优先级',100],['current_reason','依据',220],['notes','说明',220]])
const comparisonColumns = columns([['model_name','机型',180,true],['item','探头 / 功能',240],['before_status','原定义 / 现状'],['after_status','新定义 / 现状'],['details','应用排除与说明',300]])
const workspaces=ref([]),workspaceId=ref(null),releases=ref([]),busy=ref(false),error=ref(''),detail=ref(null),modelId=ref(null),before=ref(null),after=ref(null),comparison=ref(null)
async function run(task){if(busy.value)return;busy.value=true;error.value='';try{await task()}catch(e){error.value=e.response?.data?.detail||e.message;ElMessage.error(error.value)}finally{busy.value=false}}
async function load(){await run(async()=>{detail.value=null;comparison.value=null;before.value=null;after.value=null;releases.value=await api.listProbeReleases(workspaceId.value)})}
async function inspect(row){await run(async()=>{detail.value=await api.getProbeRelease(workspaceId.value,row.id);modelId.value=detail.value.snapshot.data.scope.model_ids[0];comparison.value=null})}
async function compare(){await run(async()=>{comparison.value=await api.compareProbeReleases(workspaceId.value,before.value,after.value);detail.value=null})}
const comparisonRows = computed(() => (comparison.value?.changes || []).map(row => ({
  model_name: (row.after || row.before).model_name,
  item: (row.after || row.before).probe_name + ' / ' + (row.after || row.before).feature_name,
  before_status: row.before ? probeStatusLabel(row.before.defined_status) + ' / ' + probeStatusLabel(row.before.current_status) : '无',
  after_status: row.after ? probeStatusLabel(row.after.defined_status) + ' / ' + probeStatusLabel(row.after.current_status) : '无',
  details: comparisonNotes(row),
})))
const historicalModels=computed(()=>[...new Map((detail.value?.snapshot.results||[]).map(r=>[r.model_id,{id:r.model_id,name:r.model_name}])).values()])
function comparisonNotes(row) {
  const info = result => result && ({ defined: result.defined_excludes, current: result.current_excludes, notes: result.notes })
  return JSON.stringify({ before: info(row.before), after: info(row.after) })
}
const historicalRows=computed(()=>(detail.value?.snapshot.results||[]).filter(r=>r.model_id===modelId.value))
async function restore(row){try{await ElMessageBox.confirm(`将 ${row.version_number} 恢复为未发布草稿？当前草稿将被替换，已发布历史保持不变。`,'恢复为草稿',{type:'warning'})}catch{return}await run(async()=>{const w=await api.getProbeWorkspace(workspaceId.value);await api.restoreProbeRelease(w.id,row.id,w.revision);ElMessage.success('已恢复为草稿，请回到探头配置核对当前子系列成员后发布')})}
async function download(row){await run(async()=>{const blob=await api.exportProbeWorkbook(workspaceId.value,row.id);const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`探头配置_${row.version_number}.xlsx`;a.click();URL.revokeObjectURL(url)})}
onMounted(async()=>{await run(async()=>{workspaces.value=await api.listProbeWorkspaces();if(workspaces.value.length){workspaceId.value=workspaces.value[0].id;releases.value=await api.listProbeReleases(workspaceId.value)}})})
let firstActivation = true
onActivated(async () => {
  if (firstActivation) { firstActivation = false; return }
  if (busy.value) return
  await run(async () => {
    workspaces.value = await api.listProbeWorkspaces()
    if (workspaceId.value) releases.value = await api.listProbeReleases(workspaceId.value)
  })
})
</script>
<style scoped>.toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px}.toolbar .el-button+.el-button{margin-left:0}p{font-size:13px;line-height:1.6;overflow-wrap:anywhere}</style>
