import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../src/views/KnowledgeHub.vue', import.meta.url), 'utf8')

test('returning to the knowledge workspace refreshes query data without duplicate catalog or registration reads', async () => {
  const start = source.indexOf('useWorkspaceRefresh(() => Promise.all([')
  const end = source.indexOf('\nonMounted(', start)
  const names = ['loadQaModels', 'loadQaQuestions', 'loadDocuments', 'loadQaReviewCount',
    'loadFeatureCoverage', 'loadFeatures', 'loadRegistrationModels']
  const calls = []
  let refresh, options
  const context = Object.fromEntries(names.map(name => [name, async () => calls.push(name)]))
  new Function('useWorkspaceRefresh', 'answerDialogVisible', 'answerSaving', ...names, source.slice(start, end))(
    (callback, settings) => { refresh = callback; options = settings }, { value: false }, { value: false }, ...Object.values(context)
  )
  assert.equal(options.canRefresh(), true)
  await refresh()
  assert.deepEqual(calls, ['loadQaModels', 'loadQaQuestions', 'loadDocuments', 'loadQaReviewCount'])
})

test('retired catalog and registration loaders are absent while the public read APIs remain available', () => {
  assert.doesNotMatch(source, /getKnowledgeFeatures|getKnowledgeFeatureCoverage|getConfiguredRegistrationModels|getRegistrationProbes/)
  assert.doesNotMatch(source, /const loadFeatures|const loadFeatureCoverage|const loadRegistrationModels|const loadRegistrationProbes/)
  const api = readFileSync(new URL('../src/api/data.js', import.meta.url), 'utf8')
  assert.match(api, /export const getKnowledgeFeatures/)
  assert.match(api, /export const getKnowledgeFeatureCoverage/)
  assert.match(api, /export const getRegistrationProbes/)
})
