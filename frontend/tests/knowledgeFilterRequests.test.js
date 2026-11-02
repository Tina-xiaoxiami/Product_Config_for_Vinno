import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../src/views/KnowledgeHub.vue', import.meta.url), 'utf8')
const functionSource = source.slice(source.indexOf('let featureRequestId = 0'), source.indexOf('\nconst onFeaturePageSizeChange'))

test('latest feature filter request owns results, total and loading state', async () => {
  const pending = []
  const context = {
    featureLoading: { value: false }, featureLoadError: { value: false }, featureQuery: { value: '' }, identityStatus: { value: 'confirmed' },
    missingName: { value: 'cn' }, featurePage: { value: 3 }, featurePageSize: { value: 50 },
    features: { value: [] }, featureTotal: { value: 0 }, ElMessage: { error() {} },
    getKnowledgeFeatures: params => new Promise(resolve => pending.push({ params, resolve }))
  }
  const { searchFeatures } = new Function(...Object.keys(context), `${functionSource}; return { searchFeatures }`)(...Object.values(context))
  searchFeatures()
  context.missingName.value = 'en'
  searchFeatures()
  assert.equal(pending[1].params.skip, 0)
  assert.equal(pending[1].params.identity_status, 'confirmed')
  pending[0].resolve({ items: [{ id: 1 }], total: 1 })
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(context.featureLoading.value, true)
  pending[1].resolve({ items: [{ id: 2 }], total: 2 })
  await new Promise(resolve => setImmediate(resolve))
  assert.deepEqual(context.features.value, [{ id: 2 }])
  assert.equal(context.featureTotal.value, 2)
  assert.equal(context.featureLoading.value, false)
})

test('failed latest feature query clears stale results and totals', async () => {
  const context = {
    featureLoading: { value: false }, featureLoadError: { value: false }, featureQuery: { value: '' }, identityStatus: { value: '' },
    missingName: { value: 'en' }, featurePage: { value: 1 }, featurePageSize: { value: 50 },
    features: { value: [{ id: 1 }] }, featureTotal: { value: 1 }, ElMessage: { error() {} },
    getKnowledgeFeatures: async () => { throw new Error('offline') }
  }
  const { loadFeatures } = new Function(...Object.keys(context), `${functionSource}; return { loadFeatures }`)(...Object.values(context))
  await loadFeatures()
  assert.deepEqual(context.features.value, [])
  assert.equal(context.featureTotal.value, 0)
  assert.equal(context.featureLoadError.value, true)
  assert.equal(context.featureLoading.value, false)
})
