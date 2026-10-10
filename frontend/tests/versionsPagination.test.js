import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../src/views/Versions.vue', import.meta.url), 'utf8')

test('version history requests the selected server page and renders pagination', () => {
  assert.match(source, /getVersions\(selectedSeries\.value,\s*\{[\s\S]*?skip:\s*\(currentPage\.value - 1\) \* pageSize\.value,[\s\S]*?limit:\s*pageSize\.value/)
  assert.match(source, /total\.value\s*=\s*res\.total\s*\|\|\s*0/)
  assert.match(source, /<el-pagination[\s\S]*?v-model:current-page="currentPage"[\s\S]*?:total="total"/)
})

test('changing series resets version history to its first page', () => {
  assert.match(source, /const handleSeriesChange = \(\) => \{[\s\S]*?currentPage\.value = 1[\s\S]*?loadVersions\(\)/)
  assert.match(source, /@change="handleSeriesChange"/)
})

test('compare selectors load every version through bounded API pages', () => {
  assert.match(source, /const VERSION_OPTION_PAGE_SIZE = \d+/)
  assert.match(source, /const loadAllVersionOptions = async/)
  assert.match(source, /getVersions\(seriesId,\s*\{\s*skip,\s*limit:\s*VERSION_OPTION_PAGE_SIZE\s*\}\)/)
  assert.match(source, /while \(skip < total\)/)
  assert.match(source, /<el-option v-for="v in versionOptions"/)
})
