import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../src/views/Models.vue', import.meta.url), 'utf8')
const ref = value => ({ value })

function harness(confirm = async () => {}, update = async () => {}) {
  const calls = [], errors = [], successes = []
  const context = {
    ref,
    seriesList: ref([{ id: 5, name: 'Tulip-Oversea' }]),
    ElMessageBox: { confirm },
    ElMessage: { error: message => errors.push(message), success: message => successes.push(message) },
    setModelEnabled: async (id, enabled) => { calls.push([id, enabled]); await update() },
    loadData: async () => { calls.push('reload') }
  }
  const code = source.slice(source.indexOf('const changingModelId ='), source.indexOf('let initialized ='))
  return { calls, errors, successes, ...new Function(...Object.keys(context), code + ';return {handleToggleEnabled,changingModelId}')(...Object.values(context)) }
}

test('disabling confirms retained configuration and history; reenable is available', async () => {
  let message
  const app = harness(async text => { message = text })
  await app.handleToggleEnabled({ id: 84, name: 'ULTIMUS 8E-RUA', series_id: 5, is_enabled: true })
  assert.match(message, /停用.*ULTIMUS 8E-RUA/)
  assert.match(message, /保留.*历史/)
  assert.deepEqual(app.calls, [[84, false], 'reload'])
  await app.handleToggleEnabled({ id: 84, name: 'ULTIMUS 8E-RUA', series_id: 5, is_enabled: false })
  assert.deepEqual(app.calls.slice(2), [[84, true], 'reload'])
  assert.equal(app.changingModelId.value, null)
})

test('cancel, duplicate clicks and API failure do not lose model state', async () => {
  for (const reason of ['cancel', 'close']) {
    const app = harness(async () => { throw reason })
    await app.handleToggleEnabled({ id: 84 })
    assert.deepEqual(app.calls, [])
    assert.deepEqual(app.errors, [])
  }
  let resolve
  const pending = new Promise(done => { resolve = done })
  const app = harness(() => pending, async () => { throw { response: { data: { detail: '保存失败' } } } })
  const first = app.handleToggleEnabled({ id: 84 })
  await app.handleToggleEnabled({ id: 85 })
  resolve()
  await first
  assert.deepEqual(app.calls, [[84, false]])
  assert.deepEqual(app.errors, ['保存失败'])
  assert.equal(app.changingModelId.value, null)
})

test('management hides disabled models by default with an explicit opt-in', () => {
  assert.match(source, /showDisabled\s*=\s*ref\(false\)/)
  assert.match(source, /v-model="showDisabled"/)
  assert.match(source, /include_disabled:\s*showDisabled\.value/)
  assert.doesNotMatch(source, /@click="handleDelete\(row\)"/)
})
