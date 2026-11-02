<template>
  <el-dialog v-model="visible" title="功能名称核对" width="620px" top="5vh" append-to-body :before-close="close" :show-close="!saving" :close-on-click-modal="!saving" :close-on-press-escape="!saving">
    <div v-loading="loading" class="name-review-body">
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <p><strong>{{ detail?.name }}</strong> · 功能 ID {{ featureId }}</p>
      <p class="review-help">确认表示已核对并沿用当前写法，不修改名称、IPN或配置。仅清除所选差异的提示；相关名称或来源变化后会重新提醒。</p>
      <el-checkbox-group v-model="selected"><section v-for="check in detail?.checks || []" :key="check.baseline" class="name-review-check">
        <el-checkbox :value="check.baseline" :disabled="saving || !check.confirmable || check.reviewed">{{ check.label }}</el-checkbox>
        <el-tag v-if="check.reviewed" size="small" type="success">已确认沿用</el-tag>
        <p>{{ check.message }}</p>
        <div v-if="check.standard_cn_name">标准中文：{{ check.standard_cn_name }}</div><div v-if="check.standard_en_name">标准英文：{{ check.standard_en_name }}</div><div v-if="check.ipn">IPN：{{ check.ipn }}</div>
        <p v-if="check.severity === 'ambiguous' || check.identity_ambiguous" class="review-help">对应关系有歧义，请先在功能管理中核对主数据。</p>
      </section></el-checkbox-group>
      <p v-if="detail && !detail.checks.length">当前名称没有需要确认的差异。</p>
      <el-input v-model="note" placeholder="核对说明（选填）" maxlength="1000" :disabled="saving" />
      <el-input v-model="reviewer" placeholder="核对人（选填，默认本地用户）" maxlength="100" :disabled="saving" class="review-person" />
      <details v-if="detail?.history.length" class="review-history"><summary>核对记录（{{ detail.history.length }}）</summary>
        <section v-for="record in detail.history" :key="record.id" class="name-review-check">
          <strong>{{ record.baseline === 'standard' ? '功能名称标准表' : '配置管理描述' }}</strong> · {{ record.revoked_at ? '已撤销' : record.effective ? '当前有效' : '历史记录，当前不适用' }}
          <div>{{ record.confirmed_at.replace('T',' ').slice(0,19) }} UTC · {{ record.confirmed_by === 'local_user' ? '本地用户' : record.confirmed_by }}</div>
          <div v-if="record.note">{{ record.note }}</div>
          <details><summary>查看当时核对内容</summary><pre>{{ JSON.stringify(record.snapshot, null, 2) }}</pre></details>
          <el-button v-if="!record.revoked_at" size="small" link type="warning" :disabled="saving" @click="revoke(record)">撤销此确认</el-button>
        </section>
      </details>
    </div>
    <template #footer><el-button :disabled="saving" @click="close()">取消</el-button><el-button type="primary" :loading="saving" :disabled="loading || !selected.length || !!error" @click="confirm">确认所选差异</el-button></template>
  </el-dialog>
</template>
<script setup>
import { ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getFeatureNameReviews, confirmFeatureNames, revokeFeatureNameReview } from '../api/data'
import { loadFeatureNameStandardFlags } from '../utils/featureNameStandard'
const visible=ref(false),loading=ref(false),saving=ref(false),error=ref(''),featureId=ref(null),detail=ref(null),selected=ref([]),note=ref(''),reviewer=ref('')
let requestSequence=0
async function open(id) {
  const sequence=++requestSequence
  featureId.value=id;detail.value=null;selected.value=[];note.value='';reviewer.value='';error.value='';visible.value=true;loading.value=true
  try { const response=await getFeatureNameReviews(id); if(sequence===requestSequence) detail.value=response } catch(e) { if(sequence===requestSequence) error.value=e.response?.data?.detail||e.message } finally { if(sequence===requestSequence) loading.value=false }
}
async function close(done) {
  if(saving.value)return
  if(selected.value.length||note.value||reviewer.value){try{await ElMessageBox.confirm('放弃尚未保存的名称核对？','未保存核对')}catch{return}}
  requestSequence++;visible.value=false;done?.()
}
async function confirm() {
  if(saving.value)return
  error.value='';saving.value=true;let committed=false
  try {
    const checks=Object.fromEntries(detail.value.checks.filter(c=>selected.value.includes(c.baseline)).map(c=>[c.baseline,c.fingerprint]))
    detail.value=await confirmFeatureNames(featureId.value,{checks,note:note.value,confirmed_by:reviewer.value.trim()||'local_user'})
    committed=true;selected.value=[];note.value='';reviewer.value=''
    await loadFeatureNameStandardFlags({force:true,strict:true});visible.value=false;ElMessage.success('所选差异已确认，名称提示已更新')
  } catch(e) { error.value=committed?'确认已保存，标记刷新失败，请刷新页面':e.response?.data?.detail||e.message } finally { saving.value=false }
}
async function revoke(record) {
  try { await ElMessageBox.confirm('撤销此名称确认？仍存在的差异将重新提示。','撤销名称确认') } catch { return }
  error.value='';saving.value=true;let committed=false
  try { detail.value=await revokeFeatureNameReview(featureId.value,record.id);committed=true;selected.value=[];await loadFeatureNameStandardFlags({force:true,strict:true});ElMessage.success('已撤销名称确认') }
  catch(e){error.value=committed?'撤销已保存，标记刷新失败，请刷新页面':e.response?.data?.detail||e.message}
  finally{saving.value=false}
}
onBeforeRouteLeave(async()=>{ if(!visible.value)return true; await close(); return !visible.value })
defineExpose({open})
</script>
<style scoped>
.name-review-body{max-height:calc(85vh - 140px);overflow:auto}.review-help{font-size:12px;color:#64748b;line-height:1.6}.name-review-check{border-top:1px solid #dce4ed;padding:10px 0;font-size:12px;line-height:1.6}.name-review-check p{white-space:pre-line;margin:4px 0}.review-person,.review-history{margin-top:8px}.review-history summary{cursor:pointer}pre{max-height:220px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere}
</style>
