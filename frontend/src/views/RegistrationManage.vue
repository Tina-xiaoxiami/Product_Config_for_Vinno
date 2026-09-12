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
          <p>共 {{ packageGroups.length }} 个注册资料包；注册证与差异表成对留存版本。</p>
        </div>
        <div class="package-heading-actions">
          <el-tag type="info" effect="plain">成对受控</el-tag>
          <el-button text @click="historyExpanded = !historyExpanded">
            {{ historyExpanded ? '收起版本' : '查看版本' }}
          </el-button>
        </div>
      </div>
      <div v-show="historyExpanded" class="package-list">
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
                  {{ primaryCertificateLabel(version.certificate.title) }}
                </el-button>
                <el-button
                  v-for="document in version.supporting_documents"
                  :key="`${version.id}-${document.document_id}`"
                  tag="a"
                  :href="document.preview_url"
                  target="_blank"
                  rel="noopener"
                  :icon="View"
                >
                  {{ supportingDocumentLabel(document.role) }}
                </el-button>
                <el-button
                  :icon="View"
                  @click="openArtifactPreview(version, 'difference')"
                >
                  查看差异表
                </el-button>
              </div>
              <p class="material-versions">
                注册证：{{ version.certificate.version || '未标版本' }}；
                差异表：{{ version.difference.version || '未标版本' }}
              </p>
              <p v-if="version.supporting_documents?.length" class="material-versions">
                共同使用：{{ version.supporting_documents.map(document => document.title).join('、') }}
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
      </div>
    </section>

    <el-tabs v-model="registrationView" class="registration-data-tabs">
      <el-tab-pane label="差异汇总" name="summary">
        <section
          data-testid="registration-difference-summary"
          class="difference-panel"
          v-loading="differenceLoading"
        >
          <div class="difference-toolbar">
            <el-select
              v-model="selectedPackageVersionId"
              aria-label="注册资料包"
              placeholder="选择注册资料包"
              @change="loadDifferenceSummary"
            >
              <el-option
                v-for="group in currentPackageGroups"
                :key="group.current_version.id"
                :label="`${group.display_name} · ${group.registration_number}`"
                :value="group.current_version.id"
              />
            </el-select>
            <el-input
              v-model="differenceQuery"
              clearable
              placeholder="在当前注册证内搜索型号"
              :prefix-icon="Search"
            />
            <div class="difference-actions">
              <el-button
                v-if="selectedPackageGroup?.current_version"
                tag="a"
                :href="selectedPackageGroup.current_version.certificate.preview_url"
                target="_blank"
                rel="noopener"
                :icon="View"
              >
                查看注册证
              </el-button>
              <el-button
                v-if="selectedPackageGroup?.current_version"
                :icon="View"
                @click="openArtifactPreview(selectedPackageGroup.current_version, 'difference')"
              >
                查看差异表
              </el-button>
              <el-button
                v-if="selectedPackageGroup?.current_version"
                link
                type="primary"
                tag="a"
                :href="selectedPackageGroup.current_version.difference.preview_url"
                target="_blank"
                rel="noopener"
              >
                下载原件
              </el-button>
            </div>
          </div>

          <div class="summary-row difference-metrics">
            <span>注册型号 <strong>{{ differenceSummary.total_models }}</strong></span>
            <span>探头范围 <strong>{{ differenceSummary.total_probes }}</strong></span>
            <span>全部适用探头 <strong>{{ allApplicableProbeCount }}</strong></span>
            <span class="danger">存在差异探头 <strong>{{ differenceProbeCount }}</strong></span>
            <!-- 紧跟在它筛选的那个数字之后，而不是跟资料包/搜索框挤在顶部工具栏 -->
            <el-select
              v-model="differenceProbeFilter"
              class="difference-probe-filter"
              data-testid="difference-probe-filter"
              size="small"
              clearable
              aria-label="按差异探头筛选"
              placeholder="按差异探头筛选影响的机型"
            >
              <el-option
                v-for="option in differenceProbeOptions"
                :key="option.probe_model"
                :label="differenceProbeOptionLabel(option)"
                :value="option.probe_model"
              />
            </el-select>
          </div>

          <div class="difference-section-title">
            <span>不适用/未注册探头差异</span>
          </div>
          <el-empty
            v-if="differenceTableGroups.length === 0"
            description="当前注册资料包暂无型号差异数据"
            :image-size="56"
          />
          <div v-else class="difference-original-grid">
            <table
              v-for="(group, groupIndex) in differenceTableGroups"
              :key="group[0]?.registration_model_id || groupIndex"
              class="difference-original-table"
            >
              <tbody>
                <tr>
                  <th scope="row">型号</th>
                  <td v-for="model in group" :key="model.registration_model_id">
                    <strong>{{ model.model_name }}</strong>
                    <small v-if="model.channel_count">{{ model.channel_count }} 通道</small>
                  </td>
                </tr>
                <tr>
                  <th scope="row">差异</th>
                  <td v-for="model in group" :key="`${model.registration_model_id}-difference`">
                    <span v-if="model.unregistered_probes.length === 0" class="all-applicable">
                      探头全适用
                    </span>
                    <span v-else class="not-applicable">
                      <span
                        v-for="(probe, index) in model.unregistered_probes"
                        :key="probe.probe_model"
                        :class="{ 'probe-hit': probe.probe_model === differenceProbeFilter }"
                      >{{ probe.probe_model }}{{ isLastProbe(model.unregistered_probes, index) ? '' : '、' }}</span>不适用
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </el-tab-pane>

      <el-tab-pane label="逐型号明细" name="detail">
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
      </el-tab-pane>

      <el-tab-pane label="海外注册查询" name="overseas">
        <section
          data-testid="overseas-registration-query"
          class="overseas-panel"
          v-loading="overseasLoading"
        >
          <el-alert
            title="这里显示国家－型号－探头的仅注册历史数据，可用于注册查询，但不会进入当前配置管理列表。"
            type="info"
            :closable="false"
            show-icon
            class="source-alert"
          />
          <div class="toolbar overseas-toolbar">
            <el-select
              v-model="overseasCountryCode"
              clearable
              placeholder="全部国家"
              aria-label="海外注册国家"
              @change="loadOverseasRelations"
            >
              <el-option
                v-for="country in overseasCountries"
                :key="country.country_code"
                :label="`${country.country_code}（${country.relation_count}）`"
                :value="country.country_code"
              />
            </el-select>
            <el-input
              v-model="overseasQuery"
              clearable
              placeholder="搜索型号或探头型号"
              :prefix-icon="Search"
              @keyup.enter="loadOverseasRelations"
              @clear="loadOverseasRelations"
            />
            <el-button type="primary" :icon="Search" @click="loadOverseasRelations">
              查询
            </el-button>
          </div>
          <div class="summary-row">
            <span>查询结果 <strong>{{ overseasTotal }}</strong></span>
            <span>数据范围 <strong>注册历史</strong></span>
          </div>
          <el-table :data="overseasRows" border stripe empty-text="暂无已发布的海外注册数据">
            <el-table-column prop="country_code" label="国家/地区" width="110" />
            <el-table-column prop="model_name" label="注册型号" min-width="150" />
            <el-table-column prop="probe_model" label="注册探头型号" min-width="150" />
            <el-table-column label="注册状态" width="120" align="center">
              <template #default>
                <el-tag type="success" effect="plain">已完成注册</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="数据属性" min-width="150">
              <template #default="scope">
                <el-tag type="info" effect="plain">仅注册历史数据</el-tag>
                <small v-if="scope.row.product_model_id || scope.row.probe_model_id" class="master-link-note">
                  已找到当前基础数据候选
                </small>
              </template>
            </el-table-column>
            <el-table-column prop="snapshot_date" label="资料日期" width="120" />
            <el-table-column label="原始材料" width="120" align="center">
              <template #default="scope">
                <el-button
                  link
                  type="primary"
                  tag="a"
                  :href="getKnowledgeDocumentPreviewUrl(scope.row.source_document_id)"
                  target="_blank"
                  rel="noopener"
                >
                  查看原表
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </section>
      </el-tab-pane>

      <el-tab-pane label="数据审核与修正" name="review">
        <section
          data-testid="data-review-center"
          class="review-center"
          v-loading="dataReviewLoading"
        >
          <el-alert
            title="原文和原始识别值始终保留；修正后内容作为草稿的有效值，每次修改都会留下记录。"
            type="info"
            :closable="false"
            show-icon
            class="source-alert"
          />
          <div class="review-toolbar">
            <el-select
              v-model="selectedReviewBatchKey"
              placeholder="选择待审核材料"
              aria-label="待审核材料"
              @change="handleReviewBatchChange"
            >
              <el-option
                v-for="batch in dataReviewBatches"
                :key="reviewBatchKey(batch)"
                :label="`${batch.document_title}（${batch.total_count} ${reviewBatchUnit(batch)}）`"
                :value="reviewBatchKey(batch)"
              />
            </el-select>
            <el-select
              v-model="dataReviewStatus"
              clearable
              placeholder="全部审核状态"
              aria-label="审核状态"
              @change="loadDataReviewItems"
            >
              <el-option label="待修正" value="needs_review" />
              <el-option label="已修正" value="corrected" />
              <el-option label="已确认" value="confirmed" />
              <el-option label="自动可用" value="auto_ready" />
              <el-option label="已排除" value="excluded" />
            </el-select>
            <el-input
              v-model="dataReviewQuery"
              clearable
              placeholder="搜索国家、型号、探头或原文位置"
              :prefix-icon="Search"
              @keyup.enter="loadDataReviewItems"
              @clear="loadDataReviewItems"
            />
            <el-button type="primary" :icon="Search" @click="loadDataReviewItems">查询</el-button>
          </div>

          <div v-if="selectedReviewBatch" class="summary-row review-summary">
            <span>{{ reviewRecordLabel(selectedReviewBatch) }} <strong>{{ selectedReviewBatch.total_count }}</strong></span>
            <span class="danger">待修正 <strong>{{ selectedReviewBatch.needs_review_count }}</strong></span>
            <span>已修正 <strong>{{ selectedReviewBatch.corrected_count }}</strong></span>
            <span>已排除 <strong>{{ selectedReviewBatch.excluded_count }}</strong></span>
            <el-button
              link
              type="primary"
              tag="a"
              :href="selectedReviewBatch.preview_url"
              target="_blank"
              rel="noopener"
            >
              查看原文
            </el-button>
          </div>

          <el-table
            :data="dataReviewRows"
            border
            stripe
            empty-text="暂无待审核数据"
            class="review-table"
          >
            <el-table-column prop="source_ref" label="原表位置" min-width="155" />
            <el-table-column label="原始识别值" min-width="235">
              <template #default="scope">
                <div v-if="isChunkReviewRow(scope.row)" class="source-values">
                  <span class="review-type-label">识别正文</span>
                  <span class="chunk-content">{{ scope.row.raw_payload.content }}</span>
                </div>
                <div v-else class="source-values">
                  <span>{{ scope.row.raw_payload.jurisdiction_raw || scope.row.raw_payload.jurisdiction_code }}</span>
                  <strong>{{ scope.row.raw_payload.model_raw }}</strong>
                  <span>{{ scope.row.raw_payload.probe_raw }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="修正后内容" min-width="235">
              <template #default="scope">
                <div v-if="isChunkReviewRow(scope.row)" class="source-values effective-values">
                  <span class="review-type-label">识别正文</span>
                  <span class="chunk-content">{{ scope.row.effective_payload.content }}</span>
                </div>
                <div v-else class="source-values effective-values">
                  <span>{{ scope.row.effective_payload.jurisdiction_code }}</span>
                  <strong>{{ scope.row.effective_payload.model_raw }}</strong>
                  <span>{{ scope.row.effective_payload.probe_raw }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="问题/状态" min-width="190">
              <template #default="scope">
                <el-tag :type="reviewStatusType(scope.row.review_status)" effect="plain" size="small">
                  {{ reviewStatusLabel(scope.row.review_status) }}
                </el-tag>
                <div v-if="scope.row.issue_codes.length" class="issue-list">
                  {{ scope.row.issue_codes.map(issueLabel).join('、') }}
                </div>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="145" align="center" fixed="right">
              <template #default="scope">
                <el-button link type="primary" @click="openDataReviewEditor(scope.row)">
                  审核/修正
                </el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-pagination
            v-if="dataReviewTotal > dataReviewPageSize"
            v-model:current-page="dataReviewPage"
            :page-size="dataReviewPageSize"
            :total="dataReviewTotal"
            layout="prev, pager, next, total"
            class="review-pagination"
            @current-change="loadDataReviewItems"
          />
        </section>
      </el-tab-pane>
    </el-tabs>

    <el-dialog
      v-model="artifactPreviewVisible"
      :title="artifactPreviewTitle"
      width="86%"
      top="5vh"
      :close-on-click-modal="false"
    >
      <div v-loading="artifactPreviewLoading" class="artifact-preview">
        <el-tabs v-if="artifactPreview.sheets.length" v-model="artifactPreviewSheet">
          <el-tab-pane
            v-for="sheet in artifactPreview.sheets"
            :key="sheet.name"
            :label="`${sheet.name}（${sheet.rows.length} 行）`"
            :name="sheet.name"
          >
            <el-alert
              v-if="sheet.truncated"
              title="表格过大，此处仅显示前面部分内容；完整内容请下载原件。"
              type="warning"
              :closable="false"
              class="dialog-alert"
            />
            <div class="artifact-preview-scroll">
              <table class="artifact-preview-table">
                <tbody>
                  <tr v-for="(row, rowIndex) in sheet.rows" :key="rowIndex">
                    <th scope="row">{{ rowIndex + 1 }}</th>
                    <td v-for="(cell, cellIndex) in row" :key="cellIndex">{{ cell }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </el-tab-pane>
        </el-tabs>
        <el-empty
          v-else-if="!artifactPreviewLoading"
          description="该原件没有可预览的工作表"
          :image-size="56"
        />
      </div>
      <template #footer>
        <span class="artifact-preview-name">{{ artifactPreview.file_name }}</span>
        <el-button @click="artifactPreviewVisible = false">关闭</el-button>
        <el-button link type="primary" @click="openArtifactLocally('reveal')">
          在访达中显示
        </el-button>
        <el-button link type="primary" @click="openArtifactLocally('open')">
          本机打开
        </el-button>
        <el-button
          type="primary"
          tag="a"
          :href="artifactPreviewDownloadUrl"
          target="_blank"
          rel="noopener"
        >
          下载原件
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="dataReviewDialogVisible"
      title="审核与修正提取结果"
      width="680px"
      :close-on-click-modal="false"
    >
      <el-alert
        v-if="editingReviewItem && !isChunkReviewRow(editingReviewItem)"
        :title="`原始识别值：${editingReviewItem.raw_payload.model_raw || '-'} / ${editingReviewItem.raw_payload.probe_raw || '-'}`"
        type="info"
        :closable="false"
        class="dialog-alert"
      />
      <el-alert
        v-else-if="editingReviewItem"
        :title="`原始识别正文：${editingReviewItem.raw_payload.content || '-'}`"
        type="info"
        :closable="false"
        class="dialog-alert"
      />
      <el-form :model="dataReviewForm" label-width="100px">
        <el-form-item v-if="isChunkReviewRow(editingReviewItem)" label="识别正文">
          <el-input v-model="dataReviewForm.content" type="textarea" :rows="6" />
        </el-form-item>
        <div v-else class="form-grid">
          <el-form-item label="国家代码">
            <el-input v-model="dataReviewForm.jurisdiction_code" maxlength="2" />
          </el-form-item>
          <el-form-item label="注册状态">
            <el-select v-model="dataReviewForm.registration_status">
              <el-option label="已完成注册" value="completed" />
              <el-option label="进行中" value="in_progress" />
              <el-option label="不需注册" value="not_required" />
              <el-option label="暂停/失败" value="suspended" />
            </el-select>
          </el-form-item>
          <el-form-item label="机型">
            <el-input v-model="dataReviewForm.model_raw" />
          </el-form-item>
          <el-form-item label="探头型号">
            <el-input v-model="dataReviewForm.probe_raw" />
          </el-form-item>
        </div>
        <el-form-item label="修改人">
          <el-input v-model="dataReviewChangedBy" placeholder="姓名或工号" />
        </el-form-item>
        <el-form-item label="修正说明">
          <el-input
            v-model="dataReviewChangeNote"
            type="textarea"
            :rows="2"
            placeholder="如：OCR 将 VINNO 识别为 VINNNO"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dataReviewDialogVisible = false">取消</el-button>
        <el-button type="danger" plain :loading="dataReviewSaving" @click="saveDataReview('excluded')">
          排除此行
        </el-button>
        <el-button type="success" :loading="dataReviewSaving" @click="saveDataReview('corrected')">
          保存修正
        </el-button>
      </template>
    </el-dialog>

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
  getDataReviewBatches,
  getDataReviewItems,
  getRegistrationModelProbes,
  getRegistrationModels,
  getRegistrationDifferenceSummary,
  getRegistrationArtifactSheets,
  getRegistrationPackageMappings,
  getRegistrationPackages,
  getRegistrationPackageVersions,
  openRegistrationArtifactLocally,
  getOverseasRegistrationCountries,
  getOverseasRegistrationRelations,
  updateDataReviewItem,
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
const historyExpanded = ref(false)
const registrationView = ref('summary')
const selectedPackageVersionId = ref(null)
const differenceSummary = ref({ total_models: 0, total_probes: 0, all_applicable_probes: 0, different_probes: 0, models: [] })
const differenceQuery = ref('')
const differenceProbeFilter = ref('')
const differenceLoading = ref(false)
const packageDialogVisible = ref(false)
const certificateFile = ref(null)
const differenceFile = ref(null)
const staging = ref(false)
const publishing = ref(false)
const overseasLoading = ref(false)
const overseasCountries = ref([])
const overseasCountryCode = ref('')
const overseasQuery = ref('')
const overseasRows = ref([])
const overseasTotal = ref(0)
const dataReviewLoading = ref(false)
const dataReviewBatches = ref([])
const selectedReviewBatchKey = ref('')
const dataReviewStatus = ref('needs_review')
const dataReviewQuery = ref('')
const dataReviewRows = ref([])
const dataReviewTotal = ref(0)
const dataReviewPage = ref(1)
const dataReviewPageSize = 50
const dataReviewDialogVisible = ref(false)
const dataReviewSaving = ref(false)
const editingReviewItem = ref(null)
const dataReviewForm = ref({})
const dataReviewChangedBy = ref('product_owner')
const dataReviewChangeNote = ref('')
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
const currentPackageGroups = computed(() => packageGroups.value.filter(group => group.current_version))
const selectedPackageGroup = computed(() => currentPackageGroups.value.find(
  group => group.current_version.id === selectedPackageVersionId.value
))
// 差异探头反查：从各机型的「不适用探头」汇总出 探头 → 受影响机型。
const differenceProbeOptions = computed(() => {
  const byProbe = new Map()
  for (const model of differenceSummary.value.models) {
    for (const probe of model.unregistered_probes) {
      if (!byProbe.has(probe.probe_model)) {
        byProbe.set(probe.probe_model, { probe_model: probe.probe_model, models: [] })
      }
      byProbe.get(probe.probe_model).models.push(model.model_name)
    }
  }
  return [...byProbe.values()].sort(
    (left, right) => right.models.length - left.models.length
      || left.probe_model.localeCompare(right.probe_model)
  )
})
// 下拉只给「型号（受影响机型数）」：IPN 没有决策价值，
// "影响 N 个机型"这类说明也不必写在每一项里，标题与筛选控件本身已交代口径
const differenceProbeOptionLabel = option => (
  `${option.probe_model}（${option.models.length}）`
)
const isLastProbe = (probes, index) => index === probes.length - 1
const filteredDifferenceModels = computed(() => {
  const query = differenceQuery.value.trim().toLowerCase()
  const probeFilter = differenceProbeFilter.value
  return differenceSummary.value.models.filter((model) => {
    if (probeFilter
      && !model.unregistered_probes.some(probe => probe.probe_model === probeFilter)) {
      return false
    }
    if (query && !model.model_name.toLowerCase().includes(query)) return false
    return true
  })
})
// 每行 6 个机型、合并成一个块：原表截图是一块 3 个机型，页面再把两块并排，
// 结果一行出现两套"型号/差异"行标签、还多一条块间距。合并后行标签只留一套，
// 同样的页宽下每个机型反而更宽（少的那个标签列宽度直接还给机型列）。
const DIFFERENCE_MODELS_PER_ROW = 6
const differenceTableGroups = computed(() => {
  const groups = []
  for (let index = 0; index < filteredDifferenceModels.value.length; index += DIFFERENCE_MODELS_PER_ROW) {
    groups.push(filteredDifferenceModels.value.slice(index, index + DIFFERENCE_MODELS_PER_ROW))
  }
  return groups
})
// 全部适用/存在差异以差异对象（探头）为准：所有机型必然有差异，按机型统计没有信息量。
const allApplicableProbeCount = computed(() => differenceSummary.value.all_applicable_probes)
const differenceProbeCount = computed(() => differenceSummary.value.different_probes)

// 原件在线预览：浏览器无法内嵌渲染 xlsx，改为应用内读取工作表后自行画表；下载地址保持不变。
const ARTIFACT_PREVIEW_LABEL = { certificate: '注册证', difference: '差异表' }
const artifactPreviewVisible = ref(false)
const artifactPreviewLoading = ref(false)
const artifactPreviewTitle = ref('原件预览')
const artifactPreviewDownloadUrl = ref('')
const artifactPreviewSheet = ref('')
const artifactPreview = ref({ file_name: '', sheets: [] })
const artifactPreviewTarget = ref({ versionId: null, artifactType: '' })

const openArtifactPreview = async (version, artifactType) => {
  const artifact = artifactType === 'certificate' ? version?.certificate : version?.difference
  if (!artifact) return
  artifactPreviewTitle.value = `${ARTIFACT_PREVIEW_LABEL[artifactType] || '原件'}预览`
  artifactPreviewDownloadUrl.value = artifact.preview_url
  artifactPreviewTarget.value = { versionId: version.id, artifactType }
  artifactPreviewVisible.value = true
  artifactPreviewLoading.value = true
  artifactPreview.value = { file_name: '', sheets: [] }
  artifactPreviewSheet.value = ''
  try {
    const result = await getRegistrationArtifactSheets(version.id, artifactType)
    artifactPreview.value = result
    artifactPreviewSheet.value = result.sheets?.[0]?.name || ''
  } catch (error) {
    artifactPreviewVisible.value = false
    ElMessage.error(error?.response?.data?.detail || '原件在线预览失败，请下载原件查看')
  } finally {
    artifactPreviewLoading.value = false
  }
}

// 后端就跑在本机，因此可直接调用系统默认程序打开原件（仅本机请求有效）。
const openArtifactLocally = async (mode) => {
  const { versionId, artifactType } = artifactPreviewTarget.value
  if (!versionId || !artifactType) return
  try {
    const result = await openRegistrationArtifactLocally(versionId, artifactType, mode)
    ElMessage.success(
      mode === 'reveal'
        ? `已在访达中定位 ${result.file_name}`
        : `已在本机打开 ${result.file_name}`
    )
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '本机打开失败')
  }
}
const reviewBatchKey = batch => `${batch.data_type}:${batch.batch_id}`
const isChunkReviewRow = row => row?.data_type === 'knowledge_document_chunk'
const reviewBatchUnit = batch => isChunkReviewRow(batch) ? '段' : '行'
const reviewRecordLabel = batch => isChunkReviewRow(batch) ? '原文段落' : '原表行'
const selectedReviewBatch = computed(() => dataReviewBatches.value.find(
  batch => reviewBatchKey(batch) === selectedReviewBatchKey.value
))
const reviewStatusLabel = status => ({
  auto_ready: '自动可用',
  needs_review: '待修正',
  corrected: '已修正',
  confirmed: '已确认',
  excluded: '已排除'
}[status] || status)
const reviewStatusType = status => ({
  auto_ready: 'success',
  needs_review: 'warning',
  corrected: 'primary',
  confirmed: 'success',
  excluded: 'info'
}[status] || 'info')
const issueLabel = issue => ({
  jurisdiction_requires_mapping: '国家待匹配',
  non_final_status: '非最终状态',
  narrative_rule_requires_review: '含说明性文字',
  model_scope_requires_expansion: '机型范围待展开',
  model_name_requires_review: '机型名称待修正',
  probe_scope_not_explicit: '探头范围不明确',
  complex_probe_mapping: '探头表述需拆分',
  probe_name_requires_review: '探头名称待修正'
}[issue] || issue)

const primaryCertificateLabel = title => title?.includes('变更') ? '查看变更文件' : '查看注册证'
const supportingDocumentLabel = role => role === 'original_certificate' ? '查看原注册证' : '查看关联变更文件'

const loadOverseasRelations = async () => {
  overseasLoading.value = true
  try {
    const result = await getOverseasRegistrationRelations({
      country_code: overseasCountryCode.value || undefined,
      q: overseasQuery.value || undefined,
      limit: 500
    })
    overseasRows.value = result.items || []
    overseasTotal.value = result.total || 0
  } catch {
    overseasRows.value = []
    overseasTotal.value = 0
    ElMessage.error('海外注册数据加载失败')
  } finally {
    overseasLoading.value = false
  }
}

const loadOverseasCountries = async () => {
  try {
    const result = await getOverseasRegistrationCountries()
    overseasCountries.value = result.items || []
  } catch {
    overseasCountries.value = []
    ElMessage.error('海外注册国家列表加载失败')
  }
}

const loadDataReviewBatches = async () => {
  try {
    const result = await getDataReviewBatches()
    dataReviewBatches.value = result.items || []
    if (!dataReviewBatches.value.some(batch => reviewBatchKey(batch) === selectedReviewBatchKey.value)) {
      const preferred = dataReviewBatches.value.find(batch => batch.batch_status === 'draft') || dataReviewBatches.value[0]
      selectedReviewBatchKey.value = preferred ? reviewBatchKey(preferred) : ''
    }
    await loadDataReviewItems()
  } catch {
    dataReviewBatches.value = []
    dataReviewRows.value = []
    ElMessage.error('待审核数据加载失败')
  }
}

const loadDataReviewItems = async () => {
  if (!selectedReviewBatch.value) {
    dataReviewRows.value = []
    dataReviewTotal.value = 0
    return
  }
  dataReviewLoading.value = true
  try {
    const result = await getDataReviewItems({
      data_type: selectedReviewBatch.value.data_type,
      batch_id: selectedReviewBatch.value.batch_id,
      review_status: dataReviewStatus.value || undefined,
      q: dataReviewQuery.value || undefined,
      skip: (dataReviewPage.value - 1) * dataReviewPageSize,
      limit: dataReviewPageSize
    })
    dataReviewRows.value = result.items || []
    dataReviewTotal.value = result.total || 0
  } catch {
    dataReviewRows.value = []
    dataReviewTotal.value = 0
    ElMessage.error('审核明细加载失败')
  } finally {
    dataReviewLoading.value = false
  }
}

const handleReviewBatchChange = async () => {
  dataReviewPage.value = 1
  await loadDataReviewItems()
}

const openDataReviewEditor = (item) => {
  editingReviewItem.value = item
  dataReviewForm.value = { ...item.effective_payload }
  dataReviewChangeNote.value = item.change_note || ''
  dataReviewDialogVisible.value = true
}

const saveDataReview = async (reviewStatus) => {
  if (!editingReviewItem.value) return
  if (!dataReviewChangedBy.value.trim()) {
    ElMessage.warning('请填写修改人')
    return
  }
  dataReviewSaving.value = true
  try {
    await updateDataReviewItem(editingReviewItem.value.id, {
      effective_payload: dataReviewForm.value,
      review_status: reviewStatus,
      changed_by: dataReviewChangedBy.value.trim(),
      change_note: dataReviewChangeNote.value.trim() || undefined
    })
    ElMessage.success(reviewStatus === 'excluded' ? '已排除该行' : '修正已保存')
    dataReviewDialogVisible.value = false
    await loadDataReviewBatches()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '保存修正失败')
  } finally {
    dataReviewSaving.value = false
  }
}

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

const loadDifferenceSummary = async () => {
  differenceProbeFilter.value = ''
  if (!selectedPackageVersionId.value) {
    differenceSummary.value = { total_models: 0, total_probes: 0, all_applicable_probes: 0, different_probes: 0, models: [] }
    return
  }
  differenceLoading.value = true
  try {
    differenceSummary.value = await getRegistrationDifferenceSummary(selectedPackageVersionId.value)
  } catch {
    differenceSummary.value = { total_models: 0, total_probes: 0, all_applicable_probes: 0, different_probes: 0, models: [] }
    ElMessage.error('注册差异汇总加载失败')
  } finally {
    differenceLoading.value = false
  }
}

const loadPackageHistory = async () => {
  packageLoading.value = true
  try {
    const result = await getRegistrationPackages({ country_code: countryCode.value })
    packageGroups.value = await Promise.all((result.items || []).map(async (item) => {
      const history = await getRegistrationPackageVersions(item.id)
      return { ...item, versions: history.items || [] }
    }))
    const selectedVersionStillExists = currentPackageGroups.value.some(
      group => group.current_version.id === selectedPackageVersionId.value
    )
    if (!selectedVersionStillExists) {
      const preferred = currentPackageGroups.value.find(
        group => group.is_enabled && group.unit_code?.toUpperCase().startsWith('V10')
      ) || currentPackageGroups.value.find(group => group.is_enabled) || currentPackageGroups.value[0]
      selectedPackageVersionId.value = preferred?.current_version.id || null
    }
    await loadDifferenceSummary()
  } catch {
    packageGroups.value = []
    selectedPackageVersionId.value = null
    differenceSummary.value = { total_models: 0, total_probes: 0, all_applicable_probes: 0, different_probes: 0, models: [] }
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
    await Promise.all([
      loadMappings(),
      loadModels(),
      loadPackageHistory(),
      loadOverseasCountries(),
      loadOverseasRelations(),
      loadDataReviewBatches()
    ])
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
.package-heading { justify-content: space-between; }
.package-heading-actions { display: flex; align-items: center; gap: 6px; }
.package-list { margin-top: 10px; }
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
.registration-data-tabs { margin-top: 4px; }
.difference-panel { padding: 16px; border: 1px solid #e5e7eb; border-radius: 10px; background: #fff; }
.artifact-preview-scroll { max-height: 62vh; overflow: auto; }
.artifact-preview-table { border-collapse: collapse; color: #334155; font-size: 12px; }
.artifact-preview-table th, .artifact-preview-table td { padding: 5px 8px; border: 1px solid #e2e8f0; text-align: left; white-space: nowrap; }
.artifact-preview-table th { position: sticky; left: 0; background: #f8fafc; color: #94a3b8; font-weight: 400; text-align: right; }
.artifact-preview-name { float: left; color: #94a3b8; font-size: 12px; line-height: 32px; }
.difference-toolbar { display: grid; grid-template-columns: minmax(240px, 0.8fr) minmax(220px, 1fr) auto; gap: 10px; align-items: center; }
.difference-actions { display: flex; gap: 8px; }
.difference-metrics { align-items: center; margin-bottom: 12px; }
.difference-probe-filter { flex: 0 0 240px; width: 240px; }
.difference-section-title { display: flex; align-items: center; gap: 10px; margin: 2px 0 10px; color: #475569; font-size: 13px; font-weight: 600; }
/* 一块 6 个机型占满整行：行标签只出现一次，机型列拿到全部剩余宽度 */
.difference-original-grid { display: grid; grid-template-columns: 1fr; gap: 12px; }
.difference-original-table { width: 100%; table-layout: fixed; border-collapse: collapse; color: #334155; font-size: 13px; }
.difference-original-table th, .difference-original-table td { padding: 10px 8px; border: 1px solid #cbd5e1; text-align: center; vertical-align: middle; }
.difference-original-table th { width: 54px; background: #f8fafc; color: #475569; font-weight: 600; }
.difference-original-table td { background: #fff; }
.difference-original-table td strong, .difference-original-table td small { display: block; }
.difference-original-table td small { margin-top: 3px; color: #94a3b8; font-weight: 400; }
.all-applicable { color: #15803d; }
.not-applicable { color: #b91c1c; }
.not-applicable .probe-hit { padding: 0 4px; border-radius: 4px; background: #fee2e2; font-weight: 700; }
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
.overseas-panel { padding: 16px; border: 1px solid #e5e7eb; border-radius: 10px; background: #fff; }
.overseas-toolbar { margin-bottom: 0; }
.master-link-note { display: block; margin-top: 4px; color: #64748b; }
.review-center { padding: 16px; border: 1px solid #e5e7eb; border-radius: 10px; background: #fff; }
.review-toolbar { display: grid; grid-template-columns: minmax(240px, 1fr) 150px minmax(260px, 1.3fr) auto; gap: 10px; }
.review-summary { align-items: center; }
.review-summary .el-button { margin-left: auto; }
.review-table { width: 100%; }
.source-values { display: grid; gap: 3px; color: #64748b; font-size: 12px; }
.source-values strong { color: #334155; font-size: 13px; }
.effective-values strong { color: #1d4ed8; }
.review-type-label { color: #94a3b8; font-size: 11px; }
.chunk-content { white-space: pre-wrap; word-break: break-word; line-height: 1.5; }
.issue-list { margin-top: 5px; color: #b45309; font-size: 11px; line-height: 1.45; }
.review-pagination { justify-content: flex-end; margin-top: 14px; }
.dialog-alert { margin-bottom: 16px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; column-gap: 12px; }
.upload-grid { display: grid; grid-template-columns: 1fr 1fr; column-gap: 12px; }
.review-heading { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
.review-heading h3 { margin: 0 0 5px; color: #1f2937; }
.review-heading p { margin: 0; color: #64748b; font-size: 13px; }
.mapping-alert { margin-top: 12px; }
@media (max-width: 850px) {
  .difference-toolbar, .toolbar, .content-grid, .form-grid, .upload-grid, .review-toolbar { grid-template-columns: 1fr; }
  .difference-actions { flex-wrap: wrap; }
  .model-panel { min-height: auto; }
}
</style>
