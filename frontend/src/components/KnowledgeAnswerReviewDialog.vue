<template>
  <el-dialog v-model="visible" title="核对答案与适用范围" width="min(980px, calc(100vw - 32px))" :before-close="requestClose" destroy-on-close>
    <template v-if="question">
      <h3 class="review-question">{{ questionDisplayText(question) }}</h3>
      <div class="review-meta">答案 v{{ question.answer?.version }} · {{ question.answer?.updated_at }} · {{ knowledgeScopeLabel(question.scope) }}</div>
      <section class="review-original" aria-label="当前答案全文"><pre>{{ answerDisplayText(question.answer) }}</pre></section>
      <details v-if="questionDisplayText(question) !== question.question_text || answerDisplayText(question.answer) !== question.answer?.answer_text" class="review-saved-text">
        <summary>查看保存原文（历史名称）</summary>
        <p>{{ question.question_text }}</p><pre>{{ question.answer?.answer_text }}</pre>
      </details>
      <el-alert v-if="question.answer?.change_note" :closable="false" type="info" title="已有确认或上次变更说明" class="review-existing"><p>{{ question.answer.change_note }}</p></el-alert>
      <div v-if="question.answer?.citations?.length" class="review-citations">
        <el-button v-for="citation in question.answer.citations" :key="citation.id" size="small" link @click="openCitation(citation)">{{ citation.document_title }} · {{ citation.source_ref || '未登记位置' }}</el-button>
      </div>
      <el-alert v-if="!question.evidence_review?.available" :closable="false" type="warning" title="核对记录尚未初始化，请更新服务后再保存。当前答案仍可查看。" />
      <el-alert v-if="error" :closable="false" type="error" :title="error" />
      <el-form label-position="top" class="review-form" :disabled="saving">
        <el-form-item label="本次处理">
          <el-radio-group v-model="form.action" size="small">
            <el-radio-button value="record_reference">仅补确认记录</el-radio-button>
            <el-radio-button value="confirm_scope">确认范围并用于查询</el-radio-button>
            <el-radio-button value="defer">暂缓，记录待办</el-radio-button>
          </el-radio-group>
          <p class="review-hint">{{ form.action === 'confirm_scope' ? '保存后为所选完整机型建立明确范围的问答；历史原文保留，已有不同答案时不会覆盖。' : form.action === 'record_reference' ? '保存负责人确认与依据，不改原答案，也不会自动扩大查询范围。' : '保留当前答案，记录暂缓理由，继续列在待核对中。' }}</p>
        </el-form-item>
        <div class="review-grid">
          <el-form-item v-if="form.action !== 'confirm_scope'" label="来源国家（可选）"><el-input v-model="form.country" maxlength="2" placeholder="如 CN" aria-label="核对国家代码" /></el-form-item>
          <el-form-item label="市场"><el-select v-model="form.market" clearable placeholder="国内 / 海外" aria-label="核对市场"><el-option label="国内" value="domestic" /><el-option label="海外" value="overseas" /></el-select></el-form-item>
          <el-form-item label="软件版本适用性"><el-select v-model="form.version_applicability" aria-label="软件版本适用性"><el-option label="具体版本" value="specific" /><el-option label="不涉及软件版本" value="not_applicable" /><el-option label="尚待核实" value="unknown" /></el-select></el-form-item>
          <el-form-item label="具体软件版本"><el-input v-model="form.software_version" :disabled="form.version_applicability !== 'specific'" placeholder="如 1.14.80" aria-label="核对软件版本" maxlength="80" /></el-form-item>
        </div>
        <el-form-item label="完整机型（可多选）">
          <div class="review-models">
            <el-select v-model="form.product_model_ids" multiple filterable clearable collapse-tags collapse-tags-tooltip placeholder="选择明确适用的完整机型" aria-label="核对完整机型">
              <el-option v-for="model in availableModels" :key="model.id" :value="model.id" :label="`${model.name} · ${model.series_name}`" />
            </el-select>
            <el-button size="small" :disabled="!currentScope" @click="useCurrentScope">使用当前查询范围</el-button>
          </div>
        </el-form-item>
        <el-form-item label="确认记录或文档依据" :required="form.action !== 'defer'"><el-input v-model="form.evidence_reference" type="textarea" :rows="2" maxlength="4000" placeholder="已有负责人确认记录、正式配置版本或文档名称及位置" aria-label="确认依据" /></el-form-item>
        <div class="review-bottom">
          <el-form-item label="本次核对人" required><el-input v-model="form.confirmed_by" maxlength="100" placeholder="填写您的姓名或工作标识" aria-label="本次核对人" /></el-form-item>
          <el-form-item :label="form.action === 'defer' ? '暂缓理由' : '补充说明'" :required="form.action === 'defer'"><el-input v-model="form.note" type="textarea" :rows="2" maxlength="4000" placeholder="需要修改的内容、范围例外、注册证限制或后续待办" aria-label="核对补充说明" /></el-form-item>
        </div>
      </el-form>
    </template>
    <template #footer><el-button :disabled="saving" @click="requestClose()">关闭</el-button><el-button type="primary" :loading="saving" :disabled="saving || !question?.evidence_review?.available" @click="save">保存核对结论</el-button></template>
  </el-dialog>
</template>

<script setup>
import { questionDisplayText, answerDisplayText } from '../utils/knowledgeNames'
import { computed, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { reviewKnowledgeAnswer } from '../api/data'
import { knowledgeScopeLabel } from '../utils/knowledgeQueryScope'
import { answerReviewError, answerReviewPayload } from '../utils/knowledgeAnswerReview'

const props = defineProps({ models: { type: Array, default: () => [] }, currentScope: { type: Object, default: null } })
const emit = defineEmits(['saved'])
const visible = ref(false), saving = ref(false), question = ref(null), error = ref(''), baseline = ref(''), lastReviewer = ref('')
let sessionId = 0
const form = reactive({ action: 'record_reference', country: '', market: '', product_model_ids: [], software_version: '', version_applicability: 'unknown', evidence_reference: '', note: '', confirmed_by: '' })
const availableModels = computed(() => props.models.filter(model => !form.market || model.series_name.endsWith(form.market === 'domestic' ? '-China' : '-Oversea')))
const dirty = computed(() => JSON.stringify(form) !== baseline.value)
const open = value => {
  sessionId += 1
  question.value = JSON.parse(JSON.stringify(value))
  const latest = value.evidence_review?.latest || {}
  Object.assign(form, { action: 'record_reference', country: latest.country || '', market: latest.market || '',
    product_model_ids: [...(latest.product_model_ids || [])], software_version: latest.software_version || '',
    version_applicability: latest.version_applicability || 'unknown', evidence_reference: latest.evidence_reference || value.answer?.change_note || '',
    note: '', confirmed_by: lastReviewer.value })
  baseline.value = JSON.stringify(form)
  error.value = ''
  saving.value = false
  visible.value = true
}
const requestClose = async done => {
  if (saving.value) return
  if (dirty.value) {
    try { await ElMessageBox.confirm('核对结论尚未保存，是否放弃本次修改？', '未保存的核对结论', { confirmButtonText: '放弃修改', cancelButtonText: '继续核对', type: 'warning' }) }
    catch { return }
  }
  visible.value = false
  sessionId += 1
  if (typeof done === 'function') done()
}
const useCurrentScope = () => {
  if (!props.currentScope) return
  Object.assign(form, { market: props.currentScope.market,
    product_model_ids: [props.currentScope.product_model_id], software_version: props.currentScope.software_version, version_applicability: 'specific' })
}
const save = async () => {
  if (saving.value || !question.value?.evidence_review?.available) return
  const invalid = answerReviewError(form)
  if (invalid) { error.value = invalid; return }
  const session = sessionId
  const source = question.value
  const payload = answerReviewPayload(source, form)
  saving.value = true
  error.value = ''
  try {
    const result = await reviewKnowledgeAnswer(source.id, payload)
    if (session !== sessionId) return
    lastReviewer.value = payload.confirmed_by
    baseline.value = JSON.stringify(form)
    visible.value = false
    emit('saved', result)
    ElMessage.success(payload.action === 'defer' ? '已保存暂缓理由，仍保留待核对' : '核对结论已保存')
  } catch (failure) {
    if (session === sessionId) error.value = failure?.response?.data?.detail || '保存失败，输入已保留，请重试'
  } finally {
    if (session === sessionId) saving.value = false
  }
}
const openCitation = citation => window.open(citation.preview_url, '_blank', 'noopener')
defineExpose({ open })
</script>

<style scoped>
.review-question { font-size: 17px; margin: 0 0 6px; color: #1f2937; }
.review-meta, .review-hint { color: #64748b; font-size: 12px; }
.review-meta { margin-bottom: 10px; }
.review-original { max-height: 280px; overflow: auto; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 12px; }
.review-original pre { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; line-height: 1.65; color: #334155; }
.review-saved-text { margin-top: 8px; color: #64748b; font-size: 12px; }
.review-saved-text pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 220px; overflow: auto; font: inherit; }
.review-saved-text summary { cursor: pointer; }
.review-existing { margin: 10px 0; }
.review-existing p { margin: 4px 0; white-space: pre-wrap; }
.review-form { margin-top: 14px; }
.review-hint { width: 100%; margin: 7px 0 0; line-height: 1.5; }
.review-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; }
.review-models { display: flex; align-items: center; gap: 8px; width: 100%; flex-wrap: wrap; }
.review-models .el-select { flex: 1 1 350px; }
.review-bottom { display: grid; grid-template-columns: minmax(140px, 1fr) minmax(0, 3fr); gap: 12px; }
@media (max-width: 700px) { .review-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .review-bottom { grid-template-columns: 1fr; } }
</style>
