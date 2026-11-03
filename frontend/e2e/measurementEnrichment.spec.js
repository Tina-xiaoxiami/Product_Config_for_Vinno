import { test, expect } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

test('calculation suggestions filter provisionally and require an explicit human review', async ({ page }, testInfo) => {
  page.setDefaultTimeout(10000)
  await page.setViewportSize({ width: 1800, height: 1000 })
  const buffer = await readFile(fileURLToPath(new URL('./fixtures/measurement-human.xlsx', import.meta.url)))
  const imported = await page.request.post('/api/measurements/import', { multipart: {
    version: 'enrichment-browser-check', file: { name: 'measurement-human.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer }
  } })
  expect(imported.ok()).toBe(true)
  const batchId = (await imported.json()).batch_id
  const libraryResponse = await page.request.get(`/api/measurements?batch_id=${batchId}`)
  const library = await libraryResponse.json()
  const raw = library.entries.find(row => row.kind === 'calculation')
  const input = library.entries.find(row => row.kind === 'measurement')
  const payload = { categories: ['CARD'], modes: ['Tissue', 'Doppler'], input_terms: [{ term: '隔离回归输入', possible_dependencies: [{ kind: 'measurement', item_id: input.item_id }], uncertainty: '测试候选，非正式资料', relation_kind: 'input' }],
    formula_reference: '仅用于隔离回归的参考说明', sources: [{ url: 'https://www.asecho.org/', title: '隔离回归来源占位', publisher: '测试', locator: '测试段落', supports: ['测试数据'] }],
    uncertainties: ['仅在隔离测试数据库中使用'], research_status: 'proposed', mapping_basis: 'test_fixture' }
  const candidate = await page.request.post('/api/measurements/enrichment/import', { data: {
    batch_id: batchId, expected_sha256: library.batch.sha256, expected_version: library.batch.version, schema_version: 1,
    candidates: [{ item_id: raw.item_id, payload }]
  } })
  expect(candidate.ok()).toBe(true)
  await page.goto('/measurements')
  const choose = async (control, checked = true) => {
    if (await control.isChecked() !== checked) await control.locator('..').click()
    if (checked) await expect(control).toBeChecked()
    else await expect(control).not.toBeChecked()
  }
  const parent = page.getByRole('radiogroup', { name: '测量分类' })
  const child = page.getByRole('radiogroup', { name: '记录类型' })
  const pending = page.getByRole('checkbox', { name: '包含待核对建议', exact: true })
  await page.getByPlaceholder('查找 Id、英文 UI 或中文 UI 名称').fill(raw.item_id)
  await choose(parent.getByRole('radio', { name: '应用测量', exact: true }))
  await choose(child.getByRole('radio', { name: '计算项', exact: true }))
  await expect(page.getByText('1 / 1 条', { exact: true })).toBeVisible()
  await expect(page.getByRole('cell', { name: '待核对', exact: true })).toBeVisible()

  await page.getByRole('button', { name: '筛选关联模式', exact: true }).click()
  const popover = page.locator('.el-popover:visible')
  await popover.getByRole('button', { name: '清空搜索结果', exact: true }).click()
  await choose(popover.getByRole('checkbox', { name: 'Doppler', exact: true }))
  await page.getByPlaceholder('查找 Id、英文 UI 或中文 UI 名称').click()
  await choose(pending, false)
  await expect(page.getByText('当前条件未命中', { exact: true })).toBeVisible()
  await choose(pending, true)
  await expect(page.getByText('1 / 1 条', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '筛选关联模式', exact: true })).toHaveClass(/el-button--primary/)

  await page.getByRole('button', { name: '核对建议', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '计算项补充资料人工核对', exact: true })
  await expect(dialog.getByRole('combobox', { name: '人工核对分类', exact: true })).toBeVisible()
  await dialog.screenshot({ path: testInfo.outputPath('measurement-review-dialog.png') })
  await dialog.getByRole('textbox', { name: '本次核对人', exact: true }).fill('回归核对')
  await dialog.getByRole('button', { name: '关闭', exact: true }).click()
  await page.getByRole('dialog', { name: '未保存的人工核对', exact: true }).getByRole('button', { name: '继续核对', exact: true }).click()
  await expect(dialog.getByRole('textbox', { name: '本次核对人', exact: true })).toHaveValue('回归核对')
  const modes = dialog.locator('.el-select').filter({ has: page.getByRole('combobox', { name: '人工核对模式', exact: true }) })
  await modes.click()
  const menu = await modes.getByRole('combobox').getAttribute('aria-controls')
  await page.locator(`#${menu}`).getByRole('option', { name: 'Tissue', exact: true }).click()
  await dialog.getByRole('heading', { name: '公开来源', exact: true }).click()
  await dialog.getByRole('button', { name: '确认人工核对结果', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  await choose(pending, false)
  await expect(page.getByText('1 / 1 条', { exact: true })).toBeVisible()
  await expect(page.getByRole('cell', { name: '已核对补充', exact: true })).toBeVisible()
  await expect(page.getByRole('cell', { name: 'Doppler', exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('measurement-reviewed-table.png') })

  const after = await (await page.request.get(`/api/measurements?batch_id=${batchId}`)).json()
  const saved = after.entries.find(row => row.id === raw.id)
  for (const key of Object.keys(raw).filter(key => key !== 'enrichment')) expect(saved[key], key).toEqual(raw[key])
  expect(saved.enrichment.confirmed_payload.modes).toEqual(['Doppler'])
  await page.getByRole('button', { name: '核对建议', exact: true }).click()
  await expect(dialog.getByRole('button', { name: '撤销确认', exact: true })).toBeVisible()
  await expect(dialog.getByRole('combobox', { name: '人工核对模式', exact: true }).locator('..').locator('..')).not.toContainText('Tissue')
  await dialog.getByRole('textbox', { name: '核对说明', exact: true }).fill('撤销隔离回归确认')
  await dialog.getByRole('button', { name: '撤销确认', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  await expect(page.getByText('当前条件未命中', { exact: true })).toBeVisible()
})
