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
  await expect(page.locator('.knowledge-status')).toBeVisible()

  const status = page.getByRole('radiogroup', { name: '问答发布状态' })
  const search = page.getByRole('textbox', { name: '搜索问答问题' })
  const statusBox = await status.boundingBox()
  const searchBox = await search.boundingBox()
  expect(statusBox.x + statusBox.width).toBeLessThan(searchBox.x)
  expect(Math.abs(statusBox.y - searchBox.y)).toBeLessThan(4)

  async function chooseSelect(name, option) {
    const control = page.locator('.qa-scope-controls .el-select').filter({ has: page.getByRole('combobox', { name, exact: true }) })
    await control.click()
    const menu = await control.getByRole('combobox').getAttribute('aria-controls')
    await page.locator(`#${menu}`).getByRole('option', { name: option, exact: true }).click()
  }
  await chooseSelect('查询市场', '海外')
  await chooseSelect('查询完整机型', 'QA MODEL · QA-Oversea')
  await page.getByRole('textbox', { name: '查询软件版本' }).fill('1.51.90')
  await page.getByTestId('knowledge-question-input').getByRole('textbox').fill('QA国家筛选取消回归问题')
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
