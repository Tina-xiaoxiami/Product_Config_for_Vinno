import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../src/views/Compare.vue', import.meta.url), 'utf8')
const ref = value => ({ value })

function deferred() {
  let resolve
  let reject
  const promise = new Promise((onResolve, onReject) => {
    resolve = onResolve
    reject = onReject
  })
  return { promise, resolve, reject }
}

function modelLoader(getModels) {
  const context = {
    modelLoadRequest: 0,
    selectedSeries: ref([1]),
    seriesList: ref([{ id: 1, name: 'One' }, { id: 2, name: 'Two' }]),
    allModelsMap: ref(new Map()),
    selectedModels: ref([]),
    referenceModel: ref(null),
    modelFilterText: ref(''),
    getModels,
    console: { error() {} }
  }
  const code = source.slice(
    source.indexOf('let pendingModelSelection ='),
    source.indexOf('// 获取型号名称')
  )
  const loadModels = new Function(
    ...Object.keys(context),
    `${code}\nreturn loadModels`
  )(...Object.values(context))
  return { loadModels, ...context }
}

test('latest Compare series load wins and keeps captured series metadata', async () => {
  const slow = deferred()
  const app = modelLoader(seriesId => seriesId === 1
    ? slow.promise
    : Promise.resolve({ items: [{ id: 22, name: 'Model Two' }] }))

  const oldLoad = app.loadModels()
  app.selectedSeries.value = [2]
  await app.loadModels()
  slow.resolve({ items: [{ id: 11, name: 'Model One' }] })
  await oldLoad

  assert.deepEqual(Array.from(app.allModelsMap.value.entries()), [[22, {
    id: 22,
    name: 'Model Two',
    seriesId: 2,
    seriesName: 'Two'
  }]])
})

test('clearing Compare series invalidates an older model request', async () => {
  const slow = deferred()
  const app = modelLoader(() => slow.promise)

  const oldLoad = app.loadModels()
  app.selectedSeries.value = []
  await app.loadModels()
  slow.resolve({ items: [{ id: 11, name: 'Model One' }] })
  await oldLoad

  assert.equal(app.allModelsMap.value.size, 0)
})

test('a current Compare model load clears stale choices while pending and after failure', async () => {
  const pending = deferred()
  const app = modelLoader(() => pending.promise)
  app.allModelsMap.value = new Map([
    [11, { id: 11, name: 'Old One', seriesId: 1, seriesName: 'One' }],
    [12, { id: 12, name: 'Old Two', seriesId: 1, seriesName: 'One' }]
  ])
  app.selectedModels.value = [11, 12]
  app.referenceModel.value = 11
  app.modelFilterText.value = 'Old'
  app.selectedSeries.value = [2]

  const load = app.loadModels()
  assert.equal(app.allModelsMap.value.size, 0)
  assert.deepEqual(app.selectedModels.value, [])
  assert.equal(app.referenceModel.value, null)
  assert.equal(app.modelFilterText.value, '')

  pending.reject(new Error('offline'))
  await load
  assert.equal(app.allModelsMap.value.size, 0)
  assert.deepEqual(app.selectedModels.value, [])
  assert.equal(app.referenceModel.value, null)
})

test('a successful reload restores selected models still present in the current series', async () => {
  const pending = deferred()
  const app = modelLoader(() => pending.promise)
  app.allModelsMap.value = new Map([[11, { id: 11, name: 'Model One', seriesId: 1, seriesName: 'One' }]])
  app.selectedModels.value = [11]
  app.referenceModel.value = 11

  const load = app.loadModels()
  assert.deepEqual(app.selectedModels.value, [])
  pending.resolve({ items: [{ id: 11, name: 'Model One' }, { id: 12, name: 'Model Twelve' }] })
  await load

  assert.deepEqual(app.selectedModels.value, [11])
  assert.equal(app.referenceModel.value, 11)
})

test('overlapping Compare reloads retain valid choices when the newer load wins', async () => {
  const first = deferred()
  const second = deferred()
  let calls = 0
  const app = modelLoader(() => ++calls === 1 ? first.promise : second.promise)
  app.allModelsMap.value = new Map([[11, { id: 11, name: 'Model One', seriesId: 1, seriesName: 'One' }]])
  app.selectedModels.value = [11]
  app.referenceModel.value = 11

  const oldLoad = app.loadModels()
  const latestLoad = app.loadModels()
  second.resolve({ items: [{ id: 11, name: 'Model One' }] })
  await latestLoad
  first.resolve({ items: [] })
  await oldLoad

  assert.deepEqual(app.selectedModels.value, [11])
  assert.equal(app.referenceModel.value, 11)
  assert.deepEqual([...app.allModelsMap.value.keys()], [11])
})
