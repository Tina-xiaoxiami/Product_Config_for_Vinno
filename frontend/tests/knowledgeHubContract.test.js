import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'


const read = (relativePath) => readFileSync(new URL(relativePath, import.meta.url), 'utf8')


test('knowledge hub is reachable from router and primary navigation', () => {
  const router = read('../src/router/index.js')
  const layout = read('../src/views/Layout.vue')

  assert.match(router, /path:\s*'knowledge'/)
  assert.match(router, /name:\s*'KnowledgeHub'/)
  assert.match(layout, /index="\/knowledge"/)
  assert.match(layout, />\s*产品知识库\s*</)
})


test('knowledge hub exposes search, status filters, identity details and documents', () => {
  const view = read('../src/views/KnowledgeHub.vue')

  assert.match(view, /data-testid="knowledge-search"/)
  assert.match(view, /data-testid="knowledge-status-filter"/)
  assert.match(view, /data-testid="feature-knowledge-list"/)
  assert.match(view, /中文曾用名/)
  assert.match(view, /英文曾用名/)
  assert.match(view, /aliasesByLanguage\(feature, 'cn'\)/)
  assert.match(view, /aliasesByLanguage\(feature, 'en'\)/)
  assert.match(view, /版本关系/)
  assert.match(view, /关联功能/)
  assert.match(view, /relationNote\(feature\)/)
  assert.match(view, /个功能待确认/)
  assert.match(view, /统计信息加载失败/)
  assert.match(view, /data-testid="knowledge-document-list"/)
  assert.match(view, /data-testid="document-preview-dialog"/)
  assert.match(view, /<iframe/)
})


test('knowledge hub lets users toggle displayed feature columns', () => {
  const view = read('../src/views/KnowledgeHub.vue')

  assert.match(view, /data-testid="column-settings"/)
  assert.match(view, /列显示设置/)
  assert.match(view, /columnOptions/)
  assert.match(view, /visibleColumns/)
  assert.match(view, /columnVisible\(/)
  assert.match(view, /resetColumnSettings/)
  assert.match(view, /中文曾用名/)
  assert.match(view, /英文曾用名/)
})


test('frontend API exposes knowledge feature, stats and document endpoints', () => {
  const api = read('../src/api/data.js')

  assert.match(api, /export const getKnowledgeFeatures/)
  assert.match(api, /export const getKnowledgeStats/)
  assert.match(api, /export const getKnowledgeDocuments/)
  assert.match(api, /export const getKnowledgeDocumentPreviewUrl/)
})


test('knowledge hub separates domestic registration redlines from product strategy', () => {
  const view = read('../src/views/KnowledgeHub.vue')

  assert.match(view, /label="国内注册与策略"/)
  assert.match(view, /data-testid="registration-model-select"/)
  assert.match(view, /aria-label="国内产品型号"/)
  assert.match(view, /data-testid="registration-probe-search"/)
  assert.match(view, /data-testid="registration-status-filter"/)
  assert.match(view, /aria-label="注册状态"/)
  assert.match(view, /data-testid="effective-status-filter"/)
  assert.match(view, /aria-label="最终判定"/)
  assert.match(view, /data-testid="registration-strategy-table"/)
  assert.match(view, /注册状态/)
  // 选型类别（正式）与 当前配置（备注）保留为附件列，默认不显示而不是删除
  assert.match(view, /label="选型类别（正式）"/)
  assert.match(view, /label="当前配置（备注）"/)
  assert.match(view, /v-if="registrationExtraColumns\.selection_config"/)
  assert.match(view, /v-if="registrationExtraColumns\.current_config"/)
  assert.match(view, /current_config_note/)
  assert.match(view, /config-note/)
  assert.doesNotMatch(view, /current_config_aux/)
  assert.match(view, /最终判定/)
  assert.match(view, /X 标配/)
  assert.match(view, /O 选配/)
  assert.match(view, /Δ 招标支持/)
  assert.match(view, /# 未注册/)
  assert.match(view, /注册差异表原文/)
  assert.match(view, /group\.source_document_id/)
  assert.match(view, /getKnowledgeDocumentPreviewUrl/)
  assert.match(view, /target="_blank"/)
})

test('registration strategy table keeps the requested column order', () => {
  const view = read('../src/views/KnowledgeHub.vue')
  const table = view.slice(
    view.indexOf('data-testid="registration-strategy-table"'),
    view.indexOf('</el-table>', view.indexOf('data-testid="registration-strategy-table"'))
  )
  const labels = [...table.matchAll(/label="([^"]+)"/g)].map(match => match[1])

  // 注册状态 → 最终判定 → 判定依据收尾；附件列排在最后，打开时不打乱判定链
  assert.deepEqual(labels, [
    '探头型号',
    'IPN',
    '配置名称',
    '注册状态',
    '最终判定',
    '判定依据',
    '选型类别（正式）',
    '当前配置（备注）'
  ])
})

test('registration extra columns stay available but hidden by default', () => {
  const view = read('../src/views/KnowledgeHub.vue')

  // 默认状态：两个附件列都是 false；打开入口在工具栏，选择写入 localStorage
  assert.match(view, /const registrationExtraColumnOptions = \[/)
  assert.match(view, /const REGISTRATION_EXTRA_COLUMN_KEY = 'knowledge_registration_extra_columns'/)
  assert.match(view, /selection_config: saved\?\.selection_config === true/)
  assert.match(view, /current_config: saved\?\.current_config === true/)
  assert.match(view, /return \{ selection_config: false, current_config: false \}/)
  assert.match(view, /data-testid="registration-column-settings"/)
  assert.match(view, /@update:model-value="setRegistrationExtraColumn\(option\.key, \$event\)"/)
  assert.match(view, /localStorage\.setItem\(REGISTRATION_EXTRA_COLUMN_KEY/)
  assert.match(view, /const resetRegistrationExtraColumns = \(\) =>/)
  assert.match(view, /@click="resetRegistrationExtraColumns"/)

  // 附件列宽度只在打开后参与布局，默认列宽合计仍要装得下 1074 窗口
  assert.match(view, /const REGISTRATION_DEFAULT_VISIBLE_COLUMNS = \[/)
})

test('registration strategy table supports per-column filtering', () => {
  const view = read('../src/views/KnowledgeHub.vue')

  // 三列都挂上表头漏斗筛选，且 column-key 与过滤函数一一对应
  assert.match(view, /column-key="registration_status"[\s\S]{0,200}:filters="registrationStatusColumnFilters"/)
  assert.match(view, /column-key="effective_status"[\s\S]{0,200}:filters="effectiveStatusColumnFilters"/)
  assert.match(view, /column-key="status_source"[\s\S]{0,200}:filters="statusSourceColumnFilters"/)
  assert.match(view, /@filter-change="\(filters\) => onColumnFilterChange\(group, filters\)"/)

  // 列筛选项必须覆盖后端真实取值：注册状态、最终判定五种、判定依据三种来源
  const optionBlock = view.slice(
    view.indexOf('const registrationStatusColumnFilters'),
    view.indexOf('const filterRegistrationStatus')
  )
  for (const value of ['registered', 'unregistered', 'X', 'O', 'Δ', '#', '未定义',
    'registration_redline', 'selection_config', 'missing']) {
    assert.match(optionBlock, new RegExp(`value: '${value.replace('#', '#')}'`))
  }

  // 列筛选与卡片筛选叠加，提示条条数取叠加后的结果
  assert.match(view, /const activeFilters = activeColumnFilters\(group\)/)
  assert.match(view, /return activeFilters.every/)
  assert.match(view, /const registrationFilterCount = \(group\) =>/)
  assert.match(view, /clearRegistrationFilters/)
  assert.match(view, /clearFilter\?\.\(\)/)
  assert.match(view, /columnFilters\.value = \{\}/)
})

test('registration strategy table remembers user column widths', () => {
  const view = read('../src/views/KnowledgeHub.vue')

  // 默认列宽要能在窄窗口下装得下（不靠横向滚动条），超出部分靠换行
  const defaultsBlock = view.slice(
    view.indexOf('const registrationColumnDefaults = {'),
    view.indexOf('}', view.indexOf('const registrationColumnDefaults = {'))
  )
  const defaults = Object.fromEntries(
    [...defaultsBlock.matchAll(/(\w+): (\d+)/g)].map(match => [match[1], Number(match[2])])
  )
  assert.deepEqual(Object.keys(defaults), [
    'probe_model',
    'ipn',
    'config_name',
    'registration_status',
    'effective_status',
    'status_source',
    'selection_config',
    'current_config'
  ])
  // 只有默认显示的列参与默认布局；附件列默认收起，不计入
  const defaultVisible = view.slice(
    view.indexOf('const REGISTRATION_DEFAULT_VISIBLE_COLUMNS = ['),
    view.indexOf(']', view.indexOf('const REGISTRATION_DEFAULT_VISIBLE_COLUMNS = ['))
  )
  const visibleKeys = [...defaultVisible.matchAll(/'(\w+)'/g)].map(match => match[1])
  assert.deepEqual(visibleKeys, [
    'probe_model', 'ipn', 'config_name', 'registration_status', 'effective_status', 'status_source'
  ])
  const visibleSum = visibleKeys.reduce((sum, key) => sum + defaults[key], 0)
  assert.ok(
    visibleSum <= 764,
    `默认显示列宽合计 ${visibleSum}px 超出 1074 窗口可用宽度 764px`
  )

  // 列宽走 min-width 绑定：合计不超过容器时按比例吸收余量（表格右侧不留空档），
  // 超过容器才出现横向滚动条；用户拖动后的值同样由 state 驱动
  assert.match(view, /:min-width="registrationColumnWidths\.probe_model"/)
  assert.match(view, /:min-width="registrationColumnWidths\.status_source"/)
  assert.doesNotMatch(view, /min-width="205"/)

  // 拖动表头后写入 localStorage，进入时读取，并提供重置入口
  assert.match(view, /@header-dragend="\(newWidth, oldWidth, column, source\) => onRegistrationHeaderDragend\(group, newWidth, oldWidth, column, source\)"/)
  assert.match(view, /const REGISTRATION_COLUMN_WIDTH_KEY = 'knowledge_registration_column_widths'/)
  assert.match(view, /localStorage\.setItem\(REGISTRATION_COLUMN_WIDTH_KEY/)
  // 拖动后必须清掉 Element Plus 写入的内部固定宽度，否则重置列宽对这一列失效
  assert.match(view, /column\.width = undefined/)
  assert.match(view, /column\.realWidth = undefined/)
  assert.match(view, /localStorage\.getItem\(REGISTRATION_COLUMN_WIDTH_KEY\)/)
  assert.match(view, /const resetRegistrationColumnWidths = \(\) =>/)
  assert.match(view, /v-if="registrationColumnWidthsCustomized"/)
  assert.match(view, /重置列宽/)
})

test('knowledge hub reports multiple domestic certificates separately when unspecified', () => {
  const view = read('../src/views/KnowledgeHub.vue')

  assert.match(view, /按注册证分别展示/)
  assert.match(view, /registrationGroups/)
  assert.match(view, /registration_number/)
  assert.match(view, /registration_package_name/)
})


test('registration summary tiles filter the strategy table when clicked', () => {
  const view = read('../src/views/KnowledgeHub.vue')

  // 六个分布数字是可点击的筛选入口，而不是纯展示
  assert.match(view, /registrationSummaryTiles/)
  assert.match(view, /class="summary-tile"/)
  assert.match(view, /@click="toggleSummaryTile\(group, tile.key\)"/)
  assert.match(view, /data-testid="`registration-summary-tile-\$\{tile\.key\}`"/)
  assert.match(view, /:aria-pressed="activeSummaryTile\(group\) === tile\.key"/)
  assert.doesNotMatch(view, /<div><strong>\{\{ group\.summary\.registered \}\}/)

  // 表格数据走筛选结果，而不是原始列表
  assert.match(view, /:data="filteredRegistrationItems\(group\)"/)

  // 筛选维度必须与后端统计口径一致：注册状态 + 最终判定
  assert.match(view, /dimension: 'registration', status: 'registered'/)
  assert.match(view, /dimension: 'registration', status: 'unregistered'/)
  assert.match(view, /dimension: 'effective', status: 'X'/)
  assert.match(view, /dimension: 'effective', status: 'O'/)
  assert.match(view, /dimension: 'effective', status: 'Δ'/)
  assert.match(view, /dimension: 'effective', status: '未定义'/)

  // 卡片顺序即渲染顺序：未注册属于例外态，排在策略分布之后
  const tileBlock = view.slice(
    view.indexOf('const registrationSummaryTiles = ['),
    view.indexOf('const summaryTileFilters')
  )
  const tileOrder = [...tileBlock.matchAll(/key: '(\w+)', label: '/g)].map(match => match[1])
  assert.deepEqual(tileOrder, [
    'registered',
    'standard',
    'optional',
    'tender',
    'undefined',
    'unregistered'
  ])

  // 再次点击同一个卡片要能取消筛选，并给出可见的清除入口
  assert.match(view, /if \(next\[id\] === key\) delete next\[id\]/)
  assert.match(view, /const clearSummaryTile = \(group\) =>/)
  assert.match(view, /closable @close="clearRegistrationFilters\(group\)"/)

  // 客户端筛选：分布数字保持整体口径，不因点击而重新请求后端
  assert.match(view, /点击即在当前注册证内筛选表格/)
  assert.doesNotMatch(view, /toggleSummaryTile[\s\S]{0,200}loadRegistrationProbes/)
})


test('frontend API exposes domestic registration query endpoints', () => {
  const api = read('../src/api/data.js')

  assert.match(api, /export const getConfiguredRegistrationModels/)
  assert.match(api, /export const getRegistrationModels/)
  assert.match(api, /export const getRegistrationProbes/)
  assert.match(api, /api\.get\('\/registrations\/configured-models'/)
  assert.match(api, /api\.get\('\/registrations\/models'/)
  assert.match(api, /api\.get\('\/registrations\/probes'/)
  assert.doesNotMatch(api, /\/knowledge\/registration/)
})


test('base data management owns feature identity and registration master data', () => {
  const router = read('../src/router/index.js')
  const layout = read('../src/views/Layout.vue')
  const featureView = read('../src/views/FeatureManage.vue')
  const registrationView = read('../src/views/RegistrationManage.vue')
  const api = read('../src/api/data.js')

  assert.match(router, /path:\s*'registration-manage'/)
  assert.match(router, /name:\s*'RegistrationManage'/)
  assert.match(layout, /index="\/registration-manage"/)
  assert.match(layout, />\s*注册管理\s*</)
  assert.match(featureView, /中文主名称/)
  assert.match(featureView, /英文主名称/)
  assert.match(featureView, /中文曾用名/)
  assert.match(featureView, /英文曾用名/)
  assert.match(featureView, /IPN关系/)
  assert.match(featureView, /getFeatureMasterData/)
  assert.match(featureView, /updateFeatureMasterData/)
  assert.match(registrationView, /注册数据由基础数据统一管理/)
  assert.match(registrationView, /基础探头型号/)
  assert.match(registrationView, /getRegistrationModelProbes/)
  assert.match(api, /export const getFeatureMasterData/)
  assert.match(api, /export const createFeatureMasterData/)
  assert.match(api, /export const updateFeatureMasterData/)
  assert.match(api, /export const getRegistrationModelProbes/)
})


test('registration management shows paired certificate and difference history', () => {
  const registrationView = read('../src/views/RegistrationManage.vue')
  const api = read('../src/api/data.js')

  assert.match(registrationView, /注册资料版本/)
  assert.match(registrationView, /data-testid="registration-package-history"/)
  assert.match(registrationView, /查看注册证/)
  assert.match(registrationView, /查看原注册证/)
  assert.match(registrationView, /supporting_documents/)
  assert.match(registrationView, /查看差异表/)
  assert.match(registrationView, /基线版本/)
  assert.match(registrationView, /注册状态变化/)
  assert.match(registrationView, /getRegistrationPackages/)
  assert.match(registrationView, /getRegistrationPackageVersions/)
  assert.match(api, /export const getRegistrationPackages/)
  assert.match(api, /export const getRegistrationPackageVersions/)
  assert.match(api, /export const getRegistrationPackageVersion/)
})


test('registration management defaults to an original-table-style difference summary', () => {
  const registrationView = read('../src/views/RegistrationManage.vue')
  const api = read('../src/api/data.js')

  assert.match(registrationView, /data-testid="registration-difference-summary"/)
  assert.match(registrationView, /label="差异汇总"/)
  assert.match(registrationView, /label="逐型号明细"/)
  assert.match(registrationView, /不适用\/未注册探头/)
  assert.match(registrationView, /探头全适用/)
  assert.match(registrationView, /getRegistrationDifferenceSummary/)
  assert.match(api, /export const getRegistrationDifferenceSummary/)
  assert.match(api, /package-versions\/\$\{versionId\}\/difference-summary/)
})

test('registration management supports paired upload mapping review and publish', () => {
  const view = read('../src/views/RegistrationManage.vue')
  const api = read('../src/api/data.js')
  assert.match(view, /新增注册资料包/)
  assert.match(view, /注册证文件/)
  assert.match(view, /注册差异表/)
  assert.match(view, /机型映射确认/)
  assert.match(view, /发布正式版本/)
  assert.match(api, /stageRegistrationPackageDraft/)
  assert.match(api, /publishRegistrationPackageVersion/)
  assert.match(api, /setRegistrationPackageEnabled/)
  assert.match(view, /handleTogglePackageEnabled/)
  assert.match(view, /已启用/)
  assert.match(view, /未启用/)
})


test('product model table shows the registration certificate mapping', () => {
  const modelView = read('../src/views/Models.vue')

  assert.match(modelView, /对应注册证/)
  assert.match(modelView, /registration_packages/)
  assert.match(modelView, /registration_number/)
  assert.match(modelView, /registration_model_name/)
  assert.match(modelView, /mapping\.is_enabled/)
})


test('knowledge hub is a read-only aggregate linked to master-data maintenance', () => {
  const view = read('../src/views/KnowledgeHub.vue')

  assert.match(view, /基础数据统一维护/)
  assert.match(view, /to="\/feature-manage"/)
  assert.match(view, /to="\/registration-manage"/)
})


test('knowledge hub supports the confirmed Q&A feedback loop', () => {
  const view = read('../src/views/KnowledgeHub.vue')
  const api = read('../src/api/data.js')

  assert.match(view, /label="问答查询"/)
  assert.match(view, /data-testid="knowledge-question-input"/)
  assert.match(view, /data-testid="ask-knowledge-question"/)
  assert.match(view, /待确认问题/)
  assert.match(view, /确认并发布/)
  assert.match(view, /答案依据/)
  assert.match(view, /变更说明/)
  assert.match(view, /系统不会猜测/)
  assert.match(api, /export const askKnowledgeQuestion/)
  assert.match(api, /export const getKnowledgeQuestions/)
  assert.match(api, /export const publishKnowledgeAnswer/)
  assert.match(api, /export const getKnowledgeAnswerHistory/)
})


test('knowledge hub exposes controlled document extraction and candidate evidence', () => {
  const view = read('../src/views/KnowledgeHub.vue')
  const api = read('../src/api/data.js')

  assert.match(view, /材料候选依据/)
  assert.match(view, /候选内容不能直接作为正式结论/)
  assert.match(view, /作为答案草稿/)
  assert.match(view, /提取正文/)
  assert.match(view, /正文已提取/)
  assert.match(api, /export const extractKnowledgeDocument/)
  assert.match(api, /export const getKnowledgeQuestionCandidates/)
})
