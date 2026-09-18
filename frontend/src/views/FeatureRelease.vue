<template>
  <div class="feature-release">
    <header class="release-header">
      <div>
        <h2>功能发布</h2>
        <p class="release-subtitle">
          功能版本、发布日期与发布介绍以功能（IPN）为身份单独管理；首发版本只由已确认的版本记录得出。
        </p>
      </div>
      <el-button
        type="primary"
        data-testid="release-create-version"
        @click="openCreateDialog"
      >
        手工登记功能版本
      </el-button>
    </header>

    <el-tabs v-model="activeTab" class="release-tabs">
      <el-tab-pane label="功能版本查询" name="timeline">
        <section class="release-panel">
          <div class="release-search">
            <el-input
              v-model="featureQuery"
              data-testid="release-feature-search"
              aria-label="按功能名称或 IPN 搜索"
              placeholder="搜索功能名称、曾用名或 IPN，例如 SMF / 6000273"
              clearable
              @keyup.enter="searchFeatures"
            />
            <el-input
              v-model="seriesFilter"
              data-testid="release-series-filter"
              aria-label="按产品系列过滤"
              placeholder="产品系列（例如 V10，可留空）"
              clearable
              style="width: 200px"
              @keyup.enter="loadTimeline"
            />
            <el-button type="primary" :loading="featureLoading" @click="searchFeatures">
              查询功能
            </el-button>
          </div>

          <el-table
            v-if="featureOptions.length"
            :data="featureOptions"
            border
            stripe
            max-height="260"
            @row-click="selectFeature"
          >
            <el-table-column prop="legacy_name" label="功能名称" min-width="160" />
            <el-table-column prop="primary_cn_name" label="中文主名" min-width="160" />
            <el-table-column prop="primary_en_name" label="英文主名" min-width="160" />
            <el-table-column label="IPN" width="140">
              <template #default="{ row }">{{ primaryIpn(row) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="110">
              <template #default="{ row }">
                <el-button link type="primary" @click.stop="selectFeature(row)">
                  查看发布版本
                </el-button>
              </template>
            </el-table-column>
          </el-table>

          <div v-if="timeline" class="timeline-result" data-testid="release-timeline">
            <div class="timeline-heading">
              <h3>
                {{ timeline.feature.primary_cn_name || timeline.feature.legacy_name }}
                <small>{{ primaryIpn(timeline.feature) || '无 IPN' }}</small>
              </h3>
              <el-tag v-if="timeline.first_release" type="success" data-testid="release-first-version">
                首发版本 {{ timeline.first_release.software_version }}
              </el-tag>
              <el-tag
                v-else-if="timeline.first_release_candidate"
                type="warning"
                data-testid="release-first-candidate"
              >
                首发候选 {{ timeline.first_release_candidate.software_version }}（待确认）
              </el-tag>
              <el-tag v-else type="info">尚无版本记录</el-tag>
            </div>

            <el-alert
              v-if="timeline.coverage_note"
              class="coverage-note"
              type="warning"
              :closable="false"
              show-icon
              :title="timeline.coverage_note"
            />
            <el-alert
              class="coverage-note"
              type="info"
              :closable="false"
              show-icon
              title="Release Note 正文没有发布日期，发布日期需要人工确认后填写。"
            />

            <el-table :data="timeline.items" border stripe>
              <el-table-column prop="software_version" label="软件版本" width="110" />
              <el-table-column label="产品系列" width="150">
                <template #default="{ row }">{{ row.product_series || '未指定' }}</template>
              </el-table-column>
              <el-table-column label="变更" width="110">
                <template #default="{ row }">
                  <el-tag :type="changeTagType(row.change_type)" size="small">
                    {{ changeLabel(row.change_type) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="配置口径" min-width="180">
                <template #default="{ row }">{{ row.configuration_status || '-' }}</template>
              </el-table-column>
              <el-table-column label="生命周期" width="110">
                <template #default="{ row }">{{ lifecycleLabel(row.lifecycle_status) }}</template>
              </el-table-column>
              <el-table-column label="发布日期" width="130">
                <template #default="{ row }">
                  <span v-if="row.release_date">{{ row.release_date }}</span>
                  <el-button v-else link type="primary" @click="editVersion(row)">
                    待填写
                  </el-button>
                </template>
              </el-table-column>
              <el-table-column label="复核" width="100">
                <template #default="{ row }">
                  <el-tag :type="reviewTagType(row.review_status)" size="small">
                    {{ reviewLabel(row.review_status) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="证据" min-width="200">
                <template #default="{ row }">
                  <div v-if="row.evidence_document_title">
                    <el-button link type="primary" @click="openDocument(row.preview_url)">
                      {{ row.evidence_document_title }}
                    </el-button>
                    <small>{{ row.evidence_source_ref }} · {{ evidenceKindLabel(row.evidence_kind) }}</small>
                  </div>
                  <span v-else>手工登记</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="230">
                <template #default="{ row }">
                  <el-button
                    v-if="row.review_status !== 'confirmed'"
                    link
                    type="primary"
                    @click="confirmVersion(row)"
                  >
                    确认
                  </el-button>
                  <el-button
                    v-if="row.review_status !== 'rejected'"
                    link
                    type="danger"
                    @click="rejectVersion(row)"
                  >
                    驳回
                  </el-button>
                  <el-button link @click="editVersion(row)">编辑</el-button>
                  <el-button link @click="openIntroduction(row)">发布介绍</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>

          <el-empty
            v-else-if="!featureLoading"
            description="先搜索并选择一个功能，查看它的发布版本"
          />
        </section>
      </el-tab-pane>

      <el-tab-pane label="按版本查询" name="version">
        <section class="release-panel">
          <div class="release-search">
            <el-select
              v-model="versionFilter"
              data-testid="release-version-filter"
              aria-label="选择软件版本"
              placeholder="选择软件版本"
              clearable
              style="width: 220px"
              @change="loadVersions"
            >
              <el-option
                v-for="item in versionOptions"
                :key="item.software_version"
                :label="`${item.software_version}（已确认 ${item.confirmed} / 待复核 ${item.pending}）`"
                :value="item.software_version"
              />
            </el-select>
            <el-select
              v-model="reviewFilter"
              data-testid="release-review-filter"
              aria-label="按复核状态过滤"
              placeholder="全部状态"
              clearable
              style="width: 160px"
              @change="loadVersions"
            >
              <el-option label="已确认" value="confirmed" />
              <el-option label="待复核" value="pending" />
              <el-option label="已驳回" value="rejected" />
            </el-select>
            <el-button type="primary" :loading="versionLoading" @click="loadVersions">
              查询
            </el-button>
          </div>

          <el-table v-if="versions.length" :data="versions" border stripe>
            <el-table-column prop="software_version" label="软件版本" width="110" />
            <el-table-column label="功能" min-width="180">
              <template #default="{ row }">
                {{ row.feature_primary_cn_name || row.feature_name }}
              </template>
            </el-table-column>
            <el-table-column label="IPN" width="130">
              <template #default="{ row }">{{ row.feature_ipn || '-' }}</template>
            </el-table-column>
            <el-table-column label="变更" width="100">
              <template #default="{ row }">
                <el-tag :type="changeTagType(row.change_type)" size="small">
                  {{ changeLabel(row.change_type) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="release_date" label="发布日期" width="120" />
            <el-table-column label="复核" width="100">
              <template #default="{ row }">
                <el-tag :type="reviewTagType(row.review_status)" size="small">
                  {{ reviewLabel(row.review_status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="证据" min-width="180">
              <template #default="{ row }">
                {{ row.evidence_document_title || '手工登记' }}
                <small v-if="row.evidence_source_ref"> · {{ row.evidence_source_ref }}</small>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-else description="该版本尚无功能版本记录" />
          <p class="release-total" v-if="versionTotal">共 {{ versionTotal }} 条</p>
        </section>
      </el-tab-pane>

      <el-tab-pane label="发布介绍" name="introduction">
        <section class="release-panel">
          <el-empty
            v-if="!introVersion"
            description="在「功能版本查询」里选择一个版本后，再维护它的发布介绍"
          />
          <div v-else>
            <div class="timeline-heading">
              <h3>
                发布介绍
                <small>
                  {{ introVersion.feature_primary_cn_name || introVersion.feature_name || introFeatureName }}
                  · {{ introVersion.software_version }}
                </small>
              </h3>
              <el-tag :type="introForm.review_status === 'published' ? 'success' : 'info'">
                {{ introForm.review_status === 'published' ? '已发布' : '草稿' }}
              </el-tag>
            </div>

            <el-form label-width="110px" class="intro-form">
              <el-form-item label="功能概述">
                <el-input
                  v-model="introForm.summary"
                  data-testid="release-intro-summary"
                  type="textarea"
                  :rows="3"
                  placeholder="简要描述功能的主要作用和特点"
                />
              </el-form-item>
              <el-form-item label="临床意义">
                <el-input
                  v-model="introForm.clinical_significance"
                  type="textarea"
                  :rows="3"
                  placeholder="描述该功能的临床应用价值、解决的问题"
                />
              </el-form-item>
              <el-form-item label="工作流程">
                <el-input
                  v-model="introForm.workflow"
                  type="textarea"
                  :rows="3"
                  placeholder="描述操作步骤和使用流程"
                />
              </el-form-item>
              <el-form-item label="适用范围">
                <el-input
                  v-model="introApplications"
                  data-testid="release-intro-applications"
                  type="textarea"
                  :rows="3"
                  placeholder="每行一个应用场景，如：腹部 / 产科 / 妇科"
                />
              </el-form-item>
              <el-form-item label="变更说明">
                <el-input v-model="introForm.change_note" placeholder="本次修改的原因" />
              </el-form-item>
              <el-form-item label="状态">
                <el-switch
                  v-model="publishedSwitch"
                  data-testid="release-intro-publish"
                  active-text="发布"
                  inactive-text="草稿"
                />
              </el-form-item>
              <el-form-item>
                <el-button
                  type="primary"
                  :loading="introSaving"
                  data-testid="release-intro-save"
                  @click="saveIntroduction"
                >
                  保存发布介绍
                </el-button>
                <el-button @click="loadIntroductionHistory">查看历史版本</el-button>
              </el-form-item>
            </el-form>

            <div class="intro-attachments">
              <div class="timeline-heading">
                <h4>附件</h4>
                <el-upload
                  :show-file-list="false"
                  :before-upload="uploadAttachment"
                  accept="image/*,video/*,.pdf,.doc,.docx"
                >
                  <el-button size="small">上传附件</el-button>
                </el-upload>
              </div>
              <el-table v-if="introAttachments.length" :data="introAttachments" border size="small">
                <el-table-column prop="file_name" label="文件名" min-width="180" />
                <el-table-column prop="mime_type" label="类型" width="150" />
                <el-table-column label="大小" width="110">
                  <template #default="{ row }">{{ formatSize(row.file_size) }}</template>
                </el-table-column>
                <el-table-column label="操作" width="100">
                  <template #default="{ row }">
                    <el-button link type="danger" @click="removeAttachment(row)">删除</el-button>
                  </template>
                </el-table-column>
              </el-table>
              <el-empty v-else description="暂无附件" :image-size="60" />
            </div>

            <el-table v-if="introHistory.length" :data="introHistory" border size="small">
              <el-table-column label="版本" width="90">
                <template #default="{ row }">
                  v{{ row.version }}
                  <el-tag v-if="row.is_current" size="small" type="success">当前</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="summary" label="功能概述" min-width="200" />
              <el-table-column prop="change_note" label="变更说明" min-width="140" />
              <el-table-column prop="created_at" label="时间" width="180" />
            </el-table>
          </div>
        </section>
      </el-tab-pane>

      <el-tab-pane label="候选回填" name="backfill">
        <section class="release-panel">
          <p class="release-subtitle">
            候选来自 Release Note 的「配置变更」表与正文，全部以待复核状态落库；
            目录行不作为证据，「资料中最早出现」也不等于首发版本。
          </p>
          <div class="release-search">
            <el-input
              v-model="backfillSeries"
              data-testid="release-backfill-series"
              aria-label="限定产品系列"
              placeholder="限定产品系列（可留空）"
              style="width: 220px"
            />
            <el-button
              type="primary"
              :loading="backfillLoading"
              data-testid="release-backfill-preview"
              @click="previewBackfill"
            >
              生成候选（只预览）
            </el-button>
            <el-button
              :disabled="!backfillResult || !backfillResult.applicable"
              :loading="backfillApplying"
              data-testid="release-backfill-apply"
              @click="applyBackfill"
            >
              全部落库为待复核
            </el-button>
          </div>

          <el-alert
            v-if="backfillResult"
            class="coverage-note"
            type="warning"
            :closable="false"
            show-icon
            :title="backfillResult.coverage_note || '无覆盖边界说明'"
          />
          <p v-if="backfillResult" class="release-total">
            候选 {{ backfillResult.total }} 条，可落库 {{ backfillResult.applicable }} 条，
            已存在 {{ backfillResult.skipped }} 条
          </p>

          <el-table v-if="backfillResult?.candidates?.length" :data="backfillResult.candidates" border stripe max-height="520">
            <el-table-column label="首发候选" width="100">
              <template #default="{ row }">
                <el-tag v-if="row.is_first_release_candidate" type="success" size="small">首发</el-tag>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column label="功能" min-width="170">
              <template #default="{ row }">
                {{ row.feature_primary_cn_name || row.feature_name }}
              </template>
            </el-table-column>
            <el-table-column prop="software_version" label="版本" width="100" />
            <el-table-column label="系列" width="140">
              <template #default="{ row }">{{ row.product_series || '未指定' }}</template>
            </el-table-column>
            <el-table-column label="变更" width="100">
              <template #default="{ row }">
                <el-tag :type="changeTagType(row.change_type)" size="small">
                  {{ changeLabel(row.change_type) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="证据类型" width="130">
              <template #default="{ row }">{{ evidenceKindLabel(row.evidence_kind) }}</template>
            </el-table-column>
            <el-table-column label="命中方式" width="100">
              <template #default="{ row }">{{ row.matched_by }}</template>
            </el-table-column>
            <el-table-column label="原文依据" min-width="260">
              <template #default="{ row }">
                <div>{{ row.evidence_excerpt }}</div>
                <small>{{ row.evidence_document_title }} · {{ row.evidence_source_ref }}</small>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="140">
              <template #default="{ row }">
                <el-tag v-if="row.skip_reason" type="info" size="small">{{ row.skip_reason }}</el-tag>
                <el-tag v-else type="warning" size="small">待落库</el-tag>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-else-if="!backfillLoading" description="尚未生成候选" />
        </section>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="createDialogVisible" title="手工登记功能版本" width="560px">
      <el-form label-width="110px">
        <el-form-item label="功能">
          <el-select
            v-model="createForm.feature_id"
            filterable
            remote
            :remote-method="searchFeaturesForDialog"
            placeholder="搜索功能名称或 IPN"
            style="width: 100%"
          >
            <el-option
              v-for="feature in featureOptions"
              :key="feature.id"
              :label="`${feature.primary_cn_name || feature.legacy_name}（${primaryIpn(feature) || '无 IPN'}）`"
              :value="feature.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="软件版本">
          <el-input v-model="createForm.software_version" placeholder="例如 1.14.80" />
        </el-form-item>
        <el-form-item label="产品系列">
          <el-input v-model="createForm.product_series" placeholder="例如 V10 / ULTIMUS Series" />
        </el-form-item>
        <el-form-item label="发布日期">
          <el-date-picker
            v-model="createForm.release_date"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="需人工确认"
          />
        </el-form-item>
        <el-form-item label="变更类型">
          <el-select v-model="createForm.change_type">
            <el-option
              v-for="item in changeTypeOptions"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="配置口径">
          <el-input v-model="createForm.configuration_status" placeholder="例如 选配 / 标配 / 招标支持" />
        </el-form-item>
        <el-form-item label="生命周期">
          <el-select v-model="createForm.lifecycle_status">
            <el-option
              v-for="item in lifecycleOptions"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="依据资料">
          <el-select v-model="createForm.evidence_document_id" clearable filterable style="width: 100%">
            <el-option
              v-for="document in evidenceDocuments"
              :key="document.id"
              :label="document.title"
              :value="document.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="原文依据">
          <el-input v-model="createForm.evidence_source_ref" placeholder="例如 第4页" />
        </el-form-item>
        <el-form-item label="复核状态">
          <el-select v-model="createForm.review_status">
            <el-option label="待复核" value="pending" />
            <el-option label="已确认" value="confirmed" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="createSaving" @click="submitCreate">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editDialogVisible" title="编辑功能版本" width="560px">
      <el-form label-width="110px">
        <el-form-item label="软件版本">
          <el-input v-model="editForm.software_version" />
        </el-form-item>
        <el-form-item label="产品系列">
          <el-input v-model="editForm.product_series" />
        </el-form-item>
        <el-form-item label="发布日期">
          <el-date-picker
            v-model="editForm.release_date"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="需人工确认"
          />
        </el-form-item>
        <el-form-item label="变更类型">
          <el-select v-model="editForm.change_type">
            <el-option
              v-for="item in changeTypeOptions"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="配置口径">
          <el-input v-model="editForm.configuration_status" />
        </el-form-item>
        <el-form-item label="生命周期">
          <el-select v-model="editForm.lifecycle_status">
            <el-option
              v-for="item in lifecycleOptions"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="复核状态">
          <el-select v-model="editForm.review_status">
            <el-option label="待复核" value="pending" />
            <el-option label="已确认" value="confirmed" />
            <el-option label="已驳回" value="rejected" />
          </el-select>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="editForm.change_note" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="editSaving" @click="submitEdit">保存</el-button>
        <el-button type="danger" @click="removeVersion">删除该记录</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createFeatureReleaseVersion,
  deleteReleaseAttachment,
  deleteReleaseVersion,
  applyReleaseBackfill,
  getFeatureReleaseTimeline,
  getKnowledgeFeatures,
  getReleaseEvidenceDocuments,
  getReleaseIntroduction,
  getReleaseIntroductionHistory,
  getReleaseOverview,
  getReleaseVersions,
  previewReleaseBackfill,
  saveReleaseIntroduction,
  updateReleaseVersion,
  uploadReleaseAttachment
} from '../api/data'

const activeTab = ref('timeline')

// ---------- 通用字典 ----------
const changeTypeOptions = [
  { value: 'added', label: '新增/上架' },
  { value: 'optimized', label: '优化' },
  { value: 'fixed', label: '修复' },
  { value: 'removed', label: '下架/移除' },
  { value: 'status_changed', label: '配置状态变化' },
  { value: 'unknown', label: '未判定' }
]
const lifecycleOptions = [
  { value: 'undefined', label: '未定义' },
  { value: 'developing', label: '开发中' },
  { value: 'pending', label: '待确认' },
  { value: 'released', label: '已发布' },
  { value: 'offline', label: '已下线' },
  { value: 'deprecated', label: '已废弃' }
]
const changeLabel = (value) => changeTypeOptions.find((item) => item.value === value)?.label || value
const changeTagType = (value) =>
  ({ added: 'success', optimized: 'primary', fixed: 'warning', removed: 'danger', status_changed: 'info' }[value] || 'info')
const lifecycleLabel = (value) => lifecycleOptions.find((item) => item.value === value)?.label || value
const reviewLabel = (value) => ({ pending: '待复核', confirmed: '已确认', rejected: '已驳回' }[value] || value)
const reviewTagType = (value) => ({ pending: 'warning', confirmed: 'success', rejected: 'danger' }[value] || 'info')
const evidenceKindLabel = (value) =>
  ({ configuration_change: '配置变更表', narrative: '正文叙述', manual: '手工登记' }[value] || value || '-')
const primaryIpn = (row) => row?.ipn || row?.feature_ipn || row?.ipns?.find((item) => item.relation_type === 'primary')?.ipn || ''
const formatSize = (size) => (size ? `${Math.round(size / 1024)} KB` : '-')

// ---------- 功能版本查询 ----------
const featureQuery = ref('')
const featureOptions = ref([])
const featureLoading = ref(false)
const seriesFilter = ref('')
const timeline = ref(null)
const selectedFeatureId = ref(null)
const evidenceDocuments = ref([])

const searchFeatures = async () => {
  featureLoading.value = true
  try {
    const result = await getKnowledgeFeatures({ q: featureQuery.value, limit: 20 })
    featureOptions.value = result.items || []
    if (!featureOptions.value.length) {
      ElMessage.info('没有匹配的功能')
      timeline.value = null
    }
  } catch (error) {
    ElMessage.error('功能查询失败')
  } finally {
    featureLoading.value = false
  }
}

const searchFeaturesForDialog = async (query) => {
  try {
    const result = await getKnowledgeFeatures({ q: query, limit: 20 })
    featureOptions.value = result.items || []
  } catch (error) {
    ElMessage.error('功能查询失败')
  }
}

const selectFeature = async (row) => {
  selectedFeatureId.value = row.id
  await loadTimeline()
}

const loadTimeline = async () => {
  if (!selectedFeatureId.value) return
  featureLoading.value = true
  try {
    const params = {}
    if (seriesFilter.value) params.product_series = seriesFilter.value
    timeline.value = await getFeatureReleaseTimeline(selectedFeatureId.value, params)
    introVersion.value = null
  } catch (error) {
    if (error?.response?.status === 404) {
      ElMessage.error('功能不存在')
    } else {
      ElMessage.error('发布版本加载失败')
    }
  } finally {
    featureLoading.value = false
  }
}

const openDocument = (url) => {
  if (url) window.open(url, '_blank')
}

const confirmVersion = async (row) => {
  try {
    await updateReleaseVersion(row.id, { review_status: 'confirmed' })
    ElMessage.success('已确认')
    await loadTimeline()
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '确认失败')
  }
}

const rejectVersion = async (row) => {
  try {
    await updateReleaseVersion(row.id, { review_status: 'rejected' })
    ElMessage.success('已驳回')
    await loadTimeline()
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '驳回失败')
  }
}

// ---------- 手工登记 / 编辑 ----------
const createDialogVisible = ref(false)
const createSaving = ref(false)
const createForm = reactive({
  feature_id: null,
  software_version: '',
  product_series: '',
  release_date: null,
  change_type: 'added',
  configuration_status: '',
  lifecycle_status: 'undefined',
  evidence_document_id: null,
  evidence_source_ref: '',
  review_status: 'confirmed'
})

const openCreateDialog = async () => {
  createDialogVisible.value = true
  if (!evidenceDocuments.value.length) {
    try {
      evidenceDocuments.value = (await getReleaseEvidenceDocuments()).items || []
    } catch (error) {
      ElMessage.error('依据资料加载失败')
    }
  }
}

const submitCreate = async () => {
  if (!createForm.feature_id || !createForm.software_version) {
    ElMessage.warning('请选择功能并填写软件版本')
    return
  }
  createSaving.value = true
  try {
    await createFeatureReleaseVersion(createForm.feature_id, { ...createForm })
    ElMessage.success('已登记')
    createDialogVisible.value = false
    selectedFeatureId.value = createForm.feature_id
    await loadTimeline()
    await loadOverview()
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '登记失败')
  } finally {
    createSaving.value = false
  }
}

const editDialogVisible = ref(false)
const editSaving = ref(false)
const editForm = reactive({
  id: null,
  software_version: '',
  product_series: '',
  release_date: null,
  change_type: 'unknown',
  configuration_status: '',
  lifecycle_status: 'undefined',
  review_status: 'pending',
  change_note: ''
})

const editVersion = (row) => {
  Object.assign(editForm, {
    id: row.id,
    software_version: row.software_version,
    product_series: row.product_series,
    release_date: row.release_date,
    change_type: row.change_type,
    configuration_status: row.configuration_status || '',
    lifecycle_status: row.lifecycle_status || 'undefined',
    review_status: row.review_status,
    change_note: row.change_note || ''
  })
  editDialogVisible.value = true
}

const submitEdit = async () => {
  editSaving.value = true
  try {
    await updateReleaseVersion(editForm.id, {
      software_version: editForm.software_version,
      product_series: editForm.product_series,
      release_date: editForm.release_date,
      change_type: editForm.change_type,
      configuration_status: editForm.configuration_status,
      lifecycle_status: editForm.lifecycle_status,
      review_status: editForm.review_status,
      change_note: editForm.change_note
    })
    ElMessage.success('已保存')
    editDialogVisible.value = false
    await loadTimeline()
    await loadOverview()
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '保存失败')
  } finally {
    editSaving.value = false
  }
}

const removeVersion = async () => {
  try {
    await ElMessageBox.confirm('删除后该版本记录与发布介绍都会移除，确认删除？', '确认删除', {
      type: 'warning'
    })
  } catch (error) {
    return
  }
  try {
    await deleteReleaseVersion(editForm.id)
    ElMessage.success('已删除')
    editDialogVisible.value = false
    await loadTimeline()
    await loadOverview()
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '删除失败')
  }
}

// ---------- 按版本查询 ----------
const versionOptions = ref([])
const versionFilter = ref('')
const reviewFilter = ref('')
const versions = ref([])
const versionTotal = ref(0)
const versionLoading = ref(false)

const loadOverview = async () => {
  try {
    versionOptions.value = (await getReleaseOverview()).items || []
  } catch (error) {
    ElMessage.error('版本概览加载失败')
  }
}

const loadVersions = async () => {
  versionLoading.value = true
  try {
    const params = { limit: 200 }
    if (versionFilter.value) params.software_version = versionFilter.value
    if (reviewFilter.value) params.review_status = reviewFilter.value
    const result = await getReleaseVersions(params)
    versions.value = result.items || []
    versionTotal.value = result.total || 0
  } catch (error) {
    ElMessage.error('版本查询失败')
  } finally {
    versionLoading.value = false
  }
}

// ---------- 发布介绍 ----------
const introVersion = ref(null)
const introFeatureName = ref('')
const introForm = reactive({
  summary: '',
  clinical_significance: '',
  workflow: '',
  change_note: '',
  review_status: 'draft'
})
const introApplications = ref('')
const introAttachments = ref([])
const introHistory = ref([])
const introSaving = ref(false)
const publishedSwitch = computed({
  get: () => introForm.review_status === 'published',
  set: (value) => {
    introForm.review_status = value ? 'published' : 'draft'
  }
})

const openIntroduction = async (row) => {
  introVersion.value = row
  introFeatureName.value = timeline.value?.feature?.primary_cn_name || timeline.value?.feature?.legacy_name || ''
  activeTab.value = 'introduction'
  introHistory.value = []
  try {
    const introduction = await getReleaseIntroduction(row.id)
    Object.assign(introForm, {
      summary: introduction.summary || '',
      clinical_significance: introduction.clinical_significance || '',
      workflow: introduction.workflow || '',
      change_note: introduction.change_note || '',
      review_status: introduction.review_status || 'draft'
    })
    introApplications.value = (introduction.applications || []).join('\n')
    introAttachments.value = introduction.attachments || []
  } catch (error) {
    if (error?.response?.status === 404) {
      Object.assign(introForm, {
        summary: '',
        clinical_significance: '',
        workflow: '',
        change_note: '',
        review_status: 'draft'
      })
      introApplications.value = ''
      introAttachments.value = []
    } else {
      ElMessage.error('发布介绍加载失败')
    }
  }
}

const saveIntroduction = async () => {
  if (!introVersion.value) return
  introSaving.value = true
  try {
    const introduction = await saveReleaseIntroduction(introVersion.value.id, {
      summary: introForm.summary,
      clinical_significance: introForm.clinical_significance,
      workflow: introForm.workflow,
      applications: introApplications.value.split('\n').map((line) => line.trim()).filter(Boolean),
      change_note: introForm.change_note,
      review_status: introForm.review_status
    })
    introAttachments.value = introduction.attachments || []
    ElMessage.success('发布介绍已保存')
    await loadIntroductionHistory()
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '保存失败')
  } finally {
    introSaving.value = false
  }
}

const loadIntroductionHistory = async () => {
  if (!introVersion.value) return
  try {
    introHistory.value = (await getReleaseIntroductionHistory(introVersion.value.id)).items || []
  } catch (error) {
    ElMessage.error('历史版本加载失败')
  }
}

const uploadAttachment = async (file) => {
  if (!introVersion.value) {
    ElMessage.warning('请先选择功能版本')
    return false
  }
  try {
    const introduction = await uploadReleaseAttachment(introVersion.value.id, file)
    introAttachments.value = introduction.attachments || []
    ElMessage.success('附件已上传')
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '附件上传失败')
  }
  return false
}

const removeAttachment = async (row) => {
  try {
    await deleteReleaseAttachment(row.id)
    introAttachments.value = introAttachments.value.filter((item) => item.id !== row.id)
    ElMessage.success('附件已删除')
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '附件删除失败')
  }
}

// ---------- 候选回填 ----------
const backfillSeries = ref('')
const backfillLoading = ref(false)
const backfillApplying = ref(false)
const backfillResult = ref(null)

const previewBackfill = async () => {
  backfillLoading.value = true
  try {
    const payload = {}
    if (backfillSeries.value) payload.product_series = backfillSeries.value
    backfillResult.value = await previewReleaseBackfill(payload)
    ElMessage.success(`生成 ${backfillResult.value.total} 条候选（未写库）`)
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '候选生成失败')
  } finally {
    backfillLoading.value = false
  }
}

const applyBackfill = async () => {
  try {
    await ElMessageBox.confirm(
      '候选会以「待复核」状态写入，不会成为正式结论。确认落库？',
      '确认落库',
      { type: 'warning' }
    )
  } catch (error) {
    return
  }
  backfillApplying.value = true
  try {
    const payload = {}
    if (backfillSeries.value) payload.product_series = backfillSeries.value
    backfillResult.value = await applyReleaseBackfill(payload)
    ElMessage.success(`已落库 ${backfillResult.value.created} 条待复核候选`)
    await loadOverview()
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '落库失败')
  } finally {
    backfillApplying.value = false
  }
}

onMounted(async () => {
  await loadOverview()
  await loadVersions()
})
</script>

<style scoped>
.feature-release { padding: 16px; }
.release-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 8px; }
.release-header h2 { margin: 0; font-size: 18px; color: #1f2937; }
.release-subtitle { margin: 6px 0 0; color: #64748b; font-size: 12px; }
.release-panel { padding: 4px 0; }
.release-search { display: flex; flex-wrap: wrap; gap: 10px; margin: 12px 0; }
.timeline-result { margin-top: 12px; }
.timeline-heading { display: flex; align-items: center; gap: 12px; margin: 12px 0 8px; }
.timeline-heading h3 { margin: 0; font-size: 16px; color: #1f2937; }
.timeline-heading h4 { margin: 0; font-size: 14px; color: #1f2937; }
.timeline-heading small { margin-left: 8px; color: #64748b; font-weight: normal; }
.coverage-note { margin: 8px 0; }
.release-total { margin: 10px 0 0; color: #64748b; font-size: 12px; }
.intro-form { max-width: 860px; margin-top: 12px; }
.intro-attachments { margin: 18px 0; }
</style>
