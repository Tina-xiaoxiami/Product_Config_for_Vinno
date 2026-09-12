import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'


const read = relativePath => readFileSync(new URL(relativePath, import.meta.url), 'utf8')


test('overseas name mappings can be managed from the UI and reused on import', () => {
  const view = read('../src/views/RegistrationManage.vue')
  const api = read('../src/api/data.js')

  // 海外 tab 有入口，弹窗说明「编辑一次、后续沿用」且不改原件
  assert.match(view, /openNameMappings/)
  assert.match(view, /海外名称映射（编辑一次，后续导入自动沿用）/)
  assert.match(view, /不会改写受控原件/)

  // 可登记、可删除
  assert.match(view, /const saveNameMapping = async/)
  assert.match(view, /const removeNameMapping = async/)
  assert.match(view, /原表写法，如 X4-12/)
  assert.match(view, /系统名称，如 X4-12L/)
  assert.match(view, /确认人（必填）/)

  assert.match(api, /export const getOverseasNameMappings/)
  assert.match(api, /export const saveOverseasNameMapping/)
  assert.match(api, /export const deleteOverseasNameMapping/)
  assert.match(api, /registrations\/overseas\/name-mappings/)
})
