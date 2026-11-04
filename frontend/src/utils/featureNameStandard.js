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

const emptyFlags = () => ({ by_feature: {}, by_name: {}, checks_by_feature: {}, summary: {}, standard_count: 0 })

const flags = ref(emptyFlags())
const loaded = ref(false)
let pending = null

export function normalizeFeatureName(value) {
  return String(value ?? '')
    .normalize('NFKC')
    .replace(NORMALIZE_PATTERN, '')
    .toLowerCase()
}

let requestSequence = 0
export async function loadFeatureNameStandardFlags({ force = false, strict = false } = {}) {
  if (loaded.value && !force) return flags.value
  if (!pending || force) {
    const sequence = ++requestSequence
    pending = getFeatureNameStandardFlags().then(data => {
      if (sequence !== requestSequence) return
      flags.value = {
        by_feature: data.by_feature || {}, by_name: data.by_name || {}, checks_by_feature: data.checks_by_feature || {}, summary: data.summary || {},
        standard_count: data.standard_count || 0, last_imported_at: data.last_imported_at || null, source_file: data.source_file || ''
      }
      loaded.value = true
    })
  }
  const task = pending
  try { await task } catch (error) { if (strict) throw error }
  finally { if (pending === task) pending = null }
  return flags.value
}

/**
 * 取某个功能的名称提示。
 * @param {{featureId?: number|string|null, names?: (string|null|undefined)[]}} params
 */
export function featureNameFlag({ featureId = null, names = [] } = {}) {
  const byFeature = flags.value.by_feature || {}
  if (featureId !== null && featureId !== undefined && String(featureId).trim() !== '') {
    return byFeature[String(featureId)] || null
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

// Current editable catalogs follow persisted primary names; release snapshots keep their own labels.
export function featureCurrentName(featureId, fallback, language = 'cn') {
  const entry = flags.value.checks_by_feature?.[String(featureId)]
  return entry?.[language === 'en' ? 'feature_en_name' : 'feature_cn_name'] || fallback
}
