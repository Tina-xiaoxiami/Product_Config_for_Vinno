import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
const source=readFileSync(new URL('../src/views/Config.vue',import.meta.url),'utf8')
test('model selector uses shared subseries while matrix retains series grouping',()=>{
  assert.match(source,/v-for="group in filteredModelGroups"[\s\S]*?:key="group.key"/)
  assert.match(source,/sub_series: m.sub_series \|\| \[\]/)
  assert.match(source,/其他机型/)
  assert.match(source,/selectSubseriesModels/)
})
