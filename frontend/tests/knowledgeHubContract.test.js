import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { WORKSPACE_SECTIONS, workspaceForPath } from '../src/utils/workspaceNavigation.js'


const read = (relativePath) => readFileSync(new URL(relativePath, import.meta.url), 'utf8')


test('knowledge hub is reachable from router and primary navigation', () => {
  const router = read('../src/router/index.js')
  const layout = read('../src/views/Layout.vue')

  assert.match(router, /path:\s*'knowledge'/)
  assert.match(router, /name:\s*'KnowledgeHub'/)
  assert.equal(WORKSPACE_SECTIONS.find(section => section.path === '/knowledge')?.label, '产品知识库')
  assert.match(layout, /v-for="section in WORKSPACE_SECTIONS"/)
})






test('frontend API exposes knowledge feature, stats and document endpoints', () => {
  const api = read('../src/api/data.js')

  assert.match(api, /export const getKnowledgeFeatures/)
  assert.match(api, /export const getKnowledgeStats/)
  assert.match(api, /export const getKnowledgeDocuments/)
  assert.match(api, /export const getKnowledgeDocumentPreviewUrl/)
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
  assert.equal(workspaceForPath('/registration-manage').sidebarGroup, '/manage')
  assert.equal(workspaceForPath('/registration-manage').title, '注册管理')
  assert.match(featureView, /中文主名称/)
  assert.match(featureView, /英文主名称/)
  assert.match(featureView, /中文曾用名/)
  assert.match(featureView, /英文曾用名/)
  assert.match(featureView, /IPN关系/)
  assert.match(featureView, /getFeatureMasterData/)
  assert.match(featureView, /updateFeatureMasterData/)
  assert.match(workspaceForPath('/registration-manage').description, /统一管理注册证/)
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

  assert.match(read('../src/utils/tableColumnLayout.js'), /对应注册证/)
  assert.match(modelView, /MODEL_TABLE_COLUMNS/)
  assert.match(modelView, /registration_packages/)
  assert.match(modelView, /registration_number/)
  assert.match(modelView, /registration_model_name/)
  assert.match(modelView, /mapping\.is_enabled/)
})


test('knowledge hub supports the confirmed Q&A feedback loop', () => {
  const view = read('../src/views/KnowledgeHub.vue')
  const api = read('../src/api/data.js')

  assert.match(view, /label="问答查询"/)
  assert.match(view, /data-testid="knowledge-question-input"/)
  assert.match(view, /data-testid="ask-knowledge-question"/)
  assert.match(view, /待确认问题/)
  assert.match(view, /发布草稿/)
  assert.match(view, /答案依据/)
  assert.match(view, /变更说明/)
  assert.match(view, /缺少条件时会提示/)
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
  const documents = read('../src/components/KnowledgeDocumentsWorkspace.vue')
  assert.match(documents, /提取正文/)
  assert.match(documents, /正文已提取/)
  assert.match(api, /export const extractKnowledgeDocument/)
  assert.match(api, /export const getKnowledgeQuestionCandidates/)
})


test('knowledge hub keeps query, feature detail, history and parameter workspaces', () => {
  const view = read('../src/views/KnowledgeHub.vue')
  const tabs = [...view.matchAll(/<el-tab-pane label="([^"]+)" name="([^"]+)"/g)].map(match => [match[1], match[2]])
  assert.deepEqual(tabs, [['问答查询', 'qa'], ['功能详情', 'feature-detail'], ['参数型答案', 'parameters']])
  assert.doesNotMatch(view, /feature-knowledge-list|registration-strategy-table|knowledge-feature-coverage/)
  assert.match(read('../src/views/FeatureManage.vue'), /getFeatureMasterData/)
  assert.match(read('../src/views/RegistrationManage.vue'), /getRegistrationDifferenceSummary/)
  assert.match(read('../src/components/KnowledgeDocumentsWorkspace.vue'), /data-testid="knowledge-document-list"/)
})

test('knowledge hub still provides answer sources, publication and evidence review', () => {
  const view = read('../src/views/KnowledgeHub.vue')
  assert.match(view, /v-for="document in documents"/)
  assert.match(view, /citation.preview_url/)
  assert.match(view, /KnowledgeAnswerReviewDialog/)
  assert.match(view, /questionDisplayText\(row\)/)
  assert.match(view, /answerDisplayText\(qaResult.answer\)/)
  assert.match(view, /revision.answer_text/)
  assert.match(view, /loadDocuments\(\)/)
})
