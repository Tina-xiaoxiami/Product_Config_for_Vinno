<template>
  <div class="page">
    <!-- 顶部操作栏 -->
    <div class="page-header">
      <div class="header-left">
        <h3 class="page-title">功能管理</h3>
        <span class="page-subtitle">{{ tableData.length }} 个功能组 / {{ totalFeatures }} 项功能</span>
      </div>
      <div class="header-actions">
        <el-button size="small" @click="openStandardDialog">标准名称</el-button>
        <el-button size="small" :loading="exporting" @click="handleExportTemplate">导出模板</el-button>
        <el-button size="small" type="success" @click="openImportDialog">导入更新</el-button>
        <el-button size="small" @click="handleCreateGroup">新增功能组</el-button>
        <el-button size="small" type="primary" :icon="Plus" @click="handleCreateFeature">新增功能</el-button>
      </div>
    </div>

    <!-- 功能组卡片列表 -->
    <div class="group-list" v-loading="loading">
      <div v-for="group in tableData" :key="group.id" class="group-card">
        <div class="group-header">
          <div class="group-info">
            <span class="group-name">{{ group.name }}</span>
            <span class="group-feature-count">{{ (group.features || []).length }} 项功能</span>
            <span v-if="group.sort_order > 0" class="group-order">排序 {{ group.sort_order }}</span>
          </div>
          <div class="group-actions">
            <el-button size="small" text @click="handleCreateFeatureToGroup(group.id)">+ 添加功能</el-button>
            <el-button size="small" text @click="handleEditGroup(group)">编辑组</el-button>
            <el-button size="small" text type="danger" @click="handleDeleteGroup(group)">删除组</el-button>
          </div>
        </div>
        <div class="group-body">
          <div v-if="(group.features || []).length" class="feature-list">
            <div v-for="feature in group.features" :key="feature.id" class="feature-item">
              <div class="feature-main">
                <div class="feature-names">
                  <span class="feature-name">
                    {{ feature.primary_cn_name || feature.name }}
                    <FeatureNameMark :feature-id="feature.id" :cn="feature.primary_cn_name" :en="feature.primary_en_name" :name="feature.name" />
                  </span>
                  <span v-if="feature.primary_en_name" class="feature-en-name">{{ feature.primary_en_name }}</span>
                </div>
                <span v-if="feature.ipn" class="feature-ipn">IPN: {{ feature.ipn }}</span>
              </div>
              <div class="feature-meta">
                <span v-if="feature.sort_order > 0" class="feature-order">{{ feature.sort_order }}</span>
              </div>
              <div class="feature-actions">
                <el-button size="small" text @click="handleEditFeature(feature, group.id)">编辑</el-button>
                <el-button size="small" text type="danger" @click="handleDeleteFeature(feature)">删除</el-button>
              </div>
            </div>
          </div>
          <div v-else class="group-empty">
            <el-empty description="暂无功能" :image-size="32" />
          </div>
        </div>
      </div>
    </div>

    <!-- 功能组对话框 -->
    <el-dialog v-model="showGroupForm" :title="editingGroupId ? '编辑功能组' : '新增功能组'" width="420px" destroy-on-close>
      <el-form :model="groupForm" label-width="60px">
        <el-form-item label="名称"><el-input v-model="groupForm.name" placeholder="如 基础功能" /></el-form-item>
        <el-form-item label="排序"><el-input-number v-model="groupForm.sort_order" :min="0" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showGroupForm = false">取消</el-button>
        <el-button type="primary" @click="saveGroup" :loading="saving">保存</el-button>
      </template>
    </el-dialog>

    <!-- 功能对话框 -->
    <el-dialog v-model="showFeatureForm" :title="editingFeatureId ? '编辑功能主数据' : '新增功能主数据'" width="680px" destroy-on-close>
      <el-form :model="featureForm" label-width="100px">
        <el-form-item label="功能组">
          <el-select v-model="featureForm.group_id" style="width:100%" placeholder="选择功能组">
            <el-option v-for="g in tableData" :key="g.id" :label="g.name" :value="g.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="中文主名称">
          <el-input v-model="featureForm.primary_cn_name" placeholder="以配置项中文描述为准" />
        </el-form-item>
        <el-form-item label="英文主名称">
          <el-input v-model="featureForm.primary_en_name" placeholder="以配置项英文描述为准" />
        </el-form-item>
        <el-form-item label="中文曾用名">
          <el-input
            v-model="featureForm.alias_cn_text"
            type="textarea"
            :rows="2"
            placeholder="每行一个中文曾用名"
          />
        </el-form-item>
        <el-form-item label="英文曾用名">
          <el-input
            v-model="featureForm.alias_en_text"
            type="textarea"
            :rows="2"
            placeholder="每行一个英文曾用名"
          />
        </el-form-item>
        <el-form-item label="IPN关系">
          <div class="ipn-editor">
            <div v-for="(entry, index) in featureForm.ipns" :key="index" class="ipn-editor-row">
              <el-input v-model="entry.ipn" placeholder="配置项IPN" />
              <el-select v-model="entry.relation_type" aria-label="IPN关系类型">
                <el-option label="主IPN" value="primary" />
                <el-option label="相关功能" value="related" />
                <el-option label="版本IPN" value="version_variant" />
              </el-select>
              <el-button type="danger" text @click="removeIpn(index)">移除</el-button>
            </div>
            <el-button size="small" @click="addIpn">+ 添加IPN</el-button>
          </div>
        </el-form-item>
        <el-form-item label="排序"><el-input-number v-model="featureForm.sort_order" :min="0" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showFeatureForm = false">取消</el-button>
        <el-button type="primary" @click="saveFeature" :loading="saving">保存</el-button>
      </template>
    </el-dialog>

    <!-- 批量导入对话框 -->
    <el-dialog v-model="showImportDialog" title="批量导入功能主数据" width="920px" destroy-on-close>
      <el-alert type="info" :closable="false" show-icon class="import-note">
        <template #title>
          先「导出模板」，在 Excel 里修改后上传预览；文件中未出现的功能不会被删除或停用，功能组不存在时自动创建。
        </template>
      </el-alert>

      <div class="import-toolbar">
        <el-upload
          :show-file-list="false"
          :auto-upload="false"
          :on-change="h => handlePreviewImport(h.raw)"
          accept=".xlsx"
          style="display:inline-block"
        >
          <el-button size="small" type="primary" :loading="previewing">选择 Excel 文件并预览</el-button>
        </el-upload>
        <span v-if="importFileName" class="import-file-name">{{ importFileName }}</span>
      </div>

      <template v-if="importReport">
        <div class="import-summary">
          <el-tag size="small" type="success">新增 {{ importReport.summary.create }}</el-tag>
          <el-tag size="small" type="warning">更新 {{ importReport.summary.update }}</el-tag>
          <el-tag size="small" type="info">无变化 {{ importReport.summary.unchanged }}</el-tag>
          <el-tag size="small" :type="importReport.summary.error ? 'danger' : 'info'">
            错误 {{ importReport.summary.error }}
          </el-tag>
          <span v-if="importReport.new_groups.length" class="import-new-groups">
            将新建功能组：{{ importReport.new_groups.join('、') }}
          </span>
        </div>

        <el-alert
          v-if="importReport.summary.error"
          type="error"
          :closable="false"
          show-icon
          class="import-note"
          title="有数据行未通过校验，整份文件都不会写入，请修正后重新上传。"
        />

        <el-table :data="importReport.rows" size="small" border max-height="380" class="import-table">
          <el-table-column prop="row_number" label="行" width="48" />
          <el-table-column label="操作" width="76">
            <template #default="{ row }">
              <el-tag size="small" :type="actionTagType(row.action)">{{ actionLabel(row.action) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="功能" min-width="190">
            <template #default="{ row }">
              <div class="import-cn">{{ row.primary_cn_name || '（空）' }}</div>
              <div class="import-en">{{ row.primary_en_name || '（空）' }}</div>
            </template>
          </el-table-column>
          <el-table-column label="功能组" width="110">
            <template #default="{ row }">
              {{ row.group_name }}<span v-if="row.new_group" class="import-new-tag">新</span>
            </template>
          </el-table-column>
          <el-table-column prop="primary_ipn" label="主IPN" width="90" />
          <el-table-column label="变更" min-width="250">
            <template #default="{ row }">
              <div v-for="change in row.changes" :key="change.field" class="import-change">
                <span class="import-change-label">{{ change.label }}</span>
                <span class="import-change-before">{{ change.before || '空' }}</span>
                <span class="import-arrow">→</span>
                <span class="import-change-after">{{ change.after || '空' }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="校验结果" min-width="200">
            <template #default="{ row }">
              <div v-for="(error, index) in row.errors" :key="'e' + index" class="import-error">{{ error }}</div>
              <div v-for="(warning, index) in row.warnings" :key="'w' + index" class="import-warning">{{ warning }}</div>
            </template>
          </el-table-column>
        </el-table>
      </template>

      <template #footer>
        <el-button @click="showImportDialog = false">取消</el-button>
        <el-button
          type="primary"
          :disabled="!canApplyImport"
          :loading="applying"
          @click="handleApplyImport"
        >
          确认更新
        </el-button>
      </template>
    </el-dialog>

    <!-- 标准名称核对 -->
    <el-dialog v-model="showStandardDialog" title="功能名称标准" width="980px" destroy-on-close>
      <el-alert type="info" :closable="false" show-icon class="import-note">
        <template #title>
          标准表是功能中英文名称的定义来源，系统名称与标准不一致时只在页面上提示，不会自动改写功能主数据。
        </template>
      </el-alert>

      <div class="import-toolbar">
        <el-upload
          :show-file-list="false"
          :auto-upload="false"
          :on-change="h => handleImportStandard(h.raw)"
          accept=".xlsx,.csv,.tsv"
          style="display:inline-block"
        >
          <el-button size="small" type="primary" :loading="importingStandard">导入/更新标准表</el-button>
        </el-upload>
        <span class="import-file-name">
          共 {{ standardData?.standard_count || 0 }} 条标准定义<template v-if="standardData?.source_file">，来源 {{ standardData.source_file }}</template><template v-if="standardData?.last_imported_at">，更新于 {{ standardData.last_imported_at.replace('T', ' ').slice(0, 16) }}</template>
        </span>
      </div>

      <div v-loading="loadingStandard">
        <div class="import-summary" v-if="standardData">
          <el-tag size="small" type="success">一致 {{ standardData.summary.ok }}</el-tag>
          <el-tag size="small" type="warning">写法不同 {{ standardData.summary.style }}</el-tag>
          <el-tag size="small" type="danger">不一致 {{ standardData.summary.differs }}</el-tag>
          <el-tag size="small" type="warning" v-if="standardData.summary.ambiguous">待人工确认 {{ standardData.summary.ambiguous }}</el-tag>
          <el-tag size="small" type="info">标准表有、系统未登记 {{ standardData.summary.missing }}</el-tag>
          <el-tag size="small" type="info">系统有、标准表未收录 {{ standardData.summary.uncovered }}</el-tag>
          <el-tag size="small" :type="standardData.summary.config_differs ? 'danger' : 'success'">
            配置管理描述不一致 {{ standardData.summary.config_differs }}
          </el-tag>
          <el-tag size="small" type="info" v-if="standardData.summary.config_unlinked">
            未关联主IPN {{ standardData.summary.config_unlinked }}
          </el-tag>
        </div>

        <el-tabs v-if="standardData" v-model="standardTab">
          <el-tab-pane :label="`与标准不一致（${mismatchedStandards.length}）`" name="mismatch">
            <el-table :data="mismatchedStandards" size="small" border max-height="380">
              <el-table-column label="功能" min-width="170">
                <template #default="{ row }">
                  <div class="import-cn">{{ row.feature_cn_name || '（空）' }}</div>
                  <div class="import-en">{{ row.group_name }} · ID {{ row.feature_id }}</div>
                </template>
              </el-table-column>
              <el-table-column label="中文名称对照" min-width="220">
                <template #default="{ row }">
                  <div v-if="!row.cn_field || row.cn_field.status === 'ok'" class="std-ok">一致</div>
                  <div v-else>
                    <div class="std-before">系统：{{ row.cn_field.system_value || '（空）' }}</div>
                    <div class="std-after">标准：{{ row.cn_field.standard_value }}（{{ row.cn_field.label }}）</div>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="英文名称对照" min-width="240">
                <template #default="{ row }">
                  <div v-if="!row.en_field || row.en_field.status === 'ok'" class="std-ok">一致</div>
                  <div v-else>
                    <div class="std-before">系统：{{ row.en_field.system_value || '（空）' }}</div>
                    <div class="std-after">标准：{{ row.en_field.standard_value }}（{{ row.en_field.label }}）</div>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="匹配方式" width="130" prop="match_reason" />
            </el-table>
          </el-tab-pane>

          <el-tab-pane :label="`标准表有、系统未登记（${standardData.summary.missing}）`" name="missing">
            <el-table :data="missingStandards" size="small" border max-height="380">
              <el-table-column prop="cn_name" label="标准中文名称" min-width="200" />
              <el-table-column prop="en_name" label="标准英文名称" min-width="160">
                <template #default="{ row }">{{ row.en_name || row.short_en || '-' }}</template>
              </el-table-column>
              <el-table-column prop="ui_label" label="中文UI" min-width="200" />
            </el-table>
          </el-tab-pane>

          <el-tab-pane label="白皮书正文核对" name="whitepaper" lazy>
            <div class="import-toolbar">
              <el-select
                v-model="whitepaperDocumentId"
                placeholder="选择白皮书查看逐条差异"
                clearable
                style="width:300px"
                @change="loadWhitepaperAudit"
              >
                <el-option
                  v-for="doc in whitepaperDocuments"
                  :key="doc.id"
                  :label="`${doc.title}（差异 ${whitepaperDiffByDoc[doc.id] || 0} 项）`"
                  :value="doc.id"
                />
              </el-select>
              <el-checkbox v-model="whitepaperIncludeMatched" @change="loadWhitepaperAudit">同时显示一致的条目</el-checkbox>
              <span v-if="whitepaperReport" class="import-file-name">
                {{ whitepaperReport.documents }} 份白皮书，累计差异 {{ whitepaperReport.summary.entries }} 条；白皮书正文里的选配标记（可选/选配）不参与名称比对
              </span>
            </div>

            <el-table v-if="!whitepaperDocumentId" :data="whitepaperDocumentSummaries" size="small" border max-height="340">
              <el-table-column prop="document_title" label="白皮书" min-width="240" />
              <el-table-column prop="version" label="版本" width="110">
                <template #default="{ row }">{{ row.document_version || '-' }}</template>
              </el-table-column>
              <el-table-column prop="mentioned_features" label="提及功能" width="100" />
              <el-table-column prop="mismatched_features" label="名称有差异" width="110" />
              <el-table-column label="" width="90">
                <template #default="{ row }">
                  <el-button size="small" text type="primary" @click="whitepaperDocumentId = row.document_id; loadWhitepaperAudit()">查看差异</el-button>
                </template>
              </el-table-column>
            </el-table>

            <el-table v-else :data="whitepaperReport?.entries || []" size="small" border max-height="340">
              <el-table-column label="功能" min-width="150">
                <template #default="{ row }">
                  <div class="import-cn">{{ row.feature_cn_name || '（空）' }}</div>
                  <div class="import-en">{{ row.group_name }} · ID {{ row.feature_id }}</div>
                </template>
              </el-table-column>
              <el-table-column label="白皮书里的写法" min-width="170">
                <template #default="{ row }">
                  <el-tag v-for="name in row.used_names" :key="name" size="small" class="wb-used">{{ name }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="功能名称标准表" min-width="230">
                <template #default="{ row }">
                  <el-tag size="small" :type="baselineTagType(row.standard?.severity)">{{ severityLabel(row.standard?.severity) }}</el-tag>
                  <div class="std-before" v-if="row.standard && row.standard.severity !== 'ok'">{{ row.standard.message }}</div>
                </template>
              </el-table-column>
              <el-table-column label="配置管理描述" min-width="230">
                <template #default="{ row }">
                  <el-tag size="small" :type="baselineTagType(row.config?.severity)">{{ severityLabel(row.config?.severity) }}</el-tag>
                  <div class="std-before" v-if="row.config && row.config.severity !== 'ok'">{{ row.config.message }}</div>
                </template>
              </el-table-column>
              <el-table-column label="正文出处" min-width="240">
                <template #default="{ row }">
                  <div class="wb-snippet" v-for="(snippet, index) in row.snippets" :key="index">{{ snippet }}</div>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <el-tab-pane label="两个基准逐条核对" name="baselines">
            <el-table :data="baselineRows" size="small" border max-height="380">
              <el-table-column label="功能" min-width="170">
                <template #default="{ row }">
                  <div class="import-cn">{{ row.cn_name || '（空）' }}</div>
                  <div class="import-en">{{ row.en_name }}</div>
                </template>
              </el-table-column>
              <el-table-column label="功能名称标准表" min-width="250">
                <template #default="{ row }">
                  <el-tag size="small" :type="baselineTagType(row.standard.severity)">{{ severityLabel(row.standard.severity) }}</el-tag>
                  <div class="std-after" v-if="row.standard.standard_cn_name">标准：{{ row.standard.standard_cn_name }}</div>
                  <div class="std-before" v-if="row.standard.severity === 'differs' || row.standard.severity === 'style'">{{ row.standard.message }}</div>
                </template>
              </el-table-column>
              <el-table-column label="配置管理描述" min-width="250">
                <template #default="{ row }">
                  <el-tag size="small" :type="baselineTagType(row.config.severity)">{{ severityLabel(row.config.severity) }}</el-tag>
                  <div class="std-after" v-if="row.config.ipn">IPN：{{ row.config.ipn }}</div>
                  <div class="std-before" v-if="row.config.severity === 'differs' || row.config.severity === 'style'">{{ row.config.message }}</div>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <el-tab-pane :label="`系统有、标准表未收录（${standardData.summary.uncovered}）`" name="uncovered">
            <el-table :data="standardData.uncovered_features" size="small" border max-height="380">
              <el-table-column prop="cn_name" label="功能" min-width="200" />
              <el-table-column prop="group_name" label="功能组" width="120" />
              <el-table-column prop="en_name" label="英文名称" min-width="160" />
            </el-table>
          </el-tab-pane>
        </el-tabs>
      </div>

      <template #footer>
        <el-button @click="showStandardDialog = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { loadFeatureNameStandardFlags, useFeatureNameStandard } from '../utils/featureNameStandard'
import {
  getFeatureGroups,
  createFeatureGroup,
  updateFeatureGroup,
  deleteFeatureGroup,
  getFeatures,
  deleteFeature,
  getFeatureMasterData,
  createFeatureMasterData,
  updateFeatureMasterData,
  downloadFeatureTemplate,
  previewFeatureImport,
  applyFeatureImport,
  getFeatureNameStandards,
  importFeatureNameStandards,
  getWhitepaperNameAudit,
  getWhitepaperDocuments
} from '../api/data'

const tableData = ref([])
const loading = ref(false)
const showGroupForm = ref(false)
const editingGroupId = ref(null)
const showFeatureForm = ref(false)
const editingFeatureId = ref(null)
const saving = ref(false)
const exporting = ref(false)
const previewing = ref(false)
const applying = ref(false)
const showImportDialog = ref(false)
const importFile = ref(null)
const importFileName = ref('')
const importReport = ref(null)
const showStandardDialog = ref(false)
const standardData = ref(null)
const standardTab = ref('mismatch')
const loadingStandard = ref(false)
const importingStandard = ref(false)
const whitepaperDocuments = ref([])
const whitepaperDocumentId = ref(null)
const whitepaperReport = ref(null)
const whitepaperIncludeMatched = ref(false)
const whitepaperDiffByDoc = ref({})
const whitepaperDocumentSummaries = computed(() =>
  (whitepaperReport.value?.document_summaries || []).map((row) => ({
    document_id: row.document_id,
    document_title: row.document_title,
    document_version: row.document_version,
    mentioned_features: row.mentioned_features,
    mismatched_features: row.mismatched_features
  }))
)

const { flags: featureFlags } = useFeatureNameStandard()

const mismatchedStandards = computed(() =>
  (standardData.value?.standards || []).filter(
    (entry) => entry.severity === 'differs' || entry.severity === 'style' || entry.severity === 'ambiguous'
  )
)
const missingStandards = computed(() =>
  (standardData.value?.standards || []).filter((entry) => entry.severity === 'missing')
)
const severityLabels = {
  ok: '一致',
  style: '写法不同',
  differs: '不一致',
  ambiguous: '待人工确认',
  missing: '标准表有、系统未登记',
  uncovered: '标准表未收录',
  unlinked: '未关联主IPN'
}
const severityLabel = (severity) => severityLabels[severity] || severity
const baselineTagType = (severity) => (
  { differs: 'danger', style: 'warning', ambiguous: 'warning', ok: 'success' }[severity] || 'info'
)
// 逐条列出每个功能在两个基准上的结论：标准表（从核对条目取）与配置管理描述（从提示标记取）
const baselineRows = computed(() => {
  const byFeature = featureFlags.value?.by_feature || {}
  const flagOf = (featureId) => byFeature[String(featureId)] || {}
  return (standardData.value?.standards || [])
    .filter((entry) => entry.feature_id)
    .map((entry) => {
      const flag = flagOf(entry.feature_id)
      return {
        feature_id: entry.feature_id,
        cn_name: entry.feature_cn_name,
        en_name: entry.feature_en_name,
        standard: flag.standard_check || {
          severity: entry.severity,
          message: '',
          standard_cn_name: entry.cn_name
        },
        config: flag.config_check || { severity: 'unlinked', ipn: '', message: '未关联主IPN' }
      }
    })
})
const groupForm = reactive({ name: '', sort_order: 0 })
const featureForm = reactive({
  group_id: null,
  primary_cn_name: '',
  primary_en_name: '',
  alias_cn_text: '',
  alias_en_text: '',
  ipns: [],
  sort_order: 0
})

const totalFeatures = computed(() => {
  return tableData.value.reduce((sum, g) => sum + (g.features || []).length, 0)
})

const loadData = async () => {
  loading.value = true
  try {
    const groups = (await getFeatureGroups()).items || []
    const features = (await getFeatures({ limit: 500 })).items || []
    const featMap = {}
    features.forEach(f => {
      const gid = f.group_id
      featMap[gid] = featMap[gid] || []
      featMap[gid].push(f)
    })
    tableData.value = groups.map(g => ({ ...g, features: featMap[g.id] || [] }))
  } catch { ElMessage.error('加载失败') } finally { loading.value = false }
}

// Groups
const handleCreateGroup = () => {
  editingGroupId.value = null
  groupForm.name = ''
  groupForm.sort_order = 0
  showGroupForm.value = true
}
const handleEditGroup = (row) => {
  editingGroupId.value = row.id
  groupForm.name = row.name
  groupForm.sort_order = row.sort_order
  showGroupForm.value = true
}
const saveGroup = async () => {
  if (!groupForm.name) return ElMessage.warning('请输入名称')
  saving.value = true
  try {
    if (editingGroupId.value) {
      await updateFeatureGroup(editingGroupId.value, groupForm)
    } else {
      await createFeatureGroup(groupForm)
    }
    ElMessage.success('保存成功')
    showGroupForm.value = false
    await loadData()
  } catch { ElMessage.error('保存失败') } finally { saving.value = false }
}
const handleDeleteGroup = async (row) => {
  try {
    await ElMessageBox.confirm(`确认删除功能组"${row.name}"？<p style="color:#e6a23c;font-size:12px;margin:4px 0 0">将同时删除组内所有功能。</p>`, '确认删除', { type: 'warning', dangerouslyUseHTMLString: true })
    await deleteFeatureGroup(row.id)
    ElMessage.success('删除成功')
    await loadData()
  } catch (e) { if (e !== 'cancel') ElMessage.error('删除失败') }
}

// Features
const resetFeatureForm = (groupId = null) => {
  featureForm.group_id = groupId || tableData.value[0]?.id || null
  featureForm.primary_cn_name = ''
  featureForm.primary_en_name = ''
  featureForm.alias_cn_text = ''
  featureForm.alias_en_text = ''
  featureForm.ipns = []
  featureForm.sort_order = 0
}
const parseAliases = (value) => value
  .split(/\r?\n/)
  .map(name => name.trim())
  .filter(Boolean)
const masterPayload = () => ({
  group_id: featureForm.group_id,
  sort_order: featureForm.sort_order,
  primary_cn_name: featureForm.primary_cn_name,
  primary_en_name: featureForm.primary_en_name,
  alias_cn_names: parseAliases(featureForm.alias_cn_text),
  alias_en_names: parseAliases(featureForm.alias_en_text),
  ipns: featureForm.ipns
    .map(entry => ({ ipn: entry.ipn.trim(), relation_type: entry.relation_type }))
    .filter(entry => entry.ipn)
})
const addIpn = () => featureForm.ipns.push({ ipn: '', relation_type: 'related' })
const removeIpn = (index) => featureForm.ipns.splice(index, 1)

const handleCreateFeature = () => {
  editingFeatureId.value = null
  resetFeatureForm()
  showFeatureForm.value = true
}
const handleCreateFeatureToGroup = (groupId) => {
  editingFeatureId.value = null
  resetFeatureForm(groupId)
  showFeatureForm.value = true
}
const handleEditFeature = async (row, groupId) => {
  editingFeatureId.value = row.id
  resetFeatureForm(groupId)
  featureForm.sort_order = row.sort_order
  try {
    const master = await getFeatureMasterData(row.id)
    featureForm.primary_cn_name = master.primary_cn_name || ''
    featureForm.primary_en_name = master.primary_en_name || ''
    featureForm.alias_cn_text = (master.alias_cn_names || []).join('\n')
    featureForm.alias_en_text = (master.alias_en_names || []).join('\n')
    featureForm.ipns = (master.ipns || []).map(entry => ({
      ipn: entry.ipn,
      relation_type: entry.relation_type
    }))
    showFeatureForm.value = true
  } catch {
    ElMessage.error('功能主数据加载失败')
  }
}
const saveFeature = async () => {
  if (!featureForm.group_id || !featureForm.primary_cn_name || !featureForm.primary_en_name) {
    return ElMessage.warning('功能组、中英文主名称不能为空')
  }
  saving.value = true
  try {
    const payload = masterPayload()
    if (editingFeatureId.value) {
      await updateFeatureMasterData(editingFeatureId.value, payload)
    } else {
      await createFeatureMasterData(payload)
    }
    ElMessage.success('保存成功')
    showFeatureForm.value = false
    await loadData()
  } catch { ElMessage.error('保存失败') } finally { saving.value = false }
}
const handleDeleteFeature = async (row) => {
  try {
    await ElMessageBox.confirm(`确认删除功能"${row.name}"？`, '确认删除', { type: 'warning' })
    await deleteFeature(row.id)
    ElMessage.success('删除成功')
    await loadData()
  } catch (e) { if (e !== 'cancel') ElMessage.error('删除失败') }
}

// 批量导入
const actionLabels = { create: '新增', update: '更新', unchanged: '无变化' }
const actionLabel = (action) => actionLabels[action] || action
const actionTagType = (action) => ({ create: 'success', update: 'warning' }[action] || 'info')
const canApplyImport = computed(() => Boolean(importReport.value && importReport.value.can_apply))

const handleExportTemplate = async () => {
  exporting.value = true
  try {
    const res = await downloadFeatureTemplate()
    const url = URL.createObjectURL(new Blob([res]))
    const a = document.createElement('a')
    a.href = url
    a.download = `功能主数据导入模板_${new Date().toISOString().slice(0, 10).replace(/-/g, '')}.xlsx`
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('模板已导出')
  } catch { ElMessage.error('导出失败') } finally { exporting.value = false }
}

const openImportDialog = () => {
  importFile.value = null
  importFileName.value = ''
  importReport.value = null
  showImportDialog.value = true
}

const handlePreviewImport = async (file) => {
  if (!file) return
  importFile.value = file
  importFileName.value = file.name
  previewing.value = true
  try {
    const fd = new FormData()
    fd.append('file', file)
    importReport.value = await previewFeatureImport(fd)
    if (importReport.value.summary.error) {
      ElMessage.warning(`有 ${importReport.value.summary.error} 行未通过校验`)
    } else if (importReport.value.can_apply) {
      ElMessage.success('预览完成，确认无误后点「确认更新」')
    } else {
      ElMessage.info('文件内容与现有数据一致，无需更新')
    }
  } catch (e) {
    importReport.value = null
    ElMessage.error(e?.response?.data?.detail || '预览失败，请检查文件')
  } finally { previewing.value = false }
}

const handleApplyImport = async () => {
  if (!importFile.value) return
  applying.value = true
  try {
    const fd = new FormData()
    fd.append('file', importFile.value)
    const res = await applyFeatureImport(fd)
    const s = res.summary
    ElMessage.success(`导入完成：新增 ${s.create} 项、更新 ${s.update} 项、跳过 ${s.unchanged} 项`)
    showImportDialog.value = false
    importReport.value = null
    await loadData()
  } catch (e) {
    const detail = e?.response?.data?.detail
    if (detail && typeof detail === 'object') {
      const lines = (detail.rows || [])
        .map(r => `第 ${r.row_number} 行：${(r.errors || []).join('；')}`)
        .join('<br/>')
      ElMessageBox.alert(lines || detail.message, '导入未执行', {
        type: 'error',
        dangerouslyUseHTMLString: true
      })
    } else {
      ElMessage.error(detail || '导入失败')
    }
  } finally { applying.value = false }
}

const loadWhitepaperAudit = async () => {
  try {
    whitepaperReport.value = await getWhitepaperNameAudit({
      document_id: whitepaperDocumentId.value || undefined,
      include_matched: whitepaperIncludeMatched.value
    })
    if (!whitepaperDocumentId.value) {
      whitepaperDiffByDoc.value = Object.fromEntries(
        (whitepaperReport.value.document_summaries || []).map((row) => [
          row.document_id,
          row.mismatched_features
        ])
      )
    }
  } catch { ElMessage.error('白皮书名称核对失败') }
}

const loadWhitepaperDocuments = async () => {
  try {
    whitepaperDocuments.value = (await getWhitepaperDocuments()).items || []
  } catch { whitepaperDocuments.value = [] }
}

// 功能名称标准核对
const loadStandardAudit = async () => {
  loadingStandard.value = true
  try {
    const [audit] = await Promise.all([
      getFeatureNameStandards(),
      loadFeatureNameStandardFlags({ force: true })
    ])
    standardData.value = audit
  } catch { ElMessage.error('标准名称核对结果加载失败') } finally { loadingStandard.value = false }
}

const openStandardDialog = async () => {
  showStandardDialog.value = true
  whitepaperDocumentId.value = null
  await Promise.all([loadStandardAudit(), loadWhitepaperDocuments(), loadWhitepaperAudit()])
}

const handleImportStandard = async (file) => {
  if (!file) return
  importingStandard.value = true
  try {
    const fd = new FormData()
    fd.append('file', file)
    const res = await importFeatureNameStandards(fd)
    ElMessage.success(`标准表已更新：${res.imported} 条定义，其中 ${res.summary.differs} 条与系统名称不一致`)
    await loadStandardAudit()
    await loadFeatureNameStandardFlags({ force: true })
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '标准表导入失败')
  } finally { importingStandard.value = false }
}

onMounted(() => {
  loadData()
  loadFeatureNameStandardFlags()
})
</script>

<style scoped>
.page {
  padding: 0;
  max-width: 960px;
}

/* Header */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.header-left {
  display: flex;
  align-items: baseline;
  gap: 12px;
}
.page-title {
  font-size: 16px;
  font-weight: 600;
  margin: 0;
  color: #303133;
}
.page-subtitle {
  font-size: 12px;
  color: #909399;
}
.header-actions {
  display: flex;
  gap: 8px;
}

/* Group Cards */
.group-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.group-card {
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  overflow: hidden;
  transition: box-shadow 0.2s;
  background: #fff;
}
.group-card:hover {
  box-shadow: 0 2px 12px rgba(0,0,0,0.06);
}
.group-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: linear-gradient(135deg, #f0f5ff 0%, #fafcff 100%);
  border-bottom: 1px solid #e4e7ed;
}
.group-info {
  display: flex;
  align-items: center;
  gap: 12px;
}
.group-name {
  font-weight: 600;
  font-size: 14px;
  color: #303133;
}
.group-feature-count {
  font-size: 12px;
  color: #909399;
  background: #f0f2f5;
  padding: 1px 8px;
  border-radius: 10px;
}
.group-order {
  font-size: 11px;
  color: #c0c4cc;
}
.group-actions {
  display: flex;
  gap: 2px;
}

/* Feature List */
.group-body {
  padding: 0;
}
.feature-list {
  display: flex;
  flex-direction: column;
}
.feature-item {
  display: flex;
  align-items: center;
  padding: 10px 16px;
  border-bottom: 1px solid #f0f2f5;
  transition: background 0.15s;
}
.feature-item:last-child {
  border-bottom: none;
}
.feature-item:hover {
  background: #fafafa;
}
.feature-main {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.feature-names { display: flex; flex-direction: column; gap: 2px; }
.feature-name {
  font-size: 13px;
  color: #303133;
  font-weight: 500;
}
.feature-en-name { color: #909399; font-size: 11px; }
.feature-ipn {
  font-size: 11px;
  color: #909399;
  background: #f5f7fa;
  padding: 1px 6px;
  border-radius: 3px;
  font-family: 'SF Mono', monospace;
}
.feature-meta {
  margin: 0 12px;
}
.feature-order {
  font-size: 11px;
  color: #c0c4cc;
}
.feature-actions {
  display: flex;
  gap: 2px;
  flex-shrink: 0;
}
.group-empty {
  padding: 16px 0;
}
/* 批量导入 */
.import-note { margin-bottom: 12px; }
.import-toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.import-file-name { font-size: 12px; color: #606266; }
.import-summary { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; }
.import-new-groups { font-size: 12px; color: #909399; }
.import-table { margin-top: 4px; }
.import-cn { font-size: 13px; color: #303133; }
.import-en { font-size: 11px; color: #909399; }
.import-new-tag { margin-left: 4px; font-size: 11px; color: #e6a23c; }
.import-change { font-size: 12px; line-height: 1.6; }
.import-change-label { color: #909399; margin-right: 4px; }
.import-change-before { color: #f56c6c; text-decoration: line-through; }
.import-arrow { margin: 0 4px; color: #c0c4cc; }
.import-change-after { color: #67c23a; }
.import-error { font-size: 12px; color: #f56c6c; line-height: 1.5; }
.std-ok { font-size: 12px; color: #909399; }
.wb-used { margin: 0 4px 2px 0; }
.wb-snippet { font-size: 11px; color: #909399; line-height: 1.5; margin-bottom: 2px; }
.std-before { font-size: 12px; color: #f56c6c; }
.std-after { font-size: 12px; color: #67c23a; }
.import-warning { font-size: 12px; color: #e6a23c; line-height: 1.5; }

.ipn-editor { width: 100%; display: flex; flex-direction: column; gap: 8px; }
.ipn-editor-row { display: grid; grid-template-columns: 1fr 130px auto; gap: 8px; }
</style>
