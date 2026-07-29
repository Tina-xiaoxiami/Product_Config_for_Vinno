/**
 * 型号短名称（省略公共前缀，适用于表头紧凑显示）
 * @param {Map} allModelsMap - modelId -> { id, name, seriesId, seriesName }
 * @param {number} modelId
 * @returns {string}
 */
export function getModelShortName(allModelsMap, modelId) {
  const m = allModelsMap.get(modelId)
  if (!m) return ''
  const modelName = m.name
  const seriesName = m.seriesName

  // 型号名以系列名开头 → 省略系列名，只保留差异部分
  if (seriesName && modelName.startsWith(seriesName)) {
    const suffix = modelName.slice(seriesName.length)
    if (suffix) return suffix
  }

  // 找所有同系列型号的最长公共前缀并省略
  const siblingNames = []
  for (const [, info] of allModelsMap) {
    if (info.seriesId === m.seriesId) siblingNames.push(info.name)
  }
  if (siblingNames.length > 1) {
    let prefix = siblingNames[0]
    for (const name of siblingNames) {
      while (!name.startsWith(prefix) && prefix.length > 0) {
        prefix = prefix.slice(0, -1)
      }
    }
    const boundaryIdx = Math.max(
      prefix.lastIndexOf(' '),
      prefix.lastIndexOf('-'),
      prefix.lastIndexOf('_')
    )
    if (boundaryIdx > 0) prefix = prefix.slice(0, boundaryIdx + 1)
    if (prefix.length >= 3 && modelName.length > prefix.length) {
      return modelName.slice(prefix.length)
    }
  }

  return modelName
}

/**
 * 按系列分组的已选型号（用于表头层级显示）
 * @param {Map} allModelsMap - modelId -> { id, name, seriesId, seriesName }
 * @param {number[]} selectedModels - 选中的型号 ID 数组
 * @returns {Array<{ seriesId, seriesName, modelIds: number[] }>}
 */
export function groupModelsBySeries(allModelsMap, selectedModels) {
  const groups = []
  const seen = new Set()
  for (const modelId of selectedModels) {
    const m = allModelsMap.get(modelId)
    if (!m) continue
    const key = m.seriesId
    if (!seen.has(key)) {
      seen.add(key)
      groups.push({ seriesId: key, seriesName: m.seriesName, modelIds: [] })
    }
    groups.find(g => g.seriesId === key).modelIds.push(modelId)
  }
  return groups
}

/**
 * 根据 modelId 查找对应的 seriesId
 */
export function findSeriesIdByModelId(allModelsMap, modelId) {
  const m = allModelsMap.get(typeof modelId === 'number' ? modelId : parseInt(modelId))
  return m ? m.seriesId : null
}

/**
 * 判断值是否发生变化（处理 null/空字符串等价）
 */
export function isValueChanged(oldVal, newVal) {
  if (oldVal == null && newVal == null) return false
  if (oldVal === '' && newVal == null) return false
  if (oldVal == null && newVal === '') return false
  return String(oldVal || '') !== String(newVal || '')
}

/**
 * 字段名 → 中文标签
 */
const FIELD_LABELS = {
  'final_config': '最终配置',
  'current_config': '当前配置',
  'selection_config': '选型类别',
  'rd_status': '研发状态'
}
export function getFieldLabel(field) {
  return FIELD_LABELS[field] || field
}

/** 四个配置字段的 key 列表 */
export const FIELD_KEYS = ['final_config', 'current_config', 'selection_config', 'rd_status']

/** 字段默认列宽 */
export const DEFAULT_FIELD_WIDTHS = { final_config: 100, current_config: 100, selection_config: 100, rd_status: 100 }

/**
 * 格式化时间
 * @param {string|Date} time
 * @returns {string}
 */
export function formatTime(time) {
  if (!time) return ''
  return new Date(time).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

/**
 * 判断值是否为空（-、N/A、未定义、空字符串均视为空）
 */
export function isEmptyValue(v) {
  return !v || v === '-' || v === 'N/A' || v === '未定义' || v === ''
}

/**
 * 标准化值（空值统一为 null，用于差异比较）
 */
export function normalizeValue(v) {
  return isEmptyValue(v) ? null : v
}
