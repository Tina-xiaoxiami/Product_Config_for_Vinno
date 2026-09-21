<template>
  <el-tooltip v-if="flag" placement="top" effect="dark" :show-after="120" popper-class="feature-name-mark-popper">
    <template #content>
      <div class="feature-name-mark-tip">
        <div class="feature-name-mark-title">
          {{ flag.feature_cn_name || '功能名称核对' }}
        </div>
        <div v-for="check in flag.checks" :key="check.baseline" class="feature-name-mark-check">
          <div class="feature-name-mark-check-label" :class="`is-${check.severity}`">
            {{ check.label }}：{{ severityLabel(check.severity) }}
          </div>
          <div v-if="check.standard_cn_name">标准中文名称：{{ check.standard_cn_name }}</div>
          <div v-if="check.standard_en_name">标准英文名称：{{ check.standard_en_name }}</div>
          <div v-if="check.standard_ui_label">中文UI：{{ check.standard_ui_label }}</div>
          <div v-if="check.ipn">IPN：{{ check.ipn }}</div>
          <div v-if="check.message" class="feature-name-mark-message">{{ check.message }}</div>
        </div>
      </div>
    </template>
    <el-icon class="feature-name-mark" :class="`is-${flag.severity}`"><component :is="icon" /></el-icon>
  </el-tooltip>
</template>

<script setup>
import { computed } from 'vue'
import { InfoFilled, Warning, WarningFilled } from '@element-plus/icons-vue'
import { featureNameFlag, loadFeatureNameStandardFlags } from '../utils/featureNameStandard'

const props = defineProps({
  featureId: { type: [Number, String], default: null },
  cn: { type: String, default: '' },
  en: { type: String, default: '' },
  name: { type: String, default: '' }
})

// 组件出现时确保提示标记已加载（幂等，失败静默）
loadFeatureNameStandardFlags()

const flag = computed(() => featureNameFlag({
  featureId: props.featureId,
  names: [props.cn, props.en, props.name]
}))

const SEVERITY_LABELS = {
  differs: '不一致',
  style: '写法不同',
  ambiguous: '待人工确认',
  uncovered: '标准表未收录',
  unlinked: '未关联主IPN，未核对',
  ok: '一致'
}
const ICONS = {
  differs: WarningFilled,
  ambiguous: Warning,
  style: Warning,
  uncovered: InfoFilled
}

const severityLabel = (severity) => SEVERITY_LABELS[severity] || severity
const icon = computed(() => ICONS[flag.value?.severity] || InfoFilled)
</script>

<style scoped>
.feature-name-mark {
  margin-left: 4px;
  vertical-align: -2px;
  font-size: 13px;
  cursor: help;
}
.feature-name-mark.is-differs { color: #f56c6c; }
.feature-name-mark.is-style,
.feature-name-mark.is-ambiguous { color: #e6a23c; }
.feature-name-mark.is-uncovered { color: #c0c4cc; }
</style>

<style>
.feature-name-mark-tip {
  max-width: 360px;
  line-height: 1.6;
  font-size: 12px;
}
.feature-name-mark-tip .feature-name-mark-title {
  font-weight: 600;
  margin-bottom: 4px;
}
.feature-name-mark-tip .feature-name-mark-message {
  margin-top: 4px;
  white-space: pre-line;
}
.feature-name-mark-tip .feature-name-mark-check + .feature-name-mark-check {
  margin-top: 8px;
  padding-top: 6px;
  border-top: 1px solid rgba(255, 255, 255, 0.25);
}
.feature-name-mark-tip .feature-name-mark-check-label {
  font-weight: 600;
}
.feature-name-mark-tip .feature-name-mark-check-label.is-differs { color: #ffb3b3; }
.feature-name-mark-tip .feature-name-mark-check-label.is-style,
.feature-name-mark-tip .feature-name-mark-check-label.is-ambiguous { color: #ffd591; }
.feature-name-mark-tip .feature-name-mark-check-label.is-ok { color: #b7eb8f; }
</style>
