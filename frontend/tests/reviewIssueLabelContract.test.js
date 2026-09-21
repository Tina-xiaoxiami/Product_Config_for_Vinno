import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'


const read = relativePath => readFileSync(new URL(relativePath, import.meta.url), 'utf8')


test('conclusive registration statuses read as conclusions, not as pending work', () => {
  const view = read('../src/views/RegistrationManage.vue')

  // 作者写在表里的结论：无需注册 / 未注册成功 / 已暂停，各自有自己的标签
  assert.match(view, /registration_not_required: '该国无需注册'/)
  assert.match(view, /registration_failed: '注册未成功'/)
  assert.match(view, /registration_suspended: '注册已暂停\/停止'/)

  // 「非最终状态」这种读起来像"还没做完"的说法不该再出现
  assert.doesNotMatch(view, /非最终状态/)
  assert.match(view, /non_final_status: '尚未拿证（进行中\/新地址）'/)
})
