import { test, expect } from '@playwright/test'

test('master data navigation groups measurement and keeps edited imports on their page', async ({ page }) => {
  page.setDefaultTimeout(10000)
  await page.goto('/models')
  const group = page.getByRole('menuitem', { name: /^基础数据管理/ })
  const measurementLink = group.getByRole('menuitem', { name: '测量库', exact: true })
  await expect(group.getByRole('menuitem', { name: '产品型号', exact: true })).toHaveAttribute('aria-current', 'page')
  await measurementLink.click()
  await expect(page).toHaveURL(/\/measurements$/)
  await expect(page.locator('.measurement-library')).toBeVisible()
  await expect(measurementLink).toBeVisible()
  await expect(measurementLink).toHaveAttribute('aria-current', 'page')
  await page.getByRole('button', { name: '导入人用中文表', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '导入人用测量库' })).toHaveCSS('--el-color-primary', '#2563c9')
  const versionField = page.getByRole('dialog', { name: '导入人用测量库' }).getByLabel('来源版本')
  expect((await versionField.locator('..').boundingBox()).height).toBe(36)
  await page.getByRole('dialog', { name: '导入人用测量库' }).getByLabel('来源版本').fill('尚未导入')
  const goingBack = page.goBack()
  const warning = page.getByRole('dialog', { name: '尚未导入', exact: true })
  await warning.getByRole('button', { name: '继续导入', exact: true }).click()
  await goingBack
  await expect(page).toHaveURL(/\/measurements$/)
  await expect(measurementLink).toHaveAttribute('aria-current', 'page')
  await page.getByRole('dialog', { name: '导入人用测量库' }).getByRole('button', { name: '取消', exact: true }).click()
  await warning.getByRole('button', { name: '放弃', exact: true }).click()
  await group.getByRole('menuitem', { name: '产品型号', exact: true }).click()
  await expect(page.locator('.model-table-area')).toBeVisible()
})

test('workspace frames share typography and surfaces across modules without page overflow', async ({ page }, testInfo) => {
  test.setTimeout(120000)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.setViewportSize({ width: 1440, height: 960 })
  const pages = [
    ['models', '产品型号'], ['template-features', '模板管理'], ['probe-models', '探头管理'],
    ['applications', '应用管理'], ['feature-manage', '功能管理'], ['registration-manage', '注册管理'],
    ['measurements', '测量库'], ['config', '配置管理'], ['compare', '配置对比'],
    ['version-compare', '版本对比'], ['versions', '版本历史'],
    ['probe-config', '探头配置管理'], ['probe-versions', '版本历史'], ['knowledge', '产品知识库']
  ]
  for (const [path, title] of pages) {
    await page.goto(`/${path}`)
    await expect(page.locator('.workspace-page-header')).toHaveCount(0)
    await expect(page.locator('.el-aside .el-menu-item[aria-current="page"]')).toBeVisible()
    await expect(page.locator('.system-workspace > .el-container > .el-main')).toHaveCSS('background-color', 'rgb(238, 243, 249)')
    await expect(page.locator('.workspace-content')).toBeVisible()
    await expect(page.locator('.workspace-module-navigation')).toHaveCount(0)
    await page.waitForLoadState('networkidle')
    const controlSizes = await page.locator('.workspace-content').evaluate(root => {
      const visible = element => element.getClientRects().length && element.getBoundingClientRect().height > 0
      const selectors = [
        '.el-input--small > .el-input__wrapper', '.el-select--small .el-select__wrapper',
        '.el-button--small:not(.is-text):not(.is-link):not(.is-circle)'
      ]
      return selectors.flatMap(selector => [...root.querySelectorAll(selector)].filter(visible).map(element => ({
        selector, height: element.getBoundingClientRect().height
      })))
    })
    for (const control of controlSizes) expect(control.height, `${path}: ${control.selector}`).toBeGreaterThanOrEqual(32)
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)
    expect(overflow, path).toBe(false)
    if (path === 'models') {
      const table = await page.locator('.model-table-area').boundingBox()
      const content = await page.locator('.workspace-content').boundingBox()
      expect(table.height).toBeGreaterThan(200)
      expect(table.y + table.height).toBeLessThanOrEqual(content.y + content.height + 1)
    }
    await page.screenshot({ path: testInfo.outputPath(`${path}.png`), fullPage: false })
  }
  await page.setViewportSize({ width: 860, height: 720 })
  await page.goto('/models')
  await expect(page.locator('.model-table-area')).toBeVisible()
  await expect(page.locator('.system-workspace > .el-container > .el-main')).toHaveCSS('padding', '8px')
  await page.getByRole('button', { name: '收起导航', exact: true }).click()
  await expect(page.getByRole('button', { name: '展开导航', exact: true })).toBeVisible()
  await expect(page.locator('.el-aside')).toHaveCSS('width', '64px')
  await page.waitForLoadState('networkidle')
  const pagination = await page.locator('.pagination-wrapper').boundingBox()
  const content = await page.locator('.workspace-content').boundingBox()
  expect(pagination.y + pagination.height).toBeLessThanOrEqual(content.y + content.height + 1)
  await page.screenshot({ path: testInfo.outputPath('compact-models.png'), fullPage: false })
  expect(errors).toEqual([])
})
