import { test, expect } from '@playwright/test'

const longName = 'Elastic imaging 压力式弹性成像以及超长功能名称用于验证省略号'
const features = Array.from({ length: 36 }, (_, i) => ({ id: i + 1000, name: i === 0 ? longName : `功能 ${i + 1}`, group_id: i < 18 ? 10 : 20, probe_matrix_enabled: true }))
const categories = Array.from({ length: 18 }, (_, i) => ({ id: i + 1000, name: `探头类别 ${i + 1}` }))
async function fixture(page) {
  // Real component and Element Plus layout with deterministic wide catalog data.
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    let data
    if (path === '/api/template-features/catalog') data = { items: features, matrix_items: features, total: features.length, groups: [{id:10,name:'基础功能'},{id:20,name:'血流'}] }
    else if (path === '/api/probe-categories') data = { items: categories, total: categories.length }
    else if (/\/probe-categories\/\d+\/apps$/.test(path)) data = {regular:[{id:1,name:'很长的常规应用名称用于确认省略'}],poc:[]}
    else if (path === '/api/template-features/drafts') data = { drafts: [], catalog_additions: [], total: 0 }
    else if (/^\/api\/template-features\/by-category\/\d+$/.test(path)) data = features.map(f => ({feature_id:f.id,default_support:'supported'}))
    else if (path === '/api/features/standards/flags') data = { by_feature:{},by_name:{},checks_by_feature:{} }
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
  await page.getByRole('button',{name:'列设置',exact:true}).click()
  const settings=page.getByRole('dialog',{name:'列设置',exact:true})
  await settings.getByRole('spinbutton',{name:longName+'列宽',exact:true}).fill('210')
  await settings.getByRole('button',{name:'上移'+longName,exact:true}).click()
  await settings.getByRole('button',{name:'应用',exact:true}).click()
  await expect(page.getByText('编辑中 — 1 项修改',{exact:true})).toBeVisible()
  await expect(page.getByRole('button',{name:'保存草稿',exact:true})).toBeEnabled()
  expect(Math.round((await firstHeader.boundingBox()).width)).toBe(210)
  await page.getByRole('button',{name:'列设置',exact:true}).click()
  await settings.getByRole('button',{name:'恢复默认布局',exact:true}).click()
  await settings.getByRole('button',{name:'应用',exact:true}).click()
  await expect(page.getByText('编辑中 — 1 项修改',{exact:true})).toBeVisible()
  expect(Math.round((await firstHeader.boundingBox()).width)).toBe(110)
})
