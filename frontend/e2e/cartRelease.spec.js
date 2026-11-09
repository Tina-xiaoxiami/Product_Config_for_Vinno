import { expect, test } from '@playwright/test'

test('version history shows Cart evidence and offers candidate downloads after retry', async ({ page }) => {
  const key = 'a'.repeat(64)
  await page.route('**/api/series', route => route.fulfill({ json: { items: [{ id: 1, name: 'Example' }] } }))
  await page.route('**/api/versions?*', route => route.fulfill({ json: {
    items: [{ id: 2, version_number: '1.0.2', row_count: 1 }], total: 1
  } }))
  await page.route('**/api/versions/2/cart-release', route => {
    if (route.request().method() === 'GET') {
      return route.fulfill({ json: { status: 'not_checked', reason: '历史版本尚未检查' } })
    }
    return route.fulfill({ json: {
      status: 'generated', reason: '已生成供核对的 PPT 候选', series: 'Example', market: 'domestic',
      version: { number: '1.0.2', key }, previous: { number: '1.0.1' }, artifact_sha256: 'b'.repeat(64),
      changes: [{
        identity: ['ipn', '70001'], before: { ipn: '70001', values: [] },
        after: { ipn: '70002', values: [{ id: '1', model: 'Example 10', final_config: 'O', selection_config: 'O' }] },
        models: ['Example 10'], pages: [7]
      }]
    } })
  })

  await page.goto('/versions')
  await page.getByRole('button', { name: 'Cart 资料' }).click()
  const dialog = page.getByRole('dialog', { name: 'Cart 发货资料 · 1.0.2' })
  await expect(dialog.getByText('历史版本尚未检查')).toBeVisible()
  await dialog.getByRole('button', { name: '补跑检查' }).click()
  await expect(dialog.getByText('已生成候选', { exact: true })).toBeVisible()
  await dialog.getByText('70002 · 第 7 页').click()
  await expect(dialog.getByText('适用型号 Example 10')).toBeVisible()
  await expect(dialog.getByText('修改前')).toBeVisible()
  await expect(dialog.getByText('修改后')).toBeVisible()
  await expect(dialog.getByRole('link', { name: '下载 PPT 候选' })).toHaveAttribute(
    'href', `/api/versions/cart-release/archive/${key}/presentation`
  )
  await expect(dialog.getByRole('link', { name: '下载变更记录' })).toHaveAttribute(
    'href', `/api/versions/cart-release/archive/${key}?download=true`
  )
})
