import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'


const read = relativePath => readFileSync(new URL(relativePath, import.meta.url), 'utf8')


test('registration management exposes a simple overseas history query', () => {
  const view = read('../src/views/RegistrationManage.vue')
  const api = read('../src/api/data.js')

  assert.match(view, /label="海外注册查询"/)
  assert.match(view, /data-testid="overseas-registration-query"/)
  assert.match(view, /仅注册历史数据/)
  assert.match(view, /不会进入当前配置管理列表/)
  assert.match(view, /getOverseasRegistrationCountries/)
  assert.match(view, /getOverseasRegistrationRelations/)
  assert.match(api, /api\.get\('\/registrations\/overseas\/countries'/)
  assert.match(api, /api\.get\('\/registrations\/overseas\/relations'/)
})

test('registration management exposes a generic source-row review center', () => {
  const view = read('../src/views/RegistrationManage.vue')
  const api = read('../src/api/data.js')

  assert.match(view, /label="数据审核与修正"/)
  assert.match(view, /data-testid="data-review-center"/)
  assert.match(view, /原始识别值/)
  assert.match(view, /修正后内容/)
  assert.match(view, /查看原文/)
  assert.match(view, /getDataReviewBatches/)
  assert.match(view, /getDataReviewItems/)
  assert.match(view, /updateDataReviewItem/)
  assert.match(api, /api\.get\('\/knowledge\/review-batches'/)
  assert.match(api, /api\.get\('\/knowledge\/review-items'/)
  assert.match(api, /api\.put\(`\/knowledge\/review-items\/\$\{id\}`/)
})
