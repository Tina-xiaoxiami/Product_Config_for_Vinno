import { PROBE_MANAGEMENT_TABS, probeManagementMenuPath } from './probeManagementNavigation.js'

// The sidebar and page navigation share route identities, including legacy deep links.
export const WORKSPACE_SECTIONS = [
  { id: 'knowledge', path: '/knowledge', label: '产品知识库', icon: 'Collection' },
  { id: 'release', path: '/release', label: '功能发布', icon: 'Promotion' },
  { id: 'master-data', menuId: '/manage', label: '基础数据管理', icon: 'Setting', tabs: [
    { path: '/models', label: '产品型号' },
    { path: '/template-features', label: '探头与应用管理' },
    { path: '/registration-manage', label: '注册管理' },
    { path: '/measurements', label: '测量库' }
  ] },
  { id: 'model-config', menuId: '/product-config', label: '机型配置', icon: 'Document', tabs: [
    { path: '/config', label: '配置管理' }, { path: '/compare', label: '配置对比' },
    { path: '/version-compare', label: '版本对比' }, { path: '/versions', label: '版本历史' }
  ] },
  { id: 'probe-config', menuId: '/probe', label: '探头配置', icon: 'DataAnalysis', tabs: [
    { path: '/probe-config', label: '探头配置管理' }, { path: '/probe-versions', label: '版本历史' }
  ] }
]

const PAGE_DESCRIPTIONS = {
  '/models': '统一维护产品型号、系列分组和注册映射，供配置与产品资料共同引用。',
  '/template-features': '从配置功能库选择功能、设置共用分类和探头支持，核对草稿后统一提交版本。',
  '/probe-models': '按类别管理探头型号、变体和应用关系。',
  '/applications': '维护应用名称及各探头类别下的常规、POC 应用范围。',
  '/registration-manage': '统一管理注册证、差异表和资料版本，供知识库与产品策略查询引用。',
  '/measurements': '按 Id 或中英文 UI 名称查找测量与计算项，筛选适用模式和应用。',
  '/config': '按系列和机型查看配置，集中维护草稿、核对变更并发布版本。',
  '/compare': '并排比较不同机型的配置，定位差异并集中核对修改。',
  '/version-compare': '选择同系列的两个已发布版本，核对配置及机型范围变化。',
  '/versions': '查看已发布配置与变更说明，按版本追溯、比较和维护历史。',
  '/probe-config': '维护子系列共同总集，核对各机型差异后预览并发布。',
  '/probe-versions': '查看探头配置发布快照、比较历史版本或恢复为新草稿。',
  '/knowledge': '查询已确认产品知识；没有可靠答案的问题进入待确认队列。',
  '/release': '查询发布资料，维护版本记录和功能发布内容。'
}

export function workspaceForPath(path) {
  const parentPath = probeManagementMenuPath(path)
  const section = WORKSPACE_SECTIONS.find(item => item.path === parentPath || item.tabs?.some(tab => tab.path === parentPath))
  if (!section) return null
  const pagePath = path === '/feature-manage' ? parentPath : path
  const page = PROBE_MANAGEMENT_TABS.find(tab => tab.path === pagePath) || section.tabs?.find(tab => tab.path === parentPath) || section
  return {
    sectionId: section.id, groupTitle: section.label, sidebarGroup: section.menuId || null,
    title: page.label, description: PAGE_DESCRIPTIONS[path] || PAGE_DESCRIPTIONS[parentPath],
    tabs: section.tabs || [], activeTab: parentPath
  }
}
