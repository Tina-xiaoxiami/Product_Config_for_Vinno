import { test, expect } from '@playwright/test'

const longName = 'Elastic imaging 压力式弹性成像以及超长功能名称用于验证省略号'
const features = Array.from({ length: 36 }, (_, i) => ({ id: i + 1000, name: i === 0 ? longName : `功能 ${i + 1}`, ipn: String(770000 + i), group_id: i < 18 ? 10 : 20, probe_matrix_enabled: true }))
const categories = Array.from({ length: 18 }, (_, i) => ({ id: i + 1000, name: `探头类别 ${i + 1}` }))
async function fixture(page) {
  // Real component and Element Plus layout with deterministic wide catalog data.
  let displayName = ''
  const savedDrafts = []
  const nameDetail = () => ({ name: '功能 2', display_name: displayName, default_display_name: '功能 2', primary_cn_name: '功能 2', primary_en_name: 'Feature Two', checks: [] })
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    let data
    if (path === '/api/template-features/catalog') data = { items: features, matrix_items: features, total: features.length, groups: [{id:10,name:'基础功能'},{id:20,name:'血流'}] }
    else if (path === '/api/probe-categories') data = { items: categories, total: categories.length }
    else if (/\/probe-categories\/\d+\/apps$/.test(path)) data = {regular:[{id:1,name:'很长的常规应用名称用于确认省略'}],poc:[]}
    else if (path === '/api/template-features/drafts') data = { drafts: savedDrafts, catalog_additions: [], total: savedDrafts.length }
    else if (path === '/api/template-features/save-draft') {
      savedDrafts.push(route.request().postDataJSON())
      data = {}
    }
    else if (/^\/api\/template-features\/by-category\/\d+$/.test(path)) data = features.map(f => ({feature_id:f.id,default_support:'supported'}))
    else if (path === '/api/features/standards/reviews/1001') data = nameDetail()
    else if (path === '/api/features/standards/reviews/1001/display-name' && route.request().method() === 'PUT') {
      displayName = route.request().postDataJSON().name
      data = nameDetail()
    } else if (path === '/api/features/standards/flags') data = { by_feature: {}, by_name: {}, checks_by_feature: { 1001: { feature_cn_name: '功能 2', feature_display_name: displayName } } }
    else return route.continue()
    await route.fulfill({ json: data })
  })
  await page.goto('/template-features')
  await expect(page.locator('.matrix-feature-label').first()).toHaveText(longName)
}

for (const viewport of [{width:1440,height:900},{width:860,height:600}]) {
  test(`template matrix stays scrollable and truncated at ${viewport.width}px`, async ({page},testInfo) => {
    await page.setViewportSize(viewport)
    await fixture(page)
    const table=page.locator('.table-wrap'), wrap=table.locator('.el-scrollbar__wrap')
    const bounds=await table.boundingBox()
    expect(bounds.y+bounds.height).toBeLessThanOrEqual(viewport.height)
    expect((await table.locator('.el-table__header-wrapper').boundingBox()).height).toBeLessThan(100)
    expect((await table.locator('.el-table__body-wrapper').boundingBox()).height).toBeGreaterThan(100)
    await expect(table.locator('.el-scrollbar__bar.is-horizontal')).toBeVisible()
    await expect(page.locator('.matrix-feature-label').first()).toHaveCSS('text-overflow','ellipsis')
    await expect(table.locator('.probe-support-cell').first()).toHaveCSS('white-space','nowrap')
    const initial=await wrap.evaluate(e=>e.scrollLeft)
    await page.getByRole('button',{name:'向右查看功能',exact:true}).click()
    expect(await wrap.evaluate(e=>e.scrollLeft)).toBeGreaterThan(initial)
    // Native horizontal track reaches the last feature; identity columns remain fixed.
    await wrap.evaluate(e=>{e.scrollLeft=e.scrollWidth;e.scrollTop=e.scrollHeight})
    await expect(table.getByText('功能 36',{exact:true}).first()).toBeInViewport()
    await expect(table.getByText('探头类别 18',{exact:true})).toBeInViewport()
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true)
    await page.screenshot({path:testInfo.outputPath('template-matrix-scroll.png')})
  })
}

test('drag resize, keyboard width settings, reorder and reset preserve an unsaved edit',async({page})=>{
  await page.setViewportSize({width:1280,height:800})
  await fixture(page)
  const firstHeader=page.locator('th').filter({has:page.locator('.matrix-feature-label').filter({hasText:longName})})
  const original=await firstHeader.boundingBox()
  await page.mouse.move(original.x+original.width-2,original.y+original.height/2)
  await page.mouse.down()
  await page.mouse.move(original.x+original.width+58,original.y+original.height/2,{steps:5})
  await page.mouse.up()
  await expect.poll(async()=>Math.round((await firstHeader.boundingBox()).width)).toBe(Math.round(original.width+60))
  await page.reload()
  await expect.poll(async()=>Math.round((await firstHeader.boundingBox()).width)).toBe(Math.round(original.width+60))
  await page.getByRole('button',{name:'编辑模式',exact:true}).click()
  await page.locator('.tpl-cell').first().click()
  const popover=page.locator('.el-popover:visible')
  await popover.getByText('不支持',{exact:true}).click()
  await popover.getByRole('button',{name:'确定',exact:true}).click()
  await expect(page.getByText('编辑中 — 1 项修改',{exact:true})).toBeVisible()
  await page.getByRole('button',{name:'设置',exact:true}).click()
  const settings=page.getByRole('dialog',{name:'设置',exact:true})
  await settings.getByRole('spinbutton',{name:longName+'列宽',exact:true}).fill('210')
  await settings.getByRole('button',{name:'上移'+longName,exact:true}).click()
  await settings.getByRole('button',{name:'应用',exact:true}).click()
  await expect(page.getByText('编辑中 — 1 项修改',{exact:true})).toBeVisible()
  await expect(page.getByRole('button',{name:'保存草稿',exact:true})).toBeEnabled()
  expect(Math.round((await firstHeader.boundingBox()).width)).toBe(210)
  await page.getByRole('button',{name:'设置',exact:true}).click()
  await settings.getByRole('button',{name:'恢复默认布局',exact:true}).click()
  await settings.getByRole('button',{name:'应用',exact:true}).click()
  await expect(page.getByText('编辑中 — 1 项修改',{exact:true})).toBeVisible()
  expect(Math.round((await firstHeader.boundingBox()).width)).toBe(110)
})

test('settings edits a hidden and filtered feature without dropping unsaved settings', async ({ page }) => {
  await fixture(page)
  const headers = page.locator('.matrix-feature-label')
  const settingsButton = page.getByRole('button', { name: '设置', exact: true })
  const settings = page.getByRole('dialog', { name: '设置', exact: true })
  const nameEditor = page.getByRole('dialog', { name: '编辑显示名称', exact: true })
  const editName = settings.getByRole('button', { name: '编辑显示名称', exact: true })
  const search = page.getByPlaceholder('搜索功能名称或IPN', { exact: true })
  await expect(page.locator('.table-wrap').getByRole('button', { name: /^编辑显示名称/ })).toHaveCount(0)

  await settingsButton.click()
  const select = settings.getByRole('combobox')
  await settings.locator('.settings-feature-select').click()
  await select.fill('770001')
  await page.getByRole('option', { name: '功能 2 · IPN 770001', exact: true }).click()
  const visibleColumn = settings.getByRole('checkbox', { name: '显示功能 2', exact: true })
  await visibleColumn.locator('..').click()
  await editName.click()
  await page.getByRole('button', { name: '继续设置', exact: true }).click()
  await expect(visibleColumn).not.toBeChecked()
  await expect(nameEditor).toBeHidden()
  await settings.getByRole('button', { name: '应用', exact: true }).click()
  await expect(headers.filter({ hasText: /^功能 2$/ })).toHaveCount(0)

  const group = page.getByRole('checkbox', { name: '基础功能', exact: true })
  await group.locator('..').click()
  await search.fill('770000')
  await expect(headers).toHaveCount(1)
  await settingsButton.click()
  await editName.click()
  const displayInput = nameEditor.getByPlaceholder('输入中文、英文或缩写')
  await expect(displayInput).toHaveValue('功能 2')
  await displayInput.fill('Feature Two Custom')
  await nameEditor.getByRole('button', { name: '关闭', exact: true }).click()
  await page.getByRole('dialog', { name: '未保存说明' }).getByRole('button', { name: '取消', exact: true }).click()
  await expect(displayInput).toHaveValue('Feature Two Custom')
  const saveRequest = page.waitForRequest(request => request.method() === 'PUT' && request.url().endsWith('/reviews/1001/display-name'))
  await nameEditor.getByRole('button', { name: '保存显示名称', exact: true }).click()
  expect((await saveRequest).postDataJSON()).toEqual({ name: 'Feature Two Custom' })
  await expect(page.getByText('显示名称已保存', { exact: true })).toBeVisible()
  await nameEditor.getByRole('button', { name: '关闭', exact: true }).click()
  await expect(search).toHaveValue('770000')
  await expect(group).toBeChecked()
  await expect(headers).toHaveCount(1)

  await settingsButton.click()
  const renamedColumn = settings.getByRole('checkbox', { name: '显示Feature Two Custom', exact: true })
  await expect(renamedColumn).not.toBeChecked()
  await renamedColumn.locator('..').click()
  await settings.getByRole('button', { name: '应用', exact: true }).click()
  await search.fill('770001')
  await expect(headers).toHaveText('Feature Two Custom')
})

async function keepPageOnReload(page) {
  const [prompt] = await Promise.all([
    page.waitForEvent('dialog', { timeout: 5000 }),
    // A rejected reload never commits a new document. Wait for the prompt instead.
    page.evaluate(() => window.setTimeout(() => window.location.reload(), 0))
  ])
  expect(prompt.type()).toBe('beforeunload')
  await prompt.dismiss()
}

test('matrix input survives rejected close, refresh and navigation', async ({ page }) => {
  await fixture(page)
  await page.getByRole('button', { name: '编辑模式', exact: true }).click()
  await page.locator('.tpl-cell').first().click()
  const cell = page.locator('.el-popover:visible')
  await cell.getByText('不支持', { exact: true }).click()
  const warning = page.getByRole('dialog', { name: '未保存的修改', exact: true })
  const keepEditing = warning.getByRole('button', { name: '继续编辑', exact: true })
  await cell.getByRole('button', { name: '取消', exact: true }).click()
  await keepEditing.click()
  await expect(cell.getByRole('radio', { name: '不支持', exact: true })).toBeChecked()
  await page.getByText('支持', { exact: true }).first().click()
  await keepEditing.click()
  await expect(cell.getByRole('radio', { name: '不支持', exact: true })).toBeChecked()
  await cell.getByRole('button', { name: '确定', exact: true }).click()
  await keepPageOnReload(page)
  const pending = page.getByText('编辑中 — 1 项修改', { exact: true })
  await expect(pending).toBeVisible()

  const otherTab = page.getByRole('tab', { name: '探头&应用', exact: true })
  await otherTab.click()
  await keepEditing.click()
  await expect(page).toHaveURL(/\/template-features$/)
  await expect(pending).toBeVisible()

  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await expect(page.getByText('已保存 1 条草稿，请提交后生效', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '提交并创建版本', exact: true })).toBeEnabled()
  await otherTab.click()
  await expect(page).toHaveURL(/\/probe-models$/)
  await page.getByRole('tab', { name: '模板管理', exact: true }).click()
  await expect(page.getByText(/1 条配置草稿待提交/)).toBeVisible()
})

test('unapplied column layout survives rejected refresh and Escape', async ({ page }) => {
  await fixture(page)
  await page.getByRole('button', { name: '设置', exact: true }).click()
  const settings = page.getByRole('dialog', { name: '设置', exact: true })
  const column = settings.getByRole('checkbox', { name: '显示功能 2', exact: true })
  await column.locator('..').click()
  await keepPageOnReload(page)
  await expect(column).not.toBeChecked()
  await page.keyboard.press('Escape')
  const warning = page.getByRole('dialog', { name: '未应用的列设置', exact: true })
  await warning.getByRole('button', { name: '继续设置', exact: true }).click()
  await expect(column).not.toBeChecked()
  await settings.getByRole('button', { name: '应用', exact: true }).click()
  await expect(page.locator('.matrix-feature-label').filter({ hasText: /^功能 2$/ })).toHaveCount(0)
})
