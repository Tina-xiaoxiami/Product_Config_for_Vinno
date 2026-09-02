<template>
  <div class="registration-manage-page">
    <header class="page-header">
      <div>
        <h2>注册管理</h2>
        <p>注册数据由基础数据统一管理，知识库和产品策略查询共同引用这里的数据。</p>
      </div>
      <el-tag type="success" effect="plain">受控主数据</el-tag>
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
          <strong>{{ group.display_name }}</strong>
          <span>
            {{ group.country_code }} · {{ group.unit_code }} ·
            {{ group.registration_number || '未登记注册证号' }}
          </span>
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
                  {{ version.status === 'active' ? '当前生效' : version.status === 'draft' ? '待确认草稿' : '历史版本' }}
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
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Search, View } from '@element-plus/icons-vue'
import {
  getConfiguredRegistrationModels,
  getKnowledgeDocumentPreviewUrl,
  getRegistrationModelProbes,
  getRegistrationModels,
  getRegistrationPackages,
  getRegistrationPackageVersions
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

const selectedModel = computed(() => models.value.find(model => model.id === selectedModelId.value))
const mappedProductModels = computed(() => productMappings.value
  .filter(item => item.registration_model_id === selectedModelId.value)
  .map(item => item.product_model_name))
const registeredCount = computed(() => probeRows.value.filter(row => row.registration_status === 'registered').length)
const unregisteredCount = computed(() => probeRows.value.filter(row => row.registration_status === 'unregistered').length)
const linkedConfigCount = computed(() => probeRows.value.filter(row => row.config_item_id).length)

const loadMappings = async () => {
  const result = await getConfiguredRegistrationModels({ country_code: countryCode.value })
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
@media (max-width: 850px) {
  .toolbar, .content-grid { grid-template-columns: 1fr; }
  .model-panel { min-height: auto; }
}
</style>
