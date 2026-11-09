import { test, expect } from '@playwright/test'

test('knowledge query uses three scope fields and keeps status beside search', async ({ page }, testInfo) => {
  page.setDefaultTimeout(10000)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const seriesResponse = await page.request.post('/api/series', { data: { name: 'QA-Oversea' } })
  expect(seriesResponse.ok()).toBe(true)
  const series = await seriesResponse.json()
  const modelResponse = await page.request.post('/api/models', { data: { name: 'QA MODEL', series_id: series.id } })
  expect(modelResponse.ok()).toBe(true)
  const model = await modelResponse.json()

  await page.setViewportSize({ width: 1440, height: 960 })
  await page.goto('/knowledge')
  await expect(page.getByRole('tab', { name: '问答查询', exact: true })).toBeVisible()
  await expect(page.locator('.workspace-page-header')).toHaveCount(0)
  await expect(page.locator('.master-data-note')).toHaveCount(0)
  await expect(page.getByRole('textbox', { name: '查询国家代码' })).toHaveCount(0)
  await expect(page.locator('.queue-heading')).toHaveCount(0)
  await expect(page.locator('.knowledge-status')).toHaveCount(0)

  const status = page.getByRole('radiogroup', { name: '问答发布状态' })
  const search = page.getByRole('textbox', { name: '搜索问答问题' })
  const statusBox = await status.boundingBox()
  const searchBox = await search.boundingBox()
  expect(statusBox.x + statusBox.width).toBeLessThan(searchBox.x)
  expect(Math.abs(statusBox.y - searchBox.y)).toBeLessThan(4)
  expect(statusBox.height).toBe(32)
  const marketField = page.locator('.qa-scope-controls > .el-select').first()
  const modelField = page.locator('.qa-scope-controls > .el-select').nth(1)
  const versionField = page.locator('.qa-scope-controls > .el-input')
  expect((await marketField.boundingBox()).width).toBeLessThanOrEqual(200)
  expect((await modelField.boundingBox()).width).toBeLessThanOrEqual(320)
  expect((await versionField.boundingBox()).width).toBeLessThanOrEqual(200)
  expect((await versionField.boundingBox()).height).toBe(32)

  async function chooseSelect(name, option) {
    const control = page.locator('.qa-scope-controls .el-select').filter({ has: page.getByRole('combobox', { name, exact: true }) })
    await control.click()
    const menu = await control.getByRole('combobox').getAttribute('aria-controls')
    await page.locator(`#${menu}`).getByRole('option', { name: option, exact: true }).click()
  }
  await chooseSelect('查询市场', '海外')
  await chooseSelect('查询完整机型', 'QA MODEL · QA-Oversea')
  await page.getByRole('textbox', { name: '查询软件版本' }).fill('1.51.90')
  await page.getByTestId('knowledge-question-input').fill('QA国家筛选取消回归问题')
  const asked = page.waitForResponse(response => response.url().endsWith('/api/knowledge/questions/ask') && response.request().method() === 'POST')
  await page.getByTestId('ask-knowledge-question').click()
  const response = await asked
  expect(response.ok()).toBe(true)
  expect(response.request().postDataJSON().scope).toEqual({ market: 'overseas', product_model_id: model.id, software_version: '1.51.90' })
  expect((await response.json()).status).toBe('pending')
  await expect(page.locator('.qa-result')).toContainText('等待确认')
  await expect(page.locator('.qa-table-area')).toContainText('QA国家筛选取消回归问题')
  await page.screenshot({ path: testInfo.outputPath('knowledge-compact-desktop.png') })

  await page.setViewportSize({ width: 860, height: 720 })
  await expect(page.getByRole('combobox', { name: '查询完整机型' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)).toBe(false)
  await page.screenshot({ path: testInfo.outputPath('knowledge-compact-small.png') })
  expect(errors).toEqual([])
})

test('Office citations reuse the source dialog with structural coordinates and conservative verification', async ({ page }) => {
  const sha = 'a'.repeat(64), documentId = 41, chunkId = 76
  const series = await (await page.request.post('/api/series', { data: { name: 'QA-Office-Viewer-Oversea' } })).json()
  await page.request.post('/api/models', { data: { name: 'QA OFFICE VIEWER', series_id: series.id } })
  let candidate = { document_id: documentId, chunk_id: chunkId, document_title: '合成Office定位资料', version_id: sha, source_ref: '合成结构位置', excerpt: '合成资料中的位置与限制', score: 1, preview_url: `/api/knowledge/documents/${documentId}/preview` }
  const base = () => ({ document_id: documentId, chunk_id: chunkId, version_id: sha, title: candidate.document_title, source_ref: candidate.source_ref, page: null,
    text: '合成原文 <img src=x>，不应解释为HTML。', quote: null, preview_url: `/api/knowledge/documents/${documentId}/preview?version_id=${sha}`,
    verification: { source: 'hash_verified', extraction: 'hash_verified', quote: 'not_requested', structure: 'matched', visual: 'not_checked', human: 'not_reviewed' }, model_answer_eligible: false })
  const paragraph = (body = 3, index = 3) => ({ ...base(), locator: { schema_version: 1, format: 'docx', kind: 'paragraph', document_id: documentId, source_sha256: sha, part: 'word/document.xml', body_index: body, paragraph_index: index } })
  const sheet = (name = '规格 表', index = 1) => ({ ...base(), locator: { schema_version: 1, format: 'xlsx', kind: 'worksheet_row', document_id: documentId, source_sha256: sha, sheet_name: name, sheet_index: index, row_index: 5, range: 'A5:E5', formula_state: 'not_evaluated', cells: [
    { cell: 'A5', column_index: 1, text: '规格', value_type: 'literal', number_format: 'General', merged_range: 'A5:B6' },
    { cell: 'C5', column_index: 3, text: '300 mAh', value_type: 'literal', number_format: '0.00' },
    { cell: 'E5', column_index: 5, text: '=SUM(1,1)', value_type: 'formula', number_format: 'General', formula_state: 'not_evaluated' },
  ] } })
  let reply = paragraph(), status = 200, evidenceCalls = 0, modelPosts = 0
  const popups = []
  page.on('popup', popup => popups.push(popup))
  page.on('request', request => { if (request.method() === 'POST' && /\/knowledge\/document-answer$/.test(new URL(request.url()).pathname)) modelPosts++ })
  await page.route('**/api/knowledge/questions/ask', async route => {
    const original = await route.fetch()
    await route.fulfill({ response: original, json: { ...await original.json(), candidates: [candidate] } })
  })
  await page.route(/\/api\/knowledge\/documents\/41\/evidence\?/, async route => { evidenceCalls++; await route.fulfill({ status, json: reply }) })
  await page.goto('/knowledge')
  async function choose(name, option) {
    const control = page.locator('.qa-scope-controls .el-select').filter({ has: page.getByRole('combobox', { name, exact: true }) })
    await control.click()
    const menu = await control.getByRole('combobox').getAttribute('aria-controls')
    await page.locator(`#${menu}`).getByRole('option', { name: option, exact: true }).click()
  }
  await choose('查询市场', '海外')
  await choose('查询完整机型', 'QA OFFICE VIEWER · QA-Office-Viewer-Oversea')
  await page.getByRole('textbox', { name: '查询软件版本' }).fill('1.51.90')
  async function ask(question) {
    await page.getByTestId('knowledge-question-input').fill(question)
    const answered = page.waitForResponse(response => response.url().endsWith('/api/knowledge/questions/ask') && response.request().method() === 'POST')
    await page.getByTestId('ask-knowledge-question').click(); await answered
    await expect(page.locator('.candidate-card')).toHaveCount(1)
  }
  await ask('合成Office定位验收问题')
  const dialog = page.getByRole('dialog', { name: '原文定位与核验' })
  const table = { ...base(), locator: { schema_version: 1, format: 'docx', kind: 'table_row', document_id: documentId, source_sha256: sha, part: 'word/document.xml', body_index: 4, table_index: 1, row_index: 2,
    cells: [{ cell_index: 1, text: '2.5 mm', grid_span: 2, vertical_merge: 'restart', contains_nested_tables: true }] } }
  for (const [payload, expected] of [[paragraph(), ['正文第3段']], [table, ['表格1', '第2行', '横跨2列', '嵌套表格']], [paragraph(5, 4), ['正文第4段']], [sheet(), ['规格 表', 'A5:E5', 'C5', '=SUM(1,1)', '未求值', 'A5:B6']], [sheet('其他', 2), ['其他', '工作表序号2']]]) {
    reply = payload
    await page.locator('.candidate-card').click()
    await expect(dialog.getByTestId('office-location')).toBeVisible()
    for (const value of [...expected, '文件指纹', sha, '未进行原页视觉核验', '未人工确认', '正式生产问答']) await expect(dialog).toContainText(value)
    await expect(dialog.locator('iframe')).toHaveCount(0)
    await expect(dialog.locator('img')).toHaveCount(0)
    await expect(dialog.getByRole('link')).toHaveAttribute('href', `/api/knowledge/documents/${documentId}/preview?version_id=${sha}`)
    await dialog.getByRole('button', { name: '关闭', exact: true }).click()
  }
  const invalidRange = sheet(); invalidRange.locator.range = 'B5:E5'
  const invalidHash = paragraph(); invalidHash.locator.source_sha256 = 'b'.repeat(64)
  const unsupported = paragraph(); unsupported.locator.format = 'xls'
  for (const [code, payload] of [[200, invalidRange], [200, invalidHash], [200, unsupported], [409, { detail: '原件已换版' }], [410, { detail: '原件不可用' }], [422, { detail: '旧XLS结构定位尚未支持' }]]) {
    status = code; reply = payload
    await page.locator('.candidate-card').click()
    await expect(dialog.getByTestId('verified-citation')).toHaveCount(0)
    await expect(dialog.locator('.el-alert')).toBeVisible()
    await dialog.getByRole('button', { name: '关闭', exact: true }).click()
  }
  candidate = { ...candidate, version_id: null }
  await ask('合成Office缺版本定位问题')
  const callsBefore = evidenceCalls
  await page.locator('.candidate-card').click()
  await expect(dialog).toContainText('缺少版本或准确位置')
  expect(evidenceCalls).toBe(callsBefore); expect(popups).toHaveLength(0); expect(modelPosts).toBe(0)
})


test('draft question, answer table and original cited rows stay together when edited', async ({ page }) => {
  const id = 785, documentId = 41, sha = 'a'.repeat(64)
  const citation = {
    id: 1, document_id: documentId, document_title: '续航实测表', source_ref: '工作表 实测 · 第 3 行（原表隐藏行）',
    preview_url: `/api/knowledge/documents/${documentId}/preview`
  }
  let draft = {
    id, question_text: '旧续航问题', status: 'pending', scope: null, asked_count: 0,
    answer: { id, answer_text: '旧纯文本答案', version: 1, review_status: 'draft', citations: [citation] }
  }
  await page.route(/\/api\/knowledge\/questions\?/, route => route.fulfill({
    json: { items: [draft], total: 1, skip: 0, limit: 20 }
  }))
  await page.route(`**/api/knowledge/questions/${id}/spreadsheet-citations?*`, route => route.fulfill({
    json: { warnings: [], tables: [{
      title: citation.document_title, sheet_name: '实测', header_row: 1, columns: ['模式', '时长'], column_letters: ['B', 'C'],
      preview_url: `${citation.preview_url}?version_id=${sha}`,
      rows: [{ row_number: 3, hidden: true, cells: ['B', '52 分钟'], citation_ids: [citation.id] }]
    }] }
  }))
  const answer = '52 分钟。\n\n| 模式 | 时长 |\n| --- | --- |\n| B | 52 分钟 |'
  await page.route(`**/api/knowledge/questions/${id}/draft-answer`, async route => {
    const body = route.request().postDataJSON()
    expect(body).toEqual({ question_text: 'V10 的续航是多少？', answer_text: answer, expected_version: 1, change_note: '按原表修订' })
    draft = { ...draft, question_text: body.question_text, answer: { ...draft.answer, answer_text: body.answer_text, version: 2 } }
    await route.fulfill({ json: draft })
  })
  await page.goto('/knowledge')
  await page.getByText('历史范围待核实', { exact: true }).first().click()
  await expect(page.getByTestId('qa-answer-preview')).toContainText('旧纯文本答案')
  await page.getByRole('button', { name: '修订', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '修订答案草稿' })
  await expect(dialog.getByText('原表隐藏行', { exact: true })).toBeVisible()
  await expect(dialog.getByRole('link', { name: '查看原件' })).toHaveAttribute('href', `${citation.preview_url}?version_id=${sha}`)
  await dialog.getByRole('textbox', { name: '问题', exact: true }).fill('V10 的续航是多少？')
  await dialog.locator('textarea').fill(answer)
  await dialog.getByRole('button', { name: '预览答案', exact: true }).click()
  await expect(dialog.locator('.answer-editor-preview')).toContainText('时长')
  await dialog.getByPlaceholder('例如：产品经理首次确认；依据 1.14.80 版本修订').fill('按原表修订')
  await dialog.getByRole('button', { name: '保存草稿' }).click()
  await expect(dialog).not.toBeVisible()
  await expect(page.locator('.qa-table-area')).toContainText('V10 的续航是多少？')
  await page.getByRole('button', { name: '全文', exact: true }).click()
  const details = page.getByTestId('qa-answer-full')
  await expect(details).toContainText('52 分钟')
  await expect(details).toContainText('原表隐藏行')
})
