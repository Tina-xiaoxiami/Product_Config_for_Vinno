<template>
  <div class="knowledge-page">
    <el-tabs v-model="activeTab" class="knowledge-tabs">
      <el-tab-pane label="问答查询" name="qa">
        <section class="qa-ask-panel">
          <div class="qa-ask-heading">
            <div>
              <h3>直接提问</h3>
              <p>系统只复用已经确认发布的答案；查不到时进入待确认队列，系统不会猜测。</p>
            </div>
            <el-tag type="success" effect="plain">受控知识</el-tag>
          </div>
          <div class="qa-scope-controls" data-testid="knowledge-query-scope">
            <el-select v-model="qaScope.market" size="small" aria-label="查询市场" placeholder="国内/海外" clearable @change="onQaMarketChange">
              <el-option label="国内" value="domestic" />
              <el-option label="海外" value="overseas" />
            </el-select>
            <el-select v-model="qaScope.product_model_id" size="small" aria-label="查询完整机型" placeholder="完整机型" filterable clearable :loading="qaModelsLoading" @change="onQaScopeChange">
              <el-option v-for="model in qaAvailableModels" :key="model.id" :label="`${model.name} · ${model.series_name}`" :value="model.id" />
            </el-select>
            <el-input v-model="qaScope.software_version" size="small" aria-label="查询软件版本" placeholder="软件版本，如 1.14.80" maxlength="80" @input="onQaScopeInput" @change="loadQaQuestions" />
          </div>
          <p class="qa-scope-note">{{ knowledgeScopePayload(qaScope) ? knowledgeScopeLabel({ ...knowledgeScopePayload(qaScope), model_name: qaModels.find(model => model.id === qaScope.product_model_id)?.name }) : '请明确市场、完整机型和软件版本；历史答案不会自动套用到所选范围。' }}</p>
          <el-alert v-if="qaModelsError" type="error" :closable="false" title="机型目录加载失败，请重试后查询">
            <el-button link @click="loadQaModels">重新加载</el-button>
          </el-alert>
          <el-input
            v-model="qaQuestion"
            data-testid="knowledge-question-input"
            type="textarea"
            :rows="3"
            maxlength="500"
            show-word-limit
            placeholder="例如：针增益调节这个功能是招标功能吗？"
            @keyup.ctrl.enter="askQuestion"
          />
          <div class="qa-ask-actions">
            <span>Ctrl + Enter 快速提问</span>
            <el-button
              data-testid="ask-knowledge-question"
              type="primary"
              :icon="Search"
              :loading="qaAsking"
              @click="askQuestion"
            >
              查询答案
            </el-button>
          </div>
        </section>

        <article v-if="qaResult" class="qa-result" :class="qaResult.status">
          <div class="qa-result-heading">
            <div>
              <el-tag :type="qaResult.status === 'answered' ? 'success' : 'warning'" effect="dark">
                {{ qaResult.status === 'answered' ? '已有确认答案' : qaResult.status === 'needs_clarification' ? '请补充查询范围' : '等待确认' }}
              </el-tag>
              <span v-if="qaResult.match_type === 'similar'" class="similarity-note">
                相似问法匹配 {{ Math.round(qaResult.similarity * 100) }}%
              </span>
            </div>
            <span class="qa-question-text">{{ questionDisplayText(qaResult) }}</span>
          </div>
          <template v-if="qaResult.answer">
            <p class="qa-answer-text">{{ answerDisplayText(qaResult.answer) }}</p>
            <div class="answer-meta">
              <span>版本 v{{ qaResult.answer.version }}</span>
              <span v-if="qaResult.matched_scope?.country">答案来源国家 {{ qaResult.matched_scope.country }}</span>
              <span v-if="qaResult.answer.change_note">{{ qaResult.answer.change_note }}</span>
            </div>
            <div class="citation-section">
              <span class="section-label">答案依据</span>
              <div v-if="qaResult.answer.citations.length" class="citation-list">
                <button
                  v-for="citation in qaResult.answer.citations"
                  :key="citation.id"
                  type="button"
                  class="citation-link"
                  @click="openCitation(citation)"
                >
                  <strong>{{ citation.document_title }}</strong>
                  <span v-if="citation.source_ref">{{ citation.source_ref }}</span>
                  <small v-if="citation.excerpt">{{ citation.excerpt }}</small>
                </button>
              </div>
              <span v-else class="empty-text">本答案由产品负责人确认，暂未绑定原文位置</span>
            </div>
          </template>
          <template v-else-if="qaResult.status === 'needs_clarification'">
            <p class="qa-pending-text">请补齐市场、完整机型和软件版本后重新查询；本次未创建问题或计入询问次数。</p>
          </template>
          <template v-else>
            <p class="qa-pending-text">当前没有已确认答案，问题已记录。你可以在下方“待确认问题”中补充并发布。</p>
            <div v-if="qaResult.candidates?.length" class="candidate-evidence">
              <div class="candidate-heading">
                <div>
                  <h4>材料候选依据</h4>
                  <p>以下内容来自已提取的原始资料；候选内容不能直接作为正式结论，需由你确认。</p>
                </div>
              </div>
              <button
                v-for="candidate in qaResult.candidates"
                :key="candidate.chunk_id"
                type="button"
                class="candidate-card"
                @click="openCitation(candidate)"
              >
                <span>
                  <strong>{{ candidate.document_title }}</strong>
                  <small>{{ candidate.source_ref }} · 匹配 {{ Math.round(candidate.score * 100) }}%</small>
                </span>
                <p>{{ candidate.excerpt }}</p>
              </button>
            </div>
          </template>
        </article>

        <KnowledgeHistoryTrace v-if="qaResult?.history_trace" :trace="qaResult.history_trace" />

        <section class="qa-queue">
          <div class="qa-queue-scope">
            <el-radio-group v-model="qaQueueMode" size="small" aria-label="问题列表范围" @change="onQaQueueModeChange">
              <el-radio-button value="selected">当前查询范围</el-radio-button>
              <el-radio-button value="legacy">历史范围待核实</el-radio-button>
              <el-radio-button value="review">答案核对</el-radio-button>
            </el-radio-group>
            <el-button data-testid="qa-needs-review" size="small" :type="qaQueueMode === 'review' && qaEvidenceFilter === 'needs_review' ? 'primary' : 'default'" @click="showPendingAnswerReviews">待核对<span v-if="qaReviewCount !== null"> {{ qaReviewCount }}</span></el-button>
            <span>{{ qaQueueMode === 'review' ? '跨范围维护；逐项查看原答案、已有确认记录与本次核对结论。' : qaQueueMode === 'legacy' ? '保留原问题、答案与历史记录，核实范围后再用于正式查询。' : knowledgeScopePayload(qaScope) ? '仅列出当前范围的问题。' : '补齐查询范围后显示对应问题。' }}</span>
          </div>
          <div class="qa-table-toolbar">
            <el-radio-group v-if="qaQueueMode !== 'review'" v-model="qaStatus" size="small" aria-label="问答发布状态" @change="searchQaQuestions">
              <el-radio-button value="pending">待确认</el-radio-button>
              <el-radio-button value="answered">已发布</el-radio-button>
            </el-radio-group>
            <el-input v-model="qaSearch" size="small" clearable placeholder="搜索问题" aria-label="搜索问答问题" @keyup.enter="searchQaQuestions" @clear="searchQaQuestions" />
            <el-button size="small" @click="searchQaQuestions">查询</el-button>
            <el-button v-if="qaSearch || qaEvidenceFilter !== 'all'" size="small" @click="clearQaFilters">清除筛选</el-button>
            <span class="qa-total">共 {{ qaTotal }} 条</span>
            <TableColumnSettings :model-value="qaColumnLayout" :defaults="QA_COLUMNS" @update:model-value="applyQaColumnLayout" />
          </div>
          <div ref="qaTableArea" class="qa-table-area">
          <el-table ref="qaTable" :key="qaColumnStructureKey" :data="qaQuestions" :height="qaTableHeight" @header-dragend="resizeQaColumn" v-loading="qaListLoading" row-key="id" border stripe size="small" data-table-id="knowledge-questions" empty-text="当前条件下暂无问题">
            <el-table-column type="expand" width="36">
              <template #default="{ row }">
                <div class="qa-expanded-answer" data-testid="qa-answer-full">
                  <h4>{{ questionDisplayText(row) }}</h4>
                  <p class="qa-answer-meta">{{ knowledgeScopeLabel(row.scope) }}<span v-if="row.answer"> · v{{ row.answer.version }} · {{ row.answer.updated_at }}</span></p>
                  <pre>{{ answerDisplayText(row.answer) || '此问题尚未填写答案。' }}</pre>
                  <div v-if="row.answer?.change_note" class="qa-expanded-note"><strong>已有确认 / 上次变更：</strong>{{ row.answer.change_note }}</div>
                  <div v-if="row.evidence_review?.latest" class="qa-expanded-note"><strong>最近核对：</strong>{{ row.evidence_review.latest.confirmed_by }} · {{ row.evidence_review.latest.reviewed_at }}<br />{{ row.evidence_review.latest.evidence_reference }}<br />{{ row.evidence_review.latest.note }}</div>
                  <el-button v-if="row.answer" size="small" type="primary" @click="openAnswerReview(row)">核对答案与范围</el-button>
                </div>
              </template>
            </el-table-column>
            <el-table-column v-for="column in qaVisibleColumns" :key="column.key" :prop="column.key" :label="column.label" :width="column.width" :min-width="30" :fixed="column.fixed ? 'left' : false">
              <template v-if="column.key === 'evidence_review'" #header>
                <span class="qa-filter-header">{{ column.label }}
                  <el-popover v-if="qaQueueMode === 'review'" trigger="click" placement="bottom-end" :width="230" :teleported="true">
                    <template #reference><el-button text size="small" class="qa-filter-button" :class="{ active: qaEvidenceFilter !== 'all' }" :icon="Filter" aria-label="核对状态筛选" :title="qaEvidenceFilter === 'all' ? '核对状态：不限' : qaEvidenceFilter === 'needs_review' ? '核对状态：待核对' : '核对状态：已核对'" /></template>
                    <div class="qa-filter-options"><span>选择后立即筛选</span><el-radio-group v-model="qaEvidenceFilter" @change="onQaEvidenceFilter"><el-radio value="all">不限</el-radio><el-radio value="needs_review">待核对</el-radio><el-radio value="reviewed">已核对</el-radio></el-radio-group></div>
                  </el-popover>
                </span>
              </template>
              <template #default="{ row }">
                <template v-if="column.key === 'answer'"><p data-testid="qa-answer-preview" class="qa-answer-preview">{{ answerDisplayText(row.answer) || '尚无答案' }}</p><el-button v-if="row.answer" size="small" link type="primary" @click="qaTable?.toggleRowExpansion(row)">全文</el-button></template>
                <el-tag v-else-if="column.key === 'evidence_review'" size="small" :type="row.evidence_review?.status === 'needs_review' ? 'warning' : 'info'" effect="plain">{{ answerReviewLabel(row) }}</el-tag>
                <span v-else-if="column.key === 'version'">{{ row.answer ? `v${row.answer.version}` : '—' }}</span>
                <span v-else>{{ column.key === 'question_text' ? questionDisplayText(row) : row[column.key] }}</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="160" fixed="right" align="center">
              <template #default="{ row }">
                <el-button v-if="row.answer" size="small" type="primary" link @click="openAnswerReview(row)">核对</el-button>
                <el-button v-if="row.scope || !row.answer" size="small" type="primary" link @click="openAnswerDialog(row)">{{ row.answer ? '修订' : '回答' }}</el-button>
                <el-button v-if="row.answer" size="small" link @click="showHistory(row)">记录</el-button>
              </template>
            </el-table-column>
          </el-table>
          </div>
          <el-pagination v-if="qaTotal" v-model:current-page="qaPage" v-model:page-size="qaPageSize" :total="qaTotal" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" size="small" class="qa-pagination" @current-change="loadQaQuestions" @size-change="searchQaQuestions" />
        </section>
      </el-tab-pane>

      <el-tab-pane label="历史版本追溯" name="history"><KnowledgeReleaseHistoryWorkspace :models="qaModels" :current-scope="knowledgeScopePayload(qaScope)" :query="qaQuestion" /></el-tab-pane>
      <el-tab-pane label="参数型答案" name="parameters"><KnowledgeParameterWorkspace /></el-tab-pane>
    </el-tabs>

    <el-dialog
      v-model="answerDialogVisible"
      :title="answerForm.version ? `修订答案 v${answerForm.version + 1}` : '确认答案'"
      width="720px"
      destroy-on-close
    >
      <el-alert
        v-if="qaReviewNotice(answerForm.review_status)"
        :title="qaReviewNotice(answerForm.review_status)"
        type="warning"
        :closable="false"
        show-icon
        data-testid="knowledge-answer-evidence-review"
      />
      <p v-if="answerForm.previous_change_note" class="answer-previous-change">上次变更说明：{{ answerForm.previous_change_note }}</p>
      <el-form label-position="top">
        <el-form-item label="问题">
          <div class="dialog-question">{{ questionDisplayText(answerForm) }}</div>
        </el-form-item>
        <el-form-item label="适用范围">
          <span>{{ knowledgeScopeLabel(answerForm.scope) }}</span>
        </el-form-item>
        <el-form-item :label="answerForm.display_answer_text && answerForm.display_answer_text !== answerForm.answer_text ? '正式答案（保存原文，保留历史名称）' : '正式答案'" required>
          <el-input v-model="answerForm.answer_text" type="textarea" :rows="5" maxlength="20000" show-word-limit />
        </el-form-item>
        <el-form-item label="相似问法 / 曾用问题">
          <el-input
            v-model="answerForm.alias_text"
            type="textarea"
            :rows="3"
            placeholder="每行一个问法；材料或同事使用任意一种问法都可以命中"
          />
        </el-form-item>
        <el-form-item v-if="answerCandidates.length || candidateLoading" label="材料候选依据">
          <div class="dialog-candidates" v-loading="candidateLoading">
            <p class="candidate-warning">候选内容不能直接作为正式结论；选择后仍需核对原文并确认答案。</p>
            <div v-for="candidate in answerCandidates" :key="candidate.chunk_id" class="dialog-candidate-card">
              <div>
                <strong>{{ candidate.document_title }}</strong>
                <span>{{ candidate.source_ref }} · 匹配 {{ Math.round(candidate.score * 100) }}%</span>
              </div>
              <p>{{ candidate.excerpt }}</p>
              <div>
                <el-button link @click="openCitation(candidate)">查看原文</el-button>
                <el-button type="primary" link @click="useCandidate(candidate)">作为答案草稿</el-button>
              </div>
            </div>
          </div>
        </el-form-item>
        <el-form-item label="答案依据">
          <div class="citation-editor">
            <div v-for="(citation, index) in answerForm.citations" :key="index" class="citation-editor-row">
              <el-select v-model="citation.document_id" filterable placeholder="选择原始资料">
                <el-option v-for="document in documents" :key="document.id" :label="document.title" :value="document.id" />
              </el-select>
              <el-input v-model="citation.source_ref" placeholder="页码、章节或表格位置" />
              <el-input v-model="citation.excerpt" placeholder="相关原文摘录（可选）" />
              <el-button :icon="Delete" circle plain type="danger" @click="removeCitation(index)" />
            </div>
            <el-button :icon="Plus" plain @click="addCitation">增加资料依据</el-button>
          </div>
        </el-form-item>
        <el-form-item label="变更说明" required>
          <el-input
            v-model="answerForm.change_note"
            placeholder="例如：产品经理首次确认；依据 1.14.80 版本修订"
            maxlength="1000"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="answerDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="answerSaving" :disabled="!answerForm.scope" @click="saveAnswer">确认并发布</el-button>
      </template>
    </el-dialog>

    <KnowledgeAnswerReviewDialog ref="answerReviewDialog" :models="qaModels" :current-scope="knowledgeScopePayload(qaScope)" @saved="onAnswerReviewSaved" />
    <el-dialog v-model="historyVisible" title="答案变更记录" width="650px">
      <el-timeline v-if="answerHistory.length">
        <el-timeline-item v-for="revision in answerHistory" :key="revision.version" :timestamp="revision.created_at">
          <strong>v{{ revision.version }} · {{ revision.change_note || '未填写变更说明' }}</strong>
          <p>{{ revision.answer_text }}</p>
        </el-timeline-item>
      </el-timeline>
      <el-empty v-else description="暂无变更记录" />
    </el-dialog>
  </div>
</template>

<script setup>
import KnowledgeHistoryTrace from '../components/KnowledgeHistoryTrace.vue'
import KnowledgeReleaseHistoryWorkspace from '../components/KnowledgeReleaseHistoryWorkspace.vue'
import KnowledgeParameterWorkspace from '../components/KnowledgeParameterWorkspace.vue' 
import { questionDisplayText, answerDisplayText } from '../utils/knowledgeNames'
import { computed, onMounted, onBeforeUnmount, nextTick, reactive, ref, watch } from 'vue'
import { useWorkspaceRefresh } from '../utils/useWorkspaceRefresh'
import { knowledgeScopePayload, knowledgeScopeLabel, knowledgeScopeFingerprint } from '../utils/knowledgeQueryScope'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Delete, Filter, Plus, Search } from '@element-plus/icons-vue'
import TableColumnSettings from '../components/TableColumnSettings.vue'
import KnowledgeAnswerReviewDialog from '../components/KnowledgeAnswerReviewDialog.vue'
import { QA_COLUMNS, answerReviewLabel } from '../utils/knowledgeAnswerReview'
import { loadColumnLayout, saveColumnLayout, normalizeColumnLayout } from '../utils/tableColumnLayout'
import {
  askKnowledgeQuestion,
  getKnowledgeAnswerHistory,
  getKnowledgeDocuments,
  getKnowledgeQuestions,
  getKnowledgeQuestionCandidates,
  publishKnowledgeAnswer,
  getModels,
  getSeriesList
} from '../api/data'

const route = useRoute()
const router = useRouter()
const activeTab = ref('qa')
watch(() => route.query.tab, (tab) => {
  if (tab === 'features') {
    router.replace({ path: '/template-features' })
  } else if (tab === 'registration') {
    router.replace({ path: '/registration-manage' })
  } else if (tab === 'documents') {
    router.replace({ path: '/release', query: { tab: 'documents' } })
  } else {
    activeTab.value = ['qa', 'history', 'parameters'].includes(tab) ? tab : 'qa'
  }
}, { immediate: true })
const documents = ref([])

const qaQuestion = ref('')
const qaScope = reactive({ market: '', product_model_id: null, software_version: '' })
const qaModels = ref([])
const qaModelsLoading = ref(false)
const qaModelsError = ref(false)
const qaQueueMode = ref('legacy')
const qaAvailableModels = computed(() => qaModels.value.filter(model => (
  !qaScope.market || model.series_name.endsWith(qaScope.market === 'domestic' ? '-China' : '-Oversea')
)))
const loadQaModels = async () => {
  qaModelsLoading.value = true
  qaModelsError.value = false
  try {
    const [models, series] = await Promise.all([getModels(null, { limit: 1000, include_disabled: true }), getSeriesList({ limit: 1000 })])
    const names = new Map((series.items || series).map(row => [row.id, row.name]))
    qaModels.value = (models.items || []).map(model => ({ ...model, series_name: names.get(model.series_id) || '' }))
  } catch {
    qaModels.value = []
    qaModelsError.value = true
  } finally {
    qaModelsLoading.value = false
  }
}
const qaAsking = ref(false)
const qaResult = ref(null)
const qaStatus = ref('answered')
const qaQuestions = ref([])
const qaListLoading = ref(false)
const qaEvidenceFilter = ref('all'), qaReviewCount = ref(null), qaSearch = ref(''), qaTotal = ref(0), qaPage = ref(1), qaPageSize = ref(20)
const qaTable = ref(null), qaTableArea = ref(null), qaTableHeight = ref(360), answerReviewDialog = ref(null)
const qaColumnStorageKey = 'knowledge-questions-column-layout-v1'
const qaColumnStorage = { getItem: key => localStorage.getItem(key), setItem: (key, value) => localStorage.setItem(key, value) }
const qaColumnLayout = ref(loadColumnLayout(qaColumnStorage, qaColumnStorageKey, QA_COLUMNS, message => ElMessage.warning(message)))
const qaVisibleColumns = computed(() => qaColumnLayout.value.filter(column => column.visible))
const qaColumnStructureKey = computed(() => qaVisibleColumns.value.map(column => `${column.key}:${column.fixed}`).join('|'))
const applyQaColumnLayout = value => { qaColumnLayout.value = normalizeColumnLayout(QA_COLUMNS, value); saveColumnLayout(qaColumnStorage, qaColumnStorageKey, qaColumnLayout.value, message => ElMessage.warning(message)) }
const resizeQaColumn = (width, _old, column) => applyQaColumnLayout(qaColumnLayout.value.map(item => item.key === column.property ? { ...item, width } : item))
const openAnswerReview = row => answerReviewDialog.value?.open(row)
const loadQaReviewCount = async () => {
  try { qaReviewCount.value = (await getKnowledgeQuestions({ status: 'answered', evidence_review: 'needs_review', limit: 1 })).total }
  catch { qaReviewCount.value = null }
}
const onAnswerReviewSaved = async () => { qaPage.value = 1; await Promise.all([loadQaQuestions(), loadQaReviewCount()]) }
const searchQaQuestions = () => { qaPage.value = 1; loadQaQuestions() }
const onQaQueueModeChange = () => { if (qaQueueMode.value !== 'review') qaEvidenceFilter.value = 'all'; searchQaQuestions() }
const onQaEvidenceFilter = () => { qaQueueMode.value = 'review'; qaStatus.value = 'answered'; searchQaQuestions() }
const showPendingAnswerReviews = () => { qaEvidenceFilter.value = 'needs_review'; onQaEvidenceFilter() }
const clearQaFilters = () => { qaSearch.value = ''; qaEvidenceFilter.value = 'all'; searchQaQuestions() }
const updateQaTableHeight = () => { if (qaTableArea.value) qaTableHeight.value = Math.max(260, window.innerHeight - Math.max(0, qaTableArea.value.getBoundingClientRect().top) - 80) }
let qaResizeObserver
const answerDialogVisible = ref(false)
const answerSaving = ref(false)
const answerHistory = ref([])
const answerCandidates = ref([])
const candidateLoading = ref(false)
const historyVisible = ref(false)
const answerForm = ref({
  question_id: null,
  question_text: '',
  version: 0,
  review_status: '',
  previous_change_note: '',
  answer_text: '',
  alias_text: '',
  citations: [],
  change_note: ''
})

const loadDocuments = async () => {
  try {
    const result = await getKnowledgeDocuments({ limit: 200 })
    documents.value = result.items || []
  } catch {
    ElMessage.error('引用资料加载失败')
  }
}

let qaAskRequestId = 0
let qaQueueRequestId = 0
const onQaScopeInput = () => {
  qaAskRequestId += 1
  qaQueueRequestId += 1
  qaResult.value = null
  qaQuestions.value = []
  qaAsking.value = false
  qaListLoading.value = false
  qaTotal.value = 0
  qaPage.value = 1
}
const onQaScopeChange = () => {
  onQaScopeInput()
  loadQaQuestions()
}
const onQaMarketChange = () => {
  qaScope.product_model_id = null
  onQaScopeChange()
}
const askQuestion = async () => {
  const question = qaQuestion.value.trim()
  if (!question) {
    ElMessage.warning('请输入问题')
    return
  }
  const scope = knowledgeScopePayload(qaScope)
  if (!scope) {
    ElMessage.warning('请补齐市场、完整机型和软件版本')
    return
  }
  const requestId = ++qaAskRequestId
  const fingerprint = knowledgeScopeFingerprint(qaScope)
  qaAsking.value = true
  qaResult.value = null
  try {
    const result = await askKnowledgeQuestion({ question, scope })
    if (requestId !== qaAskRequestId || fingerprint !== knowledgeScopeFingerprint(qaScope)) return
    qaResult.value = result
    qaQueueMode.value = 'selected'
    qaEvidenceFilter.value = 'all'
    qaPage.value = 1
    if (qaResult.value.status === 'pending') {
      qaStatus.value = 'pending'
      ElMessage.info('尚无确认答案，已加入待确认问题')
    }
    await loadQaQuestions()
  } catch (error) {
    if (requestId === qaAskRequestId && fingerprint === knowledgeScopeFingerprint(qaScope)) {
      ElMessage.error(error?.response?.data?.detail || '问题查询失败')
    }
  } finally {
    if (requestId === qaAskRequestId) qaAsking.value = false
  }
}

const loadQaQuestions = async () => {
  const requestId = ++qaQueueRequestId
  const scope = knowledgeScopePayload(qaScope)
  const mode = qaQueueMode.value
  const fingerprint = knowledgeScopeFingerprint(qaScope)
  if (mode === 'selected' && !scope) {
    qaQuestions.value = []
    qaTotal.value = 0
    qaListLoading.value = false
    return
  }
  qaListLoading.value = true
  qaQuestions.value = []
  qaTotal.value = 0
  try {
    const result = await getKnowledgeQuestions({ status: mode === 'review' ? 'answered' : qaStatus.value, limit: qaPageSize.value, skip: (qaPage.value - 1) * qaPageSize.value,
      ...(qaSearch.value.trim() ? { q: qaSearch.value.trim() } : {}),
      ...(mode === 'selected' ? scope : {}),
      ...(mode === 'review' ? { evidence_review: qaEvidenceFilter.value } : {}) })
    if (requestId !== qaQueueRequestId || mode !== qaQueueMode.value || fingerprint !== knowledgeScopeFingerprint(qaScope)) return
    qaQuestions.value = result.items || []
    qaTotal.value = result.total || 0
    nextTick(updateQaTableHeight)
  } catch {
    if (requestId === qaQueueRequestId) ElMessage.error('问答队列加载失败')
  } finally {
    if (requestId === qaQueueRequestId) qaListLoading.value = false
  }
}

const qaReviewNotice = (status) => ({
  source_changed: '引用资料原文已变化，请核对依据后重新确认答案。',
  scope_changed: '引用资料的适用范围已变化，请核对范围后重新确认答案。',
  evidence_changed: '引用原文和适用范围均已变化，请核对依据后重新确认答案。'
}[status] || '')

let answerDialogSessionId = 0
const openAnswerDialog = async (question) => {
  const dialogSession = ++answerDialogSessionId
  answerSaving.value = false
  answerForm.value = {
    question_id: question.id,
    question_text: question.question_text,
    display_question_text: question.display_question_text,
    display_answer_text: question.answer?.display_answer_text,
    scope: question.scope || null,
    version: question.answer?.version || 0,
    review_status: question.answer?.review_status || '',
    previous_change_note: question.answer?.change_note || '',
    answer_text: question.answer?.answer_text || '',
    alias_text: (question.alias_questions || []).join('\n'),
    citations: (question.answer?.citations || []).map(citation => ({
      document_id: citation.document_id,
      source_ref: citation.source_ref || '',
      excerpt: citation.excerpt || ''
    })),
    change_note: ''
  }
  answerDialogVisible.value = true
  answerCandidates.value = []
  candidateLoading.value = true
  try {
    const result = await getKnowledgeQuestionCandidates(question.id)
    if (dialogSession !== answerDialogSessionId || !answerDialogVisible.value) return
    answerCandidates.value = result.items || []
  } catch {
    if (dialogSession === answerDialogSessionId) ElMessage.error('材料候选依据加载失败')
  } finally {
    if (dialogSession === answerDialogSessionId) candidateLoading.value = false
  }
}

const addCitation = () => answerForm.value.citations.push({ document_id: null, source_ref: '', excerpt: '' })
const removeCitation = (index) => answerForm.value.citations.splice(index, 1)
const parseQuestionAliases = (value) => value.split(/\r?\n/).map(item => item.trim()).filter(Boolean)

const saveAnswer = async () => {
  if (!answerForm.value.scope) {
    ElMessage.warning('历史范围尚未核实，请在明确范围内建立问答后发布')
    return
  }
  if (!answerForm.value.answer_text.trim()) {
    ElMessage.warning('请填写正式答案')
    return
  }
  if (!answerForm.value.change_note.trim()) {
    ElMessage.warning('请填写变更说明')
    return
  }
  if (answerForm.value.citations.some(citation => !citation.document_id)) {
    ElMessage.warning('请选择答案依据对应的原始资料')
    return
  }
  answerSaving.value = true
  const dialogSession = answerDialogSessionId
  const savedScope = knowledgeScopeFingerprint(knowledgeScopePayload(answerForm.value.scope))
  try {
    const saved = await publishKnowledgeAnswer(answerForm.value.question_id, {
      answer_text: answerForm.value.answer_text.trim(),
      alias_questions: parseQuestionAliases(answerForm.value.alias_text),
      citations: answerForm.value.citations.map(citation => ({
        document_id: citation.document_id,
        source_ref: citation.source_ref.trim() || null,
        excerpt: citation.excerpt.trim() || null
      })),
      change_note: answerForm.value.change_note.trim()
    })
    if (dialogSession === answerDialogSessionId) answerDialogVisible.value = false
    if (dialogSession === answerDialogSessionId && knowledgeScopePayload(qaScope) && savedScope === knowledgeScopeFingerprint(knowledgeScopePayload(qaScope))) {
      qaStatus.value = 'answered'
      qaResult.value = {
        status: 'answered', question_id: saved.id, question: saved.question_text, display_question_text: saved.display_question_text,
        match_type: 'exact', similarity: 1, answer: saved.answer, scope: saved.scope
      }
    }
    ElMessage.success('答案已确认发布')
    await loadQaQuestions()
  } catch (error) {
    if (dialogSession === answerDialogSessionId) ElMessage.error(error?.response?.data?.detail || '答案发布失败')
  } finally {
    if (dialogSession === answerDialogSessionId) answerSaving.value = false
  }
}

const showHistory = async (question) => {
  try {
    const result = await getKnowledgeAnswerHistory(question.id)
    answerHistory.value = result.items || []
    historyVisible.value = true
  } catch {
    ElMessage.error('变更记录加载失败')
  }
}

const openCitation = (citation) => window.open(citation.preview_url, '_blank', 'noopener')

const useCandidate = (candidate) => {
  if (!answerForm.value.answer_text.trim()) answerForm.value.answer_text = candidate.excerpt
  const exists = answerForm.value.citations.some(citation => (
    citation.document_id === candidate.document_id
    && citation.source_ref === candidate.source_ref
  ))
  if (!exists) {
    answerForm.value.citations.push({
      document_id: candidate.document_id,
      source_ref: candidate.source_ref,
      excerpt: candidate.excerpt
    })
  }
  ElMessage.success('已加入答案草稿，请核对并完善表述')
}

useWorkspaceRefresh(() => Promise.all([
  loadQaModels(), loadQaQuestions(), loadDocuments(), loadQaReviewCount()
]), { canRefresh: () => !answerDialogVisible.value && !answerSaving.value })
onMounted(() => {
  window.addEventListener('resize', updateQaTableHeight)
  nextTick(() => { updateQaTableHeight(); qaResizeObserver = new ResizeObserver(updateQaTableHeight); if (qaTableArea.value) qaResizeObserver.observe(qaTableArea.value.parentElement) })
})
onBeforeUnmount(() => { window.removeEventListener('resize', updateQaTableHeight); qaResizeObserver?.disconnect() })
</script>

<style scoped>
.qa-table-toolbar { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin: 10px 0; }
.qa-table-toolbar > .el-input { max-width: 300px; min-width: 160px; flex: 1; }
.qa-table-toolbar > .el-button + .el-button { margin-left: 0; }
.qa-table-toolbar .qa-total { margin-left: auto; white-space: nowrap; }
.qa-table-area { width: 100%; min-width: 0; overflow: hidden; }
.qa-answer-preview { display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; white-space: pre-line; overflow-wrap: anywhere; margin: 0; line-height: 1.55; }
.qa-expanded-answer { padding: 10px 18px 16px; }
.qa-expanded-answer h4 { margin: 0 0 7px; font-size: 14px; }
.qa-expanded-answer pre { white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; line-height: 1.65; }
.qa-answer-meta, .qa-expanded-note, .qa-total { color: #64748b; font-size: 12px; }
.qa-expanded-note { margin: 8px 0; white-space: pre-wrap; }
.qa-filter-header { display: flex; align-items: center; justify-content: space-between; gap: 2px; }
.qa-filter-button { width: 24px; height: 24px; padding: 3px; color: #94a3b8; }
.qa-filter-button.active { color: #2563eb; }
.qa-filter-options { display: flex; flex-direction: column; gap: 6px; }
.qa-filter-options > span { color: #64748b; font-size: 12px; }
.qa-filter-options .el-radio-group { display: flex; flex-direction: column; align-items: flex-start; }
.qa-pagination { margin-top: 10px; justify-content: flex-end; }
.qa-scope-controls { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }
.qa-scope-controls > * { flex: 0 1 180px; min-width: 140px; max-width: 100%; }
.qa-scope-controls > :nth-child(2) { flex-basis: 300px; }
.qa-scope-note { font-size: 12px; color: #64748b; margin: 4px 0 10px; }
.qa-queue-scope { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
.qa-queue-scope > span { color: #64748b; font-size: 12px; }
.knowledge-page { position: relative; max-width: 1180px; margin: 0 auto; }
.knowledge-tabs { background: #fff; border-radius: 12px; padding: 0 18px 18px; border: 1px solid #e5e7eb; }
.knowledge-tabs :deep(.el-tabs__item) { color: #475569; }
.knowledge-tabs :deep(.el-tabs__item.is-active) { color: #1d4ed8; }
.qa-ask-panel { margin: 12px 0 14px; padding: 18px; border: 1px solid #bfdbfe; border-radius: 10px; background: linear-gradient(135deg, #eff6ff, #fff); }
.qa-ask-heading, .qa-result-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.qa-ask-heading { margin-bottom: 12px; }
.qa-ask-heading h3 { margin: 0; color: #1f2937; font-size: 16px; }
.qa-ask-heading p { margin: 5px 0 0; color: #475569; font-size: 12px; }
.qa-ask-actions { display: flex; align-items: center; justify-content: space-between; margin-top: 10px; color: #64748b; font-size: 11px; }
.qa-ask-panel :deep(.el-tag--success.el-tag--plain) { color: #166534; border-color: #16a34a; background: #f0fdf4; }
.qa-ask-panel :deep(.el-button--primary) { background: #1d4ed8; border-color: #1d4ed8; }
.qa-result { margin-bottom: 16px; padding: 17px 18px; border: 1px solid #bbf7d0; border-radius: 10px; background: #f0fdf4; }
.qa-result.pending { border-color: #fde68a; background: #fffbeb; }
.qa-result-heading { align-items: center; }
.qa-result-heading > div { display: flex; align-items: center; gap: 9px; }
.similarity-note, .qa-question-text, .answer-meta { color: #64748b; font-size: 12px; }
.qa-question-text { text-align: right; }
.qa-answer-text { margin: 15px 0 8px; color: #172554; font-size: 15px; line-height: 1.8; white-space: pre-wrap; }
.qa-pending-text { margin: 14px 0 0; color: #92400e; font-size: 13px; }
.candidate-evidence { margin-top: 14px; padding-top: 12px; border-top: 1px solid #fde68a; }
.candidate-heading h4 { margin: 0; color: #78350f; font-size: 14px; }
.candidate-heading p, .candidate-warning { margin: 4px 0 9px; color: #854d0e; font-size: 11px; }
.candidate-card { display: block; width: 100%; margin-top: 8px; padding: 10px 12px; border: 1px solid #fde68a; border-radius: 7px; background: #fff; color: #334155; text-align: left; cursor: pointer; }
.candidate-card > span { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.candidate-card small { color: #92400e; }
.candidate-card p { margin: 7px 0 0; color: #475569; font-size: 12px; line-height: 1.6; white-space: pre-wrap; }
.answer-meta { display: flex; gap: 14px; }
.citation-section { display: flex; align-items: flex-start; gap: 12px; margin-top: 14px; padding-top: 12px; border-top: 1px solid rgba(148, 163, 184, 0.25); }
.citation-list { display: flex; flex-direction: column; gap: 7px; flex: 1; }
.citation-link { display: grid; grid-template-columns: minmax(180px, 1fr) auto; gap: 4px 12px; width: 100%; padding: 9px 11px; border: 1px solid #dbeafe; border-radius: 7px; background: #fff; color: #1d4ed8; text-align: left; cursor: pointer; }
.citation-link small { grid-column: 1 / -1; color: #64748b; }
.qa-queue { margin-top: 16px; }
.qa-queue :deep(.el-radio-button__inner) { color: #475569; }
.qa-queue :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) { color: #fff; background: #1d4ed8; border-color: #1d4ed8; }
.qa-queue :deep(.el-table .cell), .qa-queue :deep(.el-table__empty-text) { color: #334155; }
.answer-previous-change { margin: 10px 0; color: #64748b; font-size: 12px; }
.dialog-question { width: 100%; padding: 10px 12px; border-radius: 7px; background: #f8fafc; color: #334155; }
.citation-editor { display: flex; flex-direction: column; gap: 9px; width: 100%; }
.citation-editor-row { display: grid; grid-template-columns: 1.1fr 0.8fr 1.2fr auto; gap: 8px; }
.dialog-candidates { width: 100%; min-height: 48px; }
.dialog-candidate-card { margin-top: 8px; padding: 10px 12px; border: 1px solid #fde68a; border-radius: 7px; background: #fffbeb; }
.dialog-candidate-card > div { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.dialog-candidate-card span { color: #92400e; font-size: 11px; }
.dialog-candidate-card p { max-height: 120px; margin: 7px 0; overflow: auto; color: #475569; font-size: 12px; line-height: 1.6; white-space: pre-wrap; }
.el-timeline p { margin: 6px 0 0; color: #475569; line-height: 1.6; white-space: pre-wrap; }
.section-label { min-width: 66px; padding-top: 3px; color: #6b7280; font-size: 12px; }
.el-pagination { justify-content: flex-end; margin-top: 16px; }
</style>
