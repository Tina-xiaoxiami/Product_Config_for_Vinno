import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
const source = readFileSync(new URL('../src/views/Config.vue', import.meta.url), 'utf8')
function state(overrides = {}) {
  const code = source.match(/const getConfigEmptyState = [\s\S]*?(?=const configEmptyState =)/)
  assert.ok(code, 'empty table must explain the current selection and offer recovery')
  const getState = new Function(`${code[0]};return getConfigEmptyState`)()
  return getState({ seriesCount: 1, modelCount: 1, fieldCount: 1, hasFilters: false, ...overrides })
}
test('empty table distinguishes missing series and model selections', () => {
  assert.match(state({ seriesCount: 0 }).description, /产品系列/)
  assert.equal(state({ modelCount: 0 }).action, 'models')
  assert.match(state({ modelCount: 0 }).description, /机型/)
})
test('empty table points unmatched filters and hidden columns to their recovery controls', () => {
  assert.equal(state({ hasFilters: true }).action, 'filters')
  assert.doesNotMatch(state({ hasFilters: true }).description, /导入/)
  assert.match(state({ fieldCount: 0 }).description, /列筛选/)
})
