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

  // 选中后只保留受影响机型；筛选状态由下拉自身承载（clearable），不再另挂提示条
  assert.match(view, /probe\.probe_model === probeFilter/)
  assert.match(view, /for \(let index = 0; index < filteredDifferenceModels\.value\.length/)
  assert.match(view, /v-model="differenceProbeFilter"[\s\S]{0,400}clearable/)
  assert.doesNotMatch(view, /difference-filter-tag/)

  // 命中的探头在单元格内高亮，原有「不适用」口径保持不变
  assert.match(view, /'probe-hit': probe\.probe_model === differenceProbeFilter/)
  assert.match(view, /\.not-applicable \.probe-hit/)
  assert.match(view, /不适用/)

  // 切换注册资料包时清空该筛选
  assert.match(view, /differenceProbeFilter\.value = ''/)

  // 下拉项精简成「型号（受影响机型数）」：不体现 IPN，也不再写"影响…个机型"的说明
  assert.match(view, /`\$\{option\.probe_model\}（\$\{option\.models\.length\}）`/)
  assert.doesNotMatch(view, /option\.ipn/)
  assert.doesNotMatch(view, /影响 \$\{option\.models\.length\} 个机型/)

  // 筛选控件排在「存在差异探头」这个数字之后，不再占顶部工具栏的轨道
  const metricsIndex = view.indexOf('存在差异探头')
  const filterIndex = view.indexOf('v-model="differenceProbeFilter"')
  assert.ok(metricsIndex > 0 && filterIndex > metricsIndex, '按差异探头筛选应排在「存在差异探头」之后')
  assert.match(view, /grid-template-columns: minmax\(240px, 0\.8fr\) minmax\(220px, 1fr\) auto;/)
  assert.match(view, /\.difference-probe-filter \{ flex: 0 0 240px; width: 240px; \}/)
})
