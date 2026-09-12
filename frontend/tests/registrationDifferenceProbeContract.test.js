import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'


const read = relativePath => readFileSync(new URL(relativePath, import.meta.url), 'utf8')


test('difference summary filters affected models by difference probe', () => {
  const view = read('../src/views/RegistrationManage.vue')

  // 下拉只列「有差异的探头」，并标注其影响的机型数量
  assert.match(view, /aria-label="按差异探头筛选"/)
  assert.match(view, /v-model="differenceProbeFilter"/)
  assert.match(view, /v-for="option in differenceProbeOptions"/)
  assert.match(view, /option\.models\.length/)
  assert.match(view, /for \(const probe of model\.unregistered_probes\)/)

  // 选中后只保留受影响机型，提示条可关闭
  assert.match(view, /probe\.probe_model === probeFilter/)
  assert.match(view, /filteredDifferenceModels\.length/)
  assert.match(view, /@close="differenceProbeFilter = ''"/)

  // 命中的探头在单元格内高亮，原有「不适用」口径保持不变
  assert.match(view, /'probe-hit': probe\.probe_model === differenceProbeFilter/)
  assert.match(view, /\.not-applicable \.probe-hit/)
  assert.match(view, /不适用/)

  // 切换注册资料包时清空该筛选
  assert.match(view, /differenceProbeFilter\.value = ''/)
})
