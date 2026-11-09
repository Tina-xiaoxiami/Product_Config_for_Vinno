import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'


const read = relativePath => readFileSync(new URL(relativePath, import.meta.url), 'utf8')


test('the review center handles one issue type at a time instead of row by row', () => {
  const view = read('../src/views/RegistrationManage.vue')
  const api = read('../src/api/data.js')

  // 按问题类型分组：每类给出条数，并提供「确认这类 / 排除这类」
  assert.match(view, /按问题类型批量处理/)
  assert.match(view, /reviewIssueSummary\.issues/)
  assert.match(view, /issue\.needs_review_count/)
  assert.match(view, /openIssueBatch\(issue, 'confirmed'\)/)
  assert.match(view, /openIssueBatch\(issue, 'excluded'\)/)

  // 冻结批次禁用入口，而不是让用户点了才报错
  assert.match(view, /:disabled="!reviewBatchEditable"/)

  // 先预览（dry_run: true）再落库（dry_run: false）
  assert.match(view, /dry_run: true/)
  assert.match(view, /dry_run: false/)

  // 修改人是留痕的一部分，落库前必填
  assert.match(view, /issueBatchChangedBy/)
  assert.match(view, /请填写修改人/)

  // 命中条数超过阈值时必须输入条数
  assert.match(view, /preview\.requires_confirm_count/)
  assert.match(view, /issueBatchConfirmCount/)

  assert.match(api, /knowledge\/review-items\/issue-summary/)
  assert.match(api, /knowledge\/review-items\/batch-confirm/)
})


test('batch review keeps per-row traceability and never rewrites original values', () => {
  const view = read('../src/views/RegistrationManage.vue')

  // 批量动作明确告知：原文与识别值不变，每行各留一条记录
  assert.match(view, /批量动作不会改动原文与识别值/)
  assert.match(view, /每行各留一条审核记录/)
  // 排除不等于删除：仍然只是审核状态
  assert.match(view, /review_status: issueBatchStatus\.value/)
})


test('release review can confirm a whole version or just the first-release candidates', () => {
  const view = read('../src/views/FeatureRelease.vue')
  const api = read('../src/api/data.js')

  assert.match(view, /data-testid="release-batch-confirm-version"/)
  assert.match(view, /data-testid="release-batch-first-candidate"/)
  assert.match(view, /确认首发候选/)
  assert.match(view, /first_candidate_only: true/)
  assert.match(view, /data-testid="release-batch-dialog"/)
  // 预览与落库分开：先 dry_run，再显式落库
  assert.match(view, /dry_run: true/)
  assert.match(view, /dry_run: false/)
  // 操作人写进留痕
  assert.match(view, /data-testid="release-operator"/)
  assert.match(view, /data-testid="release-batch-changed-by"/)
  // 单条确认也带操作人，留痕里不能只有结果没有责任人
  assert.match(view, /changed_by: releaseOperator\.value\.trim\(\) \|\| undefined/)

  assert.match(api, /release\/versions\/batch-review/)
})
