<template>
  <div class="registration-manage-page">
    <header class="page-header">
      <div>
        <h2>注册管理</h2>
        <p>注册数据由基础数据统一管理，知识库和产品策略查询共同引用这里的数据。</p>
      </div>
      <div class="header-actions">
        <el-tag type="success" effect="plain">受控主数据</el-tag>
        <el-button type="primary" :icon="Plus" @click="openPackageDialog">
          新增注册资料包
        </el-button>
      </div>
    </header>

    <el-alert
      title="注册红线以注册证和注册差异表的受控导入结果为准；页面不复制知识库数据。"
      type="info"
      :closable="false"
      show-icon
      class="source-alert"
    />

    <section
      data-testid="registration-package-history"
      class="package-history"
      v-loading="packageLoading"
    >
      <div class="package-heading">
        <div>
          <h3>注册资料版本</h3>
          <p>注册证与注册差异表成对记录；更新会生成新版本，不覆盖历史。</p>
        </div>
        <el-tag type="info" effect="plain">成对受控</el-tag>
      </div>
      <el-empty
        v-if="!packageLoading && packageGroups.length === 0"
        description="暂无注册资料版本"
        :image-size="52"
      />
      <article v-for="group in packageGroups" :key="group.id" class="package-card">
        <div class="package-title">
          <div class="package-identity">
            <strong>{{ group.display_name }}</strong>
            <span>
              {{ group.country_code }} · {{ group.unit_code }} ·
              {{ group.registration_number || '未登记注册证号' }}
            </span>
          </div>
          <div class="package-state">
            <el-tag :type="group.is_enabled ? 'success' : 'info'" effect="plain">
              {{ group.is_enabled ? '已启用' : '未启用' }}
            </el-tag>
            <el-button size="small" @click="handleTogglePackageEnabled(group)">
              {{ group.is_enabled ? '停用' : '启用' }}
            </el-button>
          </div>
        </div>
        <el-collapse>
          <el-collapse-item
            v-for="version in group.versions"
            :key="version.id"
            :name="version.id"
          >
            <template #title>
              <div class="version-title">
                <span>第 {{ version.version_no }} 版</span>
                <el-tag
                  :type="version.status === 'active' ? 'success' : version.status === 'draft' ? 'warning' : 'info'"
                  size="small"
                  effect="plain"
                >
                  {{ version.status === 'active' ? '正式版本' : version.status === 'draft' ? '待确认草稿' : '历史版本' }}
                </el-tag>
                <span class="version-counts">
                  {{ version.model_count }} 型号 · {{ version.probe_count }} 探头 ·
                  {{ version.matrix_count }} 关系
                </span>
              </div>
            </template>
            <div class="version-body">
              <div class="material-actions">
                <el-button
                  v-if="version.status === 'draft'"
                  type="warning"
                  @click="openDraftReview(group, version)"
                >
                  继续确认并发布
                </el-button>
                <el-button
                  tag="a"
                  :href="version.certificate.preview_url"
                  target="_blank"
                  rel="noopener"
                  :icon="View"
                >
                  查看注册证
                </el-button>
                <el-button
                  tag="a"
                  :href="version.difference.preview_url"
                  target="_blank"
                  rel="noopener"
                  :icon="View"
                >
                  查看差异表
                </el-button>
              </div>
              <p class="material-versions">
                注册证：{{ version.certificate.version || '未标版本' }}；
                差异表：{{ version.difference.version || '未标版本' }}
              </p>
              <div v-if="version.diff.kind === 'baseline'" class="baseline-note">
                基线版本：{{ version.diff.summary.models }} 个型号、
                {{ version.diff.summary.probes }} 个探头、
                {{ version.diff.summary.relations }} 条关系。
              </div>
              <div v-else class="change-summary">
                <strong>变更摘要</strong>
                <span>新增型号 {{ version.diff.summary.models_added }}</span>
                <span>删除型号 {{ version.diff.summary.models_removed }}</span>
                <span>探头 IPN 变化 {{ version.diff.summary.probe_ipn_changed }}</span>
                <span>型号通道数变化 {{ version.diff.summary.model_channel_count_changed || 0 }}</span>
                <span>注册状态变化 {{ version.diff.summary.registration_status_changed }}</span>
                <span v-if="version.diff.documents?.certificate_changed">注册证文件已变化</span>
                <span v-if="version.diff.documents?.difference_changed">注册差异表文件已变化</span>
              </div>
              <el-table
                v-if="version.diff.registration_status_changes?.length"
                :data="version.diff.registration_status_changes"
                size="small"
                border
                class="change-table"
              >
                <el-table-column prop="model" label="型号" />
                <el-table-column prop="probe" label="探头" />
                <el-table-column prop="from" label="变更前" />
                <el-table-column prop="to" label="变更后" />
              </el-table>
              <p v-if="version.change_note" class="change-note">
                更新说明：{{ version.change_note }}
              </p>
            </div>
          </el-collapse-item>
        </el-collapse>
      </article>
    </section>

    <section class="toolbar">
      <el-select v-model="countryCode" aria-label="注册国家" @change="loadModels">
        <el-option label="中国 / CN" value="CN" />
      </el-select>
      <el-input
        v-model="modelQuery"
        clearable
        placeholder="搜索注册型号"
        :prefix-icon="Search"
        @keyup.enter="loadModels"
        @clear="loadModels"
      />
      <el-button type="primary" :icon="Search" @click="loadModels">查询</el-button>
    </section>

    <section class="content-grid">
      <aside class="model-panel" v-loading="modelLoading">
        <div class="panel-title">注册型号</div>
        <button
          v-for="model in models"
          :key="model.id"
          type="button"
          :class="['model-item', { active: selectedModelId === model.id }]"
          @click="selectModel(model.id)"
        >
          <span>{{ model.model_name }}</span>
          <small v-if="model.channel_count">{{ model.channel_count }} 通道</small>
        </button>
        <el-empty v-if="!modelLoading && models.length === 0" description="暂无注册型号" :image-size="56" />
      </aside>

      <main class="probe-panel">
        <div class="probe-header">
          <div>
            <h3>{{ selectedModel?.model_name || '请选择注册型号' }}</h3>
            <p v-if="mappedProductModels.length">
              对应产品型号：{{ mappedProductModels.join('、') }}
            </p>
            <p v-else-if="selectedModelId">尚未关联产品型号</p>
          </div>
          <el-button
            v-if="selectedModel?.source_document_id"
            tag="a"
            :icon="View"
            :href="getKnowledgeDocumentPreviewUrl(selectedModel.source_document_id)"
            target="_blank"
            rel="noopener"
          >
            查看注册原文
          </el-button>
        </div>

        <div v-if="selectedModelId" class="summary-row">
          <span>探头总数 <strong>{{ probeRows.length }}</strong></span>
          <span>已注册 <strong>{{ registeredCount }}</strong></span>
          <span class="danger">未注册 <strong>{{ unregisteredCount }}</strong></span>
          <span>已关联配置项 <strong>{{ linkedConfigCount }}</strong></span>
        </div>

        <el-table
          :data="probeRows"
          v-loading="probeLoading"
          border
          stripe
          empty-text="请选择注册型号"
          class="probe-table"
        >
          <el-table-column prop="probe_model" label="注册探头型号" min-width="150" />
          <el-table-column prop="probe_master_model" label="基础探头型号" min-width="150">
            <template #default="scope">
              <span v-if="scope.row.probe_master_id">{{ scope.row.probe_master_model }}</span>
              <span v-else class="unlinked">未匹配探头主数据</span>
            </template>
          </el-table-column>
          <el-table-column prop="ipn" label="IPN" min-width="115" />
          <el-table-column label="注册状态" width="110" align="center">
            <template #default="scope">
              <el-tag
                :type="scope.row.registration_status === 'registered' ? 'success' : 'danger'"
                effect="plain"
              >
                {{ scope.row.registration_status === 'registered' ? '已注册' : '# 未注册' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="config_name" label="基础配置项" min-width="210">
            <template #default="scope">
              <span v-if="scope.row.config_item_id">{{ scope.row.config_name }}</span>
              <span v-else class="unlinked">未匹配配置项</span>
            </template>
          </el-table-column>
          <el-table-column prop="source_ref" label="来源位置" min-width="160" />
        </el-table>
      </main>
    </section>

    <el-dialog
      v-model="packageDialogVisible"
      title="新增注册资料包"
      width="760px"
      :close-on-click-modal="false"
    >
      <el-alert
        title="注册证文件和注册差异表必须成对提交；先生成草稿，确认机型映射后才会发布。"
        type="warning"
        :closable="false"
        show-icon
        class="dialog-alert"
      />
      <el-form v-if="!draftReview" :model="packageForm" label-width="120px">
        <div class="form-grid">
          <el-form-item label="国家">
            <el-select v-model="packageForm.country_code" disabled>
              <el-option label="中国 / CN" value="CN" />
            </el-select>
          </el-form-item>
          <el-form-item label="注册单元标识">
            <el-input v-model="packageForm.unit_code" placeholder="如 V10-CS-2026" />
          </el-form-item>
          <el-form-item label="资料包名称">
            <el-input v-model="packageForm.display_name" placeholder="如 V10 系列长沙注册" />
          </el-form-item>
          <el-form-item label="产品系列">
            <el-input v-model="packageForm.product_series" placeholder="如 V10" />
          </el-form-item>
          <el-form-item label="注册证号">
            <el-input v-model="packageForm.registration_number" />
          </el-form-item>
          <el-form-item label="生效日期">
            <el-date-picker v-model="packageForm.effective_date" type="date" value-format="YYYY-MM-DD" />
          </el-form-item>
          <el-form-item label="注册证版本">
            <el-input v-model="packageForm.certificate_version" placeholder="日期或文件版本" />
          </el-form-item>
          <el-form-item label="差异表版本">
            <el-input v-model="packageForm.difference_version" placeholder="日期或文件版本" />
          </el-form-item>
        </div>
        <el-form-item label="确认人">
          <el-input v-model="packageForm.confirmed_by" placeholder="填写你的姓名或工号" />
        </el-form-item>
        <el-form-item label="更新说明">
          <el-input v-model="packageForm.change_note" type="textarea" :rows="2" />
        </el-form-item>
        <div class="upload-grid">
          <el-form-item label="注册证文件">
            <el-upload
              action="#"
              :auto-upload="false"
              :limit="1"
              accept=".pdf,application/pdf"
              :on-change="handleCertificateChange"
              :on-remove="handleCertificateRemove"
            >
              <el-button :icon="UploadFilled">选择 PDF</el-button>
            </el-upload>
          </el-form-item>
          <el-form-item label="注册差异表">
            <el-upload
              action="#"
              :auto-upload="false"
              :limit="1"
              accept=".xlsx,.xlsm"
              :on-change="handleDifferenceChange"
              :on-remove="handleDifferenceRemove"
            >
              <el-button :icon="UploadFilled">选择 Excel</el-button>
            </el-upload>
          </el-form-item>
        </div>
      </el-form>

      <div v-else class="mapping-review">
        <div class="review-heading">
          <div>
            <h3>机型映射确认</h3>
            <p>
              已解析 {{ draftReview.model_count }} 个注册型号、
              {{ draftReview.probe_count }} 个探头；以下映射只对本注册证生效。
            </p>
          </div>
          <el-tag type="warning" effect="plain">待发布</el-tag>
        </div>
        <el-table :data="draftReview.mappings" border size="small" empty-text="未自动匹配到产品机型">
          <el-table-column prop="product_model_name" label="产品机型" min-width="180" />
          <el-table-column label="注册基础型号" min-width="210">
            <template #default="scope">
              <el-select v-model="scope.row.registration_model_name" style="width: 100%">
                <el-option
                  v-for="model in draftReview.registration_models"
                  :key="model.id"
                  :label="model.model_name"
                  :value="model.model_name"
                />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column prop="mapping_type" label="匹配方式" width="140" />
        </el-table>
        <el-alert
          v-if="!draftReview.mappings?.length"
          title="没有自动匹配到产品机型，当前草稿不能发布；请先在产品型号中补齐基础型号或衍生型号关系。"
          type="error"
          :closable="false"
          show-icon
          class="mapping-alert"
        />
      </div>

      <template #footer>
        <el-button @click="packageDialogVisible = false">关闭</el-button>
        <el-button v-if="!draftReview" type="primary" :loading="staging" @click="handleStagePackage">
          解析并生成草稿
        </el-button>
        <el-button
          v-else
          type="success"
          :loading="publishing"
          :disabled="!draftReview.mappings?.length"
          @click="handlePublishPackage"
        >
          发布正式版本
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Search, UploadFilled, View } from '@element-plus/icons-vue'
import {
  getConfiguredRegistrationModels,
  getKnowledgeDocumentPreviewUrl,
  getRegistrationModelProbes,
  getRegistrationModels,
  getRegistrationPackageMappings,
  getRegistrationPackages,
  getRegistrationPackageVersions,
  publishRegistrationPackageVersion,
  setRegistrationPackageEnabled,
  stageRegistrationPackageDraft,
  updateRegistrationPackageMappings
} from '../api/data'

const countryCode = ref('CN')
const modelQuery = ref('')
const models = ref([])
const selectedModelId = ref(null)
const probeRows = ref([])
const productMappings = ref([])
const modelLoading = ref(false)
const probeLoading = ref(false)
const packageLoading = ref(false)
const packageGroups = ref([])
const packageDialogVisible = ref(false)
const certificateFile = ref(null)
const differenceFile = ref(null)
const staging = ref(false)
const publishing = ref(false)
const draftReview = ref(null)
const packageForm = ref({
  country_code: 'CN',
  unit_code: '',
  display_name: '',
  product_series: '',
  registration_number: '',
  certificate_version: '',
  difference_version: '',
  confirmed_by: '',
  change_note: '',
  effective_date: ''
})

const selectedModel = computed(() => models.value.find(model => model.id === selectedModelId.value))
const mappedProductModels = computed(() => productMappings.value
  .filter(item => item.registration_model_id === selectedModelId.value)
  .map(item => item.product_model_name))
const registeredCount = computed(() => probeRows.value.filter(row => row.registration_status === 'registered').length)
const unregisteredCount = computed(() => probeRows.value.filter(row => row.registration_status === 'unregistered').length)
const linkedConfigCount = computed(() => probeRows.value.filter(row => row.config_item_id).length)

const loadMappings = async () => {
  const result = await getConfiguredRegistrationModels({
    country_code: countryCode.value,
    include_disabled: true
  })
  productMappings.value = result.items || []
}

const loadModels = async () => {
  modelLoading.value = true
  try {
    const result = await getRegistrationModels({
      country_code: countryCode.value,
      q: modelQuery.value || undefined,
      limit: 200
    })
    models.value = result.items || []
    if (!models.value.some(model => model.id === selectedModelId.value)) {
      selectedModelId.value = models.value[0]?.id || null
    }
    if (selectedModelId.value) await loadProbes()
    else probeRows.value = []
  } catch {
    ElMessage.error('注册型号加载失败')
  } finally {
    modelLoading.value = false
  }
}

const loadProbes = async () => {
  if (!selectedModelId.value) return
  probeLoading.value = true
  try {
    const result = await getRegistrationModelProbes(selectedModelId.value)
    probeRows.value = result.items || []
  } catch {
    ElMessage.error('注册探头加载失败')
  } finally {
    probeLoading.value = false
  }
}

const selectModel = async (modelId) => {
  selectedModelId.value = modelId
  await loadProbes()
}

const loadPackageHistory = async () => {
  packageLoading.value = true
  try {
    const result = await getRegistrationPackages({ country_code: countryCode.value })
    packageGroups.value = await Promise.all((result.items || []).map(async (item) => {
      const history = await getRegistrationPackageVersions(item.id)
      return { ...item, versions: history.items || [] }
    }))
  } catch {
    packageGroups.value = []
    ElMessage.error('注册资料版本加载失败')
  } finally {
    packageLoading.value = false
  }
}

const handleTogglePackageEnabled = async (group) => {
  const nextEnabled = !group.is_enabled
  const action = nextEnabled ? '启用' : '停用'
  try {
    await ElMessageBox.confirm(
      `${action}后，${group.display_name}将${nextEnabled ? '参与' : '不参与'}默认产品注册查询。正式版本和历史资料不会改变。`,
      `${action}注册证`,
      { type: 'warning', confirmButtonText: `确认${action}`, cancelButtonText: '取消' }
    )
    await setRegistrationPackageEnabled(group.id, {
      is_enabled: nextEnabled,
      updated_by: group.confirmed_by || 'product_owner'
    })
    ElMessage.success(`注册证已${action}`)
    await Promise.all([loadPackageHistory(), loadMappings()])
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error.response?.data?.detail || `${action}失败`)
  }
}

const openPackageDialog = () => {
  certificateFile.value = null
  differenceFile.value = null
  draftReview.value = null
  packageDialogVisible.value = true
}

const handleCertificateChange = (file) => {
  certificateFile.value = file.raw
}

const handleCertificateRemove = () => {
  certificateFile.value = null
}

const handleDifferenceChange = (file) => {
  differenceFile.value = file.raw
}

const handleDifferenceRemove = () => {
  differenceFile.value = null
}

const openDraftReview = async (group, version) => {
  try {
    draftReview.value = await getRegistrationPackageMappings(version.id)
    packageForm.value.confirmed_by = group.confirmed_by || ''
    packageDialogVisible.value = true
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '草稿映射加载失败')
  }
}

const handleStagePackage = async () => {
  const required = ['unit_code', 'display_name', 'registration_number', 'confirmed_by']
  if (required.some(key => !packageForm.value[key]?.trim())) {
    ElMessage.warning('请填写注册单元、资料包名称、注册证号和确认人')
    return
  }
  if (!certificateFile.value || !differenceFile.value) {
    ElMessage.warning('请同时选择注册证文件和注册差异表')
    return
  }
  staging.value = true
  try {
    const formData = new FormData()
    Object.entries(packageForm.value).forEach(([key, value]) => {
      if (value) formData.append(key, value)
    })
    formData.append('certificate', certificateFile.value)
    formData.append('difference', differenceFile.value)
    draftReview.value = await stageRegistrationPackageDraft(formData)
    ElMessage.success('已生成待确认草稿，请核对机型映射')
    await loadPackageHistory()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '注册资料解析失败')
  } finally {
    staging.value = false
  }
}

const handlePublishPackage = async () => {
  try {
    await ElMessageBox.confirm(
      '发布后该注册证将成为绑定机型的当前注册红线，历史版本仍会保留。确认发布？',
      '发布注册资料包',
      { type: 'warning', confirmButtonText: '确认发布', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  publishing.value = true
  try {
    const mappings = Object.fromEntries(
      draftReview.value.mappings.map(item => [item.product_model_id, item.registration_model_name])
    )
    await updateRegistrationPackageMappings(draftReview.value.id, mappings)
    await publishRegistrationPackageVersion(
      draftReview.value.id,
      packageForm.value.confirmed_by
    )
    ElMessage.success('注册资料包已发布为正式版本')
    packageDialogVisible.value = false
    draftReview.value = null
    await Promise.all([loadPackageHistory(), loadMappings(), loadModels()])
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '发布失败')
  } finally {
    publishing.value = false
  }
}

onMounted(async () => {
  try {
    await Promise.all([loadMappings(), loadModels(), loadPackageHistory()])
  } catch {
    ElMessage.error('注册主数据加载失败')
  }
})
</script>

<style scoped>
.registration-manage-page { max-width: 1180px; margin: 0 auto; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.header-actions { display: flex; align-items: center; gap: 10px; }
.page-header h2 { margin: 0 0 6px; color: #1f2937; font-size: 22px; }
.page-header p { margin: 0; color: #64748b; font-size: 13px; }
.source-alert { margin-bottom: 14px; }
.package-history { margin-bottom: 14px; padding: 14px 16px; border: 1px solid #dbeafe; border-radius: 10px; background: #f8fbff; }
.package-heading, .package-title, .version-title, .change-summary { display: flex; align-items: center; gap: 10px; }
.package-heading { justify-content: space-between; margin-bottom: 10px; }
.package-heading h3 { margin: 0 0 4px; color: #1f2937; font-size: 16px; }
.package-heading p { margin: 0; color: #64748b; font-size: 12px; }
.package-card { padding: 11px 13px; border: 1px solid #e2e8f0; border-radius: 8px; background: #fff; }
.package-card + .package-card { margin-top: 10px; }
.package-title { justify-content: space-between; margin-bottom: 6px; color: #334155; font-size: 13px; }
.package-identity { display: grid; gap: 3px; }
.package-state { display: flex; align-items: center; gap: 8px; }
.package-title span, .version-counts, .material-versions, .change-note { color: #64748b; font-size: 12px; }
.version-title { min-width: 0; }
.version-counts { margin-left: auto; padding-right: 12px; }
.version-body { padding: 4px 8px 10px; }
.material-actions { display: flex; gap: 8px; }
.baseline-note, .change-summary { margin-top: 10px; padding: 9px 11px; border-radius: 7px; background: #f8fafc; color: #475569; font-size: 12px; }
.change-summary { flex-wrap: wrap; }
.change-table { margin-top: 10px; }
.toolbar { display: grid; grid-template-columns: 180px minmax(280px, 1fr) auto; gap: 10px; margin-bottom: 14px; }
.content-grid { display: grid; grid-template-columns: 245px minmax(0, 1fr); gap: 14px; align-items: start; }
.model-panel, .probe-panel { background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; }
.model-panel { padding: 10px; min-height: 360px; }
.panel-title { padding: 4px 8px 10px; color: #475569; font-size: 12px; font-weight: 600; }
.model-item { width: 100%; display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 10px 11px; border: 0; border-radius: 7px; background: transparent; color: #334155; cursor: pointer; text-align: left; }
.model-item:hover { background: #f8fafc; }
.model-item.active { background: #eff6ff; color: #1d4ed8; font-weight: 600; }
.model-item small { color: #94a3b8; font-weight: 400; }
.probe-panel { padding: 16px; min-height: 360px; }
.probe-header { display: flex; justify-content: space-between; align-items: flex-start; min-height: 48px; }
.probe-header h3 { margin: 0; color: #1f2937; font-size: 16px; }
.probe-header p { margin: 5px 0 0; color: #64748b; font-size: 12px; }
.summary-row { display: flex; flex-wrap: wrap; gap: 18px; margin: 14px 0 12px; padding: 10px 12px; border-radius: 7px; background: #f8fafc; color: #64748b; font-size: 12px; }
.summary-row strong { margin-left: 4px; color: #1f2937; font-size: 16px; }
.summary-row .danger strong { color: #b91c1c; }
.unlinked { color: #b45309; }
.probe-table { width: 100%; }
.dialog-alert { margin-bottom: 16px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; column-gap: 12px; }
.upload-grid { display: grid; grid-template-columns: 1fr 1fr; column-gap: 12px; }
.review-heading { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
.review-heading h3 { margin: 0 0 5px; color: #1f2937; }
.review-heading p { margin: 0; color: #64748b; font-size: 13px; }
.mapping-alert { margin-top: 12px; }
@media (max-width: 850px) {
  .toolbar, .content-grid, .form-grid, .upload-grid { grid-template-columns: 1fr; }
  .model-panel { min-height: auto; }
}
</style>
