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
