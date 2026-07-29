import { ref } from 'vue'

/**
 * 草稿筛选状态管理 composable
 * 与 配置管理/配置对比 共享相同的筛选机制
 *
 * 高亮哪些，显示哪些 — draftFilters 存储"要显示的"类型（包含型）
 *
 * @returns {{
 *   draftFilterMode: import('vue').Ref<boolean>,
 *   draftFilters: import('vue').Ref<Set<'create'|'update'|'delete'>>,
 *   toggleDraftFilter: (type: 'all'|'create'|'update'|'delete') => void,
 *   clearDraftFilter: () => void,
 *   getDraftTagType: (type: 'all'|'create'|'update'|'delete') => string
 * }}
 */
export function useDraftFilter() {
  const draftFilterMode = ref(false)
  const draftFilters = ref(new Set())

  /**
   * 切换草稿筛选
   * - 全部草稿：总开关，开启时三种类型全部选中，再点关闭
   * - 单独类型：切换选中/取消选中。全部取消时自动关闭筛选
   * @param {'all'|'create'|'update'|'delete'} type
   */
  function toggleDraftFilter(type) {
    if (type === 'all') {
      if (draftFilterMode.value) {
        // 关闭筛选
        draftFilterMode.value = false
        draftFilters.value = new Set()
      } else {
        // 开启筛选：全部选中
        draftFilterMode.value = true
        draftFilters.value = new Set(['create', 'update', 'delete'])
      }
    } else {
      const next = new Set(draftFilters.value)
      if (next.has(type)) {
        next.delete(type) // 取消选中
      } else {
        next.add(type) // 选中
      }
      draftFilters.value = next
      // 无选中类型时自动关闭筛选
      draftFilterMode.value = next.size > 0
    }
  }

  /** 清除草稿筛选 */
  function clearDraftFilter() {
    draftFilterMode.value = false
    draftFilters.value = new Set()
  }

  /**
   * 获取 el-tag 的 type 属性
   * @param {'all'|'create'|'update'|'delete'} type
   * @returns {'primary'|'success'|'warning'|'danger'|'info'}
   */
  function getDraftTagType(type) {
    if (type === 'all') {
      return draftFilterMode.value ? 'primary' : 'info'
    }
    // 高亮哪些，显示哪些 — 选中的类型有颜色
    return draftFilterMode.value && draftFilters.value.has(type)
      ? ({ create: 'success', update: 'warning', delete: 'danger' })[type]
      : 'info'
  }

  /**
   * 根据草稿筛选状态过滤数据
   * 共享给配置管理和配置对比使用
   *
   * @template T
   * @param {T[]} data - 要过滤的数据数组
   * @param {(item: T) => Set<'create'|'update'|'delete'>|undefined|null} getItemTypes
   *   回调函数，接收一个数据项，返回该数据项的草稿类型 Set
   * @returns {T[]} 过滤后的数据
   */
  function filterByDraftMode(data, getItemTypes) {
    if (!draftFilterMode.value) return data
    const showTypes = draftFilters.value
    return data.filter(item => {
      const itemTypes = getItemTypes(item)
      if (!itemTypes || itemTypes.size === 0) return false
      // 高亮哪些，显示哪些 — 匹配任一选中类型即保留
      for (const type of showTypes) {
        if (itemTypes.has(type)) return true
      }
      return false
    })
  }

  return {
    draftFilterMode,
    draftFilters,
    toggleDraftFilter,
    clearDraftFilter,
    getDraftTagType,
    filterByDraftMode
  }
}