<template>
  <el-tooltip v-if="flag" placement="top" effect="dark" :show-after="120" popper-class="feature-name-mark-popper">
    <template #content>
      <div class="feature-name-mark-tip">
        <div class="feature-name-mark-title">{{ title }}</div>
        <div v-if="flag.standard_cn_name">标准中文名称：{{ flag.standard_cn_name }}</div>
        <div v-if="flag.standard_en_name">标准英文名称：{{ flag.standard_en_name }}</div>
        <div v-if="flag.standard_ui_label">中文UI：{{ flag.standard_ui_label }}</div>
        <div v-if="flag.message" class="feature-name-mark-message">{{ flag.message }}</div>
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

const TITLES = {
  differs: '与功能名称标准不一致',
  style: '名称写法与功能名称标准不同',
  ambiguous: '标准表有多条定义同时匹配该功能',
  uncovered: '功能名称标准表未收录该功能'
}
const ICONS = {
  differs: WarningFilled,
  ambiguous: Warning,
  style: Warning,
  uncovered: InfoFilled
}

const title = computed(() => TITLES[flag.value?.severity] || '功能名称标准提示')
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
</style>
