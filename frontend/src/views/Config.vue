<template>
  <el-config-provider size="small">
  <div ref="configPageRef" class="config-page compact-view">
    <!-- 工具栏 -->
    <el-card class="toolbar-card" shadow="never">
      <div class="toolbar" :inert="applyingModelGroup || reviewInteractionLocked">
        <div class="left">
          <div class="select-all-wrapper" :class="{ 'hide-tags': selectedSeries.length === seriesList.length && seriesList.length > 0 }">
            <el-select v-model="selectedSeries" :disabled="applyingModelGroup" placeholder="选择产品系列（可多选）" @visible-change="onSeriesDropdownVisibleChange" multiple collapse-tags collapse-tags-tooltip style="width: 200px">
            <template #header>
              <div style="display: flex; justify-content: space-between; padding: 4px 12px; gap: 8px;">
                <el-button size="small" @click="selectAllSeries" :disabled="selectedSeries.length === seriesList.length && seriesList.length > 0">全选</el-button>
                <el-button size="small" @click="clearAllSeries" :disabled="selectedSeries.length === 0">清空</el-button>
              </div>
            </template>
            <el-option v-for="s in seriesList" :key="s.id" :label="s.name" :value="s.id" />
          </el-select>
          <span v-if="selectedSeries.length === seriesList.length && seriesList.length > 0" class="select-all-label">ALL</span>
          </div>

          <div class="select-all-wrapper" :class="{ 'hide-tags': tempSelectedModels.length === allModelsMap.size && allModelsMap.size > 0 }">
          <el-select
            v-model="tempSelectedModels"
            :disabled="applyingModelGroup"
            multiple
            collapse-tags
            collapse-tags-tooltip
            placeholder="选择产品型号（可多选）"
            style="width: 170px"
            popper-class="model-select-dropdown"
            @visible-change="onModelDropdownVisibleChange"
            @change="applyModelSelection"
          >
            <template #header>
              <div style="padding: 4px 12px 8px;">
                <el-input
                  v-model="modelFilterText"
                  placeholder="输入搜索型号..."
                  size="small"
                  clearable
                  @keydown.stop
                />
              </div>
              <div style="display: flex; justify-content: space-between; padding: 4px 12px; gap: 8px;">
                <el-button size="small" @click="selectAllModels" :disabled="allModelsMap.size === 0">全选</el-button>
                <el-button size="small" @click="clearAllModels" :disabled="tempSelectedModels.length === 0">取消</el-button>
                <el-button size="small" @click="invertModelSelection" :disabled="allModelsMap.size === 0">反选</el-button>
                <el-button size="small" @click="selectMatchingModels" :disabled="!modelFilterText">选中匹配</el-button>
              </div>
            </template>
            <el-option-group
              v-for="group in filteredModelGroups"
              :key="group.seriesId"
              :label="group.seriesName"
            >
              <el-option
                v-for="m in group.models"
                :key="m.id"
                :label="m.name"
                :value="m.id"
              />
            </el-option-group>
          </el-select>
          <span v-if="tempSelectedModels.length === allModelsMap.size && allModelsMap.size > 0" class="select-all-label">ALL</span>
          </div>

          <el-popover ref="modelGroupsPopover" placement="bottom-start" :width="420" trigger="click">
            <template #reference><el-button :loading="applyingModelGroup">机型分组</el-button></template>
            <div class="model-groups-panel">
              <div class="model-groups-heading"><strong>机型分组</strong><span>保存在当前浏览器</span></div>
              <el-empty v-if="!savedModelGroups.length" description="选好机型后，保存为常用分组" :image-size="48" />
              <div v-for="group in savedModelGroups" :key="group.id" class="model-group-row">
                <el-button text class="model-group-name" :disabled="applyingModelGroup" :title="group.name" @click="applyModelGroup(group)">{{ group.name }} · {{ group.models.length }} 个</el-button>
                <div class="model-group-actions">
                  <el-button text :aria-label="'重命名分组 ' + group.name" @click="renameModelGroup(group)">重命名</el-button>
                  <el-button text :disabled="!selectedModels.length" :aria-label="'更新分组 ' + group.name" @click="updateModelGroup(group)">更新</el-button>
                  <el-button text type="danger" :aria-label="'删除分组 ' + group.name" @click="deleteModelGroup(group)">删除</el-button>
                </div>
              </div>
              <el-button type="primary" :disabled="!selectedModels.length || applyingModelGroup" @click="saveCurrentModelGroup">保存当前选中机型</el-button>
            </div>
          </el-popover>

          <div class="select-all-wrapper" :class="{ 'hide-tags': selectedCategories.length === categoryOptions.length && categoryOptions.length > 0 }">
          <el-select
            v-model="selectedCategories"
            :disabled="applyingModelGroup"
            multiple
            collapse-tags
            collapse-tags-tooltip
            placeholder="选择分类（可多选）"
            style="width: 200px"
            @change="onFilterChange"
          >
            <el-option label="Optional Features" value="Optional Features" />
            <el-option label="Optional peripherals" value="Optional peripherals" />
            <el-option label="*Optional peripherals(Preassemble in Factory)" value="*Optional peripherals(Preassemble in Factory)" />
            <el-option label="Probes" value="Probes" />
            <el-option label="Biopsy guide" value="Biopsy guide" />
          </el-select>
          <span v-if="selectedCategories.length === categoryOptions.length && categoryOptions.length > 0" class="select-all-label">ALL</span>
          </div>

          <el-input
            v-model="searchText"
            :disabled="applyingModelGroup"
            placeholder="搜索研发名称/IPN号"
            style="width: 200px"
            clearable
            @input="queueSearch"
            @keyup.enter="flushSearch"
            @clear="flushSearch"
          />

          <el-button v-if="hasActiveFilters" link type="primary" @click="resetActiveFilters">清除筛选</el-button>

          <el-popover ref="popoverRef" placement="bottom" :width="320" trigger="click" @before-enter="initTempColumns" @hide="applyTempColumns">
            <template #reference>
              <el-button :icon="Setting">列筛选</el-button>
            </template>
            <div class="column-filter">
              <div class="filter-title">固定列（至少固定一列）</div>
              <div class="column-row">
                <el-checkbox v-model="tempVisibleColumns.rd_name">研发名称</el-checkbox>
                <el-checkbox v-model="tempFixedColumns.rd_name" :disabled="!tempVisibleColumns.rd_name">固定</el-checkbox>
              </div>
              <div class="column-row">
                <el-checkbox v-model="tempVisibleColumns.v_code">V代码</el-checkbox>
                <el-checkbox v-model="tempFixedColumns.v_code" :disabled="!tempVisibleColumns.v_code">固定</el-checkbox>
              </div>
              <div class="column-row">
                <el-checkbox v-model="tempVisibleColumns.ipn">IPN号</el-checkbox>
                <el-checkbox v-model="tempFixedColumns.ipn" :disabled="!tempVisibleColumns.ipn">固定</el-checkbox>
              </div>
              <div class="column-row">
                <el-checkbox v-model="tempVisibleColumns.zh_desc">中文描述</el-checkbox>
                <el-checkbox v-model="tempFixedColumns.zh_desc" :disabled="!tempVisibleColumns.zh_desc">固定</el-checkbox>
              </div>
              <div class="column-row">
                <el-checkbox v-model="tempVisibleColumns.en_desc">英文描述</el-checkbox>
                <el-checkbox v-model="tempFixedColumns.en_desc" :disabled="!tempVisibleColumns.en_desc">固定</el-checkbox>
              </div>
              <el-divider />
              <div class="filter-title">型号配置列</div>
              <el-checkbox v-model="tempVisibleColumns.final_config">最终配置</el-checkbox>
              <el-checkbox v-model="tempVisibleColumns.current_config">当前配置</el-checkbox>
              <el-checkbox v-model="tempVisibleColumns.selection_config">选型类别</el-checkbox>
              <el-checkbox v-model="tempVisibleColumns.rd_status">研发状态</el-checkbox>
              <el-divider />
              <el-button size="small" @click="resetTempColumns">重置</el-button>
              <el-button type="primary" size="small" @click="applyTempColumnsAndClose">应用</el-button>
            </div>
          </el-popover>
        </div>

        <div class="right">
          <el-upload
            :show-file-list="false"
            :http-request="handleMultiFileUpload"
            accept=".xlsx,.xls"
            multiple
          >
            <el-button type="primary" :icon="Upload">导入Excel</el-button>
          </el-upload>
          <el-button :icon="Download" @click="handleExport">导出Excel</el-button>

          <!-- 批量操作 -->
          <el-dropdown v-if="selectedSeries.length > 0" @command="handleBatchOperation">
            <el-button type="warning">
              批量操作 ({{ selectedSeries.length }})<el-icon class="el-icon--right"><ArrowDown /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="batchDiscard">批量撤销草稿</el-dropdown-item>
                <el-dropdown-item command="batchSubmit">批量提交草稿</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>

          <el-button type="success" :icon="DocumentChecked" @click="handleCreateVersion">创建版本</el-button>
          <el-button
            :type="showRdIncomplete ? 'primary' : 'default'"
            :icon="EditPen"
            @click="showRdIncomplete = !showRdIncomplete"
          >{{ showRdIncomplete ? '取消标记' : '标记未完成' }}</el-button>
          <el-button
            v-if="showRdIncomplete"
            type="danger"
            :icon="DocumentChecked"
            @click="handleBatchCompleteRdStatus"
          >
            一键完成
          </el-button>
          <el-button
            v-if="selectedModels.length >= 2"
            :type="showDiffOnly ? 'primary' : 'default'"
            :icon="Filter"
            @click="toggleDiffFilter"
          >仅差异项</el-button>
          <div class="select-item" v-if="selectedModels.length >= 2">
            <label>参考机型：</label>
            <el-select v-model="referenceModel" style="width: 120px" placeholder="选择参考机型" @change="onDiffFilterChange">
              <el-option-group
                v-for="group in modelGroups"
                :key="group.seriesId"
                :label="group.seriesName"
              >
                <el-option
                  v-for="m in group.models.filter(m => selectedModels.includes(m.id))"
                  :key="m.id"
                  :label="m.name"
                  :value="m.id"
                />
              </el-option-group>
            </el-select>
          </div>
        </div>
      </div>
    </el-card>

    <!-- 草稿状态栏 -->
    <transition name="el-zoom-in-top">
      <el-card v-if="draftItemSummary.total > 0" class="draft-bar" shadow="never" :inert="configLoading || reviewInteractionLocked">
        <div class="draft-info">
          <el-icon><EditPen /></el-icon>
          <span>当前筛选内 <strong>{{ draftItemSummary.total }}</strong> 个配置项有变更：</span>
          <el-tag
            :type="getDraftTagType('all')"
            size="small"
            class="clickable-tag"
            @click="toggleDraftFilter('all')"
          >
            全部草稿 {{ draftItemSummary.total }}
          </el-tag>
          <el-tag
            v-if="draftItemSummary.create > 0"
            :type="getDraftTagType('create')"
            size="small"
            class="clickable-tag"
            @click="toggleDraftFilter('create')"
          >
            新增 {{ draftItemSummary.create }}
          </el-tag>
          <el-tag
            v-if="draftItemSummary.update > 0"
            :type="getDraftTagType('update')"
            size="small"
            class="clickable-tag"
            @click="toggleDraftFilter('update')"
          >
            修改 {{ draftItemSummary.update }}
          </el-tag>
          <el-tag
            v-if="draftItemSummary.delete > 0"
            :type="getDraftTagType('delete')"
            size="small"
            class="clickable-tag"
            @click="toggleDraftFilter('delete')"
          >
            删除 {{ draftItemSummary.delete }}
          </el-tag>
          <el-button
            v-if="draftFilterMode"
            type="primary"
            link
            size="small"
            @click="clearDraftFilter()"
            style="color: white; margin-left: 10px;"
          >
            显示全部
          </el-button>
          <div class="draft-actions">
            <el-button type="primary" size="small" @click="handleSubmitDraft()">提交发布</el-button>
            <el-button size="small" @click="handleDiscardDraft">废弃全部</el-button>
            <el-button v-if="draftModels.length > 0" size="small" type="info" plain @click="showModelBar = !showModelBar">
              按机型提交
            </el-button>
            <el-button size="small" type="info" plain @click="draftExpanded = !draftExpanded">
              <el-icon :class="{ 'is-rotated': draftExpanded }"><ArrowDown /></el-icon>
              {{ draftExpanded ? '收起列表' : '查看列表' }}
            </el-button>
          </div>
        </div>

        <div class="draft-count-note">配置项按行去重；同一项可同时包含新增、修改或删除，分类数量不能直接相加。</div>

        <!-- 机型筛选栏（默认隐藏） -->
        <div v-if="draftModels.length > 0 && showModelBar" class="draft-model-bar">
          <span class="model-bar-label">按机型提交：</span>
          <el-tag
            v-for="m in draftModels"
            :key="m.id"
            size="small"
            :type="selectedDraftModelIds.has(m.id) ? 'primary' : 'info'"
            class="clickable-tag"
            @click="toggleDraftModel(m.id)"
          >{{ m.name }}</el-tag>
          <el-button
            v-if="selectedDraftModelIds.size > 0"
            type="primary"
            size="small"
            @click="handleSubmitModel"
          >提交选中机型</el-button>
          <el-button
            v-if="selectedDraftModelIds.size > 0"
            link
            size="small"
            @click="selectedDraftModelIds = new Set()"
            style="color: rgba(255,255,255,0.7);"
          >清除</el-button>
        </div>

        <!-- 可展开的草稿项列表 -->
        <div v-show="draftExpanded" class="draft-items-panel">
          <div class="draft-items-header">
            <el-checkbox
              :checked="allDraftSelected"
              :indeterminate="someDraftSelected"
              @change="toggleSelectAll"
            >全选</el-checkbox>
            <span class="selected-count">已选 {{ selectedDraftItemIds.size }} 项</span>
            <el-button
              type="primary"
              size="small"
              :disabled="selectedDraftItemIds.size === 0"
              @click="handleSubmitDraft(selectedDraftItemIds)"
            >提交选中项</el-button>
          </div>
          <div class="draft-items-list">
            <div
              v-for="item in draftItems"
              :key="`${item.changeType}_${item.itemId}`"
              class="draft-item-row"
              :class="selectedDraftItemIds.has(item.itemId) ? 'is-selected' : ''"
            >
              <el-checkbox
                :checked="selectedDraftItemIds.has(item.itemId)"
                @change="(val) => toggleDraftItem(item.itemId, val)"
              />
              <el-tag size="small" :type="item.changeType === 'create' ? 'success' : (item.changeType === 'delete' ? 'danger' : 'warning')" class="change-badge">
                {{ item.changeType === 'create' ? '新增' : (item.changeType === 'delete' ? '删除' : '修改') }}
              </el-tag>
              <span class="item-name">{{ item.rdName }}</span>
              <span v-if="item.ipn" class="item-ipn">{{ item.ipn }}</span>
            </div>
          </div>
        </div>
      </el-card>
    </transition>

    <div v-if="draftSaveFeedback.pending || draftSaveFeedback.message" class="save-feedback" :inert="reviewInteractionLocked" role="status" aria-live="polite">
      <span>{{ draftSaveFeedback.pending ? `正在保存 ${draftSaveFeedback.pending} 处…` : draftSaveFeedback.message }}</span>
      <el-button v-if="draftSaveFeedback.lastCell && !draftSaveFeedback.pending" link type="primary" @click="undoLastCell">撤销该单元格草稿</el-button>
      <el-button v-if="draftSaveFeedback.failedCell && !draftSaveFeedback.pending" link type="primary" :title="`${draftSaveFeedback.failedCell.row.rd_name || '配置项 ' + draftSaveFeedback.failedCell.row.id} / ${getModelName(draftSaveFeedback.failedCell.modelId)} / ${fieldLabels[draftSaveFeedback.failedCell.field]}`" @click="retryFailedCell">{{ draftSaveFeedback.failedCell.action === 'undo' ? '重试撤销一处' : '重试保存一处' }}</el-button>
    </div>

    <!-- 批量操作栏 -->
    <transition name="el-zoom-in-top">
      <el-card v-if="selectedRows.length > 0" class="batch-bar" shadow="never" :inert="configLoading || reviewInteractionLocked">
        <div class="batch-info">
          <span v-if="selectedRows.length > 0">已选择 <strong>{{ selectedRows.length }}</strong> 行</span>
          <span v-if="false">已选择 <strong>{{ selectedCells.length }}</strong> 个单元格</span>
          <el-button v-if="selectedRows.length > 0" size="small" @click="handleBatchEdit">批量修改</el-button>
          <el-button v-if="false" type="primary" size="small" @click="pasteToSelectedCells">粘贴到选中单元格</el-button>
          <el-button size="small" @click="clearSelection">取消选择</el-button>
        </div>
      </el-card>
    </transition>

    <!-- 数据表格 -->
    <el-card class="config-table-card" shadow="never" :inert="reviewInteractionLocked">
      <el-table
        ref="tableRef"
        :data="paginatedTableData"
        border
        stripe
        :height="tableMaxHeight"
        v-loading="configLoading"
        @selection-change="handleSelectionChange"
        @header-dragend="onConfigDragEnd"
        @mouseup="onConfigMouseUp"
        row-key="id"
      >
        <el-table-column type="selection" width="40" fixed />

        <el-table-column v-if="visibleColumns.rd_name" :fixed="fixedColumns.rd_name ? 'left' : false" prop="rd_name" label="研发名称" width="220" show-overflow-tooltip />
        <el-table-column v-if="visibleColumns.v_code" :fixed="fixedColumns.v_code ? 'left' : false" prop="v_code" label="V代码" width="100" show-overflow-tooltip />
        <el-table-column v-if="visibleColumns.ipn" :fixed="fixedColumns.ipn ? 'left' : false" prop="ipn" label="IPN号" width="120" show-overflow-tooltip />
        <el-table-column v-if="visibleColumns.zh_desc" :fixed="fixedColumns.zh_desc ? 'left' : false" prop="zh_desc" label="中文描述" width="160" show-overflow-tooltip />
        <el-table-column v-if="visibleColumns.en_desc" :fixed="fixedColumns.en_desc ? 'left' : false" prop="en_desc" label="英文描述" width="160" show-overflow-tooltip />

        <template v-for="group in groupedSelectedModels" :key="group.seriesId">
          <el-table-column :label="group.seriesName">
            <el-table-column
              v-for="modelId in group.modelIds"
              :key="modelId"
              :label="getModelShortName(modelId)"
            >
          <el-table-column v-if="visibleColumns.final_config" label="最终配置" :width="fieldColWidths.final_config">
            <template #header>
              <div class="column-header-with-filter">
                <span>最终配置</span>
                <el-popover placement="bottom" :width="220" trigger="click" teleported popper-class="field-filter-popover" @show="openFieldFilterPopover('final_config', modelId)" @hide="applyFieldFilterPopover('final_config', modelId)">
                  <template #reference>
                    <span class="filter-icon" :class="{ active: hasFieldFilter('final_config', modelId) }" @click.stop>
                      <el-icon><Filter /></el-icon>
                    </span>
                  </template>
                  <div class="filter-body">
                    <div class="filter-actions">
                      <el-button size="small" @click="selectAllFieldFilter('final_config', modelId)">全选</el-button>
                      <el-button size="small" @click="clearFieldFilter('final_config', modelId)">清空</el-button>
                    </div>
                    <el-checkbox-group v-model="pendingFieldFilters[getFilterKey('final_config', modelId)]" class="filter-checkboxes">
                      <el-checkbox v-for="v in (fieldFilterOptions[getFilterKey('final_config', modelId)] || [])" :key="v" :label="v" :value="v" />
                    </el-checkbox-group>
                  </div>
                </el-popover>
              </div>
            </template>
            <template #default="{ row }">
              <div
                v-if="row.model_values[modelId]"
                class="cell-value"
                :class="{
                  'cell-changed': (getCellState(row.id, modelId, 'final_config').isChanged) && !(showDiffOnly && row.model_values[modelId]?._hasDiff?.final_config),
                  'cell-created': !(showDiffOnly && row.model_values[modelId]?._hasDiff?.final_config) && getCellState(row.id, modelId, 'final_config').changeType === 'create',
                  'cell-updated': !(showDiffOnly && row.model_values[modelId]?._hasDiff?.final_config) && getCellState(row.id, modelId, 'final_config').changeType === 'update',
                  'cell-deleted': getCellState(row.id, modelId, 'final_config').changeType === 'delete',
                  'cell-selected': isCellSelected(row.id, modelId, 'final_config'),
                  'cell-focused': focusedCell?.rowId === row.id && focusedCell?.modelId === modelId && focusedCell?.field === 'final_config',
                  'cell-drag-target': isDragTarget(row.id, modelId, 'final_config'),
                  'cell-diff': row.model_values[modelId]?._hasDiff?.final_config
                }"
                :data-cell="`${row.id}-${modelId}-final_config`"
                @click="handleCellClick($event, row, modelId, 'final_config')"
                @contextmenu.prevent="showContextMenu($event, row, modelId, 'final_config')"
                @dragstart="handleDragStart($event, row, modelId, 'final_config')"
                @dragover="handleDragOver($event, row, modelId, 'final_config')"
                @drop="handleDrop($event, row, modelId, 'final_config')"
                @dragend="handleDragEnd"
                draggable="true"
              >
                <template v-if="editingCell?.rowId === row.id && editingCell?.modelId === modelId && editingCell?.field === 'final_config'">
                  <el-select
                    v-model="row.model_values[modelId].final_config"
                    size="small"
                    placeholder="-"
                    clearable
                    filterable
                    allow-create
                    @change="finishEdit(row, modelId, 'final_config', row.model_values[modelId].final_config)"
                    @blur="finishEdit(row, modelId, 'final_config', row.model_values[modelId].final_config)"
                    ref="editSelectRef"
                  >
                    <el-option v-for="v in enumValues.configValues" :key="v" :label="v" :value="v" />
                  </el-select>
                </template>
                <template v-else>
                  <span class="value-text">
                    {{ getCellState(row.id, modelId, 'final_config').changeType === 'delete'
                       ? (getDeleteOldValue(row.id, modelId, 'final_config') || '-')
                       : (row.model_values[modelId].final_config || '-') }}
                  </span>
                  <span v-if="getCellState(row.id, modelId, 'final_config').draftOldValue != null" class="original-hint">
                    ({{ getCellState(row.id, modelId, 'final_config').draftOldValue }})
                  </span>
                </template>
              </div>
            </template>
          </el-table-column>
          <el-table-column v-if="visibleColumns.current_config" label="当前配置" :width="fieldColWidths.current_config">
            <template #header>
              <div class="column-header-with-filter">
                <span>当前配置</span>
                <el-popover placement="bottom" :width="220" trigger="click" teleported popper-class="field-filter-popover" @show="openFieldFilterPopover('current_config', modelId)" @hide="applyFieldFilterPopover('current_config', modelId)">
                  <template #reference>
                    <span class="filter-icon" :class="{ active: hasFieldFilter('current_config', modelId) }" @click.stop>
                      <el-icon><Filter /></el-icon>
                    </span>
                  </template>
                  <div class="filter-body">
                    <div class="filter-actions">
                      <el-button size="small" @click="selectAllFieldFilter('current_config', modelId)">全选</el-button>
                      <el-button size="small" @click="clearFieldFilter('current_config', modelId)">清空</el-button>
                    </div>
                    <el-checkbox-group v-model="pendingFieldFilters[getFilterKey('current_config', modelId)]" class="filter-checkboxes">
                      <el-checkbox v-for="v in (fieldFilterOptions[getFilterKey('current_config', modelId)] || [])" :key="v" :label="v" :value="v" />
                    </el-checkbox-group>
                  </div>
                </el-popover>
              </div>
            </template>
            <template #default="{ row }">
              <div
                v-if="row.model_values[modelId]"
                class="cell-value"
                :class="{
                  'cell-changed': (getCellState(row.id, modelId, 'current_config').isChanged) && !(showDiffOnly && row.model_values[modelId]?._hasDiff?.current_config),
                  'cell-created': !(showDiffOnly && row.model_values[modelId]?._hasDiff?.current_config) && getCellState(row.id, modelId, 'current_config').changeType === 'create',
                  'cell-updated': !(showDiffOnly && row.model_values[modelId]?._hasDiff?.current_config) && getCellState(row.id, modelId, 'current_config').changeType === 'update',
                  'cell-deleted': getCellState(row.id, modelId, 'current_config').changeType === 'delete',
                  'cell-selected': isCellSelected(row.id, modelId, 'current_config'),
                  'cell-focused': focusedCell?.rowId === row.id && focusedCell?.modelId === modelId && focusedCell?.field === 'current_config',
                  'cell-drag-target': isDragTarget(row.id, modelId, 'current_config'),
                  'cell-diff': row.model_values[modelId]?._hasDiff?.current_config
                }"
                :data-cell="`${row.id}-${modelId}-current_config`"
                @click="handleCellClick($event, row, modelId, 'current_config')"
                @contextmenu.prevent="showContextMenu($event, row, modelId, 'current_config')"
                @dragstart="handleDragStart($event, row, modelId, 'current_config')"
                @dragover="handleDragOver($event, row, modelId, 'current_config')"
                @drop="handleDrop($event, row, modelId, 'current_config')"
                @dragend="handleDragEnd"
                draggable="true"
              >
                <template v-if="editingCell?.rowId === row.id && editingCell?.modelId === modelId && editingCell?.field === 'current_config'">
                  <el-select
                    ref="editSelectRef"
                    v-model="row.model_values[modelId].current_config"
                    size="small"
                    placeholder="-"
                    clearable
                    filterable
                    allow-create
                    @change="finishEdit(row, modelId, 'current_config', row.model_values[modelId].current_config)"
                    @blur="finishEdit(row, modelId, 'current_config', row.model_values[modelId].current_config)"
                  >
                    <el-option v-for="v in enumValues.configValues" :key="v" :label="v" :value="v" />
                  </el-select>
                </template>
                <template v-else>
                  <span class="value-text">
                    {{ getCellState(row.id, modelId, 'current_config').changeType === 'delete'
                       ? (getDeleteOldValue(row.id, modelId, 'current_config') || '-')
                       : (row.model_values[modelId].current_config || '-') }}
                  </span>
                  <span v-if="getCellState(row.id, modelId, 'current_config').draftOldValue != null" class="original-hint">
                    ({{ getCellState(row.id, modelId, 'current_config').draftOldValue }})
                  </span>
                </template>
              </div>
            </template>
          </el-table-column>
          <el-table-column v-if="visibleColumns.selection_config" label="选型类别" :width="fieldColWidths.selection_config">
            <template #header>
              <div class="column-header-with-filter">
                <span>选型类别</span>
                <el-popover placement="bottom" :width="220" trigger="click" teleported popper-class="field-filter-popover" @show="openFieldFilterPopover('selection_config', modelId)" @hide="applyFieldFilterPopover('selection_config', modelId)">
                  <template #reference>
                    <span class="filter-icon" :class="{ active: hasFieldFilter('selection_config', modelId) }" @click.stop>
                      <el-icon><Filter /></el-icon>
                    </span>
                  </template>
                  <div class="filter-body">
                    <div class="filter-actions">
                      <el-button size="small" @click="selectAllFieldFilter('selection_config', modelId)">全选</el-button>
                      <el-button size="small" @click="clearFieldFilter('selection_config', modelId)">清空</el-button>
                    </div>
                    <el-checkbox-group v-model="pendingFieldFilters[getFilterKey('selection_config', modelId)]" class="filter-checkboxes">
                      <el-checkbox v-for="v in (fieldFilterOptions[getFilterKey('selection_config', modelId)] || [])" :key="v" :label="v" :value="v" />
                    </el-checkbox-group>
                  </div>
                </el-popover>
              </div>
            </template>
            <template #default="{ row }">
              <div
                v-if="row.model_values[modelId]"
                class="cell-value"
                :class="{
                  'cell-changed': (getCellState(row.id, modelId, 'selection_config').isChanged) && !(showDiffOnly && row.model_values[modelId]?._hasDiff?.selection_config),
                  'cell-created': !(showDiffOnly && row.model_values[modelId]?._hasDiff?.selection_config) && getCellState(row.id, modelId, 'selection_config').changeType === 'create',
                  'cell-updated': !(showDiffOnly && row.model_values[modelId]?._hasDiff?.selection_config) && getCellState(row.id, modelId, 'selection_config').changeType === 'update',
                  'cell-deleted': getCellState(row.id, modelId, 'selection_config').changeType === 'delete',
                  'cell-selected': isCellSelected(row.id, modelId, 'selection_config'),
                  'cell-focused': focusedCell?.rowId === row.id && focusedCell?.modelId === modelId && focusedCell?.field === 'selection_config',
                  'cell-drag-target': isDragTarget(row.id, modelId, 'selection_config'),
                  'cell-diff': row.model_values[modelId]?._hasDiff?.selection_config
                }"
                :data-cell="`${row.id}-${modelId}-selection_config`"
                @click="handleCellClick($event, row, modelId, 'selection_config')"
                @contextmenu.prevent="showContextMenu($event, row, modelId, 'selection_config')"
                @dragstart="handleDragStart($event, row, modelId, 'selection_config')"
                @dragover="handleDragOver($event, row, modelId, 'selection_config')"
                @drop="handleDrop($event, row, modelId, 'selection_config')"
                @dragend="handleDragEnd"
                draggable="true"
              >
                <template v-if="editingCell?.rowId === row.id && editingCell?.modelId === modelId && editingCell?.field === 'selection_config'">
                  <el-select
                    ref="editSelectRef"
                    v-model="row.model_values[modelId].selection_config"
                    size="small"
                    placeholder="-"
                    clearable
                    filterable
                    allow-create
                    @change="finishEdit(row, modelId, 'selection_config', row.model_values[modelId].selection_config)"
                    @blur="finishEdit(row, modelId, 'selection_config', row.model_values[modelId].selection_config)"
                  >
                    <el-option v-for="v in enumValues.selectionTypes" :key="v" :label="v" :value="v" />
                  </el-select>
                </template>
                <template v-else>
                  <span class="value-text">
                    {{ getCellState(row.id, modelId, 'selection_config').changeType === 'delete'
                       ? (getDeleteOldValue(row.id, modelId, 'selection_config') || '-')
                       : (row.model_values[modelId].selection_config || '-') }}
                  </span>
                  <span v-if="getCellState(row.id, modelId, 'selection_config').draftOldValue != null" class="original-hint">
                    ({{ getCellState(row.id, modelId, 'selection_config').draftOldValue }})
                  </span>
                </template>
              </div>
            </template>
          </el-table-column>
          <el-table-column v-if="visibleColumns.rd_status" label="研发状态" :width="fieldColWidths.rd_status">
            <template #header>
              <div class="column-header-with-filter">
                <span>研发状态</span>
                <el-popover placement="bottom" :width="220" trigger="click" teleported popper-class="field-filter-popover" @show="openFieldFilterPopover('rd_status', modelId)" @hide="applyFieldFilterPopover('rd_status', modelId)">
                  <template #reference>
                    <span class="filter-icon" :class="{ active: hasFieldFilter('rd_status', modelId) }" @click.stop>
                      <el-icon><Filter /></el-icon>
                    </span>
                  </template>
                  <div class="filter-body">
                    <div class="filter-actions">
                      <el-button size="small" @click="selectAllFieldFilter('rd_status', modelId)">全选</el-button>
                      <el-button size="small" @click="clearFieldFilter('rd_status', modelId)">清空</el-button>
                    </div>
                    <el-checkbox-group v-model="pendingFieldFilters[getFilterKey('rd_status', modelId)]" class="filter-checkboxes">
                      <el-checkbox v-for="v in (fieldFilterOptions[getFilterKey('rd_status', modelId)] || [])" :key="v" :label="v" :value="v" />
                    </el-checkbox-group>
                  </div>
                </el-popover>
              </div>
            </template>
            <template #default="{ row }">
              <div
                v-if="row.model_values[modelId]"
                class="cell-value"
                :class="{
                  'cell-changed': (getCellState(row.id, modelId, 'rd_status').isChanged) && !(showDiffOnly && row.model_values[modelId]?._hasDiff?.rd_status),
                  'cell-created': !(showDiffOnly && row.model_values[modelId]?._hasDiff?.rd_status) && getCellState(row.id, modelId, 'rd_status').changeType === 'create',
                  'cell-updated': !(showDiffOnly && row.model_values[modelId]?._hasDiff?.rd_status) && getCellState(row.id, modelId, 'rd_status').changeType === 'update',
                  'cell-deleted': getCellState(row.id, modelId, 'rd_status').changeType === 'delete',
                  'cell-selected': isCellSelected(row.id, modelId, 'rd_status'),
                  'cell-focused': focusedCell?.rowId === row.id && focusedCell?.modelId === modelId && focusedCell?.field === 'rd_status',
                  'cell-drag-target': isDragTarget(row.id, modelId, 'rd_status'),
                  'cell-diff': row.model_values[modelId]?._hasDiff?.rd_status,
                  'cell-rd-incomplete': showRdIncomplete && row.model_values[modelId].rd_status && row.model_values[modelId].rd_status !== '已完成' && row.model_values[modelId].rd_status !== 'N/A' && row.model_values[modelId].rd_status !== '-'
                }"
                :data-cell="`${row.id}-${modelId}-rd_status`"
                @click="handleCellClick($event, row, modelId, 'rd_status')"
                @contextmenu.prevent="showContextMenu($event, row, modelId, 'rd_status')"
                @dragstart="handleDragStart($event, row, modelId, 'rd_status')"
                @dragover="handleDragOver($event, row, modelId, 'rd_status')"
                @drop="handleDrop($event, row, modelId, 'rd_status')"
                @dragend="handleDragEnd"
                draggable="true"
              >
                <template v-if="editingCell?.rowId === row.id && editingCell?.modelId === modelId && editingCell?.field === 'rd_status'">
                  <el-select
                    ref="editSelectRef"
                    v-model="row.model_values[modelId].rd_status"
                    size="small"
                    placeholder="-"
                    clearable
                    filterable
                    allow-create
                    @change="finishEdit(row, modelId, 'rd_status', row.model_values[modelId].rd_status)"
                    @blur="finishEdit(row, modelId, 'rd_status', row.model_values[modelId].rd_status)"
                  >
                    <el-option v-for="v in enumValues.rdStatuses" :key="v" :label="v" :value="v" />
                  </el-select>
                </template>
                <template v-else>
                  <span class="value-text">
                    {{ getCellState(row.id, modelId, 'rd_status').changeType === 'delete'
                       ? (getDeleteOldValue(row.id, modelId, 'rd_status') || '-')
                       : (row.model_values[modelId].rd_status || '-') }}
                  </span>
                  <span v-if="getCellState(row.id, modelId, 'rd_status').draftOldValue != null" class="original-hint">
                    ({{ getCellState(row.id, modelId, 'rd_status').draftOldValue }})
                  </span>
                </template>
              </div>
            </template>
          </el-table-column>
            </el-table-column>
          </el-table-column>
        </template>

        <template #empty>
          <el-empty description="暂无数据，请导入Excel或选择产品系列" />
        </template>
      </el-table>

      <!-- 分页（前端分页） -->
      <div class="pagination-wrapper" v-if="filteredTableData.length > 0">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :page-sizes="[50, 100, 200, 500]"
          :total="filteredTableData.length"
          layout="total, sizes, prev, pager, next, jumper"
        />
      </div>
    </el-card>

    <!-- 导入预览对话框 -->
    <el-dialog v-model="previewDialogVisible" title="导入影响预览" width="85%" top="5vh" :close-on-click-modal="!importing" :close-on-press-escape="!importing" :show-close="!importing">
      <div v-if="previewData" class="preview-content">
        <el-alert
          :title="`共选择 ${previewData.totalFiles} 个文件 - ${previewData.totalModels} 个型号，${previewData.totalItems} 条配置项`"
          type="info"
          show-icon
          :closable="false"
          style="margin-bottom: 16px"
        />

        <el-table :data="previewData.files" border stripe size="small" style="margin-bottom: 16px">
          <el-table-column prop="filename" label="文件名" width="200" show-overflow-tooltip />
          <el-table-column prop="summary.totalModels" label="型号数" width="80" />
          <el-table-column prop="summary.totalItems" label="配置项数" width="100" />
          <el-table-column label="本文件影响（项×机型）" min-width="180"><template #default="{ row }">新增 {{ row.impact?.added || 0 }} / 修改 {{ row.impact?.modified || 0 }} / 删除 {{ row.impact?.deleted || 0 }}</template></el-table-column>
          <el-table-column label="系列" min-width="160" show-overflow-tooltip>
            <template #default="{ row }">
              <el-tag v-for="s in row.series" :key="s.name" size="small" style="margin: 2px">{{ s.name }}</el-tag>
            </template>
          </el-table-column>
        </el-table>

        <div v-if="previewData.impact" class="import-impact">
          <el-alert type="warning" :closable="false" title="以下为相对当前工作配置的实际影响；文件按列表顺序导入，后面的文件可能覆盖前面的值。" />
          <p>配置项 × 机型：新增 <strong>{{ previewData.impact.added }}</strong>，修改 <strong>{{ previewData.impact.modified }}</strong>，删除 <strong>{{ previewData.impact.deleted }}</strong>，未变化 {{ previewData.impact.unchanged }}；共 {{ previewData.impact.changed_cells }} 处配置字段变更。</p>
          <p>共享基础信息：新增 {{ previewData.impact.item_counts?.added || 0 }} 项，修改 {{ previewData.impact.item_counts?.modified || 0 }} 项，删除 {{ previewData.impact.item_counts?.deleted || 0 }} 项；会影响这些配置项的相关机型。</p>
          <p class="scope-note"><strong>涉及 {{ impactModelGroups.length }} 个系列 / {{ previewData.impact.models.length }} 个机型</strong><span v-if="previewData.impact.changed_item_fields > 0">（含共享基础信息关联机型）</span>；涉及字段：{{ previewData.impact.fields.map(field => fieldLabels[field] || field).join('、') || '无' }}</p>
          <el-collapse>
            <el-collapse-item :title="`查看涉及机型（${previewData.impact.models.length} 个）`" name="models">
              <div class="impact-model-list" role="region" aria-label="按系列查看涉及机型">
                <div v-for="group in impactModelGroups" :key="group.seriesName" class="impact-model-group">
                  <strong>{{ group.seriesName }}（{{ group.models.length }} 个）</strong>
                  <div>
                    <el-tag v-for="model in group.models" :key="model.model_id || model.model_name" :title="model.model_name" size="small">{{ model.model_name }}</el-tag>
                  </div>
                </div>
              </div>
            </el-collapse-item>
            <el-collapse-item :title="`查看变更明细（${previewData.impact.total_changes} 条）`" name="impact">
              <el-alert v-if="previewData.impact.truncated" type="info" :closable="false" :title="`明细仅展示前 ${previewData.impact.detail_limit} 条，以上数量包含全部变更。`" />
              <el-table :data="previewData.impact.changes" max-height="300" size="small">
                <el-table-column prop="series_name" label="系列" min-width="110" />
                <el-table-column prop="model_name" label="机型" min-width="120" />
                <el-table-column prop="rd_name" label="研发名称" min-width="150" />
                <el-table-column prop="ipn" label="IPN号" width="100" />
                <el-table-column label="字段" min-width="100"><template #default="{ row }">{{ fieldLabels[row.field_name] || row.field_name }}</template></el-table-column>
                <el-table-column prop="old_value" label="当前工作值" min-width="100" />
                <el-table-column prop="new_value" label="导入值" min-width="100" />
                <el-table-column label="类型" width="75"><template #default="{ row }">{{ { create: '新增', added: '新增', update: '修改', modified: '修改', delete: '删除', deleted: '删除' }[row.change_type] || row.change_type }}</template></el-table-column>
              </el-table>
            </el-collapse-item>
          </el-collapse>
        </div>

        <el-tabs v-if="previewData.files.length === 1">
          <el-tab-pane label="型号列表">
            <el-tag v-for="m in previewData.files[0].series?.flatMap(s => s.models) || []" :key="m" style="margin: 4px">{{ m }}</el-tag>
          </el-tab-pane>
          <el-tab-pane label="分类统计">
            <el-tag v-for="c in previewData.allCategories" :key="c" style="margin: 4px">{{ c }}</el-tag>
          </el-tab-pane>
        </el-tabs>

        <!-- 导入进度 -->
        <div v-if="importing" style="margin-top: 16px">
          <el-progress :percentage="Math.round(importProgress.current / importProgress.total * 100)" />
          <p style="text-align: center; margin-top: 8px">正在导入第 {{ importProgress.current }} / {{ importProgress.total }} 个文件...</p>
        </div>
      </div>
      <template #footer>
        <el-button :disabled="importing" @click="previewDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmImport" :loading="importing">确认导入</el-button>
      </template>
    </el-dialog>

    <!-- 导入变更详情对话框 -->
    <!-- 批量修改对话框 -->
    <el-dialog v-model="batchEditDialogVisible" title="批量修改" width="540px" :close-on-click-modal="!batchEditSubmitting" :close-on-press-escape="!batchEditSubmitting" :show-close="!batchEditSubmitting">
      <el-form :model="batchEditForm" label-width="100px" :disabled="batchEditSubmitting">
        <el-form-item label="修改字段">
          <el-select v-model="batchEditForm.field" placeholder="选择要修改的字段">
            <el-option label="最终配置" value="final_config" />
            <el-option label="当前配置" value="current_config" />
            <el-option label="选型类别" value="selection_config" />
            <el-option label="研发状态" value="rd_status" />
          </el-select>
        </el-form-item>
        <el-form-item label="修改为">
          <el-select v-model="batchEditForm.value" placeholder="选择或输入值" filterable allow-create clearable>
            <el-option v-for="v in getBatchEditOptions()" :key="v" :label="v" :value="v" />
          </el-select>
        </el-form-item>
        <el-form-item label="应用范围">
          <el-radio-group v-model="batchEditForm.scope">
            <el-radio label="selected">仅选中行 ({{ selectedRows.length }}行)</el-radio>
            <el-radio label="filtered">当前筛选结果 ({{ filteredTableData.length }} 行，包含其他页)</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <el-alert :closable="false" type="info" :title="`${batchEditRowCount} 行 × ${selectedModels.length} 个已选机型 × 1 个字段；仅修改这些目标，不包含筛选外行。`" />
      <p v-if="batchEditResult" role="status">保存成功 {{ batchEditResult.success }} 处，失败 {{ batchEditResult.failed }} 处，值未变 {{ batchEditResult.unchanged }} 处，无该机型配置 {{ batchEditResult.missing }} 处。</p>
      <template #footer>
        <el-button :disabled="batchEditSubmitting" @click="batchEditDialogVisible = false">关闭</el-button>
        <el-button type="primary" :loading="batchEditSubmitting" :disabled="!batchEditRowCount || !selectedModels.length" @click="confirmBatchEdit">确认修改</el-button>
      </template>
    </el-dialog>

    <!-- 右键菜单 -->
    <div
      v-if="contextMenu.visible"
      class="context-menu"
      :style="{ left: contextMenu.x + 'px', top: contextMenu.y + 'px' }"
    >
      <div class="menu-item" @click="handleCopyCell">
        <el-icon><DocumentCopy /></el-icon>
        <span>复制 (Ctrl+C)</span>
      </div>
      <div class="menu-item" @click="handlePasteCell" :class="{ 'menu-disabled': !copiedCell }">
        <el-icon><CopyDocument /></el-icon>
        <span>粘贴 (Ctrl+V)</span>
      </div>
      <div class="menu-divider"></div>
      <div class="menu-item" @click="pasteToSelectedCells" :class="{ 'menu-disabled': !copiedCell || selectedCells.length === 0 }">
        <el-icon><CopyDocument /></el-icon>
        <span v-if="false">粘贴到所有选中单元格 ({{ selectedCells.length }}个)</span>
        <span v-else>粘贴到所有选中单元格</span>
      </div>
      <div class="menu-divider"></div>
      <div class="menu-item" @click="handleApplyToAllModels('field')">
        <el-icon><CopyDocument /></el-icon>
        <span>应用到所有机型（仅当前字段）</span>
      </div>
      <div class="menu-item" @click="handleApplyToAllModels('row')">
        <el-icon><CopyDocument /></el-icon>
        <span>应用到所有机型（整行4个字段）</span>
      </div>
      <div class="menu-item" @click="handleApplyValueToAllFields">
        <el-icon><DocumentCopy /></el-icon>
        <span>当前值应用到该行所有字段</span>
      </div>
      <div class="menu-divider"></div>
      <div class="menu-item" @click="handleClearCell">
        <el-icon><Delete /></el-icon>
        <span>清空</span>
      </div>
      <div class="menu-divider"></div>
      <div class="menu-item" @click="handleCopyRowConfig">
        <el-icon><DocumentCopy /></el-icon>
        <span>复制整行配置</span>
      </div>
      <div class="menu-divider"></div>
      <div class="menu-item" @click="handleViewRowDiff">
        <el-icon><View /></el-icon>
        <span>查看该行差异</span>
      </div>
    </div>

    <!-- 应用到所有机型确认对话框 -->
    <el-dialog v-model="applyToAllDialog.visible" title="应用到所有机型" width="450px">
      <div v-if="applyToAllDialog.scope === 'field'">
        <p>将 <strong>{{ applyToAllDialog.fieldName }}</strong> 的值</p>
        <p style="margin: 10px 0; padding: 8px; background: #f5f7fa; border-radius: 4px; font-weight: 500;">
          "{{ applyToAllDialog.value || '-' }}"
        </p>
        <p>应用到该行 <strong>{{ selectedModels.length }}</strong> 个机型的<strong>{{ applyToAllDialog.fieldName }}</strong>字段</p>
      </div>
      <div v-else>
        <p>将当前机型的<strong>全部4个字段</strong>配置</p>
        <p style="margin: 10px 0; color: #606266; font-size: 13px;">
          （最终配置、当前配置、选型类别、研发状态）
        </p>
        <p>复制到该行其他 <strong>{{ selectedModels.length - 1 }}</strong> 个机型</p>
      </div>
      <template #footer>
        <el-button @click="applyToAllDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="confirmApplyToAll">确认</el-button>
      </template>
    </el-dialog>

    <!-- 粘贴整行配置对话框 -->
    <el-dialog v-model="pasteRowDialog.visible" title="粘贴整行配置" width="500px">
      <p>选择要粘贴配置的目标行：</p>
      <el-select v-model="pasteRowDialog.targetRowId" placeholder="选择目标行" style="width: 100%; margin-top: 10px;">
        <el-option
          v-for="row in tableData"
          :key="row.id"
          :label="row.rd_name || row.ipn || 'ID:' + row.id"
          :value="row.id"
        />
      </el-select>
      <p style="color: #909399; font-size: 12px; margin-top: 10px;">
        来源行: {{ pasteRowDialog.sourceRow?.rd_name || pasteRowDialog.sourceRow?.ipn }}
      </p>
      <template #footer>
        <el-button @click="pasteRowDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="confirmPasteRowConfig">确认粘贴</el-button>
      </template>
    </el-dialog>

    <!-- 行差异查看对话框 -->
    <el-dialog v-model="rowDiffDialog.visible" title="该行配置差异对比" width="90%" top="5vh">
      <div v-if="rowDiffDialog.row" class="row-diff-content">
        <el-descriptions :column="1" border size="small" style="margin-bottom: 20px;">
          <el-descriptions-item label="研发名称">{{ rowDiffDialog.row.rd_name }}</el-descriptions-item>
          <el-descriptions-item label="中文名称">{{ rowDiffDialog.row.zh_desc || '-' }}</el-descriptions-item>
          <el-descriptions-item label="英文名称">{{ rowDiffDialog.row.en_desc || '-' }}</el-descriptions-item>
          <el-descriptions-item label="IPN号">{{ rowDiffDialog.row.ipn }}</el-descriptions-item>
          <el-descriptions-item label="V代码">{{ rowDiffDialog.row.v_code }}</el-descriptions-item>
          <el-descriptions-item label="分类">{{ rowDiffDialog.row.category }}</el-descriptions-item>
        </el-descriptions>

        <el-table :data="getRowDiffData(rowDiffDialog.row)" border stripe size="small">
          <el-table-column prop="modelName" label="机型" width="200" fixed />
          <el-table-column prop="final_config" label="最终配置">
            <template #default="{ row }">
              <span :class="{ 'diff-highlight': row.isDiffFinal }">{{ row.final_config || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="current_config" label="当前配置">
            <template #default="{ row }">
              <span :class="{ 'diff-highlight': row.isDiffCurrent }">{{ row.current_config || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="selection_config" label="选型类别">
            <template #default="{ row }">
              <span :class="{ 'diff-highlight': row.isDiffSelection }">{{ row.selection_config || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="rd_status" label="研发状态">
            <template #default="{ row }">
              <span :class="{ 'diff-highlight': row.isDiffRd }">{{ row.rd_status || '-' }}</span>
            </template>
          </el-table-column>
        </el-table>

        <div class="diff-legend" style="margin-top: 16px;">
          <el-tag type="danger" effect="plain">红色文字 = 存在差异的值</el-tag>
        </div>
      </div>
      <template #footer>
        <el-button @click="rowDiffDialog.visible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 创建版本对话框 -->
    <el-dialog v-model="versionDialogVisible" title="创建版本" width="500px">
      <el-form :model="versionForm" label-width="100px">
        <el-form-item label="版本号">
          <el-input v-model="versionForm.version_number" placeholder="留空则自动生成" />
        </el-form-item>
        <el-form-item label="版本名称">
          <el-input v-model="versionForm.version_name" placeholder="可选" />
        </el-form-item>
        <el-form-item label="版本说明">
          <el-input v-model="versionForm.description" type="textarea" :rows="3" placeholder="可选" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="versionDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmCreateVersion">确定</el-button>
      </template>
    </el-dialog>

    <!-- 提交草稿对话框 -->
    <el-dialog v-model="submitDialogVisible" title="确认发布范围" width="760px" :close-on-click-modal="!submitSubmitting" :close-on-press-escape="!submitSubmitting" :show-close="!submitSubmitting">
      <div v-loading="submitPreviewLoading" class="submit-info">
        <p>{{ submitForm.model_ids ? `仅提交选中机型：${getModelNames(submitForm.model_ids)}` : submitForm.item_ids ? `仅提交选中的 ${submitForm.item_ids.size} 个配置项（所有有变更机型）` : '提交所选系列的全部草稿，包含当前筛选外的变更。' }}</p>
        <el-alert v-if="submitPreviewError" :title="submitPreviewError" type="error" :closable="false" />
        <el-table :data="submitPreviews" size="small" max-height="240">
          <el-table-column prop="series_name" label="系列" min-width="140" />
          <el-table-column prop="total_items" label="配置项数" width="85" />
          <el-table-column prop="total_changes" label="变更记录" width="85" />
          <el-table-column prop="total_models" label="机型数" width="75" />
          <el-table-column prop="hidden_changes" label="当前页不可见" width="110" />
          <el-table-column prop="remaining_changes" label="保留草稿" width="90" />
        </el-table>
        <p class="scope-note">“不可见”包含筛选外行、其他页、未选机型和隐藏字段。配置项数按行去重；变更记录数包含不同机型和字段。</p>
        <p v-for="review in submitPreviews" :key="review.batch_id" class="scope-note">{{ review.series_name }}：{{ review.models.map(model => model.name).join('、') || '无机型变更' }}；字段：{{ review.fields.map(field => fieldLabels[field] || field).join('、') || '无' }}</p>
        <el-collapse v-if="submitPreviews.some(review => review.total_changes)">
          <el-collapse-item title="查看将发布的变更明细" name="changes">
            <el-table :data="submitPreviews.flatMap(review => review.drafts.map(draft => ({ ...draft, series_name: review.series_name })))" max-height="240">
              <el-table-column prop="series_name" label="系列" min-width="110" />
              <el-table-column prop="rd_name" label="配置项" min-width="130" />
              <el-table-column prop="model_name" label="机型" min-width="110" />
              <el-table-column label="字段" width="90"><template #default="{ row }">{{ fieldLabels[row.field_name] || '整项配置' }}</template></el-table-column>
              <el-table-column label="原值" min-width="170"><template #default="{ row }">{{ formatSubmissionValue(row, 'old') }}</template></el-table-column>
              <el-table-column label="草稿值" min-width="170"><template #default="{ row }">{{ formatSubmissionValue(row, 'new') }}</template></el-table-column>
            </el-table>
          </el-collapse-item>
        </el-collapse>
      </div>
      <el-form :model="submitForm" label-width="100px" :disabled="submitSubmitting || submitPreviewLoading">
        <el-form-item label="版本号"><el-input v-model="submitForm.version_number" placeholder="留空则自动生成" /></el-form-item>
        <el-form-item label="版本说明"><el-input v-model="submitForm.description" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <el-table v-if="submitResults.length" :data="submitResults" max-height="180">
        <el-table-column prop="seriesName" label="系列" /><el-table-column prop="message" label="提交结果" />
      </el-table>
      <template #footer>
        <el-button :disabled="submitSubmitting" @click="submitDialogVisible = false">取消</el-button>
        <el-button :disabled="submitSubmitting || submitPreviewLoading" @click="refreshSubmitPreview">刷新范围</el-button>
        <el-button type="primary" :loading="submitSubmitting" :disabled="submitPreviewLoading || !!submitPreviewError || !submitPreviews.some(review => review.total_changes)" @click="confirmSubmitDraft">确认发布</el-button>
      </template>
    </el-dialog>

    <!-- 批量操作对话框 -->
    <el-dialog v-model="batchSubmitDialog.visible" title="确认批量发布范围" width="760px" :close-on-click-modal="!batchSubmitSubmitting" :close-on-press-escape="!batchSubmitSubmitting" :show-close="!batchSubmitSubmitting">
      <el-alert type="warning" :closable="false" title="提交下列系列的全部草稿，包含当前筛选外和未显示的变更。" />
      <el-alert v-if="batchSubmitDialog.error" type="error" :closable="false" :title="batchSubmitDialog.error" />
      <el-form label-width="80px" :disabled="batchSubmitSubmitting || batchSubmitDialog.loading">
        <el-form-item label="提交系列">
          <div v-loading="batchSubmitDialog.loading" style="max-height: 240px; overflow-y: auto; width: 100%;">
            <el-checkbox :indeterminate="batchSubmitDialog.selectedBatchIds.length > 0 && batchSubmitDialog.selectedBatchIds.length < batchSubmitDialog.availableBatches.length" :checked="batchSubmitDialog.availableBatches.length > 0 && batchSubmitDialog.selectedBatchIds.length === batchSubmitDialog.availableBatches.length" @change="toggleSubmitAllBatches">全选</el-checkbox>
            <div v-for="review in batchSubmitDialog.availableBatches" :key="review.batch_id" style="margin: 8px 0;">
              <el-checkbox :checked="batchSubmitDialog.selectedBatchIds.includes(review.batch_id)" @change="checked => toggleSubmitBatch(review.batch_id, checked)">{{ review.series_name }}：{{ review.total_items }} 个配置项 · {{ review.total_changes }} 条变更 · {{ review.total_models }} 个机型</el-checkbox>
              <div class="scope-note">当前页不可见 {{ review.hidden_changes }} 条；{{ review.models.map(model => model.name).join('、') }}；字段 {{ review.fields.map(field => fieldLabels[field] || field).join('、') }}</div>
            </div>
          </div>
        </el-form-item>
        <el-form-item label="版本号"><el-input v-model="batchSubmitDialog.versionNumber" placeholder="留空则各系列自动生成" /></el-form-item>
        <el-form-item label="版本说明"><el-input v-model="batchSubmitDialog.description" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <p class="scope-note">指定版本号会用于全部选中系列；已有同名版本的系列会提交失败。每个系列的结果将单独显示。</p>
      <template #footer>
        <el-button :disabled="batchSubmitSubmitting" @click="batchSubmitDialog.visible = false">取消</el-button>
        <el-button :disabled="batchSubmitSubmitting || batchSubmitDialog.loading" @click="refreshBatchSubmitPreview">刷新范围</el-button>
        <el-button type="primary" :loading="batchSubmitSubmitting" :disabled="batchSubmitDialog.loading || !!batchSubmitDialog.error || !batchSubmitDialog.selectedBatchIds.length" @click="confirmBatchSubmit">确认发布 ({{ batchSubmitDialog.selectedBatchIds.length }})</el-button>
      </template>
    </el-dialog>

    <!-- 批量提交结果 -->
    <el-dialog v-model="batchSubmitResultDialog.visible" title="批量提交结果" width="550px">
      <el-table :data="batchSubmitResultDialog.results" max-height="400">
        <el-table-column prop="seriesName" label="系列" width="150" />
        <el-table-column prop="versionNumber" label="版本号" width="120" />
        <el-table-column prop="changes" label="变更数" width="80" />
        <el-table-column prop="success" label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.success ? 'success' : 'danger'" size="small">
              {{ row.success ? '成功' : '失败' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="message" label="说明" />
      </el-table>
      <template #footer>
        <el-button type="primary" @click="batchSubmitResultDialog.visible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
  </el-config-provider>
</template>

<script setup>
import { draftBaseline, draftWorkingValue, updateDraftStats } from '../utils/configDraftHelpers'
import { ref, reactive, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Upload, Download, DocumentChecked, EditPen, Setting, CopyDocument, Delete, DocumentCopy, InfoFilled, View, ArrowDown, Filter } from '@element-plus/icons-vue'
import { getModelShortName as _getModelShortName, groupModelsBySeries, findSeriesIdByModelId as _findSeriesIdByModelId, isValueChanged as _isValueChanged, isEmptyValue as _isEmptyValue, normalizeValue } from '../utils/modelHelpers'
import { useDraftFilter } from '../utils/useDraftFilter'
import { buildModelSelectionGroup, resolveGroupSeries, resolveGroupModels, loadModelSelectionGroups, saveModelSelectionGroups } from '../utils/modelSelectionGroups'
import {
  getSeriesList, getModels, getConfigRows,
  getCurrentDraftBatch, createDraftBatch, createDraft,
  submitDraftBatch, discardDraftBatch, deleteDraftByKey,
  importExcel, exportExcel, createVersion,
  getEnumValues, previewImportBatch, previewDraftSubmission,
  batchDiscardDrafts, batchSubmitDrafts
} from '../api/data'

const tableRef = ref(null)
const configPageRef = ref(null)
let configResizeObserver

// 数据
const seriesList = ref([])
const allModelsMap = ref(new Map())  // modelId -> { id, name, seriesId, seriesName }
const tableData = ref([])
const originalData = ref([])  // 存储原始数据，用于比较变化
const loading = ref(false)
const configReady = ref(false)
const selectedRows = ref([])

// 按系列分组的型号列表（用于 optgroup 下拉）
const modelGroups = computed(() => {
  const seriesMap = new Map()
  for (const [id, m] of allModelsMap.value) {
    const key = m.seriesId
    if (!seriesMap.has(key)) {
      seriesMap.set(key, { seriesId: key, seriesName: m.seriesName, models: [] })
    }
    seriesMap.get(key).models.push(m)
  }
  return Array.from(seriesMap.values())
})

// 机型搜索文本（下拉内搜索框）
const modelFilterText = ref('')

// 根据搜索文本过滤后的型号分组
const filteredModelGroups = computed(() => {
  const q = modelFilterText.value.trim().toLowerCase()
  if (!q) return modelGroups.value
  return modelGroups.value
    .map(g => ({
      ...g,
      models: g.models.filter(m => m.name.toLowerCase().includes(q))
    }))
    .filter(g => g.models.length > 0)
})

// 根据 modelId 查找对应的 seriesId（使用共享方法）
const findSeriesIdByModelId = (modelId) => _findSeriesIdByModelId(allModelsMap.value, modelId)

// 草稿变更记录（用于UI高亮和撤销）
// key: `${rowId}_${modelId}_${field}`
// value: { oldValue, newValue, draftId }
const draftChanges = ref(new Map())
const { draftFilterMode, draftFilters, getDraftTagType, toggleDraftFilter: _toggleDraftFilter, clearDraftFilter: _clearDraftFilter, filterByDraftMode } = useDraftFilter()
const showDiffOnly = ref(false)  // 是否只显示有差异的配置
const referenceModel = ref(null)  // 参考机型 ID
const showRdIncomplete = ref(false)  // 是否高亮并筛选未完成的研发状态

// 机型列拖拽排序
const MODEL_ORDER_KEY = 'config_model_order'
const modelDragSource = ref(null)  // { modelId, sourceIndex }
const isModelDragging = ref(false)
const modelDragOverIndex = ref(-1)
const modelDragPosition = ref('')  // 'before' | 'after'

// 同类型字段列宽联动 + localStorage 持久化
const FW_KEY = "config_field_widths"
const fieldColWidths = reactive(
  (() => { try { const s = localStorage.getItem(FW_KEY); return s ? JSON.parse(s) : { final_config: 100, current_config: 100, selection_config: 100, rd_status: 100 } } catch { return { final_config: 100, current_config: 100, selection_config: 100, rd_status: 100 } } })()
)
const onConfigDragEnd = (newWidth, oldWidth, column) => {
  const m = { "最终配置": "final_config", "当前配置": "current_config", "选型类别": "selection_config", "研发状态": "rd_status" }
  const k = m[column?.label] || column?.columnKey || ""
  if (k in fieldColWidths && newWidth > 0) { fieldColWidths[k] = newWidth; localStorage.setItem(FW_KEY, JSON.stringify(fieldColWidths)) }
}

// 机型列拖拽事件处理器
const onModelDragStart = (e, modelId, sourceIndex) => {
  e.stopPropagation()
  modelDragSource.value = { modelId, sourceIndex }
  isModelDragging.value = true
  const th = e.target.closest('th')
  if (th) {
    th.classList.add('is-dragging-source')
    // 给所有其他机型 th 添加半透明效果
    const headerWrapper = th.closest('.el-table__header-wrapper')
    if (headerWrapper) {
      headerWrapper.querySelectorAll('th[data-model-id]').forEach(other => {
        if (other !== th) other.classList.add('is-drag-dimmed')
      })
    }
  }
}

const onModelDragOver = (e) => {
  e.preventDefault()
  e.stopPropagation()
  const th = e.target.closest('th[data-model-id]')
  if (!th || !modelDragSource.value) return
  const targetIndex = parseInt(th.dataset.modelIndex)
  // 清除所有 th 上的指示线
  th.closest('.el-table__header-wrapper')?.querySelectorAll('th[data-model-id]').forEach(other => {
    other.classList.remove('is-drag-over-before', 'is-drag-over-after')
  })
  if (targetIndex === modelDragSource.value.sourceIndex) {
    modelDragOverIndex.value = -1
    return
  }
  // 根据鼠标在 cell 水平方向的位置判定 before / after
  const rect = th.getBoundingClientRect()
  const midX = rect.left + rect.width / 2
  const pos = e.clientX < midX ? 'before' : 'after'
  modelDragOverIndex.value = targetIndex
  modelDragPosition.value = pos
  th.classList.remove('is-drag-over-before', 'is-drag-over-after')
  th.classList.add(pos === 'before' ? 'is-drag-over-before' : 'is-drag-over-after')
}

const onModelDrop = (e) => {
  e.preventDefault()
  e.stopPropagation()
  if (!modelDragSource.value) return
  const sourceIdx = modelDragSource.value.sourceIndex
  let targetIdx = modelDragOverIndex.value
  if (targetIdx < 0) { cleanupModelDrag(); return }
  if (sourceIdx === targetIdx) { cleanupModelDrag(); return }
  // 如果拖到目标之后且 source 在 target 之前，实际插入位置要减1（因为源元素移除后索引前移）
  const models = [...selectedModels.value]
  const [removed] = models.splice(sourceIdx, 1)
  const adjustedTarget = modelDragPosition.value === 'after'
    ? (sourceIdx < targetIdx ? targetIdx : targetIdx + 1)
    : (sourceIdx < targetIdx ? targetIdx - 1 : targetIdx)
  models.splice(adjustedTarget, 0, removed)
  selectedModels.value = models
  saveModelOrder()
  cleanupModelDrag()
}

const onModelDragEnd = () => {
  cleanupModelDrag()
}

const cleanupModelDrag = () => {
  modelDragSource.value = null
  isModelDragging.value = false
  modelDragOverIndex.value = -1
  modelDragPosition.value = ''
  document.querySelectorAll('.is-dragging-source, .is-drag-dimmed, .is-drag-over-before, .is-drag-over-after').forEach(el => {
    el.classList.remove('is-dragging-source', 'is-drag-dimmed', 'is-drag-over-before', 'is-drag-over-after')
  })
}
let _configMouseUpTs = 0
const onConfigMouseUp = () => {
  const now = Date.now()
  if (now - _configMouseUpTs < 500) return  // 500ms 节流
  _configMouseUpTs = now
  nextTick(() => {
    const el = tableRef.value?.$el
    const row = el?.querySelector(".el-table__header-wrapper tr:last-child")
    if (!row) return
    const m = { "最终配置": "final_config", "当前配置": "current_config", "选型类别": "selection_config", "研发状态": "rd_status" }
    const max = {}
    row.querySelectorAll("th").forEach(th => {
      const k = m[th.querySelector(".cell")?.textContent?.trim() || ""]
      if (k && th.offsetWidth > 0) max[k] = Math.max(max[k] || 0, th.offsetWidth)
    })
    let ch = false
    for (const [k, w] of Object.entries(max)) { if (fieldColWidths[k] !== w && w > 0) { fieldColWidths[k] = w; ch = true } }
    if (ch) localStorage.setItem(FW_KEY, JSON.stringify(fieldColWidths))
    syncHeaderTitles()
  })
}

// 同步表头和数据单元格的 title 属性
const syncHeaderTitles = () => {
  const el = tableRef.value?.$el
  if (!el) return
  // header cells
  el.querySelectorAll('.el-table__header-wrapper .cell').forEach(cell => {
    const text = cell.textContent?.trim() || ''
    cell.setAttribute('title', text)
  })
  // data cells（固定行高后内容溢出）
  el.querySelectorAll('.el-table__body-wrapper .cell .cell-value').forEach(cell => {
    const text = cell.textContent?.trim() || ''
    cell.setAttribute('title', text)
  })
}

// 同步表头机型列的 data-model-id 并注入拖拽手柄
const syncModelColumnHeaders = () => {
  const el = tableRef.value?.$el
  if (!el || selectedModels.value.length < 2) return
  // 重置重试计数（每次显式调用都重试）
  _modelSyncRetries = 0
  if (_modelSyncTimer) { clearTimeout(_modelSyncTimer); _modelSyncTimer = null }
  // Element Plus 的 fixed 列表头在 .el-table__fixed-header-wrapper 中
  // 但机型列不在 fixed 中，所以主区 .el-table__header-wrapper 就够了
  // 用 setTimeout 0 确保 Vue DOM 已更新完毕
  requestAnimationFrame(() => _doSyncModelColumnHeaders(el))
}

let _modelSyncRetries = 0
const _modelSyncMaxRetries = 5
let _modelSyncTimer = null
const _doSyncModelColumnHeaders = (el) => {
  if (_modelSyncRetries >= _modelSyncMaxRetries) { _modelSyncRetries = 0; return }
  _modelSyncRetries++
  // 收集所有 header-wrapper 中所有行所有 th 的 label → th 映射
  const headersWrappers = el.querySelectorAll('.el-table__header-wrapper, .el-table__fixed-header-wrapper, .el-table__fixed-right-header-wrapper')
  if (!headersWrappers.length) { _scheduleRetry(el); return }
  // 收集所有候选 th（在第二个 tr 中，label 匹配任一机型短名）
  const shortNameMap = {}
  selectedModels.value.forEach((mid, idx) => {
    shortNameMap[getModelShortName(mid)] = { modelId: mid, index: idx }
  })
  if (Object.keys(shortNameMap).length < 2) { _scheduleRetry(el); return }

  // 逐个 wrapper 查找匹配的 th
  let injectedCount = 0
  headersWrappers.forEach(wrapper => {
    const tables = wrapper.querySelectorAll('table')
    if (!tables.length) return
    // 多级表头：row[0]=系列组，row[1]=机型名，row[2]=配置字段
    tables.forEach(table => {
      const rows = table.querySelectorAll('thead tr, tr')
      if (rows.length < 2) return
      // 尝试 rows[1] 作为机型行
      const modelRow = rows[1]
      const ths = modelRow.querySelectorAll('th')
      ths.forEach(th => {
        const label = th.querySelector('.cell')?.textContent?.trim() || th.textContent?.trim() || ''
        const match = shortNameMap[label]
        if (!match) return
        _injectDragHandle(th, match.modelId, match.index, label)
        injectedCount++
      })
    })
  })

  if (injectedCount >= selectedModels.value.length) {
    // 成功
    _modelSyncRetries = 0
    if (_modelSyncTimer) { clearTimeout(_modelSyncTimer); _modelSyncTimer = null }
  } else if (injectedCount === 0) {
    // 完全没有匹配到，需要重试
    _scheduleRetry(el)
  }
}

const _injectDragHandle = (th, modelId, index, label) => {
  th.setAttribute('data-model-id', modelId)
  th.setAttribute('data-model-index', index)
  const cell = th.querySelector('.cell')
  if (!cell) return
  if (cell.querySelector('.model-drag-handle')) return  // 已注入
  const handle = document.createElement('span')
  handle.className = 'model-drag-handle'
  handle.textContent = '⠿'
  handle.draggable = true
  handle.setAttribute('aria-label', `拖拽调整 ${label} 顺序`)
  cell.insertBefore(handle, cell.firstChild)
}

const _scheduleRetry = (el) => {
  if (_modelSyncTimer) return
  _modelSyncTimer = setTimeout(() => {
    _modelSyncTimer = null
    _doSyncModelColumnHeaders(el)
  }, 300)
}

// 绑定机型列拖拽事件（事件委托）
const attachModelDragEvents = () => {
  const el = tableRef.value?.$el
  if (!el) return
  const headerWrapper = el.querySelector('.el-table__header-wrapper')
  if (!headerWrapper) return
  // 移除旧监听避免重复绑定（用标记避免多次绑定）
  if (headerWrapper._modelDragAttached) return
  headerWrapper._modelDragAttached = true

  headerWrapper.addEventListener('dragstart', (e) => {
    const handle = e.target.closest('.model-drag-handle')
    if (!handle) return  // 非拖拽手柄触发则忽略
    const th = handle.closest('th[data-model-id]')
    if (!th) return
    const modelId = parseInt(th.dataset.modelId)
    const sourceIndex = parseInt(th.dataset.modelIndex)
    onModelDragStart(e, modelId, sourceIndex)
  })

  headerWrapper.addEventListener('dragover', onModelDragOver)
  headerWrapper.addEventListener('drop', onModelDrop)
  headerWrapper.addEventListener('dragend', onModelDragEnd)
}

// localStorage 持久化机型列顺序
const saveModelOrder = () => {
  try {
    localStorage.setItem(MODEL_ORDER_KEY, JSON.stringify(selectedModels.value))
  } catch (e) {
    console.error('保存机型列顺序失败:', e)
  }
}

// 应用保存的机型列顺序
const applySavedOrder = (models) => {
  try {
    const saved = localStorage.getItem(MODEL_ORDER_KEY)
    if (!saved) return
    const savedOrder = JSON.parse(saved)
    if (!Array.isArray(savedOrder) || savedOrder.length === 0) return
    // 按保存顺序重排，仅保留当前仍选中的，新追加的放在末尾
    const savedSet = new Set(savedOrder)
    const ordered = savedOrder.filter(id => savedSet.has(id) && models.includes(id))
    const remaining = models.filter(id => !savedSet.has(id) || !ordered.includes(id))
    // 用 set 去重但保持顺序
    const result = []
    const seen = new Set()
    for (const id of [...ordered, ...remaining]) {
      if (!seen.has(id) && models.includes(id)) {
        seen.add(id)
        result.push(id)
      }
    }
    // 只有当顺序实际改变且长度一致时才应用
    if (result.length === models.length) {
      selectedModels.value = result
    }
  } catch (e) {
    console.error('恢复机型列顺序失败:', e)
  }
}


// 枚举值
const enumValues = reactive({
  selectionTypes: [],
  rdStatuses: [],
  configValues: []
})

// 筛选条件
const selectedSeries = ref([])
const selectedModels = ref([])

// 配置字段列值筛选（按 `field|modelId` 键控，空数组 = 不过滤当前列的该字段）
const fieldFilters = reactive({})
const getFilterKey = (field, modelId) => `${field}|${modelId}`

// 选中机型变化时初始化/清理列筛选状态
watch(selectedModels, () => {
  const fields = ['final_config', 'current_config', 'selection_config', 'rd_status']
  const validKeys = new Set()
  for (const modelId of selectedModels.value) {
    for (const field of fields) {
      const key = getFilterKey(field, modelId)
      validKeys.add(key)
      if (!(key in fieldFilters)) fieldFilters[key] = []
    }
  }
  for (const key of Object.keys(fieldFilters)) {
    if (!validKeys.has(key)) delete fieldFilters[key]
  }
}, { immediate: true })

// 列筛选暂存状态（弹窗关闭时统一应用到 fieldFilters，避免每次勾选立即刷新）
const pendingFieldFilters = reactive({})
const openFieldFilterPopover = (field, modelId) => {
  const key = getFilterKey(field, modelId)
  pendingFieldFilters[key] = [...(fieldFilters[key] || [])]
}
const applyFieldFilterPopover = (field, modelId) => {
  const key = getFilterKey(field, modelId)
  if (key in pendingFieldFilters) {
    fieldFilters[key] = pendingFieldFilters[key]
    delete pendingFieldFilters[key]
  }
}

const tempSelectedModels = ref([])  // 机型下拉临时选择，收起时才同步到 selectedModels
const savedModelGroups = ref([])
const modelGroupsPopover = ref(null)
const applyingModelGroup = ref(false)
const configLoading = computed(() => (
  loading.value ||
  applyingModelGroup.value ||
  (selectedSeries.value.length > 0 && !configReady.value)
))
try { savedModelGroups.value = loadModelSelectionGroups() } catch (error) { console.error('读取机型分组失败', error); ElMessage.warning('无法读取已保存的机型分组，请检查浏览器存储设置') }

const persistModelGroups = (groups) => {
  try {
    saveModelSelectionGroups(groups)
    savedModelGroups.value = groups
    return true
  } catch (error) {
    console.error('保存机型分组失败', error)
    ElMessage.error('分组未保存，请检查浏览器存储空间和权限')
    return false
  }
}
const askModelGroupName = (group) => ElMessageBox.prompt('请输入分组名称', group ? '重命名机型分组' : '保存机型分组', {
  inputValue: group?.name || '',
  inputPlaceholder: '例如：9E 科研版、常用对比机型',
  confirmButtonText: '保存', cancelButtonText: '取消',
  inputValidator: value => {
    const name = (value || '').trim()
    if (!name || name.length > 60) return '请输入 1–60 个字符的名称'
    if (savedModelGroups.value.some(item => item.id !== group?.id && item.name === name)) return '该名称已存在，请换一个名称'
    return true
  }
})
const saveCurrentModelGroup = async () => {
  modelGroupsPopover.value?.hide()
  const ids = [...selectedModels.value]
  const models = new Map(allModelsMap.value)
  try {
    const { value } = await askModelGroupName()
    const group = buildModelSelectionGroup(value, ids, models)
    if (persistModelGroups([...savedModelGroups.value, group])) ElMessage.success('机型分组已保存')
  } catch (error) { if (error !== 'cancel' && error !== 'close') ElMessage.error(error.message || '保存机型分组失败') }
}
const renameModelGroup = async (group) => {
  modelGroupsPopover.value?.hide()
  try {
    const { value } = await askModelGroupName(group)
    if (persistModelGroups(savedModelGroups.value.map(item => item.id === group.id ? { ...item, name: value.trim() } : item))) ElMessage.success('分组已重命名')
  } catch (error) { if (error !== 'cancel' && error !== 'close') ElMessage.error(error.message || '重命名失败') }
}
const updateModelGroup = (group) => {
  try {
    const updated = buildModelSelectionGroup(group.name, selectedModels.value, allModelsMap.value, group.id)
    if (persistModelGroups(savedModelGroups.value.map(item => item.id === group.id ? updated : item))) ElMessage.success('已用当前选中机型更新分组')
  } catch (error) { ElMessage.error(error.message) }
}
const deleteModelGroup = async (group) => {
  modelGroupsPopover.value?.hide()
  try {
    await ElMessageBox.confirm(`删除分组“${group.name}”？`, '删除机型分组', { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' })
    if (persistModelGroups(savedModelGroups.value.filter(item => item.id !== group.id))) ElMessage.success('分组已删除')
  } catch (error) { if (error !== 'cancel' && error !== 'close') ElMessage.error('删除分组失败') }
}
const applyModelGroup = async (group) => {
  if (applyingModelGroup.value) return
  const { ids } = resolveGroupSeries(group, seriesList.value)
  if (!ids.length) { ElMessage.warning('该分组的产品系列已不存在'); return }
  const previousSeries = [...selectedSeries.value]
  const previousModels = allModelsMap.value
  const previousReady = configReady.value
  applyingModelGroup.value = true
  modelGroupsPopover.value?.hide()
  selectedSeries.value = ids
  currentPage.value = 1
  modelFilterText.value = ''
  try {
    const success = await loadModels({ modelGroup: group })
    if (success) { saveSeriesSelection(); saveModelOrder() }
    else if (allModelsMap.value === previousModels && ids.length === selectedSeries.value.length && ids.every((id, i) => id === selectedSeries.value[i])) {
      selectedSeries.value = previousSeries
      configReady.value = previousReady
    }
  } finally { applyingModelGroup.value = false }
}

const categoryOptions = ['Optional Features', 'Optional peripherals', '*Optional peripherals(Preassemble in Factory)', 'Probes', 'Biopsy guide']
const selectedCategories = ref([...categoryOptions])
const searchText = ref('')

// 临时筛选条件（用于编辑，点击应用后才生效）
const tempCategories = ref([])
const tempSearchText = ref('')

// 分页
const currentPage = ref(1)
const pageSize = ref(100)

// 列筛选
const VISIBLE_COLUMNS_KEY = 'config_visible_columns'
const FIXED_COLUMNS_KEY = 'config_fixed_columns'
const SERIES_SELECTION_KEY = 'config_series_selection'

const defaultVisibleColumns = {
  rd_name: true,
  v_code: false,
  ipn: true,
  zh_desc: true,
  en_desc: false,
  final_config: true,
  current_config: false,
  selection_config: false,
  rd_status: false
}

const defaultFixedColumns = {
  rd_name: true,
  v_code: false,
  ipn: false,
  zh_desc: false,
  en_desc: false
}

// 从 localStorage 加载设置
const loadColumnSettings = () => {
  try {
    const savedVisible = localStorage.getItem(VISIBLE_COLUMNS_KEY)
    const savedFixed = localStorage.getItem(FIXED_COLUMNS_KEY)

    if (savedVisible) {
      const parsed = JSON.parse(savedVisible)
      Object.assign(visibleColumns, { ...defaultVisibleColumns, ...parsed })
    } else {
      Object.assign(visibleColumns, defaultVisibleColumns)
    }

    if (savedFixed) {
      const parsed = JSON.parse(savedFixed)
      Object.assign(fixedColumns, { ...defaultFixedColumns, ...parsed })
    } else {
      Object.assign(fixedColumns, defaultFixedColumns)
    }
  } catch (e) {
    console.error('加载列设置失败:', e)
    Object.assign(visibleColumns, defaultVisibleColumns)
    Object.assign(fixedColumns, defaultFixedColumns)
  }
}

// 保存系列选择到 localStorage
const saveSeriesSelection = () => {
  try {
    localStorage.setItem(SERIES_SELECTION_KEY, JSON.stringify({
      selected_ids: selectedSeries.value
    }))
  } catch (e) {
    console.error('保存系列选择失败:', e)
  }
}

// 保存设置到 localStorage
const saveColumnSettings = () => {
  try {
    localStorage.setItem(VISIBLE_COLUMNS_KEY, JSON.stringify(visibleColumns))
    localStorage.setItem(FIXED_COLUMNS_KEY, JSON.stringify(fixedColumns))
  } catch (e) {
    console.error('保存列设置失败:', e)
  }
}

const visibleColumns = reactive({ ...defaultVisibleColumns })

// 固定列设置（哪些列固定在左侧）
const fixedColumns = reactive({ ...defaultFixedColumns })

// 临时列筛选（用于弹窗编辑，避免频繁更新表格）
const tempVisibleColumns = reactive({})
const tempFixedColumns = reactive({})
const popoverRef = ref(null)

// 表格高度
const tableMaxHeight = ref(600)

// 单元格编辑状态（点击时才显示下拉框）
const editingCell = ref(null)
const editSelectRef = ref(null)  // 编辑时的select组件引用

// 草稿
const draftBatchMap = ref(new Map())  // seriesId -> batchId
const draftStats = reactive({
  total: 0,
  create: 0,
  update: 0,
  delete: 0
})
const newItemModelMap = ref(new Map())  // 新增: item_id → Set<model_id>
const deletedItemModelMap = ref(new Map())  // 删除: item_id → Set<model_id>
const newItemIds = ref(new Set())  // 由 newItemModelMap 的 keys 推导
const deletedItemIds = ref(new Set())  // 由 deletedItemModelMap 的 keys 推导
const draftItemInfo = ref(new Map())  // item_id -> { rdName, ipn } 草稿项名称信息
const draftDeleteValues = ref(new Map())  // 'itemId_modelId' -> { final_config, current_config, selection_config, rd_status } 删除项的旧值
const selectedDraftItemIds = ref(new Set())  // 选中的草稿项ID
const selectedDraftModelIds = ref(new Set())  // 选中的机型ID（按机型过滤提交）
const draftModelIdSet = ref(new Set())  // 后端返回的实际有变更的机型ID，用于避免从key解析
const draftExpanded = ref(false)  // 草稿项列表是否展开
const showModelBar = ref(false)  // 按机型提��栏是否展开
const draftItemSummary = computed(() => {
  const selectedSet = new Set(selectedModels.value)
  // 没选机型时统计均为0
  if (selectedSet.size === 0) {
    return { total: 0, create: 0, update: 0, delete: 0 }
  }
  const createItems = new Set()
  const updateItems = new Set()
  const deleteItems = new Set()

  // 基于 baseFilteredData 统计可见项（排除草稿筛选，统计数字不随草稿标签变化）
  let visibleItemIds = new Set(baseFilteredData.value.map(r => r.id))

  // 新增项：仅当至少有一个变更机型在选中列表中，且在可见范围内
  for (const [itemId, modelSet] of newItemModelMap.value.entries()) {
    if (!visibleItemIds.has(itemId)) continue
    for (const mid of modelSet) {
      if (selectedSet.has(mid)) {
        createItems.add(itemId)
        break
      }
    }
  }

  // 单元格级新增（从未定义/空改为有值）：draftChanges 中 changeType 为 create
  for (const [key, change] of draftChanges.value.entries()) {
    if (change.changeType === 'create') {
      const parts = key.split('_')
      const rowId = parseInt(parts[0])
      if (!visibleItemIds.has(rowId)) continue
      const modelId = parseInt(parts[1])
      const field = parts.slice(2).join('_')
      if (selectedSet.has(modelId) && visibleConfigFields.value.includes(field)) {
        createItems.add(rowId)
      }
    }
  }

  // 修改项：仅当变更所在的机型在选中列表中，且在可见范围内，且匹配列筛选
  for (const [key, change] of draftChanges.value.entries()) {
    if (change.changeType === 'update') {
      const parts = key.split('_')
      const rowId = parseInt(parts[0])
      if (!visibleItemIds.has(rowId)) continue
      const modelId = parseInt(parts[1])
      const field = parts.slice(2).join('_')
      if (selectedSet.has(modelId)) {
        // 仅统计当前列筛选可见的字段变更
        if (!visibleConfigFields.value.includes(field)) continue
        updateItems.add(rowId)
      }
    }
  }

  // 删除项：仅当至少有一个变更机型在选中列表中，且在可见范围内
  for (const [itemId, modelSet] of deletedItemModelMap.value.entries()) {
    if (!visibleItemIds.has(itemId)) continue
    for (const mid of modelSet) {
      if (selectedSet.has(mid)) {
        deleteItems.add(itemId)
        break
      }
    }
  }

  return {
    total: new Set([...createItems, ...updateItems, ...deleteItems]).size,
    create: createItems.size,
    update: updateItems.size,
    delete: deleteItems.size
  }
})

// 各字段修改的草稿数（仅可见项中，按字段统计）
// 当前可见的配置列字段名列表
const visibleConfigFields = computed(() => {
  const fields = []
  if (visibleColumns.final_config) fields.push('final_config')
  if (visibleColumns.current_config) fields.push('current_config')
  if (visibleColumns.selection_config) fields.push('selection_config')
  if (visibleColumns.rd_status) fields.push('rd_status')
  return fields
})

// 草稿项列表（去重，每项一行，含名称信息）
const draftItems = computed(() => {
  const selectedSet = new Set(selectedModels.value)
  if (selectedSet.size === 0) return []
  // 基于 baseFilteredData 统计可见项（排除草稿筛选，统计数字不随草稿标签变化）
  const visibleItemIds = new Set(baseFilteredData.value.map(r => r.id))
  const itemsMap = new Map()
  // 新增项 — 在可见范围内且至少有一个变更机型在选中列表中
  for (const [itemId, modelSet] of newItemModelMap.value.entries()) {
    if (!visibleItemIds.has(itemId)) continue
    let hasMatch = false
    for (const mid of modelSet) {
      if (selectedSet.has(mid)) { hasMatch = true; break }
    }
    if (!hasMatch) continue
    const info = draftItemInfo.value.get(itemId) || {}
    const row = tableData.value.find(r => r.id === itemId)
    itemsMap.set(`create_${itemId}`, {
      itemId,
      rdName: info.rdName || row?.rd_name || `ID: ${itemId}`,
      ipn: info.ipn || row?.ipn || '',
      changeType: 'create'
    })
  }
  // 单元格级新增（从未定义/空改为有值）— 来自 draftChanges
  const seenCreateIds = new Set()
  for (const [key, change] of draftChanges.value.entries()) {
    if (change.changeType === 'create') {
      const parts = key.split('_')
      const rowId = parseInt(parts[0])
      if (!visibleItemIds.has(rowId)) continue
      const modelId = parseInt(parts[1])
      const field = parts.slice(2).join('_')
      if (selectedSet.size > 0 && !selectedSet.has(modelId)) continue
      if (!visibleConfigFields.value.includes(field)) continue
      if (!seenCreateIds.has(rowId)) {
        seenCreateIds.add(rowId)
        const info = draftItemInfo.value.get(rowId) || {}
        const row = tableData.value.find(r => r.id === rowId)
        if (!itemsMap.has(`create_${rowId}`)) {
          itemsMap.set(`create_${rowId}`, {
            itemId: rowId,
            rdName: info.rdName || row?.rd_name || `ID: ${rowId}`,
            ipn: info.ipn || row?.ipn || '',
            changeType: 'create'
          })
        }
      }
    }
  }
  // 修改项（按 item_id 去重）— 仅当（有筛选时）在可见范围内、变更机型在选中列表中、且匹配列筛选
  const seenUpdateIds = new Set()
  for (const [key, change] of draftChanges.value.entries()) {
    if (change.changeType === 'update') {
      const parts = key.split('_')
      const rowId = parseInt(parts[0])
      if (!visibleItemIds.has(rowId)) continue
      const modelId = parseInt(parts[1])
      const field = parts.slice(2).join('_')
      if (selectedSet.size > 0 && !selectedSet.has(modelId)) continue
      // 仅当该字段的列可见时才计入
      if (!visibleConfigFields.value.includes(field)) continue
      if (!seenUpdateIds.has(rowId)) {
        seenUpdateIds.add(rowId)
        const info = draftItemInfo.value.get(rowId) || {}
        const row = tableData.value.find(r => r.id === rowId)
        itemsMap.set(`update_${rowId}`, {
          itemId: rowId,
          rdName: info.rdName || row?.rd_name || `ID: ${rowId}`,
          ipn: info.ipn || row?.ipn || '',
          changeType: 'update'
        })
      }
    }
  }
  // 删除项 — 在可见范围内且至少有一个变更机型在选中列表中
  for (const [itemId, modelSet] of deletedItemModelMap.value.entries()) {
    if (!visibleItemIds.has(itemId)) continue
    let hasMatch = false
    for (const mid of modelSet) {
      if (selectedSet.has(mid)) { hasMatch = true; break }
    }
    if (!hasMatch) continue
    const info = draftItemInfo.value.get(itemId) || {}
    itemsMap.set(`delete_${itemId}`, {
      itemId,
      rdName: info.rdName || `ID: ${itemId}`,
      ipn: info.ipn || '',
      changeType: 'delete'
    })
  }
  return Array.from(itemsMap.values())
})

// 全选/部分选状态
const allDraftSelected = computed(() => {
  return draftItems.value.length > 0 && draftItems.value.every(i => selectedDraftItemIds.value.has(i.itemId))
})
const someDraftSelected = computed(() => {
  return selectedDraftItemIds.value.size > 0 && !allDraftSelected.value
})

// 有机型变更的机型列表（用于按机型过滤提交）
const draftModels = computed(() => {
  return Array.from(draftModelIdSet.value).map(id => ({
    id,
    name: allModelsMap.value.get(id)?.name || `型号 ${id}`
  }))
})

// 配置字段列值筛选辅助函数（按 modelId 隔离，操作 pending 暂存）
const hasFieldFilter = (field, modelId) => {
  const arr = fieldFilters[getFilterKey(field, modelId)]
  return arr && arr.length > 0
}
const clearFieldFilter = (field, modelId) => {
  const key = getFilterKey(field, modelId)
  pendingFieldFilters[key] = []
}
const selectAllFieldFilter = (field, modelId) => {
  const key = getFilterKey(field, modelId)
  pendingFieldFilters[key] = [...(fieldFilterOptions.value[key] || [])]
}

const isEmptyValue = (v) => _isEmptyValue(v)

// 根据草稿筛选过滤表格数据
function _computeFilteredData(skipDraftFilter = false) {
  let data = tableData.value

  // 隐藏全空行：所有选中机型的当前可见配置字段都为空
  const visibleFields = visibleConfigFields.value
  data = data.filter(row => {
    if (!row.model_values || visibleFields.length === 0) return false
    return selectedModels.value.some(modelId => {
      const mv = row.model_values[modelId]
      if (!mv) return false
      return visibleFields.some(f => !isEmptyValue(mv[f]))
    })
  })

  // 草稿筛选（统计场景跳过此阶段）
  if (!skipDraftFilter && draftFilterMode.value) {
    const selectedSet = new Set(selectedModels.value)
    const visibleFields = visibleConfigFields.value
    data = filterByDraftMode(data, (row) => {
      const types = new Set()
      const rowId = row.id
      // 新增：newItemModelMap 或 draftChanges 中有 create 类型（仅可见字段）
      if (newItemModelMap.value.has(rowId)) {
        const modelSet = newItemModelMap.value.get(rowId)
        for (const mid of modelSet) {
          if (selectedSet.has(mid)) { types.add('create'); break }
        }
      }
      if (!types.has('create')) {
        for (const [k, c] of draftChanges.value.entries()) {
          if (c.changeType !== 'create') continue
          const parts = k.split('_')
          if (parseInt(parts[0]) !== rowId) continue
          if (!selectedSet.has(parseInt(parts[1]))) continue
          const field = parts.slice(2).join('_')
          if (visibleFields.includes(field)) { types.add('create'); break }
        }
      }
      // 修改：draftChanges 中有 update 类型（仅可见字段）
      for (const [k, c] of draftChanges.value.entries()) {
        if (c.changeType !== 'update') continue
        const parts = k.split('_')
        if (parseInt(parts[0]) !== rowId) continue
        if (!selectedSet.has(parseInt(parts[1]))) continue
        const field = parts.slice(2).join('_')
        if (visibleFields.includes(field)) { types.add('update'); break }
      }
      // 删除
      if (deletedItemModelMap.value.has(rowId)) {
        const modelSet = deletedItemModelMap.value.get(rowId)
        for (const mid of modelSet) {
          if (selectedSet.has(mid)) { types.add('delete'); break }
        }
      }
      return types
    })
  }

  // 差异筛选
  if (showDiffOnly.value && selectedModels.value.length >= 2) {
    data = data.filter(row =>
      selectedModels.value.some(mid =>
        row.model_values[mid] && Object.values(row.model_values[mid]._hasDiff || {}).some(Boolean)
      )
    )
  }

  // 研发状态未完成筛选
  if (showRdIncomplete.value) {
    data = data.filter(row => {
      const modelValues = row.model_values
      if (!modelValues) return false
      return selectedModels.value.some(modelId => {
        const v = modelValues[modelId]?.rd_status
        return v && v !== '已完成' && v !== 'N/A' && v !== '-'
      })
    })
  }

  // 配置字段列值筛选：按 `field|modelId` 逐列检查，多列 AND
  const activeFieldFilters = Object.entries(fieldFilters).filter(([, v]) => v.length > 0)
  if (activeFieldFilters.length > 0) {
    data = data.filter(row => {
      if (!row.model_values) return false
      return activeFieldFilters.every(([key, filterValues]) => {
        const [field, modelIdStr] = key.split('|')
        const modelId = parseInt(modelIdStr)
        const mv = row.model_values[modelId]
        if (!mv) return false
        const val = mv[field]
        const display = (val && val !== '' && val !== '-' && val !== 'N/A' && val !== '未定义') ? val : '(空)'
        return filterValues.includes(display)
      })
    })
  }

  return data
}

// 配置字段列值筛选选项：按 `field|modelId` 键控，收集每个机型在各字段上的唯一值
const fieldFilterOptions = computed(() => {
  const options = {}
  const seen = {}
  for (const row of tableData.value) {
    if (!row.model_values) continue
    for (const modelId of selectedModels.value) {
      for (const field of ['final_config', 'current_config', 'selection_config', 'rd_status']) {
        const mv = row.model_values[modelId]
        if (!mv) continue
        const key = getFilterKey(field, modelId)
        if (!options[key]) { options[key] = []; seen[key] = new Set() }
        const v = mv[field]
        const display = (v && v !== '' && v !== '-' && v !== 'N/A' && v !== '未定义') ? v : '(空)'
        if (!seen[key].has(display)) {
          seen[key].add(display)
          options[key].push(display)
        }
      }
    }
  }
  return options
})

// 预计算 _hasDiff（用 watch 避免 computed 副作用导致响应式异常）
const diffReady = ref(false)
const computeDiffs = () => {
  if (!showDiffOnly.value || selectedModels.value.length < 2) {
    // 清除陈旧的 _hasDiff
    for (const row of tableData.value) {
      if (!row.model_values) continue
      for (const mid of selectedModels.value) {
        if (row.model_values[mid]) row.model_values[mid]._hasDiff = {}
      }
    }
    diffReady.value = false
    return
  }
  const normalize = normalizeValue
  for (const row of tableData.value) {
    if (!row.model_values) continue
    for (const mid of selectedModels.value) {
      if (row.model_values[mid]) {
        row.model_values[mid]._hasDiff = {}
      }
    }
    for (const field of visibleConfigFields.value) {
      const refVal = normalize(referenceModel.value ? row.model_values[referenceModel.value]?.[field] : null)
      for (const mid of selectedModels.value) {
        if (mid === referenceModel.value) continue
        const mv = row.model_values[mid]
        if (!mv) continue
        if (normalize(mv[field]) !== refVal) {
          mv._hasDiff[field] = true
        }
      }
    }
  }
  diffReady.value = true
}
// 同步执行 watch，确保 _hasDiff 在 computed 求值前就绪
watch([showDiffOnly, tableData, selectedModels, referenceModel, visibleConfigFields], computeDiffs, { immediate: true, flush: 'sync' })

const filteredTableData = computed(() => {
  // 显式声明依赖，确保 draftFilterMode/draftFilters 变化时触发重新计算
  void draftFilterMode.value
  void draftFilters.value
  return _computeFilteredData(false)
})

// 不含草稿筛选的基础可见数据（用于统计，不随草稿标签变化）
const baseFilteredData = computed(() => _computeFilteredData(true))

// 前端分页后的表格数据
const paginatedTableData = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredTableData.value.slice(start, start + pageSize.value)
})

// tableData / originalData O(1) 索引
const tableDataMap = computed(() => new Map(tableData.value.map(r => [r.id, r])))
const originalDataMap = computed(() => new Map(originalData.value.map(r => [r.id, r])))

// 单元格状态缓存：预计算当前页所有可见单元格的状态，模板中 O(1) 查找
const cellStateCache = computed(() => {
  const cache = new Map()
  for (const row of paginatedTableData.value) {
    const origRow = originalDataMap.value.get(row.id)
    for (const mid of selectedModels.value) {
      if (!row.model_values[mid]) continue
      for (const field of visibleConfigFields.value) {
        const key = `${row.id}_${mid}_${field}`
        const origVal = origRow?.model_values?.[mid]?.[field]
        cache.set(key, {
          isChanged: computeIsChanged(row.id, mid, field, origVal),
          changeType: computeChangeType(row.id, mid, field),
          draftOldValue: computeDraftOldVal(row.id, mid, field)
        })
      }
    }
  }
  return cache
})

// 辅助：预计算 isChanged (优先草稿/增删标记，其次对比原始值)
const computeIsChanged = (rowId, modelId, field, origVal) => {
  const ct = computeChangeType(rowId, modelId, field)
  if (ct) return true
  const key = `${rowId}_${modelId}_${field}`
  if (draftChanges.value.has(key)) return true
  if (origVal !== undefined) {
    const curVal = tableDataMap.value.get(rowId)?.model_values?.[modelId]?.[field]
    return isValueChanged(origVal, curVal)
  }
  return false
}

// 辅助：预计算 changeType
const computeChangeType = (rowId, modelId, field) => {
  const key = `${rowId}_${modelId}_${field}`
  const draftChange = draftChanges.value.get(key)
  if (draftChange) return draftChange.changeType || 'update'
  const createModels = newItemModelMap.value.get(rowId)
  if (createModels && (createModels.size === 0 || createModels.has(modelId))) return 'create'
  const deleteModels = deletedItemModelMap.value.get(rowId)
  if (deleteModels && (deleteModels.size === 0 || deleteModels.has(modelId))) return 'delete'
  return null
}

// 辅助：预计算草稿旧值
const computeDraftOldVal = (rowId, modelId, field) => {
  const key = `${rowId}_${modelId}_${field}`
  const change = draftChanges.value.get(key)
  return change ? change.oldValue : undefined
}

// 默认空状态
const EMPTY_CELL_STATE = { isChanged: false, changeType: null, draftOldValue: undefined }

// 模板用：O(1) 获取单元格状态
const getCellState = (rowId, modelId, field) => {
  return cellStateCache.value.get(`${rowId}_${modelId}_${field}`) || EMPTY_CELL_STATE
}

// 导入预览
const previewDialogVisible = ref(false)

const previewData = ref(null)
const groupImportImpactModels = models => {
  const groups = new Map()
  for (const model of models) {
    const seriesName = model.series_name || '未分类系列'
    if (!groups.has(seriesName)) groups.set(seriesName, { seriesName, models: [] })
    groups.get(seriesName).models.push(model)
  }
  return Array.from(groups.values())
}
const impactModelGroups = computed(() => groupImportImpactModels(previewData.value?.impact?.models || []))
const previewFiles = ref([])  // 支持多文件
const importing = ref(false)
const importProgress = ref({ current: 0, total: 0 })  // 导入进度

// 多文件上传临时变量
let pendingFiles = []
let processTimer = null
let previewRequest = 0
let committedPreviewRequest = 0

// 右键菜单状态
const contextMenu = reactive({
  visible: false,
  x: 0,
  y: 0,
  row: null,
  modelId: null,
  field: null
})

// 应用到所有机型对话框
const applyToAllDialog = reactive({
  visible: false,
  row: null,
  modelId: null,
  field: null,
  fieldName: '',
  value: null
})

// 粘贴整行配置对话框
const pasteRowDialog = reactive({
  visible: false,
  sourceRow: null,
  targetRowId: null
})

// 行差异查看对话框
const rowDiffDialog = reactive({
  visible: false,
  row: null
})

// 复制的整行配置
const copiedRowConfig = ref(null)

// Phase 2: 多选单元格和复制粘贴
const selectedCells = ref([]) // { rowId, modelId, field }[]
const copiedCell = ref(null) // { row, modelId, field, value }
const isMultiSelectMode = ref(false)

// Phase 3: 键盘导航
const focusedCell = ref(null) // { rowId, modelId, field }

// 拖拽填充相关
const isDragging = ref(false)
const dragSource = ref(null) // { rowId, modelId, field, value }
const dragTargetCells = ref([]) // { rowId, modelId, field }[]

// 批量修改
const batchEditDialogVisible = ref(false)
const batchEditSubmitting = ref(false)
const batchEditResult = ref(null)
const batchEditRowCount = computed(() => batchEditForm.scope === 'selected' ? selectedRows.value.length : filteredTableData.value.length)
const batchEditForm = reactive({
  field: '',
  value: '',
  scope: 'selected'
})

// 对话框
const versionDialogVisible = ref(false)
const submitDialogVisible = ref(false)
const submitPreviewLoading = ref(false)
const submitSubmitting = ref(false)
const submitPreviews = ref([])
const submitPreviewError = ref('')
const submitResults = ref([])
let submitPreviewRequest = 0
const submitScope = ref(null)
const versionForm = reactive({
  version_number: '',
  version_name: '',
  description: ''
})
const submitForm = reactive({
  version_number: '',
  description: '',
  item_ids: null,  // 部分提交时选中项ID列表
  model_ids: null  // 按机型提交时选中的机型ID列表
})

// 批量操作
const batchSubmitDialog = reactive({
  visible: false,
  loading: false,
  error: '',
  scope: null,
  availableBatches: [],  // { batchId, seriesId, seriesName, changeCount }
  selectedBatchIds: [],
  versionNumber: '',
  description: ''
})
const batchSubmitSubmitting = ref(false)
let batchSubmitPreviewRequest = 0
const reviewInteractionLocked = computed(() => submitDialogVisible.value || batchSubmitDialog.visible || batchEditSubmitting.value)
const batchSubmitResultDialog = reactive({
  visible: false,
  results: []  // { seriesName, versionNumber, changes, success, message }
})

// 加载枚举值
const loadEnumValues = async () => {
  try {
    const res = await getEnumValues()
    // 选型类别：排除"已完成"
    enumValues.selectionTypes = (res.selection_types || []).filter(v => v !== '已完成')
    // 研发状态：包含未定义、未完成、招标完成、已完成
    enumValues.rdStatuses = (res.rd_statuses || []).filter(v =>
      ['未定义', '未完成', '招标完成', '已完成'].includes(v)
    )
    // 最终配置和当前配置：合并后排除"已完成"
    const allValues = [...new Set([...res.selection_types || [], ...res.rd_statuses || []])]
    enumValues.configValues = allValues.filter(v => v !== '已完成')
  } catch (error) {
    console.error('加载枚举值失败:', error)
  }
}

// 获取批量修改选项
const getBatchEditOptions = () => {
  switch (batchEditForm.field) {
    case 'selection_config':
      return enumValues.selectionTypes
    case 'rd_status':
      return enumValues.rdStatuses
    default:
      return enumValues.configValues
  }
}

// 加载产品系列
const loadSeries = async () => {
  try {
    const res = await getSeriesList()
    seriesList.value = res.items || []

    if (seriesList.value.length > 0) {
      // 尝试从 localStorage 恢复上次的系列选择
      const saved = localStorage.getItem(SERIES_SELECTION_KEY)
      if (saved) {
        try {
          const parsed = JSON.parse(saved)
          const validIds = parsed.selected_ids.filter(id =>
            seriesList.value.some(s => s.id === id)
          )
          if (validIds.length > 0) {
            selectedSeries.value = validIds
          } else {
            selectedSeries.value = []
          }
        } catch {
          // JSON 解析失败，保持空选择
          selectedSeries.value = []
        }
      } else {
        // 没有保存的选择，默认不选任何系列
        selectedSeries.value = []
      }

      // 如果有选中系列，加载型号
      if (selectedSeries.value.length > 0) {
        await loadModels()
      }
    } else {
      selectedSeries.value = []
      allModelsMap.value.clear()
      selectedModels.value = []
      tempSelectedModels.value = []
      tableData.value = []
    }
  } catch (error) {
    console.error('加载产品系列失败:', error)
    ElMessage.error('加载产品系列失败')
  }
}

// 全选系列
const selectAllSeries = () => {
  const allIds = seriesList.value.map(s => s.id)
  selectedSeries.value = allIds
  saveSeriesSelection()
  handleSeriesSelect(allIds)
}

// 清空系列
const clearAllSeries = () => {
  selectedSeries.value = []
  allModelsMap.value.clear()
  selectedModels.value = []
  tempSelectedModels.value = []
  tableData.value = []
  saveSeriesSelection()
}

// 机型选择即时生效，快捷选择与手动勾选使用相同入口。
const applyModelSelection = () => { selectedModels.value = [...tempSelectedModels.value]; currentPage.value = 1 }

// 机型下拉打开时同步当前选择
const onModelDropdownVisibleChange = (visible) => {
  if (!visible) {
    applyModelSelection()
  } else {
    // 打开时用当前生效的选择初始化临时值
    tempSelectedModels.value = [...selectedModels.value]
  }
}

// 机型全选
const selectAllModels = () => {
  tempSelectedModels.value = Array.from(allModelsMap.value.keys())
  applyModelSelection()
}

// 机型取消全选
const clearAllModels = () => {
  tempSelectedModels.value = []
  applyModelSelection()
}

// 机型反选
const invertModelSelection = () => {
  const currentSet = new Set(tempSelectedModels.value)
  tempSelectedModels.value = Array.from(allModelsMap.value.keys()).filter(id => !currentSet.has(id))
  applyModelSelection()
}

// 选中所有匹配搜索文本的型号
const selectMatchingModels = () => {
  const q = modelFilterText.value.trim().toLowerCase()
  if (!q) return
  const matched = []
  for (const [id, m] of allModelsMap.value) {
    if (m.name.toLowerCase().includes(q)) {
      matched.push(id)
    }
  }
  if (matched.length > 0) {
    const current = new Set(tempSelectedModels.value)
    for (const id of matched) current.add(id)
    tempSelectedModels.value = Array.from(current)
    applyModelSelection()
  }
}

// 记录下拉打开时的系列选择，用于比较是否真的变化
const prevSelectedSeries = ref([])

// 系列下拉 visible-change 事件：收起时才真正刷新数据
const onSeriesDropdownVisibleChange = (visible) => {
  if (!visible) {
    // 下拉收起，检查选择是否真的变了
    const prev = prevSelectedSeries.value
    const curr = selectedSeries.value
    const changed = prev.length !== curr.length || prev.some(id => !curr.includes(id)) || curr.some(id => !prev.includes(id))
    if (changed) {
      handleSeriesSelect(curr)
    }
  } else {
    // 下拉打开，记录当前选择
    prevSelectedSeries.value = [...selectedSeries.value]
  }
}

// 处理系列选择变化
const handleSeriesSelect = (val) => {
  const ids = Array.isArray(val) ? val : [val]
  if (ids.length === 0) {
    allModelsMap.value.clear()
    selectedModels.value = []
    tempSelectedModels.value = []
    tableData.value = []
    saveSeriesSelection()
    return
  }
  currentPage.value = 1
  showDiffOnly.value = false
  referenceModel.value = null
  saveSeriesSelection()
  loadModels()
}

// 加载产品型号（从所有选中系列并行加载）
let modelLoadRequest = 0
const loadModels = async ({ modelGroup } = {}) => {
  const request = ++modelLoadRequest
  const seriesIds = [...selectedSeries.value]
  configReady.value = false
  if (!seriesIds.length) {
    allModelsMap.value.clear()
    selectedModels.value = []
    tempSelectedModels.value = []
    tableData.value = []
    originalData.value = []
    configReady.value = true
    return false
  }
  try {
    const results = await Promise.all(seriesIds.map(sid => getModels(sid)))
    if (request !== modelLoadRequest || seriesIds.length !== selectedSeries.value.length || seriesIds.some((id, i) => id !== selectedSeries.value[i])) return false
    const models = new Map()
    results.forEach((res, idx) => {
      const seriesId = seriesIds[idx]
      const seriesName = seriesList.value.find(s => s.id === seriesId)?.name || ''
      for (const m of (res.items || [])) models.set(m.id, { id: m.id, name: m.name, seriesId, seriesName, source_uuid: m.source_uuid, aliases: m.aliases || [] })
    })
    const selection = modelGroup ? resolveGroupModels(modelGroup, models) : null
    if (selection && !selection.ids.length) { ElMessage.warning('该分组的机型已不存在或名称不唯一，请更新分组'); return false }
    allModelsMap.value = models
    selectedModels.value = selection ? selection.ids : selectedModels.value.filter(mid => models.has(mid))
    if (!modelGroup) applySavedOrder(selectedModels.value)
    showDiffOnly.value = false
    referenceModel.value = null
    tempSelectedModels.value = [...selectedModels.value]
    if (!await loadData()) return false
    if (request !== modelLoadRequest) return false
    const draftLoaded = await initDraft()
    if (request !== modelLoadRequest) return false
    if (!draftLoaded) {
      tableData.value = []
      originalData.value = []
      ElMessage.error('草稿状态加载失败，请重新选择系列或分组后再编辑')
      return false
    }
    configReady.value = true
    if (selection?.missing) ElMessage.warning(`已恢复 ${selection.ids.length} 个机型，${selection.missing} 个机型未找到或名称不唯一`)
    return true
  } catch (error) {
    console.error('加载产品型号失败:', error)
    if (error.response?.status === 404) {
      ElMessage.warning('当前选中的系列已被删除，请重新选择')
      if (!modelGroup) await loadSeries()
    } else ElMessage.error('加载产品型号失败，请重试')
    return false
  }
}

// 加载配置数据（从所有选中系列并行加载，按 IPN 合并）
let dataLoadRequest = 0
const loadData = async () => {
  if (selectedSeries.value.length === 0) {
    tableData.value = []
    originalData.value = []
    return true
  }

  const seriesIds = [...selectedSeries.value]
  const request = ++dataLoadRequest
  loading.value = true
  try {
    // 加载全部数据（limit: 99999），前端分页
    const paramsBase = {
      categories: selectedCategories.value.length > 0 ? selectedCategories.value.join(',') : undefined,
      search: searchText.value || undefined,
      include_empty: true,
      skip: 0,
      limit: 99999
    }

    const results = await Promise.all(
      seriesIds.map(sid => getConfigRows({ ...paramsBase, series_id: sid }))
    )

    if (request !== dataLoadRequest || seriesIds.length !== selectedSeries.value.length || seriesIds.some((id, i) => id !== selectedSeries.value[i])) return false

    // 按 IPN 合并 model_values
    const mergedMap = new Map() // ipn -> mergedRow
    results.forEach((res, idx) => {
      const seriesId = seriesIds[idx]
      for (const item of (res.items || [])) {
        const ipn = item.ipn || `__no_ipn_${item.id}`
        if (!mergedMap.has(ipn)) {
          // 以第一个出现的 ConfigItem 字段为权威值
          mergedMap.set(ipn, {
            id: item.id,
            ipn: item.ipn,
            rd_name: item.rd_name,
            v_code: item.v_code,
            zh_desc: item.zh_desc,
            en_desc: item.en_desc,
            category: item.category,
            model_values: {}
          })
        }
        const merged = mergedMap.get(ipn)
        // 合并 model_values
        if (item.model_values) {
          for (const [modelId, values] of Object.entries(item.model_values)) {
            const mid = parseInt(modelId)
            if (!merged.model_values[mid]) {
              merged.model_values[mid] = values
            }
          }
        }
      }
    })

    tableData.value = Array.from(mergedMap.values())
    // 深拷贝保存原始数据
    originalData.value = JSON.parse(JSON.stringify(tableData.value))
    return true
  } catch (error) {
    if (request !== dataLoadRequest) return false
    tableData.value = []
    originalData.value = []
    console.error('加载配置数据失败:', error)
    if (error.response?.status === 404) {
      ElMessage.warning('当前选中的系列已被删除，请重新选择')
      tableData.value = []
      if (!applyingModelGroup.value) await loadSeries()
    } else {
      ElMessage.error('加载数据失败')
    }
    return false
  } finally {
    if (request === dataLoadRequest) loading.value = false
  }
}

// 检查字段是否被修改（基于实际值与原始值的比较）
const isFieldChanged = (rowId, modelId, field) => {
  // 检查是否是机型级新增（仅标记新增机型的列）
  const createModels = newItemModelMap.value.get(rowId)
  if (createModels && (createModels.size === 0 || createModels.has(modelId))) return true
  // 检查是否是机型级删除（仅标记删除机型的列）
  const deleteModels = deletedItemModelMap.value.get(rowId)
  if (deleteModels && (deleteModels.size === 0 || deleteModels.has(modelId))) return true
  // 优先检查草稿记录（适用于导入、回滚等批量操作产生的草稿）
  const key = `${rowId}_${modelId}_${field}`
  if (draftChanges.value.has(key)) {
    return true
  }

  // 获取当前显示的值
  const currentRow = tableData.value.find(r => r.id === rowId)
  const currentValue = currentRow?.model_values?.[modelId]?.[field]

  // 获取原始值（从 originalData）
  const originalRow = originalData.value.find(r => r.id === rowId)
  const originalValue = originalRow?.model_values?.[modelId]?.[field]

  // 比较是否真正不同
  return isValueChanged(originalValue, currentValue)
}

// 获取单元格变更类型：'create' | 'update' | 'delete' | null
const getCellChangeType = (rowId, modelId, field) => {
  // 优先检查草稿记录（精确到 field）
  const key = `${rowId}_${modelId}_${field}`
  const draftChange = draftChanges.value.get(key)
  if (draftChange) {
    return draftChange.changeType || 'update'
  }

  // 检查机型级新增
  const createModels = newItemModelMap.value.get(rowId)
  if (createModels && (createModels.size === 0 || createModels.has(modelId))) {
    return 'create'
  }

  // 检查机型级删除
  const deleteModels = deletedItemModelMap.value.get(rowId)
  if (deleteModels && (deleteModels.size === 0 || deleteModels.has(modelId))) {
    return 'delete'
  }

  return null
}

// 获取原始值
const getOriginalValue = (rowId, modelId, field) => {
  const key = `${rowId}_${modelId}_${field}`
  const change = draftChanges.value.get(key)
  if (change) {
    return change.oldValue
  }
  // 回退到 originalData（注意：导入/回滚后数据库已被更新，此值可能不是真正的原始值）
  const originalRow = originalData.value.find(r => r.id === rowId)
  return originalRow?.model_values?.[modelId]?.[field]
}

// 仅从草稿记录取原值，不依赖 originalData（导入/回滚后 originalData 可能已被数据库新值覆盖）
const getDraftOldValue = (rowId, modelId, field) => {
  const key = `${rowId}_${modelId}_${field}`
  const change = draftChanges.value.get(key)
  return change ? change.oldValue : undefined
}

// 获取删除项的旧值（来自快照），无效值返回 undefined 以便模板回退到 '-'
const getDeleteOldValue = (rowId, modelId, field) => {
  const snapKey = `${rowId}_${modelId}`
  const snapVals = draftDeleteValues.value.get(snapKey)
  if (!snapVals) return undefined
  const val = snapVals[field]
  // N/A、None、空字符串均视为无有效旧值
  if (val == null || val === '' || val === 'N/A' || val === 'None') return undefined
  return val
}

// 调试：从控制台查看特定单元格的草稿数据，用法: debugDraft(行id, 机型id, '字段名')
window.debugDraft = (rowId, modelId, field) => {
  if (rowId == null) {
    console.log('=== 所有草稿项信息 ===')
    draftItemInfo.value.forEach((info, id) => {
      console.log(`  item_id=${id}, rdName="${info.rdName}", ipn="${info.ipn}"`)
    })
    console.log('=== draftChanges 数量:', draftChanges.value.size)
    return
  }
  const key = `${rowId}_${modelId}_${field}`
  const change = draftChanges.value.get(key)
  console.log('draftChanges key:', key)
  console.log('change:', change)
  console.log('draftChanges has key:', draftChanges.value.has(key))
  const info = draftItemInfo.value.get(rowId)
  console.log('item info:', info)
}

// 检查值是否真正变化（使用共享方法）
const isValueChanged = (oldVal, newVal) => _isValueChanged(oldVal, newVal)

let searchTimer
const queueSearch = () => { clearTimeout(searchTimer); searchTimer = setTimeout(flushSearch, 300) }
const flushSearch = () => { clearTimeout(searchTimer); onFilterChange() }
const hasActiveFilters = computed(() => Boolean(searchText.value || selectedCategories.value.length !== categoryOptions.length || draftFilterMode.value || showDiffOnly.value || showRdIncomplete.value || Object.values(fieldFilters).some(values => values.length)))
const resetActiveFilters = async () => {
  clearTimeout(searchTimer)
  searchText.value = ''
  selectedCategories.value = [...categoryOptions]
  draftFilterMode.value = false; draftFilters.value = new Set()
  showDiffOnly.value = false; showRdIncomplete.value = false
  for (const key of Object.keys(fieldFilters)) { fieldFilters[key] = []; pendingFieldFilters[key] = [] }
  await onFilterChange()
}

// 筛选条件变更时立即刷新
const onFilterChange = async () => {
  if (applyingModelGroup.value) return
  currentPage.value = 1
  await loadData()
}

// 初始化草稿批次（多系列）
let draftLoadRequest = 0
const initDraft = async () => {
  const request = ++draftLoadRequest
  const seriesIds = [...selectedSeries.value]
  const isCurrent = () => request === draftLoadRequest && seriesIds.length === selectedSeries.value.length && seriesIds.every((id, i) => id === selectedSeries.value[i])
  configReady.value = false
  if (!seriesIds.length) {
    configReady.value = true
    return true
  }

  // 先清空旧状态
  draftChanges.value.clear()
  draftItemInfo.value = new Map()
  newItemModelMap.value = new Map()
  deletedItemModelMap.value = new Map()
  newItemIds.value = new Set()
  deletedItemIds.value = new Set()
  draftDeleteValues.value = new Map()
  draftModelIdSet.value = new Set()
  draftStats.total = 0
  draftStats.create = 0
  draftStats.update = 0
  draftStats.delete = 0

  let success = true
  const newBatchMap = new Map()
  const createModelMap = new Map()
  const deleteModelMap = new Map()
  const infoMap = new Map()
  const modelIdSet = new Set()

  for (const seriesId of seriesIds) {
    try {
      let batchId
      try {
        const res = await getCurrentDraftBatch(seriesId)
        if (!isCurrent()) return false
        if (res?.exists) {
          batchId = res.batch.id
          // 恢复草稿变更记录
          for (const d of (res.drafts || [])) {
            if (d.item_id && !infoMap.has(d.item_id)) {
              infoMap.set(d.item_id, { rdName: d.rd_name, ipn: d.ipn })
            }
            if (d.change_type === 'create' && d.item_id && d.model_id) {
              // 有 field_name 的是单元格级新增（从未定义改为有值），放入 draftChanges
              if (d.field_name) {
                const key = `${d.item_id}_${d.model_id}_${d.field_name}`
                draftChanges.value.set(key, {
                  oldValue: d.old_value,
                  newValue: d.new_value,
                  draftId: d.id,
                  changeType: 'create'
                })
                draftStats.create++
                draftStats.total++
              } else {
                if (!createModelMap.has(d.item_id)) createModelMap.set(d.item_id, new Set())
                createModelMap.get(d.item_id).add(d.model_id)
                modelIdSet.add(d.model_id)
                draftStats.create++
                draftStats.total++
              }
            } else if (d.change_type === 'delete' && d.item_id && d.model_id) {
              if (!deleteModelMap.has(d.item_id)) deleteModelMap.set(d.item_id, new Set())
              deleteModelMap.get(d.item_id).add(d.model_id)
              modelIdSet.add(d.model_id)
              draftStats.delete++
              draftStats.total++
              if (d.snapshot_values) {
                try {
                  const snapVals = JSON.parse(d.snapshot_values)
                  draftDeleteValues.value.set(`${d.item_id}_${d.model_id}`, snapVals)
                } catch (e) { /* ignore */ }
              }
            } else if (d.change_type === 'update' && d.item_id && d.model_id) {
              modelIdSet.add(d.model_id)
              const key = `${d.item_id}_${d.model_id}_${d.field_name}`
              // 重新判断：旧值为空/未定义等应视为新增而非修改
              const isValueEmpty = (v) => !v || v === '-' || v === 'N/A' || v === '未定义' || v === ''
              const actualChangeType = isValueEmpty(d.old_value) ? 'create' : 'update'
              draftChanges.value.set(key, {
                oldValue: d.old_value,
                newValue: d.new_value,
                draftId: d.id,
                changeType: actualChangeType
              })
              if (actualChangeType === 'create') {
                draftStats.create++
              } else {
                draftStats.update++
              }
              draftStats.total++
            }
          }
        }
      } catch (error) { if (error.response?.status !== 404) throw error }

      if (!batchId) {
        const batchRes = await createDraftBatch(seriesId)
        if (!isCurrent()) return false
        batchId = batchRes.id
      }
      newBatchMap.set(seriesId, batchId)
    } catch (error) {
      if (!isCurrent()) return false
      success = false
      console.error(`系列 ${seriesId} 初始化草稿失败:`, error)
    }
  }

  if (!isCurrent()) return false
  draftBatchMap.value = newBatchMap
  refreshSaveFeedback()
  draftItemInfo.value = infoMap
  newItemModelMap.value = createModelMap
  deletedItemModelMap.value = deleteModelMap
  newItemIds.value = new Set(createModelMap.keys())
  deletedItemIds.value = new Set(deleteModelMap.keys())
  draftModelIdSet.value = modelIdSet
  configReady.value = success
  return success
}

// 获取型号名称（跨系列格式：seriesName / modelName，用于下拉显示等）
const getModelName = (modelId) => {
  const m = allModelsMap.value.get(modelId)
  return m ? `${m.seriesName} / ${m.name}` : ''
}

// 获取型号简称（仅 modelName，自动省略与系列名重复的前缀）
const getModelShortName = (modelId) => _getModelShortName(allModelsMap.value, modelId)

// 按系列分组的已选型号（用于表头层级显示）
const groupedSelectedModels = computed(() => groupModelsBySeries(allModelsMap.value, selectedModels.value))

const getModelNames = (modelIds) => {
  return Array.from(modelIds).map(id => getModelName(id)).filter(Boolean).join(', ')
}

// 表格选择变化
const handleSelectionChange = (rows) => {
  selectedRows.value = rows
}

// 开始编辑单元格
const startEdit = (row, modelId, field) => {
  if (!configReady.value || loading.value || applyingModelGroup.value || submitDialogVisible.value || batchSubmitDialog.visible) return false
  editingCell.value = { rowId: row.id, modelId, field }
  // 自动展开下拉框
  nextTick(() => {
    if (editSelectRef.value) {
      // el-select 的 ref 可能是数组或单个元素
      const select = Array.isArray(editSelectRef.value) ? editSelectRef.value[0] : editSelectRef.value
      if (select) {
        select.focus()
        // 延迟调用 toggleMenu 确保组件已渲染
        setTimeout(() => {
          if (select.toggleMenu) {
            select.toggleMenu()
          }
        }, 50)
      }
    }
  })
  return true
}

// 结束编辑单元格
const finishEdit = async (row, modelId, field, newValue) => {
  editingCell.value = null

  // 获取原始值
  const originalRow = originalData.value.find(r => r.id === row.id)
  const key = `${row.id}_${modelId}_${field}`
  const oldValue = draftBaseline(draftChanges.value.get(key), originalRow?.model_values?.[modelId]?.[field])

  // 检查值是否真正变化
  if (!isValueChanged(oldValue, newValue)) {
    // 值改回原值，删除草稿
    if (draftChanges.value.has(key) || hasPendingDraftCellOperation(row, modelId, field)) {
      await removeDraftChange(row, modelId, field, key)
    }
    return
  }

  await handleCellChange(row, modelId, field, newValue, oldValue)
}

const draftSaveFeedback = reactive({ pending: 0, message: '', lastCell: null, failedCell: null, failures: new Map(), successes: new Map(), sequence: 0 })
const isFeedbackCellScopeCurrent = context => Boolean(context) &&
  (!context.seriesId || selectedSeries.value.includes(context.seriesId)) && isDraftCellScopeCurrent(context)
const refreshSaveFeedback = (context = null) => {
  for (const entries of [draftSaveFeedback.failures, draftSaveFeedback.successes]) {
    for (const [key, cell] of entries) if (!isFeedbackCellScopeCurrent(cell)) entries.delete(key)
  }
  draftSaveFeedback.pending = Array.from(draftCellOperations.values())
    .filter(state => isFeedbackCellScopeCurrent(state.context)).reduce((total, state) => total + state.pending, 0)
  const latest = entries => Array.from(entries.values()).sort((left, right) => right.sequence - left.sequence)[0] || null
  draftSaveFeedback.lastCell = latest(draftSaveFeedback.successes)
  draftSaveFeedback.failedCell = latest(draftSaveFeedback.failures)
  draftSaveFeedback.message = draftSaveFeedback.failures.size
    ? `仍有 ${draftSaveFeedback.failures.size} 处保存或撤销失败，可逐一重试`
    : isFeedbackCellScopeCurrent(context) && context.action === 'undo' ? '已撤销单元格草稿'
    : draftSaveFeedback.lastCell ? '草稿已保存' : ''
}
const undoLastCell = async () => {
  refreshSaveFeedback()
  const cell = draftSaveFeedback.lastCell
  if (!cell || !isDraftCellScopeCurrent(cell)) { ElMessage.warning('操作范围已变化，请在当前单元格上撤销'); return }
  const row = tableData.value.find(row => row.id === cell.row.id)
  if (!row) { ElMessage.warning('该行不在当前筛选中，请清除筛选后撤销'); return }
  await removeDraftChange(row, cell.modelId, cell.field, cell.key)
}
const retryFailedCell = async () => {
  refreshSaveFeedback()
  const cell = draftSaveFeedback.failedCell
  if (!cell || !isDraftCellScopeCurrent(cell)) return
  const row = tableData.value.find(row => row.id === cell.row.id)
  if (!row?.model_values?.[cell.modelId]) { ElMessage.warning('该行不在当前筛选中，请清除筛选后重试'); return }
  if (cell.action === 'undo') { await removeDraftChange(row, cell.modelId, cell.field, cell.key); return }
  if (cell.attemptedValue === undefined) return
  row.model_values[cell.modelId][cell.field] = cell.attemptedValue
  await handleCellChange(row, cell.modelId, cell.field, cell.attemptedValue)
}

// 同一单元格的保存和撤销必须按用户操作顺序到达后端。
const draftCellOperations = new Map()
const getDraftCellOperationKey = (row, modelId, field) => {
  const seriesId = findSeriesIdByModelId(modelId)
  const batchId = seriesId ? draftBatchMap.value.get(seriesId) : undefined
  return `${seriesId}_${batchId}_${row.id}_${modelId}_${field}`
}

const hasPendingDraftCellOperation = (row, modelId, field) => {
  const state = draftCellOperations.get(getDraftCellOperationKey(row, modelId, field))
  return Boolean(state?.pending)
}

const enqueueDraftCellOperation = (context, operation) => {
  let state = draftCellOperations.get(context.operationKey)
  if (!state) {
    state = {
      tail: Promise.resolve(),
      generation: 0,
      pending: 0,
      serverHasDraft: draftChanges.value.has(context.key)
    }
    draftCellOperations.set(context.operationKey, state)
  }

  const generation = ++state.generation
  context.sequence = ++draftSaveFeedback.sequence
  state.pending++
  state.context = context
  refreshSaveFeedback()
  const isLatest = () => draftCellOperations.get(context.operationKey) === state && state.generation === generation
  const result = state.tail.then(() => operation(isLatest, state))
  state.tail = result.catch(() => undefined)
  return result.then(success => {
    if (isLatest() && isFeedbackCellScopeCurrent(context)) {
      if (success) {
        draftSaveFeedback.failures.delete(context.operationKey)
        if (context.action === 'undo') draftSaveFeedback.successes.delete(context.operationKey)
        else draftSaveFeedback.successes.set(context.operationKey, { ...context })
      } else {
        draftSaveFeedback.failures.set(context.operationKey, { ...context })
      }
      refreshSaveFeedback(context)
    }
    return success
  }).finally(() => {
    const latestOutcome = isLatest() && isFeedbackCellScopeCurrent(context) ? context : null
    state.pending--
    if (state.pending === 0 && draftCellOperations.get(context.operationKey) === state) {
      draftCellOperations.delete(context.operationKey)
    }
    refreshSaveFeedback(latestOutcome)
  })
}

const captureDraftCellContext = (row, modelId, field, key) => {
  const seriesId = findSeriesIdByModelId(modelId)
  return {
    row,
    modelId,
    field,
    key,
    seriesId,
    batchId: seriesId ? draftBatchMap.value.get(seriesId) : undefined,
    originalRow: originalDataMap.value.get(row.id),
    operationKey: getDraftCellOperationKey(row, modelId, field)
  }
}

const isDraftCellScopeCurrent = (context) => {
  if (context.seriesId && findSeriesIdByModelId(context.modelId) !== context.seriesId) return false
  if (context.batchId !== undefined && draftBatchMap.value.get(context.seriesId) !== context.batchId) return false
  return true
}

const isDraftCellContextCurrent = (context) => {
  return tableData.value.includes(context.row) && isDraftCellScopeCurrent(context)
}

const reconcileCurrentDraftCell = (context, value, isLatest = () => true) => {
  if (!isLatest() || !isDraftCellScopeCurrent(context)) return
  const currentRow = tableData.value.find(row => row.id === context.row.id)
  if (currentRow?.model_values?.[context.modelId]) {
    currentRow.model_values[context.modelId][context.field] = value
  }
}

const restoreWorkingCell = (context, isLatest = () => true) => {
  if (!isLatest() || !isDraftCellContextCurrent(context)) return
  const fallback = context.originalRow?.model_values?.[context.modelId]?.[context.field]
  const value = draftWorkingValue(draftChanges.value.get(context.key), fallback)
  if (context.row.model_values?.[context.modelId]) {
    context.row.model_values[context.modelId][context.field] = value
  }
}

// 删除草稿变更
const removeDraftChange = (row, modelId, field, key) => {
  const context = captureDraftCellContext(row, modelId, field, key)
  context.action = 'undo'
  if (!context.seriesId || context.batchId === undefined) {
    restoreWorkingCell(context)
    ElMessage.error('草稿批次未准备好，请重新加载后编辑')
    return Promise.resolve(false)
  }

  return enqueueDraftCellOperation(context, async (isLatest, state) => {
    const change = draftChanges.value.get(key)
    if (!state.serverHasDraft) {
      restoreWorkingCell(context, isLatest)
      return true
    }

    try {
      await deleteDraftByKey(context.batchId, row.id, modelId, field)
      state.serverHasDraft = false
      if (isDraftCellScopeCurrent(context)) {
        const baselineValue = draftBaseline(change, context.originalRow?.model_values?.[modelId]?.[field])
        if (context.originalRow?.model_values?.[modelId]) {
          context.originalRow.model_values[modelId][field] = baselineValue
        }
        const currentOriginalRow = originalDataMap.value.get(row.id)
        if (currentOriginalRow?.model_values?.[modelId]) {
          currentOriginalRow.model_values[modelId][field] = baselineValue
        }
        draftChanges.value.delete(key)
        Object.assign(draftStats, updateDraftStats(draftStats, change?.changeType, null))
        reconcileCurrentDraftCell(context, baselineValue, isLatest)
      }
      return true
    } catch (error) {
      restoreWorkingCell(context, isLatest)
      console.error('删除草稿失败:', error)
      if (isLatest() && isFeedbackCellScopeCurrent(context)) ElMessage.error('撤销变更失败: ' + (error.response?.data?.detail || '请重试'))
      return false
    }
  })
}

// 单元格变更
const handleCellChange = (row, modelId, field, newValue, oldValue, frozenContext = null) => {
  const key = `${row.id}_${modelId}_${field}`
  const context = frozenContext || captureDraftCellContext(row, modelId, field, key)
  if (!context.seriesId || context.batchId === undefined) {
    restoreWorkingCell(context)
    ElMessage.error('草稿批次未准备好，请重新加载后编辑')
    return Promise.resolve(false)
  }

  context.attemptedValue = newValue
  return enqueueDraftCellOperation(context, async (isLatest, state) => {
    const originalValue = context.originalRow?.model_values?.[modelId]?.[field]
    oldValue = draftBaseline(draftChanges.value.get(key), originalValue !== undefined ? originalValue : oldValue)

    try {
      const isValueEmpty = (v) => !v || v === '-' || v === 'N/A' || v === '未定义' || v === ''
      const changeType = isValueEmpty(oldValue) ? 'create' : 'update'

      const res = await createDraft({
        series_id: context.seriesId,
        batch_id: context.batchId,
        change_type: changeType,
        item_id: row.id,
        model_id: modelId,
        field_name: field,
        new_value: newValue,
        old_value: oldValue
      })

      state.serverHasDraft = true
      if (isDraftCellScopeCurrent(context)) {
        // 记录变更用于UI高亮
        const previousType = draftChanges.value.get(key)?.changeType
        draftChanges.value.set(key, {
          oldValue,
          newValue,
          draftId: res.draft_id,
          changeType
        })
        Object.assign(draftStats, updateDraftStats(draftStats, previousType, changeType))
        reconcileCurrentDraftCell(context, newValue, isLatest)
      }
      return true
    } catch (error) {
      restoreWorkingCell(context, isLatest)
      console.error('保存草稿失败:', error)
      if (isLatest() && isFeedbackCellScopeCurrent(context)) ElMessage.error('保存失败: ' + (error.response?.data?.detail || '请重试'))
      return false
    }
  })
}

// 多文件上传处理（自定义 http-request）
const handleMultiFileUpload = async (options) => {
  const request = ++previewRequest
  // Element Plus http-request 模式下，options.file 是包装对象，需要用 .raw 获取原始文件
  const rawFile = options.file.raw || options.file
  pendingFiles.push(rawFile)

  // 延迟处理，确保所有文件都已添加
  clearTimeout(processTimer)
  processTimer = setTimeout(async () => {
    if (pendingFiles.length === 0) return

    const validFiles = pendingFiles.filter(f => f.name.endsWith('.xlsx') || f.name.endsWith('.xls'))

    pendingFiles = []

    if (validFiles.length === 0) {
      if (request === previewRequest) ElMessage.warning('请选择 Excel 文件 (.xlsx, .xls)')
      return
    }

    // 预览所有文件
    try {
      const formData = new FormData()
      for (const file of validFiles) formData.append('files', file)
      const batch = await previewImportBatch(formData)
      if (request !== previewRequest) return
      const allPreviewData = (batch.files || []).map(res => ({
        filename: res.filename, series: res.series || [], impact: res.impact,
        summary: { totalModels: res.summary?.total_models || 0, totalItems: res.summary?.total_items || 0,
          categories: res.summary?.categories || [], totalRows: res.total_rows || 0 }, raw: res
      }))
      if (allPreviewData.length !== validFiles.length) throw new Error('预览文件数量不一致，请重新选择文件')

      // 合并预览数据
      const nextPreviewData = {
        files: allPreviewData,
        impact: batch.impact,
        totalFiles: allPreviewData.length,
        totalModels: allPreviewData.reduce((sum, d) => sum + d.summary.totalModels, 0),
        totalItems: allPreviewData.reduce((sum, d) => sum + d.summary.totalItems, 0),
        allCategories: [...new Set(allPreviewData.flatMap(d => d.summary.categories))]
      }

      if (request !== previewRequest) return
      previewFiles.value = [...validFiles]
      previewData.value = nextPreviewData
      committedPreviewRequest = request
      previewDialogVisible.value = true
    } catch (error) {
      if (request !== previewRequest) return
      console.error('预览失败:', error)
      ElMessage.error('文件解析失败: ' + (error.response?.data?.detail || '未知错误'))
    }
  }, 100)
}

// 确认导入（支持多文件）
const confirmImport = async () => {
  if (importing.value) return
  const request = committedPreviewRequest
  const files = [...previewFiles.value]
  const preview = previewData.value
  if (files.length === 0) return
  if (!preview || request !== previewRequest) {
    ElMessage.warning('预览已更新，请确认最新文件后再导入')
    return
  }

  importing.value = true
  importProgress.value = { current: 0, total: files.length }

  const results = []
  let hasError = false

  for (let i = 0; i < files.length; i++) {
    const file = files[i]
    importProgress.value.current = i + 1

    const formData = new FormData()
    formData.append('file', file)

    try {
      const res = await importExcel(formData)
      results.push({ filename: file.name, success: true, message: res.message })
    } catch (error) {
      console.error('导入失败:', error)
      results.push({ filename: file.name, success: false, message: error.response?.data?.detail || '导入失败' })
      hasError = true
    }
  }

  importing.value = false
  if (request === previewRequest && committedPreviewRequest === request && previewData.value === preview) {
    previewDialogVisible.value = false
  }

  // 显示导入结果
  const successCount = results.filter(r => r.success).length
  if (hasError) {
    const failedFiles = results.filter(r => !r.success).map(r => r.filename).join(', ')
    ElMessage.warning(`导入完成：成功 ${successCount} 个，失败 ${results.length - successCount} 个 (${failedFiles})`)
  } else {
    ElMessage.success(`${successCount} 个文件全部导入成功`)
  }

  // 重新加载数据（包含表格数据、草稿状态和枚举值）
  currentPage.value = 1  // 重置到第1页
  await loadSeries()
  await loadModels()
  await loadEnumValues()
}

// 导出Excel - 所见即所得，仅导出当前筛选视图的内容
const handleExport = async () => {
  if (selectedSeries.value.length === 0) {
    ElMessage.warning('请先选择产品系列')
    return
  }

  // 仅导出第一个选中的系列（当前视图对应的系列）
  const seriesId = selectedSeries.value[0]
  const seriesName = seriesList.value.find(s => s.id === seriesId)?.name || ''

  try {
    // 使用 filteredTableData（已应用所有前端筛选：分类、搜索、草稿、差异、空行隐藏）
    const visibleData = filteredTableData.value
    if (visibleData.length === 0) {
      ElMessage.warning('当前筛选视图没有数据可导出')
      return
    }

    ElMessage.info(`正在导出 ${visibleData.length} 行数据，请稍候...`)

    // 提取筛选后的行 ID
    const visibleItemIds = visibleData.map(r => r.id).filter(id => id != null)

    // 获取该系列当前选中的机型
    const seriesModelIds = []
    for (const [mid, m] of allModelsMap.value) {
      if (m.seriesId === seriesId && selectedModels.value.includes(mid)) {
        seriesModelIds.push(mid)
      }
    }

    // 传入筛选后的行 ID、机型 ID 和可见列，后端按此生成 Excel
    const exportParams = { item_ids: visibleItemIds.join(',') }
    if (seriesModelIds.length > 0) {
      exportParams.model_ids = seriesModelIds.join(',')
    }
    // 传入当前可见的配置列字段（最终配置/当前配置/选型类别/研发状态）
    const visibleFields = visibleConfigFields.value
    if (visibleFields.length > 0) {
      exportParams.visible_fields = visibleFields.join(',')
    }
    // 传入草稿变更记录，使导出包含变更前后对比
    const relatedDraftChanges = {}
    const modelIdSet = new Set(seriesModelIds)
    const itemIdSet = new Set(visibleItemIds)
    for (const [key, change] of draftChanges.value.entries()) {
      const parts = key.split('_')
      const rowId = parseInt(parts[0])
      const modelId = parseInt(parts[1])
      if (itemIdSet.has(rowId) && modelIdSet.has(modelId)) {
        relatedDraftChanges[key] = { oldValue: change.oldValue, newValue: change.newValue, changeType: change.changeType }
      }
    }
    if (Object.keys(relatedDraftChanges).length > 0) {
      exportParams.draft_changes = JSON.stringify(relatedDraftChanges)
    }
    // 传入删除项的快照值和新增项标识
    const deletedItems = {}
    for (const [itemId, modelSet] of deletedItemModelMap.value.entries()) {
      if (!itemIdSet.has(itemId)) continue
      for (const modelId of modelSet) {
        if (modelIdSet.has(modelId)) {
          const snapKey = `${itemId}_${modelId}`
          const snapVals = draftDeleteValues.value.get(snapKey)
          deletedItems[snapKey] = snapVals ? { ...snapVals } : {}
        }
      }
    }
    if (Object.keys(deletedItems).length > 0) {
      exportParams.deleted_items = JSON.stringify(deletedItems)
    }
    const newItems = {}
    for (const [itemId, modelSet] of newItemModelMap.value.entries()) {
      if (!itemIdSet.has(itemId)) continue
      for (const modelId of modelSet) {
        if (modelIdSet.has(modelId)) {
          newItems[`${itemId}_${modelId}`] = true
        }
      }
    }
    if (Object.keys(newItems).length > 0) {
      exportParams.new_items = JSON.stringify(newItems)
    }

    const res = await exportExcel(seriesId, exportParams)
    const modelNamesList = seriesModelIds.map(id => {
      const m = allModelsMap.value.get(id)
      return m ? m.name : ''
    }).filter(Boolean)
    const mergedModelNames = mergeModelNames(modelNamesList)

    const categoryNames = selectedCategories.value.map(c => c.replace(/\s+/g, '')).join('-')

    let suffix = seriesName
    if (mergedModelNames) {
      suffix += `_${mergedModelNames}`
    }
    if (categoryNames) {
      suffix += `_${categoryNames}`
    }

    const filename = `Export_SpecExcel_${suffix}.xlsx`

    const url = window.URL.createObjectURL(new Blob([res]))
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', filename)
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)

    ElMessage.success(`导出成功：${seriesName}`)
  } catch (error) {
    console.error('导出失败:', error)
    ElMessage.error('导出失败')
  }
}

// 合并型号名称（相同前缀合并，如 VINNO 5, VINNO 3, VINNO 6 -> VINNO 5/3/6）
const mergeModelNames = (modelNames) => {
  if (!modelNames || modelNames.length === 0) return ''
  if (modelNames.length === 1) return modelNames[0]

  // 提取公共前缀
  const getPrefix = (name) => {
    const match = name.match(/^([a-zA-Z]+\s*)/)
    return match ? match[1].trim() : name
  }

  // 提取数字部分
  const getNumber = (name) => {
    const match = name.match(/(\d+)/)
    return match ? match[1] : name
  }

  // 按前缀分组
  const groups = {}
  modelNames.forEach(name => {
    const prefix = getPrefix(name)
    const number = getNumber(name)
    if (!groups[prefix]) groups[prefix] = []
    groups[prefix].push(number)
  })

  // 合并各组
  const result = []
  for (const [prefix, numbers] of Object.entries(groups)) {
    if (numbers.length === 1) {
      result.push(`${prefix} ${numbers[0]}`)
    } else {
      result.push(`${prefix} ${numbers.join('/')}`)
    }
  }

  return result.join('-')
}

// 批量修改
const handleBatchEdit = () => {
  batchEditForm.field = ''
  batchEditForm.value = ''
  batchEditForm.scope = 'selected'
  batchEditResult.value = null
  batchEditDialogVisible.value = true
}

const confirmBatchEdit = async () => {
  if (batchEditSubmitting.value) return
  const { field, value, scope } = batchEditForm
  if (!field || !value) { ElMessage.warning('请选择修改字段和值'); return }
  const rows = [...(scope === 'selected' ? selectedRows.value : filteredTableData.value)]
  const models = [...selectedModels.value]
  if (!rows.length || !models.length) { ElMessage.warning('没有要修改的数据或机型'); return }
  const targets = rows.flatMap(row => models.map(modelId => ({
    row, modelId, oldValue: row.model_values[modelId]?.[field],
    context: captureDraftCellContext(row, modelId, field, `${row.id}_${modelId}_${field}`)
  })))
  batchEditSubmitting.value = true
  batchEditResult.value = null
  const result = { success: 0, failed: 0, unchanged: 0, missing: 0 }
  try {
    for (const { row, modelId, oldValue, context } of targets) {
      if (!row.model_values[modelId]) { result.missing++; continue }
      if (!isValueChanged(oldValue, value)) { result.unchanged++; continue }
      row.model_values[modelId][field] = value
      try {
        if (await handleCellChange(row, modelId, field, value, oldValue, context)) result.success++
        else result.failed++
      } catch (error) { result.failed++; console.error('批量修改单元格失败:', error) }
    }
    batchEditResult.value = result
    if (result.failed) ElMessage.warning(`已保存 ${result.success} 处，${result.failed} 处失败；可重新确认修改以重试`)
    else ElMessage.success(`已保存 ${result.success} 处，跳过 ${result.unchanged + result.missing} 处`)
  } finally { batchEditSubmitting.value = false }
}

// 创建版本
const handleCreateVersion = () => {
  versionForm.version_number = ''
  versionForm.version_name = ''
  versionForm.description = ''
  versionDialogVisible.value = true
}

const confirmCreateVersion = async () => {
  if (selectedSeries.value.length === 0) {
    ElMessage.warning('请先选择产品系列')
    return
  }

  try {
    await Promise.all(selectedSeries.value.map(seriesId =>
      createVersion({
        series_id: seriesId,
        version_number: versionForm.version_number || undefined,
        version_name: versionForm.version_name || undefined,
        description: versionForm.description || undefined
      })
    ))

    ElMessage.success(`${selectedSeries.value.length} 个系列版本创建成功，请前往"版本历史"页面查看`)
    versionDialogVisible.value = false

    // 清空表单
    versionForm.version_number = ''
    versionForm.version_name = ''
    versionForm.description = ''
  } catch (error) {
    console.error('创建版本失败:', error)
    ElMessage.error('创建版本失败: ' + (error.response?.data?.detail || '未知错误'))
  }
}

// 提交草稿
// 切换草稿筛选（使用共享 composable）
const toggleDraftFilter = (type) => {
  _toggleDraftFilter(type)
  currentPage.value = 1
}
const clearDraftFilter = () => {
  _clearDraftFilter()
  currentPage.value = 1
}

// 切换差异筛选
const toggleDiffFilter = () => {
  showDiffOnly.value = !showDiffOnly.value
  currentPage.value = 1
}
const onDiffFilterChange = () => {
  currentPage.value = 1
}

// 批量完成研发状态 - 将所有未完成的研发状态设为"已完成"
const handleBatchCompleteRdStatus = async () => {
  if (draftBatchMap.value.size === 0) {
    ElMessage.warning('请先创建草稿批次')
    return
  }

  try {
    await ElMessageBox.confirm(
      '确定将所有未完成的研发状态设为"已完成"？此操作将创建草稿变更。',
      '批量完成研发状态',
      { confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }

  let count = 0
  const promises = []

  for (const row of tableData.value) {
    for (const modelId of selectedModels.value) {
      const currentValue = row.model_values[modelId]?.rd_status
      const isIncomplete = currentValue && currentValue !== '已完成' && currentValue !== 'N/A' && currentValue !== '-'
      if (isIncomplete) {
        const oldValue = currentValue
        row.model_values[modelId].rd_status = '已完成'
        promises.push(handleCellChange(row, modelId, 'rd_status', '已完成', oldValue))
        count++
      }
    }
  }

  if (count === 0) {
    ElMessage.info('没有未完成的研发状态')
    return
  }

  try {
    const successCount = (await Promise.all(promises)).filter(Boolean).length
    if (successCount > 0) ElMessage.success(`已完成 ${successCount} 项研发状态设置为"已完成"`)
  } catch (error) {
    console.error('批量完成研发状态失败:', error)
    ElMessage.error('部分操作失败，请刷新后重试')
  }
}

// 显示右键菜单
const showContextMenu = (event, row, modelId, field) => {
  // 关闭之前的菜单
  contextMenu.visible = false

  // 设置菜单位置（相对于视口）
  const x = event.clientX
  const y = event.clientY

  // 确保菜单不超出视口边界
  const menuWidth = 220
  const menuHeight = 180
  const viewportWidth = window.innerWidth
  const viewportHeight = window.innerHeight

  contextMenu.x = Math.min(x, viewportWidth - menuWidth)
  contextMenu.y = Math.min(y, viewportHeight - menuHeight)
  contextMenu.row = row
  contextMenu.modelId = modelId
  contextMenu.field = field
  contextMenu.visible = true

  // 点击其他地方关闭菜单
  setTimeout(() => {
    document.addEventListener('click', hideContextMenu, { once: true })
  }, 0)
}

// 隐藏右键菜单
const hideContextMenu = () => {
  contextMenu.visible = false
}

// 处理应用到所有机型
const handleApplyToAllModels = (scope) => {
  hideContextMenu()

  if (!contextMenu.row || !contextMenu.modelId || !contextMenu.field) return

  // 检查是否至少选择了2个机型（整行模式需要）
  if (scope === 'row' && selectedModels.value.length < 2) {
    ElMessage.warning('整行应用需要至少选择 2 个机型，请先在顶部选择多个型号')
    return
  }

  const row = contextMenu.row
  const modelId = contextMenu.modelId
  const field = contextMenu.field

  // 获取当前值
  const value = row.model_values[modelId]?.[field]

  // 设置对话框数据
  applyToAllDialog.row = row
  applyToAllDialog.modelId = modelId
  applyToAllDialog.field = field
  applyToAllDialog.scope = scope
  applyToAllDialog.value = value

  // 设置字段显示名
  const fieldNames = {
    final_config: '最终配置',
    current_config: '当前配置',
    selection_config: '选型类别',
    rd_status: '研发状态'
  }
  applyToAllDialog.fieldName = scope === 'field'
    ? fieldNames[field]
    : `${fieldNames[field]} 等4个字段`

  applyToAllDialog.visible = true
}

// 确认应用到所有机型
const confirmApplyToAll = async () => {
  if (!applyToAllDialog.row || !applyToAllDialog.field) {
    applyToAllDialog.visible = false
    return
  }

  const row = applyToAllDialog.row
  const field = applyToAllDialog.field
  const value = applyToAllDialog.value
  const scope = applyToAllDialog.scope

  try {
    const promises = []

    if (scope === 'field') {
      // 仅应用到当前字段
      for (const modelId of selectedModels.value) {
        if (row.model_values[modelId]) {
          const oldValue = row.model_values[modelId][field]
          if (isValueChanged(oldValue, value)) {
            row.model_values[modelId][field] = value
            // 并行发送请求，不等待
            promises.push(handleCellChange(row, modelId, field, value, oldValue))
          }
        }
      }
    } else if (scope === 'row') {
      // 应用到整行（所有4个字段）
      const fields = ['final_config', 'current_config', 'selection_config', 'rd_status']
      const sourceModelId = applyToAllDialog.modelId

      for (const modelId of selectedModels.value) {
        if (row.model_values[modelId] && modelId !== sourceModelId) {
          for (const f of fields) {
            const sourceValue = row.model_values[sourceModelId]?.[f]
            const oldValue = row.model_values[modelId][f]
            if (isValueChanged(oldValue, sourceValue)) {
              row.model_values[modelId][f] = sourceValue
              // 并行发送请求，不等待
              promises.push(handleCellChange(row, modelId, f, sourceValue, oldValue))
            }
          }
        }
      }
    }

    // 并行执行所有请求
    if (promises.length > 0) {
      const successCount = (await Promise.all(promises)).filter(Boolean).length
      if (successCount > 0) ElMessage.success(`已应用到 ${successCount} 处`)
    } else {
      ElMessage.info('没有需要更新的内容')
    }

    applyToAllDialog.visible = false
  } catch (error) {
    console.error('应用失败:', error)
    ElMessage.error('应用失败')
  }
}

// 当前值应用到该行所有字段（仅当前机型）
const handleApplyValueToAllFields = async () => {
  hideContextMenu()

  if (!contextMenu.row || !contextMenu.modelId || !contextMenu.field) return

  const row = contextMenu.row
  const modelId = contextMenu.modelId
  const sourceField = contextMenu.field
  const value = row.model_values[modelId]?.[sourceField]

  if (!value) {
    ElMessage.warning('当前单元格为空，无法应用')
    return
  }

  const fields = ['final_config', 'current_config', 'selection_config', 'rd_status']
  const promises = []

  try {
    for (const field of fields) {
      if (field === sourceField) continue // 跳过源字段

      const oldValue = row.model_values[modelId][field]
      if (isValueChanged(oldValue, value)) {
        row.model_values[modelId][field] = value
        promises.push(handleCellChange(row, modelId, field, value, oldValue))
      }
    }

    if (promises.length > 0) {
      const successCount = (await Promise.all(promises)).filter(Boolean).length
      if (successCount > 0) ElMessage.success(`已将值应用到该机型其他 ${successCount} 个字段`)
    } else {
      ElMessage.info('其他字段已经是相同值')
    }
  } catch (error) {
    console.error('应用失败:', error)
    ElMessage.error('应用失败')
  }
}

// 处理清空单元格
const handleClearCell = async () => {
  hideContextMenu()

  if (!contextMenu.row || !contextMenu.modelId || !contextMenu.field) return

  const row = contextMenu.row
  const modelId = contextMenu.modelId
  const field = contextMenu.field
  const oldValue = row.model_values[modelId]?.[field]

  if (!oldValue) return // 已经是空的

  try {
    row.model_values[modelId][field] = null
    if (await handleCellChange(row, modelId, field, null, oldValue)) ElMessage.success('已清空')
  } catch (error) {
    console.error('清空失败:', error)
    ElMessage.error('清空失败')
  }
}

// 处理复制整行配置
const handleCopyRowConfig = () => {
  hideContextMenu()

  if (!contextMenu.row) return

  // 复制当前行的所有配置
  const row = contextMenu.row
  const config = {}

  for (const modelId of selectedModels.value) {
    if (row.model_values[modelId]) {
      config[modelId] = {
        final_config: row.model_values[modelId].final_config,
        current_config: row.model_values[modelId].current_config,
        selection_config: row.model_values[modelId].selection_config,
        rd_status: row.model_values[modelId].rd_status
      }
    }
  }

  copiedRowConfig.value = {
    sourceRowId: row.id,
    sourceRowName: row.rd_name || row.ipn,
    config: config
  }

  // 显示粘贴对话框
  pasteRowDialog.sourceRow = row
  pasteRowDialog.targetRowId = null
  pasteRowDialog.visible = true
}

// 查看该行差异
const handleViewRowDiff = () => {
  hideContextMenu()

  if (!contextMenu.row) return

  rowDiffDialog.row = contextMenu.row
  rowDiffDialog.visible = true
}

// 获取行差异对比数据
const getRowDiffData = (row) => {
  if (!row || !row.model_values) return []

  const data = []
  const fieldValues = {
    final_config: [],
    current_config: [],
    selection_config: [],
    rd_status: []
  }

  // 收集所有值
  for (const modelId of selectedModels.value) {
    const values = row.model_values[modelId]
    if (values) {
      const modelName = getModelName(modelId)
      data.push({
        modelId,
        modelName,
        final_config: values.final_config,
        current_config: values.current_config,
        selection_config: values.selection_config,
        rd_status: values.rd_status
      })

      // 收集各字段的值
      fieldValues.final_config.push(values.final_config)
      fieldValues.current_config.push(values.current_config)
      fieldValues.selection_config.push(values.selection_config)
      fieldValues.rd_status.push(values.rd_status)
    }
  }

  // 判断每个字段是否有差异
  const hasDiff = (values) => {
    const normalized = values.map(v => v || '-')
    return !normalized.every(v => v === normalized[0])
  }

  const isDiffFinal = hasDiff(fieldValues.final_config)
  const isDiffCurrent = hasDiff(fieldValues.current_config)
  const isDiffSelection = hasDiff(fieldValues.selection_config)
  const isDiffRd = hasDiff(fieldValues.rd_status)

  // 标记差异
  return data.map(item => ({
    ...item,
    isDiffFinal,
    isDiffCurrent,
    isDiffSelection,
    isDiffRd
  }))
}

// 确认粘贴整行配置
const confirmPasteRowConfig = async () => {
  if (!pasteRowDialog.targetRowId || !copiedRowConfig.value) {
    pasteRowDialog.visible = false
    return
  }

  const targetRow = tableData.value.find(r => r.id === pasteRowDialog.targetRowId)
  if (!targetRow) {
    ElMessage.error('目标行不存在')
    return
  }

  const sourceConfig = copiedRowConfig.value.config
  const promises = []

  try {
    for (const modelId of selectedModels.value) {
      if (sourceConfig[modelId] && targetRow.model_values[modelId]) {
        const fields = ['final_config', 'current_config', 'selection_config', 'rd_status']
        for (const field of fields) {
          const newValue = sourceConfig[modelId][field]
          const oldValue = targetRow.model_values[modelId][field]

          if (isValueChanged(oldValue, newValue)) {
            targetRow.model_values[modelId][field] = newValue
            promises.push(handleCellChange(targetRow, modelId, field, newValue, oldValue))
          }
        }
      }
    }

    if (promises.length > 0) {
      const successCount = (await Promise.all(promises)).filter(Boolean).length
      if (successCount > 0) ElMessage.success(`已粘贴到目标行，共修改 ${successCount} 处`)
    }
    pasteRowDialog.visible = false
    copiedRowConfig.value = null
  } catch (error) {
    console.error('粘贴失败:', error)
    ElMessage.error('粘贴失败')
  }
}

const fieldLabels = { final_config: '最终配置', current_config: '当前配置', selection_config: '选型类别', rd_status: '研发状态', rd_name: '研发名称', v_code: 'V代码', ipn: 'IPN号', zh_desc: '中文描述', en_desc: '英文描述', category: '分类', row_index: '排序位置' }
const formatSubmissionValue = (draft, side) => {
  if (draft.field_name) return draft[`${side}_value`] || '-'
  const values = draft[`${side}_values`]
  if (!values) return '配置值未提供，请刷新范围'
  return ['final_config', 'current_config', 'selection_config', 'rd_status']
    .map(field => `${fieldLabels[field]}：${values[field] || '-'}`).join('；')
}
const captureVisibleSubmissionScope = () => ({
  itemIds: new Set(paginatedTableData.value.map(row => row.id)),
  modelIds: new Set(selectedModels.value), fields: new Set(visibleConfigFields.value)
})
const describeSubmission = (review, visible) => ({
  ...review,
  hidden_changes: review.drafts.filter(draft => !visible.itemIds.has(draft.item_id) ||
    (draft.model_id != null && !visible.modelIds.has(draft.model_id)) ||
    (draft.field_name ? !visible.fields.has(draft.field_name) : ['final_config', 'current_config', 'selection_config', 'rd_status'].some(field => !visible.fields.has(field)))).length
})
const waitForDraftSaves = async () => {
  await Promise.all(Array.from(draftCellOperations.values(), state => state.tail))
}
const handleSubmitDraft = async (itemIds = null, modelIds = null) => {
  if (submitSubmitting.value || submitPreviewLoading.value || batchSubmitDialog.visible) return
  submitForm.version_number = ''; submitForm.description = ''
  submitForm.item_ids = itemIds == null ? null : new Set(itemIds)
  submitForm.model_ids = modelIds == null ? null : new Set(modelIds)
  const params = {}
  if (itemIds != null) params.item_ids = Array.from(itemIds)
  if (modelIds != null) params.model_ids = Array.from(modelIds)
  submitScope.value = { entries: Array.from(draftBatchMap.value.entries()), params, visible: captureVisibleSubmissionScope() }
  submitResults.value = []
  submitDialogVisible.value = true
  await refreshSubmitPreview()
}
const refreshSubmitPreview = async () => {
  if (submitSubmitting.value || !submitScope.value) return
  const request = ++submitPreviewRequest
  const scope = submitScope.value
  submitPreviews.value = []; submitPreviewError.value = ''; submitPreviewLoading.value = true
  try {
    await waitForDraftSaves()
    const reviews = await Promise.all(scope.entries.map(async ([, batchId]) =>
      describeSubmission(await previewDraftSubmission(batchId, scope.params), scope.visible)))
    if (request !== submitPreviewRequest || scope !== submitScope.value) return
    submitPreviews.value = reviews
  } catch (error) {
    if (request === submitPreviewRequest) submitPreviewError.value = '无法核验提交范围：' + (error.response?.data?.detail || '请检查连接后刷新范围')
  } finally { if (request === submitPreviewRequest) submitPreviewLoading.value = false }
}
const confirmSubmitDraft = async () => {
  if (submitSubmitting.value || submitPreviewLoading.value || submitPreviewError.value || !submitScope.value) return
  const reviews = submitPreviews.value.filter(review => review.total_changes > 0)
  if (!reviews.length) { ElMessage.info('当前范围没有要提交的变更'); return }
  const params = { ...submitScope.value.params, version_number: submitForm.version_number || undefined, description: submitForm.description || undefined }
  submitSubmitting.value = true
  submitResults.value = []
  try {
    const outcomes = await Promise.all(reviews.map(async review => {
      try {
        const res = await submitDraftBatch(review.batch_id, { ...params, expected_signature: review.signature })
        return { seriesName: review.series_name, success: true, message: `已发布 ${res.changes ?? review.total_changes} 条变更` }
      } catch (error) {
        return { seriesName: review.series_name, success: false, message: error.response?.data?.detail || '连接失败，请重试' }
      }
    }))
    submitResults.value = outcomes
    const succeeded = outcomes.filter(outcome => outcome.success).length
    if (succeeded) {
      ElMessage.success(`成功发布 ${succeeded} 个系列`)
      await loadData(); await initDraft()
    }
    if (outcomes.every(outcome => outcome.success)) submitDialogVisible.value = false
    else {
      submitPreviewError.value = '部分系列未发布，请核对结果并刷新范围后重试。已成功发布的系列不会重复提交。'
      ElMessage.warning(submitPreviewError.value)
      submitScope.value = { ...submitScope.value, entries: Array.from(draftBatchMap.value.entries()) }
    }
  } finally { submitSubmitting.value = false }
}

// 提交选中机型
const handleSubmitModel = () => {
  if (selectedDraftModelIds.value.size === 0) {
    ElMessage.warning('请先选择要提交的机型')
    return
  }
  handleSubmitDraft(null, selectedDraftModelIds.value)
}

// 切换草稿项选中状态
const toggleDraftItem = (itemId, checked) => {
  const newSet = new Set(selectedDraftItemIds.value)
  if (checked) {
    newSet.add(itemId)
  } else {
    newSet.delete(itemId)
  }
  selectedDraftItemIds.value = newSet
}

// 全选/取消全选
const toggleSelectAll = (checked) => {
  if (checked) {
    selectedDraftItemIds.value = new Set(draftItems.value.map(i => i.itemId))
  } else {
    selectedDraftItemIds.value = new Set()
  }
}

// 切换机型筛选状态
const toggleDraftModel = (modelId) => {
  const newSet = new Set(selectedDraftModelIds.value)
  if (newSet.has(modelId)) {
    newSet.delete(modelId)
  } else {
    newSet.add(modelId)
  }
  selectedDraftModelIds.value = newSet
}

// 废弃草稿（废弃所有系列批次）
const handleDiscardDraft = async () => {
  const entries = Array.from(draftBatchMap.value.entries())
  if (entries.length === 0) return

  try {
    await ElMessageBox.confirm('确认废弃所有草稿？此操作不可恢复。', '确认', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    })

    await Promise.all(entries.map(([seriesId, batchId]) => discardDraftBatch(batchId)))
    ElMessage.success('已废弃')

    draftStats.total = 0
    draftStats.create = 0
    draftStats.update = 0
    draftStats.delete = 0
    draftChanges.value.clear()  // 清空变更记录
    draftFilterMode.value = false; draftFilters.value = new Set()  // 清空筛选
    draftExpanded.value = false
    selectedDraftItemIds.value = new Set()
    selectedDraftModelIds.value = new Set()
    draftItemInfo.value = new Map()
    draftBatchMap.value.clear()

    await loadData()  // 重新加载数据
    await initDraft()
  } catch (error) {
    if (error !== 'cancel') {
      console.error('废弃失败:', error)
      ElMessage.error('废弃失败')
    }
  }
}

// 批量操作处理入口
const handleBatchOperation = async (command) => {
  if (command === 'batchDiscard') {
    await handleBatchDiscardDrafts()
  } else if (command === 'batchSubmit') {
    await handleOpenBatchSubmit()
  }
}

// 批量撤销
const handleBatchDiscardDrafts = async () => {
  // 收集选中的系列及其草稿信息
  const batchInfo = []
  for (const seriesId of selectedSeries.value) {
    try {
      const res = await getCurrentDraftBatch(seriesId)
      if (res.exists && res.batch.total_count > 0) {
        const seriesName = seriesList.value.find(s => s.id === seriesId)?.name || `系列 ${seriesId}`
        batchInfo.push({
          seriesId,
          seriesName,
          batchId: res.batch.id,
          changeCount: res.batch.total_count || 0
        })
      }
    } catch (e) {
      // 跳过没有草稿的系列
    }
  }

  if (batchInfo.length === 0) {
    ElMessage.info('没有可撤销的草稿')
    return
  }

  const summaryParts = batchInfo.map(b => `${b.seriesName}(${b.changeCount}项变更)`)
  try {
    await ElMessageBox.confirm(
      `确认撤销以下系列的草稿？数据将回滚到最近一次提交版本。\n${summaryParts.join('、')}`,
      '批量撤销草稿',
      { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' }
    )

    const batchIds = batchInfo.map(b => b.batchId)
    const res = await batchDiscardDrafts({ batch_ids: batchIds })

    const successCount = res.discarded_count || 0
    if (successCount > 0) {
      ElMessage.success(`成功撤销 ${successCount} 个系列的草稿`)
    } else {
      ElMessage.warning('没有成功撤销的草稿')
    }

    // 刷新当前数据
    draftStats.total = 0
    draftStats.create = 0
    draftStats.update = 0
    draftStats.delete = 0
    draftChanges.value.clear()
    draftFilterMode.value = false; draftFilters.value = new Set()
    draftExpanded.value = false
    selectedDraftItemIds.value = new Set()
    selectedDraftModelIds.value = new Set()
    draftItemInfo.value = new Map()

    await loadData()
    await initDraft()
  } catch (error) {
    if (error !== 'cancel') {
      console.error('批量撤销失败:', error)
      ElMessage.error('批量撤销失败')
    }
  }
}

// 打开批量提交对话框
const handleOpenBatchSubmit = async () => {
  if (batchSubmitSubmitting.value || batchSubmitDialog.loading || submitDialogVisible.value) return
  batchSubmitDialog.scope = { seriesIds: [...selectedSeries.value], visible: captureVisibleSubmissionScope() }
  batchSubmitDialog.versionNumber = ''; batchSubmitDialog.description = ''
  batchSubmitDialog.visible = true
  await refreshBatchSubmitPreview()
}
const refreshBatchSubmitPreview = async () => {
  if (batchSubmitSubmitting.value || !batchSubmitDialog.scope) return
  const request = ++batchSubmitPreviewRequest
  const scope = batchSubmitDialog.scope
  batchSubmitDialog.loading = true; batchSubmitDialog.error = ''; batchSubmitDialog.availableBatches = []; batchSubmitDialog.selectedBatchIds = []
  try {
    await waitForDraftSaves()
    const reviews = await Promise.all(scope.seriesIds.map(async seriesId => {
      const res = await getCurrentDraftBatch(seriesId)
      if (!res.exists) return null
      return describeSubmission(await previewDraftSubmission(res.batch.id, {}), scope.visible)
    }))
    if (request !== batchSubmitPreviewRequest || scope !== batchSubmitDialog.scope) return
    batchSubmitDialog.availableBatches = reviews.filter(review => review && review.total_changes > 0)
    batchSubmitDialog.selectedBatchIds = batchSubmitDialog.availableBatches.map(review => review.batch_id)
    if (!batchSubmitDialog.availableBatches.length) ElMessage.info('所选系列没有可提交的草稿')
  } catch (error) {
    if (request === batchSubmitPreviewRequest) batchSubmitDialog.error = '无法核验提交范围：' + (error.response?.data?.detail || '请检查连接后刷新范围')
  } finally { if (request === batchSubmitPreviewRequest) batchSubmitDialog.loading = false }
}
const toggleSubmitAllBatches = checked => {
  batchSubmitDialog.selectedBatchIds = checked ? batchSubmitDialog.availableBatches.map(review => review.batch_id) : []
}
const toggleSubmitBatch = (batchId, checked) => {
  batchSubmitDialog.selectedBatchIds = checked
    ? Array.from(new Set([...batchSubmitDialog.selectedBatchIds, batchId]))
    : batchSubmitDialog.selectedBatchIds.filter(id => id !== batchId)
}
const confirmBatchSubmit = async () => {
  if (batchSubmitSubmitting.value || batchSubmitDialog.loading || batchSubmitDialog.error) return
  const reviews = batchSubmitDialog.availableBatches.filter(review => batchSubmitDialog.selectedBatchIds.includes(review.batch_id))
  if (!reviews.length) { ElMessage.warning('请至少选择一个系列'); return }
  const params = {
    batch_ids: reviews.map(review => review.batch_id),
    expected_signatures: Object.fromEntries(reviews.map(review => [review.batch_id, review.signature])),
    version_number: batchSubmitDialog.versionNumber || undefined, description: batchSubmitDialog.description || undefined
  }
  batchSubmitSubmitting.value = true
  try {
    const res = await batchSubmitDrafts(params)
    batchSubmitResultDialog.results = (res.results || []).map(result => ({
      seriesName: reviews.find(review => review.batch_id === result.batch_id)?.series_name || `系列 ${result.series_id}`,
      versionNumber: result.version_number || '-', changes: result.changes || 0, success: result.success, message: result.message
    }))
    batchSubmitDialog.visible = false; batchSubmitResultDialog.visible = true
    if (res.submitted_count) ElMessage.success(`成功提交 ${res.submitted_count} 个系列`)
    await loadData(); await initDraft()
  } catch (error) {
    batchSubmitDialog.error = '提交失败：' + (error.response?.data?.detail || '请核对结果并刷新范围后重试')
    ElMessage.error(batchSubmitDialog.error)
  } finally { batchSubmitSubmitting.value = false }
}

// 计算表格高度
const calculateTableHeight = () => {
  const table = tableRef.value?.$el
  if (!table || !table.getClientRects().length) return
  const pagination = configPageRef.value?.querySelector('.pagination-wrapper')
  const footerHeight = (pagination?.getBoundingClientRect().height || 32) + 36
  const height = Math.max(180, window.innerHeight - table.getBoundingClientRect().top - footerHeight)
  if (tableMaxHeight.value !== height) tableMaxHeight.value = height
  tableRef.value?.doLayout()
}

// 列筛选方法
const initTempColumns = () => {
  // 打开弹窗时，复制当前配置到临时变量
  Object.assign(tempVisibleColumns, visibleColumns)
  Object.assign(tempFixedColumns, fixedColumns)
}

const applyTempColumns = () => {
  // 关闭弹窗时，应用临时配置
  Object.assign(visibleColumns, tempVisibleColumns)
  Object.assign(fixedColumns, tempFixedColumns)
  // 保存到 localStorage
  saveColumnSettings()
}

const applyTempColumnsAndClose = () => {
  // 检查至少有一列固定（且该列是显示的）
  const hasFixedColumn = Object.keys(tempFixedColumns).some(
    key => tempFixedColumns[key] && tempVisibleColumns[key]
  )

  if (!hasFixedColumn) {
    ElMessage.warning('至少需要固定一列')
    return
  }

  applyTempColumns()
  // 关闭popover
  if (popoverRef.value) {
    popoverRef.value.hide()
  }
}

const resetTempColumns = () => {
  Object.assign(tempVisibleColumns, defaultVisibleColumns)
  Object.assign(tempFixedColumns, defaultFixedColumns)
}

// 清除所有选择
const clearSelection = () => {
  selectedRows.value = []
  selectedCells.value = []
  focusedCell.value = null
  dragSource.value = null
  dragTargetCells.value = []
}

// 拖拽填充开始
const handleDragStart = (e, row, modelId, field) => {
  const value = row.model_values[modelId]?.[field]
  dragSource.value = {
    rowId: row.id,
    modelId,
    field,
    value,
    row
  }
  isDragging.value = true
  e.dataTransfer.effectAllowed = 'copy'
  // 设置拖拽时的视觉效果
  if (e.target) {
    e.target.style.cursor = 'copy'
  }
}

// 拖拽经过单元格
const handleDragOver = (e, row, modelId, field) => {
  e.preventDefault()
  if (!isDragging.value || !dragSource.value) return

  e.dataTransfer.dropEffect = 'copy'

  // 高亮目标区域（从源到当前的所有单元格）
  highlightDragTarget(row.id, modelId, field)
}

// 高亮拖拽目标区域
const highlightDragTarget = (targetRowId, targetModelId, targetField) => {
  if (!dragSource.value) return

  const { rowId: sourceRowId, modelId: sourceModelId, field: sourceField } = dragSource.value

  // 只支持同字段拖拽填充
  if (sourceField !== targetField) return

  // 获取范围
  const rowIds = tableData.value.map(r => r.id)
  const sourceIndex = rowIds.indexOf(sourceRowId)
  const targetIndex = rowIds.indexOf(targetRowId)

  if (sourceIndex < 0 || targetIndex < 0) return

  const startIndex = Math.min(sourceIndex, targetIndex)
  const endIndex = Math.max(sourceIndex, targetIndex)

  // 生成目标单元格列表
  const cells = []
  for (let i = startIndex; i <= endIndex; i++) {
    const row = tableData.value[i]
    if (row && row.model_values[targetModelId]) {
      cells.push({
        rowId: row.id,
        modelId: targetModelId,
        field: targetField
      })
    }
  }

  dragTargetCells.value = cells
}

// 判断是否正在拖拽的目标
const isDragTarget = (rowId, modelId, field) => {
  return dragTargetCells.value.some(
    c => c.rowId === rowId && c.modelId === modelId && c.field === field
  )
}

// 拖拽放置
const handleDrop = async (e, row, modelId, field) => {
  e.preventDefault()
  if (!isDragging.value || !dragSource.value) return

  // 执行拖拽填充
  await performDragFill()

  // 重置拖拽状态
  isDragging.value = false
  dragSource.value = null
  dragTargetCells.value = []
}

// 执行拖拽填充
const performDragFill = async () => {
  if (!dragSource.value || dragTargetCells.value.length === 0) return

  const source = dragSource.value
  const value = source.value
  const promises = []

  try {
    for (const cell of dragTargetCells.value) {
      // 跳过源单元格
      if (cell.rowId === source.rowId && cell.modelId === source.modelId) continue

      const targetRow = tableData.value.find(r => r.id === cell.rowId)
      if (!targetRow || !targetRow.model_values[cell.modelId]) continue

      const oldValue = targetRow.model_values[cell.modelId][cell.field]
      if (isValueChanged(oldValue, value)) {
        targetRow.model_values[cell.modelId][cell.field] = value
        promises.push(handleCellChange(targetRow, cell.modelId, cell.field, value, oldValue))
      }
    }

    if (promises.length > 0) {
      const successCount = (await Promise.all(promises)).filter(Boolean).length
      if (successCount > 0) ElMessage.success(`已填充 ${successCount} 个单元格`)
    }
  } catch (error) {
    console.error('拖拽填充失败:', error)
    ElMessage.error('填充失败')
  }
}

// 拖拽结束
const handleDragEnd = () => {
  isDragging.value = false
  dragSource.value = null
  dragTargetCells.value = []
}

// Phase 3: 键盘导航
const navigateToCell = (currentRowId, currentModelId, currentField, direction) => {
  const visibleFields = ['final_config', 'current_config', 'selection_config', 'rd_status']
    .filter(f => visibleColumns[f])
  const currentFieldIndex = visibleFields.indexOf(currentField)
  const visibleModelIds = selectedModels.value
  const currentModelIndex = visibleModelIds.indexOf(currentModelId)
  const currentRowIndex = tableData.value.findIndex(r => r.id === currentRowId)

  let newRowIndex = currentRowIndex
  let newModelIndex = currentModelIndex
  let newFieldIndex = currentFieldIndex

  switch (direction) {
    case 'up':
      newRowIndex = Math.max(0, currentRowIndex - 1)
      break
    case 'down':
      newRowIndex = Math.min(tableData.value.length - 1, currentRowIndex + 1)
      break
    case 'left':
      if (currentFieldIndex > 0) {
        newFieldIndex = currentFieldIndex - 1
      } else if (currentModelIndex > 0) {
        newModelIndex = currentModelIndex - 1
        newFieldIndex = visibleFields.length - 1
      }
      break
    case 'right':
      if (currentFieldIndex < visibleFields.length - 1) {
        newFieldIndex = currentFieldIndex + 1
      } else if (currentModelIndex < visibleModelIds.length - 1) {
        newModelIndex = currentModelIndex + 1
        newFieldIndex = 0
      }
      break
  }

  const newRow = tableData.value[newRowIndex]
  const newModelId = visibleModelIds[newModelIndex]
  const newField = visibleFields[newFieldIndex]

  if (newRow && newModelId && newField) {
    const newCell = { rowId: newRow.id, modelId: newModelId, field: newField }
    focusedCell.value = newCell

    // 如果按住 Shift，添加到多选
    if (isMultiSelectMode.value) {
      if (!isCellSelected(newRow.id, newModelId, newField)) {
        selectedCells.value.push(newCell)
      }
    } else {
      selectedCells.value = [newCell]
    }

    // 滚动到视野内
    scrollCellIntoView(newRow.id, newModelId, newField)
  }
}

// 滚动单元格到视野内
const scrollCellIntoView = (rowId, modelId, field) => {
  // 使用 nextTick 等待 DOM 更新
  nextTick(() => {
    const cell = document.querySelector(`[data-cell="${rowId}-${modelId}-${field}"]`)
    if (cell) {
      cell.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' })
    }
  })
}

// Ctrl+A 全选
const selectAllVisibleCells = () => {
  if (!tableData.value.length || !selectedModels.value.length) return

  const visibleFields = ['final_config', 'current_config', 'selection_config', 'rd_status']
    .filter(f => visibleColumns[f])

  const cells = []
  for (const row of tableData.value) {
    for (const modelId of selectedModels.value) {
      for (const field of visibleFields) {
        if (row.model_values[modelId]) {
          cells.push({ rowId: row.id, modelId, field })
        }
      }
    }
  }

  selectedCells.value = cells
  ElMessage.success(`已选择 ${cells.length} 个单元格`)
}

// 更新单元格点击处理，设置焦点
const handleCellClick = (e, row, modelId, field) => {
  // 如果是右键点击，不处理多选，但设置焦点
  if (e.button === 2) {
    focusedCell.value = { rowId: row.id, modelId, field }
    return
  }

  const cellData = { rowId: row.id, modelId, field }
  focusedCell.value = cellData

  if (isMultiSelectMode.value) {
    // Ctrl+点击：切换选中状态
    const index = selectedCells.value.findIndex(
      c => c.rowId === row.id && c.modelId === modelId && c.field === field
    )
    if (index >= 0) {
      selectedCells.value.splice(index, 1)
    } else {
      selectedCells.value.push(cellData)
    }
  } else {
    // 普通点击：清除其他选择，只选中当前
    selectedCells.value = [cellData]
    // 开始编辑
    startEdit(row, modelId, field)
  }
}

// Phase 2: 键盘事件处理
const handleKeyDown = (e) => {
  if (e.ctrlKey || e.metaKey) {
    isMultiSelectMode.value = true

    // Ctrl+C 复制
    if (e.key === 'c' && contextMenu.row && contextMenu.modelId && contextMenu.field) {
      e.preventDefault()
      copyCell(contextMenu.row, contextMenu.modelId, contextMenu.field)
    }

    // Ctrl+V 粘贴
    if (e.key === 'v' && copiedCell.value && contextMenu.row && contextMenu.modelId && contextMenu.field) {
      e.preventDefault()
      pasteCell(contextMenu.row, contextMenu.modelId, contextMenu.field)
    }

    // Ctrl+A 全选单元格（在当前可见列）
    if (e.key === 'a') {
      e.preventDefault()
      selectAllVisibleCells()
    }
  }

  // Phase 3: 键盘导航
  if (!editingCell.value && focusedCell.value) {
    const { rowId, modelId, field } = focusedCell.value
    const fields = ['final_config', 'current_config', 'selection_config', 'rd_status']
    const currentFieldIndex = fields.indexOf(field)

    switch (e.key) {
      case 'ArrowUp':
        e.preventDefault()
        navigateToCell(rowId, modelId, field, 'up')
        break
      case 'ArrowDown':
        e.preventDefault()
        navigateToCell(rowId, modelId, field, 'down')
        break
      case 'ArrowLeft':
        e.preventDefault()
        navigateToCell(rowId, modelId, field, 'left')
        break
      case 'ArrowRight':
        e.preventDefault()
        navigateToCell(rowId, modelId, field, 'right')
        break
      case 'Enter':
        e.preventDefault()
        const row = tableData.value.find(r => r.id === rowId)
        if (row) startEdit(row, modelId, field)
        break
      case 'Escape':
        e.preventDefault()
        selectedCells.value = []
        focusedCell.value = null
        break
    }
  } else if (editingCell.value && e.key === 'Escape') {
    // Esc 退出编辑模式
    editingCell.value = null
    e.preventDefault()
  }
}

const handleKeyUp = (e) => {
  if (!e.ctrlKey && !e.metaKey) {
    isMultiSelectMode.value = false
  }
}

// 判断单元格是否被选中
const isCellSelected = (rowId, modelId, field) => {
  return selectedCells.value.some(
    c => c.rowId === rowId && c.modelId === modelId && c.field === field
  )
}

// 复制单元格
const copyCell = (row, modelId, field) => {
  const value = row.model_values[modelId]?.[field]
  copiedCell.value = {
    row,
    modelId,
    field,
    value,
    rowData: {
      rd_name: row.rd_name,
      ipn: row.ipn
    }
  }
  ElMessage.success('已复制')
}

// 粘贴单元格
const pasteCell = async (targetRow, targetModelId, targetField) => {
  if (!copiedCell.value) {
    ElMessage.warning('请先复制单元格')
    return
  }

  const source = copiedCell.value
  const newValue = source.value

  // 如果目标单元格不存在，跳过
  if (!targetRow.model_values[targetModelId]) {
    ElMessage.warning('目标单元格不存在')
    return
  }

  const oldValue = targetRow.model_values[targetModelId][targetField]

  // 如果值相同，不需要修改
  if (!isValueChanged(oldValue, newValue)) {
    return
  }

  try {
    targetRow.model_values[targetModelId][targetField] = newValue
    if (await handleCellChange(targetRow, targetModelId, targetField, newValue, oldValue)) ElMessage.success('已粘贴')
  } catch (error) {
    console.error('粘贴失败:', error)
    ElMessage.error('粘贴失败')
  }
}

// 右键菜单中处理复制
const handleCopyCell = () => {
  hideContextMenu()
  if (contextMenu.row && contextMenu.modelId && contextMenu.field) {
    copyCell(contextMenu.row, contextMenu.modelId, contextMenu.field)
  }
}

// 右键菜单中处理粘贴
const handlePasteCell = () => {
  hideContextMenu()
  if (contextMenu.row && contextMenu.modelId && contextMenu.field) {
    pasteCell(contextMenu.row, contextMenu.modelId, contextMenu.field)
  }
}

// 批量粘贴到选中的单元格
const pasteToSelectedCells = async () => {
  if (!copiedCell.value || selectedCells.value.length === 0) return

  const source = copiedCell.value
  const promises = []

  try {
    for (const cell of selectedCells.value) {
      // 跳过源单元格本身
      if (cell.rowId === source.row.id && cell.modelId === source.modelId && cell.field === source.field) {
        continue
      }

      const targetRow = tableData.value.find(r => r.id === cell.rowId)
      if (!targetRow || !targetRow.model_values[cell.modelId]) continue

      const oldValue = targetRow.model_values[cell.modelId][cell.field]
      if (isValueChanged(oldValue, source.value)) {
        targetRow.model_values[cell.modelId][cell.field] = source.value
        promises.push(handleCellChange(targetRow, cell.modelId, cell.field, source.value, oldValue))
      }
    }

    if (promises.length > 0) {
      const successCount = (await Promise.all(promises)).filter(Boolean).length
      if (successCount > 0) ElMessage.success(`已粘贴到 ${successCount} 个单元格`)
    }
  } catch (error) {
    console.error('批量粘贴失败:', error)
    ElMessage.error('批量粘贴失败')
  }
}

onMounted(() => {
  loadColumnSettings()
  loadSeries()
  loadEnumValues()
  calculateTableHeight()
  window.addEventListener('resize', calculateTableHeight)
  configResizeObserver = new ResizeObserver(() => nextTick(calculateTableHeight))
  if (configPageRef.value) configResizeObserver.observe(configPageRef.value)
  // Excel-like keyboard events removed
  nextTick(() => {
    syncHeaderTitles()
    syncModelColumnHeaders()
    attachModelDragEvents()
  })
})

onUnmounted(() => {
  clearTimeout(searchTimer)
  clearTimeout(processTimer)
  window.removeEventListener('resize', calculateTableHeight)
  configResizeObserver?.disconnect()
  // Excel-like keyboard events removed
})

watch([selectedSeries, draftBatchMap, allModelsMap], () => refreshSaveFeedback(), { deep: true })

// 数据加载完成后同步表头 title
watch(loading, (val) => {
  if (!val) nextTick(() => {
    syncHeaderTitles()
    syncModelColumnHeaders()
    attachModelDragEvents()
  })
})

// 机型变化后重新同步
watch(selectedModels, () => {
  // 自动设置参考机型
  if (selectedModels.value.length > 0) {
    if (referenceModel.value === null || !selectedModels.value.includes(referenceModel.value)) {
      referenceModel.value = selectedModels.value[0]
    }
  } else {
    referenceModel.value = null
  }
  nextTick(() => {
    syncModelColumnHeaders()
    attachModelDragEvents()
  })
}, { deep: false })

// 全选时隐藏 el-select 内部标签，显示 ALL
const updateAllSelectDisplay = () => {
  document.querySelectorAll('.select-all-wrapper.hide-tags .el-select__selected-item').forEach(el => {
    el.style.display = 'none'
  })
  document.querySelectorAll('.select-all-wrapper:not(.hide-tags) .el-select__selected-item').forEach(el => {
    el.style.display = ''
  })
}
watch(selectedSeries, updateAllSelectDisplay, { immediate: true })
watch(selectedCategories, updateAllSelectDisplay, { immediate: true })
watch(tempSelectedModels, updateAllSelectDisplay, { immediate: true })

onMounted(() => {
  // 直接注入全局 CSS，绕过 Vue scoped 限制
  if (!document.getElementById('select-all-style')) {
    const style = document.createElement('style')
    style.id = 'select-all-style'
    style.textContent = `
      .select-all-wrapper.hide-tags .el-select__selected-item {
        display: none !important;
      }
    `
    document.head.appendChild(style)
  }
  updateAllSelectDisplay()
})

</script>

<style scoped>
.impact-model-list { max-height: 180px; overflow-y: auto; padding: 4px 8px; }
.impact-model-group { margin-bottom: 10px; }
.impact-model-group :deep(.el-tag) { margin: 4px 4px 0 0; max-width: 100%; }
.impact-model-group :deep(.el-tag__content) { overflow: hidden; text-overflow: ellipsis; }
.scope-note { color: #606266; font-size: 12px; line-height: 1.6; margin: 8px 0; overflow-wrap: anywhere; }
.draft-count-note { font-size: 12px; color: rgba(255, 255, 255, .86); margin-top: 6px; }
.save-feedback { display: flex; gap: 16px; align-items: center; padding: 6px 12px; background: #f0f7ff; color: #355373; font-size: 12px; }

.config-page {
  padding: 0;
}

.toolbar-card {
  margin-bottom: 8px;
}

.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.toolbar-card :deep(.el-card__body), .config-table-card :deep(.el-card__body) { padding: 10px; }
.toolbar :deep(.el-button + .el-button) { margin-left: 0; }
.select-item label { white-space: nowrap; }
.compact-view :deep(.el-table) { font-size: 12px; }
.compact-view :deep(.el-table th.el-table__cell) { padding: 2px 0; }
.compact-view :deep(.el-table th .cell) { padding: 2px 6px; line-height: 20px; }
.compact-view :deep(.el-table td.el-table__cell) { padding: 0; }
.compact-view :deep(.el-table__body-wrapper .el-table__body tr.el-table__row) { height: 30px; }
.compact-view :deep(.el-table__body-wrapper .cell) { padding: 1px 6px; line-height: 24px; }
.compact-view .cell-value { min-height: 24px; padding: 0; }
.compact-view .draft-info { gap: 8px; font-size: 12px; }
.compact-view .draft-actions { flex-wrap: wrap; }
.model-groups-panel { display: flex; flex-direction: column; gap: 8px; }
.model-groups-heading { display: flex; justify-content: space-between; align-items: center; }
.model-groups-heading span { color: #909399; font-size: 12px; }
.model-group-row { display: flex; align-items: center; justify-content: space-between; gap: 4px; border-bottom: 1px solid #ebeef5; padding: 4px 0; }
.model-group-name { flex: 1; min-width: 0; justify-content: flex-start; }
.model-group-name :deep(span) { display: block; overflow: hidden; text-overflow: ellipsis; }
.model-group-actions { display: flex; flex-shrink: 0; }
.model-group-actions :deep(.el-button) { margin-left: 0; padding: 4px 6px; }

.select-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.select-all-wrapper {
  position: relative;
}

.select-all-label {
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  pointer-events: none;
  z-index: 1;
  white-space: nowrap;
  font-size: 12px;
  height: 24px;
  line-height: 22px;
  padding: 0 8px;
  border-radius: 4px;
  border: 1px solid var(--el-color-primary-light-8);
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
}

.toolbar .left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  flex: 1 1 100%;
}

.toolbar .right {
  flex-wrap: wrap;
  display: flex;
  align-items: center;
  gap: 8px;
}

.draft-bar {
  margin-bottom: 8px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

.draft-bar :deep(.el-card__body) {
  padding: 8px 12px;
}

.draft-info {
  color: white;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.draft-info .el-icon {
  font-size: 18px;
}

.clickable-tag {
  cursor: pointer;
  transition: all 0.2s;
}

.clickable-tag:hover {
  transform: scale(1.05);
}

.draft-info strong {
  font-size: 14px;
}

.draft-actions {
  margin-left: auto;
  display: flex;
  gap: 8px;
}

.draft-items-panel {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.2);
  max-height: 320px;
  overflow-y: auto;
}

.draft-items-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
  color: white;
  font-size: 13px;
}

.draft-items-header :deep(.el-checkbox__label) {
  color: white;
}

.draft-items-header .selected-count {
  color: rgba(255, 255, 255, 0.8);
}

.series-tags {
  display: inline-flex;
  gap: 4px;
  align-items: center;
  flex-wrap: wrap;
}

.draft-model-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 4px;
  border-top: 1px solid rgba(255, 255, 255, 0.15);
  flex-wrap: wrap;
}

.draft-model-bar .model-bar-label {
  color: rgba(255, 255, 255, 0.8);
  font-size: 12px;
  white-space: nowrap;
  margin-right: 2px;
}

.draft-items-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.draft-item-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  border-radius: 4px;
  transition: background 0.2s;
  color: white;
}

.draft-item-row:hover {
  background: rgba(255, 255, 255, 0.1);
}

.draft-item-row.is-selected {
  background: rgba(255, 255, 255, 0.15);
}

.draft-item-row .change-badge {
  min-width: 42px;
  text-align: center;
}

.draft-item-row .item-name {
  flex: 1;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.draft-item-row .item-ipn {
  color: rgba(255, 255, 255, 0.6);
  font-size: 12px;
}

.submit-info {
  background: #ecf5ff;
  border-radius: 4px;
  padding: 10px 16px;
  margin-bottom: 16px;
  font-size: 13px;
  color: #606266;
}

.batch-bar {
  margin-bottom: 16px;
  background: #ecf5ff;
}

.batch-bar :deep(.el-card__body) {
  padding: 12px 20px;
}

.batch-info {
  display: flex;
  align-items: center;
  gap: 16px;
}

.batch-info strong {
  color: #409EFF;
}

.pagination-wrapper {
  margin-top: 8px;
  display: flex;
  justify-content: flex-end;
}

:deep(.el-table .cell) {
  padding: 4px 8px;
}

:deep(.el-select) {
  width: 100%;
}

.preview-content {
  max-height: 60vh;
  overflow-y: auto;
}

.column-filter {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.column-filter .filter-title {
  font-weight: bold;
  color: #606266;
  margin-bottom: 4px;
}

.column-filter .el-checkbox {
  margin-right: 0;
  height: 28px;
}

.column-filter .el-divider {
  margin: 8px 0;
}

.column-filter .column-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.column-filter .column-row .el-checkbox:first-child {
  flex: 1;
}

.column-filter .column-row .el-checkbox:last-child {
  width: 50px;
  color: #909399;
  font-size: 12px;
}

.cell-value {
  cursor: pointer;
  min-height: 24px;
  padding: 2px 0;
}

.cell-value:hover {
  background-color: #f5f7fa;
}

.value-text {
  display: block;
  padding: 0 8px;
  line-height: 24px;
  color: #606266;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 变更单元格高亮 - 按类型区分 */
.cell-changed {
  border-radius: 4px;
}

.cell-updated {
  background-color: #fdf6ec;
}

.cell-updated .value-text {
  color: #e6a23c;
  font-weight: 500;
}

.cell-created {
  background-color: #f0f9eb;
}

.cell-created .value-text {
  color: #67c23a;
  font-weight: 500;
}

.cell-deleted {
  background-color: #fef0f0;
  text-decoration: line-through;
}

.cell-deleted .value-text {
  color: #f56c6c;
  font-weight: 500;
}

/* 原值提示 */
.original-hint {
  color: #909399;
  font-size: 11px;
  margin-left: 4px;
}

/* 导入变更对话框 */
.import-changes {
  padding: 0;
}

.import-changes .el-table {
  margin-top: 16px;
}

.empty-changes {
  padding: 40px 0;
}

/* 右键菜单样式 */
.context-menu {
  position: fixed;
  background: white;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.1);
  z-index: 9999;
  min-width: 200px;
  padding: 4px 0;
}

.context-menu .menu-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  cursor: pointer;
  font-size: 13px;
  color: #606266;
  transition: all 0.2s;
}

.context-menu .menu-item:hover {
  background-color: #f5f7fa;
  color: #409eff;
}

.context-menu .menu-item .el-icon {
  font-size: 14px;
}

.context-menu .menu-divider {
  height: 1px;
  background-color: #e4e7ed;
  margin: 4px 0;
}

.context-menu .menu-disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.context-menu .menu-disabled:hover {
  background-color: transparent;
  color: #606266;
}

/* 多选单元格高亮 */
.cell-selected {
  background-color: #ecf5ff !important;
  border: 2px solid #409eff !important;
  border-radius: 4px;
}

.cell-selected .value-text {
  color: #409eff;
  font-weight: 500;
}

/* 焦点单元格 */
.cell-focused {
  outline: 2px solid #67c23a;
  outline-offset: -2px;
}

/* 拖拽目标高亮 */
.cell-drag-target {
  background-color: #e6f7ff !important;
  border: 2px dashed #1890ff !important;
}

.cell-value[draggable="true"] {
  cursor: grab;
}

.cell-value[draggable="true"]:active {
  cursor: grabbing;
}


/* 差异高亮（沿用配置对比样式） */
.cell-diff {
  background-color: #f4f0fd;
  color: #7c3aed;
  font-weight: 600;
  border-radius: 3px;
}

/* 参考机型删除态在差异模式下保留删除线 */
.cell-diff.cell-deleted {
  text-decoration: line-through;
}

.cell-diff.cell-deleted .value-text {
  text-decoration: line-through;
  color: #7c3aed;
  font-weight: 600;
}

/* 行差异对话框样式 */
.row-diff-content {
  max-height: 70vh;
  overflow-y: auto;
}

.row-diff-content .diff-highlight {
  color: #cf1322;
  font-weight: 600;
  background-color: #fff5f5;
  padding: 2px 6px;
  border-radius: 4px;
}

.row-diff-content .el-table .cell {
  white-space: nowrap;
}

.diff-legend {
  display: flex;
  justify-content: flex-end;
}

/* 快捷操作提示 */
.tips-card {
  margin-bottom: 16px;
  background: linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%);
}

.tips-card.collapsed :deep(.el-card__body) {
  padding: 0;
}

.tips-card :deep(.el-card__header) {
  padding: 12px 20px;
  border-bottom: 1px solid #bae6fd;
}

.tips-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: #0369a1;
  font-weight: 500;
  cursor: pointer;
}

.tips-header:hover {
  color: #0ea5e9;
}

.tips-header .el-icon {
  margin-right: 8px;
}

.tips-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.expand-icon {
  font-size: 14px;
  color: #64748b;
  transition: transform 0.3s;
  cursor: pointer;
}

.expand-icon.is-expanded {
  transform: rotate(180deg);
}

.is-rotated {
  transform: rotate(180deg);
  transition: transform 0.3s;
}

.tips-content {
  padding: 16px 20px;
}

.tips-content {
  padding: 8px 0;
}

.tip-item {
  padding: 8px 12px;
  background: white;
  border-radius: 6px;
  border-left: 3px solid #0ea5e9;
}

.tip-title {
  font-weight: 600;
  color: #0c4a6e;
  margin-bottom: 4px;
  font-size: 13px;
}

.tip-desc {
  color: #64748b;
  font-size: 12px;
  line-height: 1.4;
}

/* 研发状态未完成高亮 */
.cell-rd-incomplete {
  background-color: #fef2f2 !important;
  border-radius: 4px;
  position: relative;
}

.cell-rd-incomplete .value-text {
  color: #dc2626 !important;
  font-weight: 600;
}

.cell-rd-incomplete::after {
  content: '';
  position: absolute;
  top: 0;
  right: 0;
  width: 0;
  height: 0;
  border-style: solid;
  border-width: 0 8px 8px 0;
  border-color: transparent #ef4444 transparent transparent;
}

/* 表头文字溢出省略号 + hover 显示完整内容 */
:deep(.el-table__header-wrapper .cell) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 固定行高 + 溢出省略 */
:deep(.el-table__body-wrapper .el-table__body tr.el-table__row) {
  height: 40px;
}
:deep(.el-table__body-wrapper .cell) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* === 机型列拖拽排序 === */
.model-drag-handle {
  display: inline-block;
  margin-right: 6px;
  opacity: 0.35;
  cursor: grab;
  font-size: 15px;
  color: #606266;
  user-select: none;
  transition: opacity 0.15s;
  line-height: 1;
}
th:hover .model-drag-handle {
  opacity: 1;
  color: #409eff;
}
.model-drag-handle:active {
  cursor: grabbing;
}

/* 拖拽源半透明 + 虚线边框 */
th.is-dragging-source {
  opacity: 0.5;
  outline: 2px dashed #409eff;
  outline-offset: -2px;
}

/* 其他机型列半透明 */
th.is-drag-dimmed {
  opacity: 0.4;
}

/* drop 指示线 — before */
th.is-drag-over-before {
  box-shadow: inset 3px 0 0 0 #409eff;
}

/* drop 指示线 — after */
th.is-drag-over-after {
  box-shadow: inset -3px 0 0 0 #409eff;
}

/* 配置字段列头筛选图标 */
.column-header-with-filter {
  display: flex;
  align-items: center;
  gap: 2px;
  width: 100%;
  overflow: hidden;
}
.column-header-with-filter > span {
  flex-shrink: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}
.filter-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 3px;
  cursor: pointer;
  opacity: 0.4;
  transition: opacity var(--duration-fast, 150ms), color var(--duration-fast, 150ms), background var(--duration-fast, 150ms);
  flex-shrink: 0;
  color: #999;
}
.filter-icon:hover {
  opacity: 0.8;
  color: #409eff;
  background: #ecf5ff;
}
.filter-icon.active {
  opacity: 1;
  color: #409eff;
  background: #d9ecff;
}
.filter-icon .el-icon {
  font-size: 12px;
}

/* 列值筛选弹窗 */
.field-filter-popover {
  padding: 0;
}
.field-filter-popover .filter-body {
  padding: 8px 12px;
}
.field-filter-popover .filter-actions {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
  padding-bottom: 8px;
  border-bottom: 1px solid #eee;
}
.field-filter-popover .filter-checkboxes {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 240px;
  overflow-y: auto;
}
.field-filter-popover .filter-checkboxes .el-checkbox {
  height: 28px;
  margin-right: 0;
}
</style>
