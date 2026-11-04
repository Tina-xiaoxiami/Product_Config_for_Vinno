<template>
  <el-dialog v-model="visible" :title="editingDisplay ? '编辑显示名称' : '功能名称核对'" width="620px" top="5vh" append-to-body :before-close="close" :show-close="!saving" :close-on-click-modal="!saving" :close-on-press-escape="!saving">
    <div v-loading="loading" class="name-review-body">
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <p><strong>{{ detail?.name }}</strong> · 功能 ID {{ featureId }}</p>
      <section v-if="detail" class="display-name-editor">
        <label :for="displayInputId">显示名称</label>
        <el-input :id="displayInputId" v-model="displayName" maxlength="200" :disabled="saving" placeholder="输入中文、英文或缩写" />
        <div class="display-name-actions">
          <el-button size="small" :disabled="saving || !detail.primary_cn_name" @click="displayName = detail.primary_cn_name">使用中文名</el-button>
          <el-button size="small" :disabled="saving || !detail.primary_en_name" @click="displayName = detail.primary_en_name">使用英文名</el-button>
          <el-button size="small" :disabled="saving" @click="displayName = ''; saveDisplay()">恢复默认显示</el-button>
          <el-button size="small" type="primary" :disabled="saving || !displayDirty" @click="saveDisplay">保存显示名称</el-button>
        </div>
        <p class="review-help">每个功能可单独设置，中英文可以混合显示；这里只改变显示，不修改标准主名、IPN 和配置。</p>
      </section>
      <p v-if="!editingDisplay" class="review-help">功能名称以标准表为准。更新时采用标准中文、英文名称，并保留旧名为曾用名。配置表只用于确定 IPN 链接，不比较描述名称。</p>
      <div v-if="!editingDisplay"><section v-for="check in detail?.checks || []" :key="check.baseline" class="name-review-check">
        <strong>{{ check.label }}</strong>
        <el-tag v-if="check.severity === 'ok'" size="small" type="success">{{ check.baseline === 'config' ? '已链接' : '一致' }}</el-tag>
        <p>{{ check.message }}</p>
        <div v-if="check.standard_cn_name">标准中文：{{ check.standard_cn_name }}</div><div v-if="check.standard_en_name">标准英文：{{ check.standard_en_name }}</div><div v-if="check.ipn">IPN：{{ check.ipn }}</div>
        <p v-if="check.severity === 'ambiguous' || check.identity_ambiguous" class="review-help">对应关系有歧义，请先在功能管理中核对主数据。</p>
      </section></div>
      <p v-if="!editingDisplay && detail && !detail.checks.length">当前没有可用的标准定义，请先维护标准表。</p>
      <el-input v-if="!editingDisplay" v-model="note" placeholder="核对说明（选填）" maxlength="1000" :disabled="saving" />
      <el-input v-if="!editingDisplay" v-model="reviewer" placeholder="核对人（选填，默认本地用户）" maxlength="100" :disabled="saving" class="review-person" />
      <details v-if="!editingDisplay && detail?.history.length" class="review-history"><summary>核对记录（{{ detail.history.length }}）</summary>
        <section v-for="record in detail.history" :key="record.id" class="name-review-check">
          <strong>{{ record.baseline === 'standard' ? '功能名称标准表' : '配置项链接' }}</strong> · {{ ['apply_standard','sync_standard'].includes(record.action) ? '已按标准表更新与核对' : record.action === 'display_name' ? '已更新显示名称' : record.revoked_at ? '已撤销的历史确认' : '历史确认，不再用于消除名称差异' }}
          <div>{{ record.confirmed_at.replace('T',' ').slice(0,19) }} UTC · {{ record.confirmed_by === 'local_user' ? '本地用户' : record.confirmed_by }}</div>
          <div v-if="record.note">{{ record.note }}</div>
          <details><summary>查看当时核对内容</summary><pre>{{ JSON.stringify(record.snapshot, null, 2) }}</pre></details>
          <el-button v-if="record.action === 'legacy_confirmation' && !record.revoked_at" size="small" link type="warning" :disabled="saving" @click="revoke(record)">撤销此确认</el-button>
        </section>
      </details>
    </div>
    <template #footer><el-button :disabled="saving" @click="close()">{{ editingDisplay ? '关闭' : '取消' }}</el-button><el-button v-if="!editingDisplay" type="primary" :loading="saving" :disabled="loading || !standardCheck?.can_apply || !!error" @click="confirm">按标准表更新名称</el-button></template>
  </el-dialog>
</template>
<script setup>
import { ref, computed, getCurrentInstance } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getFeatureNameReviews, applyFeatureStandardNames, revokeFeatureNameReview, updateFeatureDisplayName } from '../api/data'
import { loadFeatureNameStandardFlags } from '../utils/featureNameStandard'
const props=defineProps({ globalHost:Boolean })
const displayInputId='feature-display-name-'+getCurrentInstance().uid
const visible=ref(false),loading=ref(false),saving=ref(false),error=ref(''),featureId=ref(null),detail=ref(null),note=ref(''),reviewer=ref('')
const editingDisplay=ref(false)
const displayName=ref(''), displayBaseline=ref('')
const displayDirty=computed(()=>displayName.value !== displayBaseline.value)
const standardCheck = computed(() => detail.value?.checks.find(check => check.baseline === 'standard'))
let requestSequence=0
async function open(id, displayMode = false) {
  editingDisplay.value=displayMode
  const sequence=++requestSequence
  featureId.value=id;detail.value=null;displayName.value='';displayBaseline.value='';note.value='';reviewer.value='';error.value='';visible.value=true;loading.value=true
  try { const response=await getFeatureNameReviews(id); if(sequence===requestSequence) { detail.value=response; displayName.value=response.display_name || response.default_display_name || response.name; displayBaseline.value=displayName.value } } catch(e) { if(sequence===requestSequence) error.value=e.response?.data?.detail||e.message } finally { if(sequence===requestSequence) loading.value=false }
}
async function close(done) {
  if(saving.value)return
  if(note.value||reviewer.value||displayDirty.value){try{await ElMessageBox.confirm('放弃尚未保存的名称核对？','未保存说明')}catch{return}}
  requestSequence++;visible.value=false;done?.()
}
async function confirm() {
  if(saving.value)return
  if(displayDirty.value){ElMessage.warning('请先保存或恢复显示名称，再更新标准主名');return}
  error.value='';saving.value=true;let committed=false
  try {
    detail.value=await applyFeatureStandardNames(featureId.value,{fingerprint:standardCheck.value.fingerprint,note:note.value,confirmed_by:reviewer.value.trim()||'local_user'})
    committed=true;note.value='';reviewer.value=''
    await loadFeatureNameStandardFlags({force:true,strict:true});visible.value=false;ElMessage.success('已按标准表更新名称，旧名保留为曾用名')
  } catch(e) { error.value=committed?'名称已更新，显示刷新失败，请刷新页面':e.response?.data?.detail||e.message } finally { saving.value=false }
}
async function saveDisplay() {
  if(saving.value || loading.value)return
  error.value='';saving.value=true;let committed=false
  try {
    detail.value=await updateFeatureDisplayName(featureId.value,{name:displayName.value.trim()})
    committed=true;displayName.value=detail.value.display_name || detail.value.default_display_name || detail.value.name;displayBaseline.value=displayName.value
    await loadFeatureNameStandardFlags({force:true,strict:true});ElMessage.success('显示名称已保存')
  } catch(e) {error.value=committed?'显示名称已保存，刷新失败，请刷新页面':e.response?.data?.detail||e.message}
  finally {saving.value=false}
}
async function revoke(record) {
  try { await ElMessageBox.confirm('撤销此历史确认记录？名称仍按标准表核对。','撤销名称确认') } catch { return }
  error.value='';saving.value=true;let committed=false
  try { detail.value=await revokeFeatureNameReview(featureId.value,record.id);committed=true;await loadFeatureNameStandardFlags({force:true,strict:true});ElMessage.success('已撤销名称确认') }
  catch(e){error.value=committed?'撤销已保存，标记刷新失败，请刷新页面':e.response?.data?.detail||e.message}
  finally{saving.value=false}
}
async function requestLeave(){ if(!visible.value)return true; await close(); return !visible.value }
if(!props.globalHost) onBeforeRouteLeave(requestLeave)
defineExpose({open,requestLeave})
</script>
<style scoped>
.display-name-editor{padding:8px 0}.display-name-editor label{display:block;font-size:12px;font-weight:600;margin-bottom:6px}.display-name-actions{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}.display-name-actions .el-button+.el-button{margin-left:0}.name-review-body{max-height:calc(85vh - 140px);overflow:auto}.review-help{font-size:12px;color:#64748b;line-height:1.6}.name-review-check{border-top:1px solid #dce4ed;padding:10px 0;font-size:12px;line-height:1.6}.name-review-check p{white-space:pre-line;margin:4px 0}.review-person,.review-history{margin-top:8px}.review-history summary{cursor:pointer}pre{max-height:220px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere}
</style>
