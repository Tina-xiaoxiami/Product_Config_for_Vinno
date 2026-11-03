<template>
  <el-dialog v-model="state.visible" title="从功能库添加" width="min(680px, calc(100vw - 32px))" append-to-body
    :before-close="editor.close" :show-close="!state.saving" :close-on-click-modal="!state.saving" :close-on-press-escape="!state.saving">
    <p class="catalog-help">选择共用配置功能项，保存为待提交预览；提交模板版本后，功能分类和探头支持设置才生效。</p>
    <el-alert v-if="state.error" :title="state.error" type="error" :closable="false" />
    <el-alert v-if="state.refreshError" :title="state.refreshError" type="warning" :closable="false" />
    <el-form label-position="top" size="small" :disabled="state.saving || state.saved">
      <el-form-item label="共用功能库" required>
        <el-select v-model="state.form.feature_id" filterable clearable :filter-method="searchFeatures" placeholder="搜索中文、英文或IPN" aria-label="从共用功能库选择功能" @change="editor.chooseFeature">
          <el-option v-for="feature in candidates" :key="feature.id" :value="feature.id" :label="catalogFeatureLabel(feature)"
            :disabled="feature.probe_matrix_enabled || feature.pending">
            <div class="catalog-option"><span>{{ catalogFeatureLabel(feature) }}</span><small v-if="feature.probe_matrix_enabled">已加入</small><small v-else-if="feature.pending">待提交</small></div>
          </el-option>
        </el-select>
      </el-form-item>
      <el-form-item label="功能分类（共用）" required>
        <el-select v-model="state.form.group_id" placeholder="选择现有功能分类" aria-label="共用功能分类">
          <el-option v-for="group in catalog?.groups || []" :key="group.id" :label="group.name" :value="group.id" />
        </el-select>
        <small class="catalog-help">提交后更新该功能的共用分类，不修改配置项名称或IPN。</small>
      </el-form-item>
      <el-form-item label="支持的探头类别" required>
        <el-checkbox-group v-model="state.form.category_ids" class="catalog-categories" aria-label="支持的探头类别">
          <el-checkbox v-for="category in categories" :key="category.id" :value="category.id" :label="category.name" />
        </el-checkbox-group>
        <small class="catalog-help">至少选择一个探头类别；未选类别保持不支持。提交前可在矩阵继续设置条件和应用范围。</small>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button size="small" :disabled="state.saving" @click="editor.close()">{{ state.saved ? '关闭' : '取消' }}</el-button>
      <el-button v-if="state.saved" size="small" type="primary" :loading="state.saving" @click="editor.retryRefresh()">重试刷新</el-button>
      <el-button v-else size="small" type="primary" :loading="state.saving" @click="submit">保存待提交</el-button>
    </template>
  </el-dialog>
</template>
<script setup>
import { computed, reactive, onBeforeUnmount } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { saveTemplateCatalogDraft } from '../api/data'
import { catalogFeatureLabel, catalogCandidates, createTemplateCatalogEditorState, createTemplateCatalogEditor } from '../utils/templateFeatureCatalog'
const props = defineProps({ catalog: { type: Object, default: null }, categories: { type: Array, default: () => [] }, refreshAfterSave: { type: Function, required: true } })
const state = reactive(createTemplateCatalogEditorState())
const candidates = computed(() => catalogCandidates(props.catalog, state.search))
const searchFeatures = value => { state.search = value }
const editor = createTemplateCatalogEditor({ state, getContext: () => ({ catalog: props.catalog, categories: props.categories }),
  save: saveTemplateCatalogDraft, refresh: props.refreshAfterSave,
  confirmDiscard: () => ElMessageBox.confirm('功能选择尚未保存，是否放弃？', '未保存的修改', { confirmButtonText: '放弃修改', cancelButtonText: '继续编辑', type: 'warning' }) })
const submit = async () => { if (await editor.submit()) ElMessage.success('已保存为待提交草稿，提交模板版本后生效') }
onBeforeRouteLeave(() => state.visible ? editor.close() : true)
onBeforeUnmount(editor.dispose)
defineExpose({ open: editor.open, isOpen: computed(() => state.visible) })
</script>
<style scoped>
.catalog-help { color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.6; margin: 6px 0; }
.el-select { width: 100%; }.catalog-option { display: flex; align-items: center; gap: 12px; }.catalog-option small { color: var(--el-text-color-secondary); margin-left: auto; }
.catalog-categories { display: flex; flex-wrap: wrap; gap: 4px 14px; }.catalog-categories .el-checkbox { margin: 0; }.el-alert { margin-bottom: 10px; }
</style>
