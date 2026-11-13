import { test, expect } from '@playwright/test'

test('feature scope, independent snapshot and citation return remain in one view', async ({ page }, testInfo) => {
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const series = await (await page.request.post('/api/series', { data: { name: 'KH04-China' } })).json()
  const model = await (await page.request.post('/api/models', { data: { name: 'KH04 MODEL', series_id: series.id } })).json()
  const feature = { id: 21, legacy_name: '超声衰减成像', primary_cn_name: '超声衰减成像', primary_en_name: 'VATT', group_name: 'GI', identity_status: 'confirmed', names: [], ipns: [{ ipn: '6000358', relation_type: 'primary' }] }
  const sha = 'a'.repeat(64)
  const citation = { document_id: 41, chunk_id: 76, document_title: '合成VATT资料', version_id: sha, source_ref: '段落235', excerpt: 'VATT 原文与条件', preview_url: '/api/knowledge/documents/41/preview' }
  await page.route(/\/api\/knowledge\/features\?/, route => route.fulfill({ json: { items: [feature], total: 1 } }))
  await page.route(/\/api\/versions\?/, route => route.fulfill({ json: { items: [{ id: 28, version_number: '1.51.90-正式版' }], total: 1 } }))
  let failure = false, modelCalls = 0, payload
  page.on('request', request => { if (request.url().endsWith('/knowledge/document-answer') && request.method() === 'POST') modelCalls++ })
  await page.route('**/api/knowledge/features/21/detail', async route => {
    payload = route.request().postDataJSON()
    if (failure) return route.fulfill({ status: 503, json: { detail: '资料暂不可用' } })
    await route.fulfill({ json: { feature, status: 'ready', scope: { ...payload.scope, model_name: model.name, series_name: series.name }, issues: [], citations: [citation], history: null,
      configuration: { snapshot: { id: 28, version_number: '1.51.90-正式版' }, model, items: [{ ipn: '6000358', relation_type: 'primary', snapshot_name: '超声衰减成像', selection_config: 'O', selection_label: '选配', current_config_note: '研发备注' }] } } })
  })
  await page.route(/\/api\/knowledge\/documents\/41\/evidence\?/, route => route.fulfill({ json: { document_id: 41, chunk_id: 76, version_id: sha, title: citation.document_title, source_ref: citation.source_ref, page: null, text: citation.excerpt, quote: null, preview_url: citation.preview_url,
    verification: { source: 'hash_verified', extraction: 'hash_verified', quote: 'not_requested', structure: 'matched' },
    locator: { schema_version: 1, format: 'docx', kind: 'paragraph', document_id: 41, source_sha256: sha, part: 'word/document.xml', body_index: 235, paragraph_index: 235 } } }))
  await page.goto('/knowledge?tab=feature-detail')
  const workspace = page.getByTestId('knowledge-feature-detail')
  async function choose(name, option) {
    const control = workspace.locator('.el-select').filter({ has: page.getByRole('combobox', { name, exact: true }) })
    await control.click()
    const id = await control.getByRole('combobox').getAttribute('aria-controls')
    await page.locator(`#${id}`).getByRole('option', { name: option }).click()
  }
  await choose('详情功能', /VATT/)
  await choose('详情市场', '国内')
  await choose('详情完整机型', 'KH04 MODEL · KH04-China')
  await workspace.getByRole('textbox', { name: '详情软件版本' }).fill('1.51.80')
  await choose('详情配置快照', '1.51.90-正式版')
  await workspace.getByRole('button', { name: '查看详情', exact: true }).click()
  await expect(workspace.locator('.detail-result')).toContainText('选配（O）')
  expect(payload.scope.software_version).toBe('1.51.80')
  expect(payload.configuration_version_id).toBe(28)
  await workspace.getByRole('button', { name: /合成VATT资料/ }).click()
  const dialog = page.getByRole('dialog', { name: '原文定位与核验' })
  await expect(dialog.getByTestId('office-location')).toContainText('235')
  await dialog.getByRole('button', { name: '关闭', exact: true }).click()
  await expect(workspace.locator('.detail-result')).toContainText('选配（O）')
  await workspace.getByRole('textbox', { name: '详情软件版本' }).fill('1.51.90')
  await expect(workspace.locator('.detail-result')).toHaveCount(0)
  failure = true
  await workspace.getByRole('button', { name: '查看详情', exact: true }).click()
  await expect(workspace).toContainText('资料暂不可用')
  await expect(workspace.locator('.detail-result')).toHaveCount(0)
  await page.setViewportSize({ width: 860, height: 720 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)).toBe(false)
  await page.screenshot({ path: testInfo.outputPath('feature-detail.png') })
  expect(modelCalls).toBe(0)
  expect(errors).toEqual([])
})

test('failed model directory can be retried directly from feature detail', async ({ page }) => {
  let failed = true, requests = 0
  await page.route(/\/api\/models(?:\?|$)/, async route => {
    if (route.request().method() !== 'GET') return route.continue()
    requests++
    if (failed) return route.fulfill({ status: 503, json: { detail: '目录暂不可用' } })
    await route.continue()
  })
  await page.goto('/knowledge?tab=feature-detail')
  const workspace = page.getByTestId('knowledge-feature-detail')
  await expect(workspace).toContainText('机型目录加载失败')
  failed = false
  await workspace.getByRole('button', { name: '重新加载机型', exact: true }).click()
  await expect(workspace.getByText('机型目录加载失败，请重试后查询', { exact: true })).toHaveCount(0)
  expect(requests).toBeGreaterThan(1)
})
