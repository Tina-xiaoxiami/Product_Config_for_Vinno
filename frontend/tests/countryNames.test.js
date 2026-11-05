import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { formatCountryCode } from '../src/utils/countryNames.js'

test('country labels retain codes and provide Chinese region names', () => {
  assert.equal(formatCountryCode('AR'), '阿根廷（AR）')
  assert.equal(formatCountryCode('BR'), '巴西（BR）')
  assert.equal(formatCountryCode('ZZ'), 'ZZ')
  assert.equal(formatCountryCode(''), '')
})

test('overseas country selector and results use the same label while filtering by code', () => {
  const view = readFileSync(new URL('../src/views/RegistrationManage.vue', import.meta.url), 'utf8')
  assert.match(view, /formatCountryCode\(country\.country_code\)/)
  assert.match(view, /:value="country\.country_code"/)
  assert.match(view, /formatCountryCode\(scope\.row\.country_code\)/)
  assert.match(view, /v-model="overseasCountryCode"\s+clearable\s+filterable/)
})
