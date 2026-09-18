import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = (relativePath) => readFileSync(new URL(relativePath, import.meta.url), 'utf8')

test('feature release page is reachable from the menu and the router', () => {
  const router = read('../src/router/index.js')
  const layout = read('../src/views/Layout.vue')

  assert.match(router, /path:\s*'release'/)
  assert.match(router, /name:\s*'FeatureRelease'/)
  assert.match(router, /views\/FeatureRelease\.vue/)
  assert.match(layout, /index="\/release"/)
  assert.match(layout, />\s*功能发布\s*</)
  assert.match(layout, /Promotion/)
})

test('feature release page answers which version shipped a feature', () => {
  const view = read('../src/views/FeatureRelease.vue')

  // 查询入口与首发版本结论
  assert.match(view, /data-testid="release-feature-search"/)
  assert.match(view, /data-testid="release-timeline"/)
  assert.match(view, /data-testid="release-first-version"/)
  assert.match(view, /data-testid="release-first-candidate"/)
  assert.match(view, /首发版本/)
  assert.match(view, /首发候选/)
  // 覆盖边界与发布日期来源必须显式告知
  assert.match(view, /timeline\.coverage_note/)
  assert.match(view, /Release Note 正文没有发布日期/)
  // 确认 / 驳回是人工动作，不能自动确认候选
  assert.match(view, /confirmVersion/)
  assert.match(view, /rejectVersion/)
  assert.match(view, /review_status: 'confirmed'/)
})

test('release version rows keep evidence and review state visible', () => {
  const view = read('../src/views/FeatureRelease.vue')

  assert.match(view, /evidenceKindLabel/)
  assert.match(view, /配置变更表/)
  assert.match(view, /正文叙述/)
  assert.match(view, /evidence_source_ref/)
  assert.match(view, /preview_url/)
  assert.match(view, /生命周期/)
  assert.match(view, /配置口径/)
})

test('release introduction keeps the four sections and its own history', () => {
  const view = read('../src/views/FeatureRelease.vue')

  assert.match(view, /data-testid="release-intro-summary"/)
  assert.match(view, /data-testid="release-intro-applications"/)
  assert.match(view, /data-testid="release-intro-save"/)
  assert.match(view, /临床意义/)
  assert.match(view, /工作流程/)
  assert.match(view, /适用范围/)
  assert.match(view, /introHistory/)
  assert.match(view, /introAttachments/)
  // 附件删除要真的调后端，而不是只改本地状态
  assert.match(view, /deleteReleaseAttachment/)
})

test('release backfill previews before writing and lands candidates as pending', () => {
  const view = read('../src/views/FeatureRelease.vue')
  const api = read('../src/api/data.js')

  assert.match(view, /data-testid="release-backfill-preview"/)
  assert.match(view, /data-testid="release-backfill-apply"/)
  assert.match(view, /只预览/)
  assert.match(view, /ElMessageBox\.confirm/)
  assert.match(view, /待复核/)
  assert.match(view, /is_first_release_candidate/)
  assert.match(api, /export const previewReleaseBackfill/)
  assert.match(api, /export const applyReleaseBackfill/)
  // 落库接口必须显式带 apply 标记
  assert.match(api, /apply:\s*true/)
})

test('feature release api surface matches the backend routes', () => {
  const api = read('../src/api/data.js')

  assert.match(api, /getFeatureReleaseTimeline[\s\S]{0,80}\/release\/features\/\$\{featureId\}\/versions/)
  assert.match(api, /export const createFeatureReleaseVersion/)
  assert.match(api, /export const getReleaseVersions/)
  assert.match(api, /export const updateReleaseVersion/)
  assert.match(api, /export const deleteReleaseVersion/)
  assert.match(api, /export const getReleaseOverview/)
  assert.match(api, /export const getReleaseEvidenceDocuments/)
  assert.match(api, /export const getReleaseIntroduction\b/)
  assert.match(api, /export const saveReleaseIntroduction/)
  assert.match(api, /export const getReleaseIntroductionHistory/)
  assert.match(api, /export const uploadReleaseAttachment/)
  assert.match(api, /introduction\/attachments/)
})
