<template>
  <div class="knowledge-page">
    <header class="knowledge-header">
      <div>
        <h2>产品知识库</h2>
        <p>查询已确认产品知识；没有可靠答案的问题自动回流，确认后成为可复用知识。</p>
        <p class="master-data-note">
          主数据由基础数据统一维护：
          <router-link to="/feature-manage">功能管理</router-link>
          <span>·</span>
          <router-link to="/registration-manage">注册管理</router-link>
        </p>
      </div>
      <el-tag :type="stats.pending === 0 ? 'success' : 'danger'" effect="plain">
        {{ stats.pending === 0 ? '无待确认功能' : `${stats.pending} 个功能待确认` }}
      </el-tag>
    </header>

    <section class="stats-grid" v-loading="statsLoading">
      <div class="stat-card primary">
        <span class="stat-value">{{ stats.total_features }}</span>
        <span class="stat-label">功能总数</span>
      </div>
      <div class="stat-card">
        <span class="stat-value">{{ stats.auto_matched }}</span>
        <span class="stat-label">自动匹配</span>
      </div>
      <div class="stat-card">
        <span class="stat-value">{{ stats.confirmed }}</span>
        <span class="stat-label">人工确认</span>
      </div>
      <div class="stat-card">
        <span class="stat-value">{{ stats.related }}</span>
        <span class="stat-label">关系型功能</span>
      </div>
    </section>

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
                {{ qaResult.status === 'answered' ? '已有确认答案' : '等待确认' }}
              </el-tag>
              <span v-if="qaResult.match_type === 'similar'" class="similarity-note">
                相似问法匹配 {{ Math.round(qaResult.similarity * 100) }}%
              </span>
            </div>
            <span class="qa-question-text">{{ qaResult.question }}</span>
          </div>
          <template v-if="qaResult.answer">
            <p class="qa-answer-text">{{ qaResult.answer.answer_text }}</p>
            <div class="answer-meta">
              <span>版本 v{{ qaResult.answer.version }}</span>
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

        <section class="qa-queue">
          <div class="queue-heading">
            <div>
              <h3>{{ qaStatus === 'pending' ? '待确认问题' : '已发布问答' }}</h3>
              <p>{{ qaStatus === 'pending' ? '优先处理被重复询问次数较多的问题。' : '已发布内容可以修订，历史版本不会丢失。' }}</p>
            </div>
            <el-radio-group v-model="qaStatus" size="small" @change="loadQaQuestions">
              <el-radio-button value="pending">待确认</el-radio-button>
              <el-radio-button value="answered">已发布</el-radio-button>
            </el-radio-group>
          </div>
          <el-table :data="qaQuestions" v-loading="qaListLoading" border stripe empty-text="暂无问题">
            <el-table-column prop="question_text" label="问题" min-width="360" />
            <el-table-column prop="asked_count" label="询问次数" width="95" align="center" />
            <el-table-column label="答案版本" width="95" align="center">
              <template #default="scope">{{ scope.row.answer ? `v${scope.row.answer.version}` : '—' }}</template>
            </el-table-column>
            <el-table-column label="操作" width="150" align="center">
              <template #default="scope">
                <el-button type="primary" link @click="openAnswerDialog(scope.row)">
                  {{ scope.row.status === 'pending' ? '回答' : '修订' }}
                </el-button>
                <el-button v-if="scope.row.answer" link @click="showHistory(scope.row)">记录</el-button>
              </template>
            </el-table-column>
          </el-table>
        </section>
      </el-tab-pane>

      <el-tab-pane label="功能主数据" name="features">
        <section class="toolbar">
          <el-input
            v-model="featureQuery"
            data-testid="knowledge-search"
            clearable
            placeholder="搜索 IPN、中英文名称或备用名"
            :prefix-icon="Search"
            @keyup.enter="searchFeatures"
            @clear="searchFeatures"
          />
          <el-select
            v-model="identityStatus"
            data-testid="knowledge-status-filter"
            clearable
            placeholder="全部身份状态"
            @change="searchFeatures"
          >
            <el-option label="自动匹配" value="auto_matched" />
            <el-option label="人工确认" value="confirmed" />
            <el-option label="关系型功能" value="related" />
          </el-select>
          <el-button type="primary" :icon="Search" @click="searchFeatures">查询</el-button>
        </section>

        <div data-testid="feature-knowledge-list" class="feature-list" v-loading="featureLoading">
          <article v-for="feature in features" :key="feature.id" class="feature-card">
            <div class="feature-heading">
              <div>
                <div class="feature-title-row">
                  <h3>{{ feature.primary_cn_name || feature.legacy_name }}</h3>
                  <el-tag :type="statusType(feature.identity_status)" size="small" effect="plain">
                    {{ statusLabel(feature.identity_status) }}
                  </el-tag>
                </div>
                <p class="english-name">{{ feature.primary_en_name || '暂无英文主名' }}</p>
              </div>
              <span class="group-name">{{ feature.group_name }}</span>
            </div>

            <div class="ipn-list">
              <div v-for="entry in feature.ipns" :key="`${entry.ipn}-${entry.relation_type}`" class="ipn-item">
                <code>{{ entry.ipn }}</code>
                <span>{{ relationLabel(entry.relation_type) }}</span>
                <span v-if="entry.zh_desc && entry.zh_desc !== feature.primary_cn_name" class="ipn-description">
                  {{ entry.zh_desc }}
                </span>
              </div>
            </div>

            <div class="name-section aliases-by-language">
              <div class="alias-language-group">
                <span class="section-label">中文曾用名</span>
                <div class="alias-list">
                  <el-tag
                    v-for="name in aliasesByLanguage(feature, 'cn')"
                    :key="`${name.language}-${name.name}`"
                    size="small"
                    type="info"
                    effect="plain"
                  >
                    {{ name.name }}
                  </el-tag>
                  <span v-if="aliasesByLanguage(feature, 'cn').length === 0" class="empty-text">无</span>
                </div>
              </div>
              <div class="alias-language-group">
                <span class="section-label">英文曾用名</span>
                <div class="alias-list">
                  <el-tag
                    v-for="name in aliasesByLanguage(feature, 'en')"
                    :key="`${name.language}-${name.name}`"
                    size="small"
                    type="info"
                    effect="plain"
                  >
                    {{ name.name }}
                  </el-tag>
                  <span v-if="aliasesByLanguage(feature, 'en').length === 0" class="empty-text">无</span>
                </div>
              </div>
            </div>

            <div v-if="feature.identity_status === 'related'" class="relation-note">
              <el-icon><Link /></el-icon>
              <span>{{ relationNote(feature) }}</span>
            </div>
          </article>
          <el-empty v-if="!featureLoading && features.length === 0" description="未找到匹配功能" />
        </div>

        <el-pagination
          v-if="featureTotal > featureLimit"
          v-model:current-page="featurePage"
          :page-size="featureLimit"
          :total="featureTotal"
          layout="prev, pager, next, total"
          @current-change="loadFeatures"
        />
      </el-tab-pane>

      <el-tab-pane label="国内注册与策略" name="registration">
        <section class="registration-intro">
          <div>
            <div class="registration-title-row">
              <h3>国内注册探头判定</h3>
              <el-tag type="success" effect="plain">国内 / CN</el-tag>
            </div>
            <p>先执行注册红线，再读取正式选型；研发当前配置仅在没有正式选型时作为辅助信息。</p>
          </div>
          <el-button
            tag="a"
            :icon="View"
            :href="registrationSourceUrl"
            target="_blank"
            rel="noopener"
            :disabled="!registrationSourceDocumentId"
          >
            注册差异表原文
          </el-button>
        </section>

        <section class="status-legend" aria-label="配置状态图例">
          <span><strong class="status-x">X</strong> X 标配</span>
          <span><strong class="status-o">O</strong> O 选配</span>
          <span><strong class="status-tender">Δ</strong> Δ 招标支持</span>
          <span><strong class="status-blocked">#</strong> # 未注册</span>
        </section>

        <section class="registration-toolbar">
          <el-select
            v-model="selectedProductModelId"
            data-testid="registration-model-select"
            aria-label="国内产品型号"
            filterable
            placeholder="选择国内产品型号"
            @change="searchRegistrationProbes"
          >
            <el-option
              v-for="model in registrationModels"
              :key="model.product_model_id"
              :label="registrationModelLabel(model)"
              :value="model.product_model_id"
            />
          </el-select>
          <el-input
            v-model="registrationQuery"
            data-testid="registration-probe-search"
            aria-label="探头搜索"
            clearable
            placeholder="搜索探头型号、IPN 或配置名称"
            :prefix-icon="Search"
            @keyup.enter="searchRegistrationProbes"
            @clear="searchRegistrationProbes"
          />
          <el-select
            v-model="registrationStatus"
            data-testid="registration-status-filter"
            aria-label="注册状态"
            clearable
            placeholder="全部注册状态"
            @change="searchRegistrationProbes"
          >
            <el-option label="已注册" value="registered" />
            <el-option label="# 未注册" value="unregistered" />
          </el-select>
          <el-select
            v-model="effectiveStatus"
            data-testid="effective-status-filter"
            aria-label="最终判定"
            clearable
            placeholder="全部最终判定"
            @change="searchRegistrationProbes"
          >
            <el-option label="X 标配" value="X" />
            <el-option label="O 选配" value="O" />
            <el-option label="Δ 招标支持" value="Δ" />
            <el-option label="# 未注册" value="#" />
            <el-option label="未定义" value="未定义" />
          </el-select>
          <el-button type="primary" :icon="Search" @click="searchRegistrationProbes">查询</el-button>
        </section>

        <section v-if="selectedProductModelId" class="registration-context">
          <span>产品型号：<strong>{{ registrationMeta.product_model_name || '-' }}</strong></span>
          <span v-if="registrationMeta.registration_model_name">
            注册基础型号：<strong>{{ registrationMeta.registration_model_name }}</strong>
          </span>
          <el-tag v-if="isDerivedRegistrationModel" type="warning" size="small" effect="plain">
            衍生型号沿用基础型号注册
          </el-tag>
        </section>

        <section class="registration-summary" v-loading="registrationLoading">
          <div><strong>{{ registrationSummary.registered }}</strong><span>已注册</span></div>
          <div class="danger"><strong>{{ registrationSummary.unregistered }}</strong><span>未注册</span></div>
          <div><strong>{{ registrationSummary.standard }}</strong><span>标配</span></div>
          <div><strong>{{ registrationSummary.optional }}</strong><span>选配</span></div>
          <div><strong>{{ registrationSummary.tender }}</strong><span>招标支持</span></div>
          <div><strong>{{ registrationSummary.undefined }}</strong><span>策略未定义</span></div>
        </section>

        <el-table
          data-testid="registration-strategy-table"
          :data="registrationItems"
          v-loading="registrationLoading"
          border
          stripe
          empty-text="请选择型号或调整筛选条件"
          class="registration-table"
        >
          <el-table-column prop="probe_model" label="探头型号" min-width="130" fixed="left" />
          <el-table-column prop="ipn" label="IPN" min-width="115" />
          <el-table-column prop="config_name" label="配置名称" min-width="180">
            <template #default="scope">{{ scope.row.config_name || '配置系统暂无对应项' }}</template>
          </el-table-column>
          <el-table-column label="注册状态" min-width="105" align="center">
            <template #default="scope">
              <el-tag :type="scope.row.registration_status === 'registered' ? 'success' : 'danger'" effect="plain">
                {{ scope.row.registration_status === 'registered' ? '已注册' : '# 未注册' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="选型类别（正式）" min-width="135" align="center">
            <template #default="scope">{{ displayConfigStatus(scope.row.selection_config) }}</template>
          </el-table-column>
          <el-table-column label="当前配置（辅助）" min-width="135" align="center">
            <template #default="scope">{{ displayConfigStatus(scope.row.current_config) }}</template>
          </el-table-column>
          <el-table-column label="最终判定" min-width="120" align="center" fixed="right">
            <template #default="scope">
              <el-tag :type="effectiveStatusType(scope.row.effective_status)" effect="dark">
                {{ displayConfigStatus(scope.row.effective_status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="判定依据" min-width="165">
            <template #default="scope">
              <span :class="{ 'auxiliary-source': scope.row.status_source === 'current_config_aux' }">
                {{ statusSourceLabel(scope.row.status_source) }}
              </span>
              <el-tag v-if="scope.row.conflict" type="danger" size="small" class="conflict-tag">存在冲突</el-tag>
            </template>
          </el-table-column>
        </el-table>

        <el-pagination
          v-if="registrationTotal > registrationLimit"
          v-model:current-page="registrationPage"
          :page-size="registrationLimit"
          :total="registrationTotal"
          layout="prev, pager, next, total"
          @current-change="loadRegistrationProbes"
        />
      </el-tab-pane>

      <el-tab-pane label="原始资料" name="documents">
        <section class="toolbar document-toolbar">
          <el-input
            v-model="documentQuery"
            clearable
            placeholder="搜索资料名、版本或产品"
            :prefix-icon="Search"
            @keyup.enter="searchDocuments"
            @clear="searchDocuments"
          />
          <el-select v-model="documentType" clearable placeholder="全部资料类型" @change="searchDocuments">
            <el-option label="注册证/注册变更" value="registration_certificate" />
            <el-option label="注册差异表" value="registration_difference" />
            <el-option label="产品说明书" value="manual" />
            <el-option label="产品白皮书" value="whitepaper" />
            <el-option label="Release Note" value="release_note" />
          </el-select>
          <el-button type="primary" :icon="Search" @click="searchDocuments">查询</el-button>
        </section>

        <div data-testid="knowledge-document-list" class="document-list" v-loading="documentLoading">
          <article v-for="document in documents" :key="document.id" class="document-card">
            <div class="document-icon"><el-icon><Document /></el-icon></div>
            <div class="document-info">
              <div class="document-title-row">
                <h3>{{ document.title }}</h3>
                <el-tag size="small" effect="plain">{{ documentTypeLabel(document.document_type) }}</el-tag>
              </div>
              <p>{{ document.file_name }}</p>
              <div class="document-meta">
                <span v-if="document.product_series">{{ document.product_series }}</span>
                <span v-if="document.version">版本 {{ document.version }}</span>
                <span>{{ formatFileSize(document.file_size) }}</span>
                <span :class="document.available ? 'available' : 'unavailable'">
                  {{ document.available ? '原文已同步' : '原文未同步' }}
                </span>
              </div>
            </div>
            <div class="document-actions">
              <el-tag
                v-if="document.extraction_status === 'completed'"
                type="success"
                size="small"
                effect="plain"
              >
                正文已提取 · {{ document.chunk_count }}片段
              </el-tag>
              <el-button
                :loading="Boolean(extractionLoading[document.id])"
                :disabled="!document.available"
                @click="extractDocument(document)"
              >
                {{ document.extraction_status === 'completed' ? '重新提取' : '提取正文' }}
              </el-button>
              <el-button :icon="View" :disabled="!document.available" @click="previewDocument(document)">
                {{ canInline(document) ? '预览' : '打开原文' }}
              </el-button>
            </div>
          </article>
          <el-empty v-if="!documentLoading && documents.length === 0" description="暂无已登记资料" />
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-dialog
      v-model="previewVisible"
      data-testid="document-preview-dialog"
      :title="previewTitle"
      width="88%"
      top="4vh"
      destroy-on-close
    >
      <iframe v-if="previewVisible" :src="previewUrl" class="preview-frame" :title="previewTitle" />
    </el-dialog>

    <el-dialog
      v-model="answerDialogVisible"
      :title="answerForm.version ? `修订答案 v${answerForm.version + 1}` : '确认答案'"
      width="720px"
      destroy-on-close
    >
      <el-form label-position="top">
        <el-form-item label="问题">
          <div class="dialog-question">{{ answerForm.question_text }}</div>
        </el-form-item>
        <el-form-item label="正式答案" required>
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
        <el-button type="primary" :loading="answerSaving" @click="saveAnswer">确认并发布</el-button>
      </template>
    </el-dialog>

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
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Delete, Document, Link, Plus, Search, View } from '@element-plus/icons-vue'
import {
  askKnowledgeQuestion,
  extractKnowledgeDocument,
  getKnowledgeAnswerHistory,
  getKnowledgeDocuments,
  getKnowledgeDocumentPreviewUrl,
  getKnowledgeFeatures,
  getKnowledgeStats,
  getKnowledgeQuestions,
  getKnowledgeQuestionCandidates,
  publishKnowledgeAnswer,
  getConfiguredRegistrationModels,
  getRegistrationProbes
} from '../api/data'

const activeTab = ref('qa')
const stats = ref({ total_features: 0, auto_matched: 0, confirmed: 0, related: 0, pending: 0 })
const statsLoading = ref(false)

const featureQuery = ref('')
const identityStatus = ref('')
const featureLoading = ref(false)
const features = ref([])
const featureTotal = ref(0)
const featurePage = ref(1)
const featureLimit = 20

const documentQuery = ref('')
const documentType = ref('')
const documentLoading = ref(false)
const documents = ref([])
const extractionLoading = ref({})

const registrationModels = ref([])
const selectedProductModelId = ref(null)
const registrationQuery = ref('')
const registrationStatus = ref('')
const effectiveStatus = ref('')
const registrationLoading = ref(false)
const registrationItems = ref([])
const registrationTotal = ref(0)
const registrationPage = ref(1)
const registrationLimit = 100
const registrationMeta = ref({})
const registrationSourceDocumentId = ref(null)
const registrationSummary = ref({
  registered: 0,
  unregistered: 0,
  standard: 0,
  optional: 0,
  tender: 0,
  undefined: 0,
  auxiliary: 0,
  conflicts: 0
})

const previewVisible = ref(false)
const previewUrl = ref('')
const previewTitle = ref('')

const qaQuestion = ref('')
const qaAsking = ref(false)
const qaResult = ref(null)
const qaStatus = ref('pending')
const qaQuestions = ref([])
const qaListLoading = ref(false)
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
  answer_text: '',
  alias_text: '',
  citations: [],
  change_note: ''
})

const isDerivedRegistrationModel = computed(() => (
  registrationMeta.value.mapping_type
  && registrationMeta.value.mapping_type !== 'direct'
))
const registrationSourceUrl = computed(() => registrationSourceDocumentId.value
  ? getKnowledgeDocumentPreviewUrl(registrationSourceDocumentId.value)
  : '')

const statusLabel = (status) => ({
  auto_matched: '自动匹配',
  confirmed: '人工确认',
  related: '关系型功能',
  pending: '待确认'
}[status] || status)

const statusType = (status) => ({
  auto_matched: 'success',
  confirmed: 'primary',
  related: 'warning',
  pending: 'danger'
}[status] || 'info')

const relationLabel = (relation) => ({
  primary: '主 IPN',
  related: '相关功能',
  version_variant: '版本 IPN'
}[relation] || relation)

const documentTypeLabel = (type) => ({
  registration_certificate: '注册证/变更',
  registration_difference: '注册差异表',
  manual: '产品说明书',
  whitepaper: '产品白皮书',
  release_note: 'Release Note'
}[type] || type)

const registrationModelLabel = (model) => model.product_model_name === model.registration_model_name
  ? model.product_model_name
  : `${model.product_model_name} → ${model.registration_model_name}`
const displayConfigStatus = (status) => ({
  X: 'X 标配',
  O: 'O 选配',
  '∆': 'Δ 招标支持',
  'Δ': 'Δ 招标支持',
  '#': '# 未注册',
  未定义: '未定义'
}[status] || status || '—')
const effectiveStatusType = (status) => ({
  X: 'success',
  O: 'primary',
  'Δ': 'warning',
  '#': 'danger',
  未定义: 'info'
}[status] || 'info')
const statusSourceLabel = (source) => ({
  registration_redline: '注册红线',
  selection_config: '正式选型类别',
  current_config_aux: '研发当前配置（辅助）',
  missing: '尚无正式策略'
}[source] || source || '—')

const aliasesByLanguage = (feature, language) => (feature.names || []).filter(
  name => name.name_type === 'alias' && name.language === language
)
const relationNote = (feature) => (feature.ipns || []).some(entry => entry.relation_type === 'version_variant')
  ? '版本关系：保留各组 IPN 独立身份，当前名称作为关系入口。'
  : '关联功能：保留关联 IPN 的独立身份，当前名称作为查询入口。'
const canInline = (document) => document.mime_type === 'application/pdf' || document.mime_type?.startsWith('image/')
const formatFileSize = (size) => {
  if (!size) return '0 KB'
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

const loadStats = async () => {
  statsLoading.value = true
  try {
    stats.value = await getKnowledgeStats()
  } catch {
    ElMessage.error('统计信息加载失败')
  } finally {
    statsLoading.value = false
  }
}

const loadFeatures = async () => {
  featureLoading.value = true
  try {
    const result = await getKnowledgeFeatures({
      q: featureQuery.value || undefined,
      identity_status: identityStatus.value || undefined,
      skip: (featurePage.value - 1) * featureLimit,
      limit: featureLimit
    })
    features.value = result.items || []
    featureTotal.value = result.total || 0
  } catch {
    ElMessage.error('功能知识加载失败')
  } finally {
    featureLoading.value = false
  }
}

const searchFeatures = () => {
  featurePage.value = 1
  loadFeatures()
}

const loadDocuments = async () => {
  documentLoading.value = true
  try {
    const result = await getKnowledgeDocuments({
      q: documentQuery.value || undefined,
      document_type: documentType.value || undefined,
      limit: 100
    })
    documents.value = result.items || []
  } catch {
    ElMessage.error('原始资料加载失败')
  } finally {
    documentLoading.value = false
  }
}

const searchDocuments = () => loadDocuments()

const loadRegistrationModels = async () => {
  try {
    const result = await getConfiguredRegistrationModels({ country_code: 'CN' })
    registrationModels.value = result.items || []
    if (!selectedProductModelId.value && registrationModels.value.length > 0) {
      const preferred = registrationModels.value.find(model => model.product_model_name === 'VINNO 10')
      selectedProductModelId.value = (preferred || registrationModels.value[0]).product_model_id
    }
    if (selectedProductModelId.value) await loadRegistrationProbes()
  } catch {
    ElMessage.error('国内注册型号加载失败')
  }
}

const loadRegistrationProbes = async () => {
  if (!selectedProductModelId.value) return
  registrationLoading.value = true
  try {
    const result = await getRegistrationProbes({
      product_model_id: selectedProductModelId.value,
      q: registrationQuery.value || undefined,
      registration_status: registrationStatus.value || undefined,
      effective_status: effectiveStatus.value || undefined,
      skip: (registrationPage.value - 1) * registrationLimit,
      limit: registrationLimit
    })
    registrationItems.value = result.items || []
    registrationTotal.value = result.total || 0
    registrationSummary.value = result.summary || {}
    registrationSourceDocumentId.value = result.source_document_id || null
    registrationMeta.value = {
      product_model_name: result.product_model_name,
      registration_model_name: result.registration_model_name,
      mapping_type: result.mapping_type
    }
  } catch {
    ElMessage.error('注册与策略数据加载失败')
  } finally {
    registrationLoading.value = false
  }
}

const searchRegistrationProbes = () => {
  registrationPage.value = 1
  loadRegistrationProbes()
}

const previewDocument = (document) => {
  const url = getKnowledgeDocumentPreviewUrl(document.id)
  if (!canInline(document)) {
    window.open(url, '_blank', 'noopener')
    return
  }
  previewTitle.value = document.title
  previewUrl.value = url
  previewVisible.value = true
}

const askQuestion = async () => {
  const question = qaQuestion.value.trim()
  if (!question) {
    ElMessage.warning('请输入问题')
    return
  }
  qaAsking.value = true
  try {
    qaResult.value = await askKnowledgeQuestion({ question })
    if (qaResult.value.status === 'pending') {
      qaStatus.value = 'pending'
      ElMessage.info('尚无确认答案，已加入待确认问题')
    }
    await loadQaQuestions()
  } catch {
    ElMessage.error('问题查询失败')
  } finally {
    qaAsking.value = false
  }
}

const loadQaQuestions = async () => {
  qaListLoading.value = true
  try {
    const result = await getKnowledgeQuestions({ status: qaStatus.value, limit: 100 })
    qaQuestions.value = result.items || []
  } catch {
    ElMessage.error('问答队列加载失败')
  } finally {
    qaListLoading.value = false
  }
}

const openAnswerDialog = async (question) => {
  answerForm.value = {
    question_id: question.id,
    question_text: question.question_text,
    version: question.answer?.version || 0,
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
    answerCandidates.value = result.items || []
  } catch {
    ElMessage.error('材料候选依据加载失败')
  } finally {
    candidateLoading.value = false
  }
}

const addCitation = () => answerForm.value.citations.push({ document_id: null, source_ref: '', excerpt: '' })
const removeCitation = (index) => answerForm.value.citations.splice(index, 1)
const parseQuestionAliases = (value) => value.split(/\r?\n/).map(item => item.trim()).filter(Boolean)

const saveAnswer = async () => {
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
    answerDialogVisible.value = false
    qaStatus.value = 'answered'
    qaResult.value = {
      status: 'answered',
      question_id: saved.id,
      question: saved.question_text,
      match_type: 'exact',
      similarity: 1,
      answer: saved.answer
    }
    ElMessage.success('答案已确认发布')
    await loadQaQuestions()
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '答案发布失败')
  } finally {
    answerSaving.value = false
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

const extractDocument = async (document) => {
  extractionLoading.value = { ...extractionLoading.value, [document.id]: true }
  try {
    const result = await extractKnowledgeDocument(document.id, document.extraction_status === 'completed')
    ElMessage.success(`正文提取完成：${result.chunk_count} 个片段`)
    await loadDocuments()
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '正文提取失败')
  } finally {
    extractionLoading.value = { ...extractionLoading.value, [document.id]: false }
  }
}

onMounted(() => {
  loadQaQuestions()
  loadStats()
  loadFeatures()
  loadDocuments()
  loadRegistrationModels()
})
</script>

<style scoped>
.knowledge-page { max-width: 1180px; margin: 0 auto; }
.knowledge-header { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 18px; }
.knowledge-header h2 { margin: 0 0 6px; font-size: 22px; color: #1f2937; }
.knowledge-header p { margin: 0; color: #475569; font-size: 13px; }
.knowledge-header .master-data-note { margin-top: 6px; font-size: 12px; }
.knowledge-header :deep(.el-tag--success.el-tag--plain) { color: #166534; border-color: #16a34a; background: #f0fdf4; }
.master-data-note a { color: #1d4ed8; text-decoration: underline; text-underline-offset: 2px; }
.master-data-note span { margin: 0 5px; color: #94a3b8; }
.stats-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 18px; }
.stat-card { background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; padding: 15px 18px; display: flex; flex-direction: column; }
.stat-card.primary { background: linear-gradient(135deg, #ecf5ff, #fff); border-color: #bfdbfe; }
.stat-value { color: #111827; font-size: 24px; font-weight: 700; }
.stat-label { margin-top: 3px; color: #6b7280; font-size: 12px; }
.knowledge-tabs { background: #fff; border-radius: 12px; padding: 0 18px 18px; border: 1px solid #e5e7eb; }
.knowledge-tabs :deep(.el-tabs__item) { color: #475569; }
.knowledge-tabs :deep(.el-tabs__item.is-active) { color: #1d4ed8; }
.qa-ask-panel { margin: 12px 0 14px; padding: 18px; border: 1px solid #bfdbfe; border-radius: 10px; background: linear-gradient(135deg, #eff6ff, #fff); }
.qa-ask-heading, .queue-heading, .qa-result-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.qa-ask-heading { margin-bottom: 12px; }
.qa-ask-heading h3, .queue-heading h3 { margin: 0; color: #1f2937; font-size: 16px; }
.qa-ask-heading p, .queue-heading p { margin: 5px 0 0; color: #475569; font-size: 12px; }
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
.queue-heading { align-items: center; margin-bottom: 11px; }
.qa-queue :deep(.el-radio-button__inner) { color: #475569; }
.qa-queue :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) { color: #fff; background: #1d4ed8; border-color: #1d4ed8; }
.qa-queue :deep(.el-table .cell), .qa-queue :deep(.el-table__empty-text) { color: #334155; }
.dialog-question { width: 100%; padding: 10px 12px; border-radius: 7px; background: #f8fafc; color: #334155; }
.citation-editor { display: flex; flex-direction: column; gap: 9px; width: 100%; }
.citation-editor-row { display: grid; grid-template-columns: 1.1fr 0.8fr 1.2fr auto; gap: 8px; }
.dialog-candidates { width: 100%; min-height: 48px; }
.dialog-candidate-card { margin-top: 8px; padding: 10px 12px; border: 1px solid #fde68a; border-radius: 7px; background: #fffbeb; }
.dialog-candidate-card > div { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.dialog-candidate-card span { color: #92400e; font-size: 11px; }
.dialog-candidate-card p { max-height: 120px; margin: 7px 0; overflow: auto; color: #475569; font-size: 12px; line-height: 1.6; white-space: pre-wrap; }
.document-actions { display: flex; align-items: center; gap: 8px; }
.el-timeline p { margin: 6px 0 0; color: #475569; line-height: 1.6; white-space: pre-wrap; }
.toolbar { display: grid; grid-template-columns: minmax(320px, 1fr) 190px auto; gap: 10px; margin: 10px 0 16px; }
.feature-list, .document-list { display: flex; flex-direction: column; gap: 10px; min-height: 180px; }
.feature-card, .document-card { border: 1px solid #e5e7eb; border-radius: 9px; padding: 15px 16px; background: #fff; }
.feature-card:hover, .document-card:hover { border-color: #bfdbfe; box-shadow: 0 3px 14px rgba(30, 64, 175, 0.06); }
.feature-heading, .feature-title-row, .document-title-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.feature-title-row, .document-title-row { justify-content: flex-start; }
.feature-card h3, .document-card h3 { margin: 0; font-size: 15px; color: #1f2937; }
.english-name, .document-info p { margin: 4px 0 0; color: #6b7280; font-size: 12px; }
.group-name { color: #6b7280; background: #f3f4f6; border-radius: 12px; padding: 3px 9px; font-size: 12px; }
.ipn-list { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 13px; }
.ipn-item { display: flex; align-items: center; gap: 7px; background: #f8fafc; border-radius: 6px; padding: 6px 9px; font-size: 12px; color: #64748b; }
.ipn-item code { color: #1d4ed8; font-weight: 600; }
.ipn-description { border-left: 1px solid #dbe3ef; padding-left: 7px; }
.name-section { display: flex; align-items: flex-start; gap: 12px; margin-top: 12px; }
.aliases-by-language { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px 20px; }
.alias-language-group { display: flex; align-items: flex-start; gap: 10px; min-width: 0; }
.section-label { min-width: 66px; padding-top: 3px; color: #6b7280; font-size: 12px; }
.alias-list { display: flex; flex-wrap: wrap; gap: 6px; }
.empty-text { color: #9ca3af; font-size: 12px; }
.relation-note { display: flex; align-items: center; gap: 6px; margin-top: 11px; color: #92400e; font-size: 12px; }
.document-card { display: flex; align-items: center; gap: 14px; }
.document-icon { width: 42px; height: 42px; border-radius: 9px; display: grid; place-items: center; background: #eff6ff; color: #2563eb; font-size: 20px; }
.document-info { flex: 1; min-width: 0; }
.document-meta { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 7px; color: #6b7280; font-size: 11px; }
.available { color: #15803d; }
.unavailable { color: #b91c1c; }
.registration-intro { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; margin: 12px 0; padding: 14px 16px; border: 1px solid #dbeafe; border-radius: 9px; background: #f8fbff; }
.registration-title-row { display: flex; align-items: center; gap: 9px; }
.registration-title-row h3 { margin: 0; color: #1f2937; font-size: 15px; }
.registration-intro p { margin: 6px 0 0; color: #64748b; font-size: 12px; }
.status-legend { display: flex; flex-wrap: wrap; gap: 8px 18px; margin-bottom: 12px; color: #475569; font-size: 12px; }
.status-legend span { display: flex; align-items: center; gap: 5px; }
.status-legend strong { display: inline-grid; place-items: center; width: 20px; height: 20px; border-radius: 5px; color: #fff; }
.status-x { background: #15803d; }
.status-o { background: #2563eb; }
.status-tender { background: #92400e; }
.status-blocked { background: #dc2626; }
.registration-toolbar { display: grid; grid-template-columns: minmax(190px, 1.1fr) minmax(220px, 1.4fr) 150px 150px auto; gap: 9px; margin-bottom: 12px; }
.registration-context { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 18px; margin-bottom: 12px; color: #64748b; font-size: 12px; }
.registration-context strong { color: #1f2937; }
.registration-summary { display: grid; grid-template-columns: repeat(6, minmax(90px, 1fr)); gap: 8px; margin-bottom: 12px; }
.registration-summary div { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; padding: 10px 12px; border: 1px solid #e5e7eb; border-radius: 8px; background: #fff; }
.registration-summary strong { color: #1f2937; font-size: 19px; }
.registration-summary span { color: #64748b; font-size: 11px; }
.registration-summary .danger strong { color: #dc2626; }
.registration-table { width: 100%; }
.registration-intro :deep(.el-tag--success.el-tag--plain) { color: #166534; border-color: #86efac; }
.registration-intro :deep(.el-button) { color: #334155; }
.registration-toolbar :deep(.el-button--primary) { background: #1d4ed8; border-color: #1d4ed8; }
.registration-context :deep(.el-tag--warning.el-tag--plain) { color: #92400e; border-color: #f59e0b; }
.registration-table :deep(th.el-table__cell .cell) { color: #374151; }
.registration-table :deep(.el-tag--success.el-tag--plain) { color: #166534; border-color: #86efac; background: #f0fdf4; }
.registration-table :deep(.el-tag--danger.el-tag--plain) { color: #b91c1c; border-color: #fca5a5; background: #fef2f2; }
.registration-table :deep(.el-tag--success.el-tag--dark) { background: #15803d; border-color: #15803d; }
.registration-table :deep(.el-tag--primary.el-tag--dark) { background: #1d4ed8; border-color: #1d4ed8; }
.registration-table :deep(.el-tag--warning.el-tag--dark) { background: #92400e; border-color: #92400e; }
.registration-table :deep(.el-tag--danger.el-tag--dark) { background: #b91c1c; border-color: #b91c1c; }
.registration-table :deep(.el-tag--info.el-tag--dark) { background: #475569; border-color: #475569; }
.auxiliary-source { color: #b45309; }
.conflict-tag { display: block; width: fit-content; margin-top: 4px; }
.preview-frame { width: 100%; height: 78vh; border: 0; background: #f3f4f6; }
.el-pagination { justify-content: flex-end; margin-top: 16px; }
@media (max-width: 850px) {
  .stats-grid { grid-template-columns: repeat(2, 1fr); }
  .toolbar, .registration-toolbar { grid-template-columns: 1fr; }
  .registration-summary { grid-template-columns: repeat(2, 1fr); }
  .registration-intro { flex-direction: column; }
  .aliases-by-language { grid-template-columns: 1fr; }
  .knowledge-header { flex-direction: column; gap: 10px; }
}
</style>
