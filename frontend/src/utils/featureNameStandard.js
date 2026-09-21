/**
 * 功能名称标准提示
 *
 * 后端把「功能名称标准表」与功能主数据比对后的提示标记一次性下发，这里做全局缓存，
 * 任何显示功能名称的位置都可以用 featureNameFlag() 判断是否需要提示。
 */
import { computed, ref } from 'vue'
import { getFeatureNameStandardFlags } from '../api/data'

// 与后端 services/feature_name_standards.normalize_feature_name_key 保持一致
const NORMALIZE_PATTERN = /[\s\u3000（）()\[\]【】{}〈〉《》:：,，、;；·.\-_/\\|!！?？"'"'“”‘’]+/g

const emptyFlags = () => ({ by_feature: {}, by_name: {}, summary: {}, standard_count: 0 })

const flags = ref(emptyFlags())
const loaded = ref(false)
let pending = null

export function normalizeFeatureName(value) {
  return String(value ?? '')
    .normalize('NFKC')
    .replace(NORMALIZE_PATTERN, '')
    .toLowerCase()
}

export async function loadFeatureNameStandardFlags({ force = false } = {}) {
  if (loaded.value && !force) return flags.value
  if (!pending || force) {
    pending = getFeatureNameStandardFlags()
      .then((data) => {
        flags.value = {
          by_feature: data.by_feature || {},
          by_name: data.by_name || {},
          summary: data.summary || {},
          standard_count: data.standard_count || 0,
          last_imported_at: data.last_imported_at || null,
          source_file: data.source_file || ''
        }
        loaded.value = true
      })
      .catch(() => { flags.value = emptyFlags() })
      .finally(() => { pending = null })
  }
  await pending
  return flags.value
}

/**
 * 取某个功能的名称提示。
 * @param {{featureId?: number|string|null, names?: (string|null|undefined)[]}} params
 */
export function featureNameFlag({ featureId = null, names = [] } = {}) {
  const byFeature = flags.value.by_feature || {}
  if (featureId !== null && featureId !== undefined && byFeature[String(featureId)]) {
    return byFeature[String(featureId)]
  }
  const byName = flags.value.by_name || {}
  for (const name of names) {
    const key = normalizeFeatureName(name)
    if (key && byName[key]) return byName[key]
  }
  return null
}

export function useFeatureNameStandard() {
  return {
    flags: computed(() => flags.value),
    summary: computed(() => flags.value.summary || {}),
    loadFeatureNameStandardFlags,
    featureNameFlag,
    normalizeFeatureName
  }
}
