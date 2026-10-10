import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../src/views/Compare.vue', import.meta.url), 'utf8')
const ref = value => ({ value })

function deferred() {
  let resolve
  const promise = new Promise(onResolve => { resolve = onResolve })
  return { promise, resolve }
}

function modelLoader(getModels) {
  const context = {
    modelLoadRequest: 0,
    selectedSeries: ref([1]),
    seriesList: ref([{ id: 1, name: 'One' }, { id: 2, name: 'Two' }]),
    allModelsMap: ref(new Map()),
    selectedModels: ref([]),
    getModels,
    console: { error() {} }
  }
  const code = source.slice(
    source.indexOf('const loadModels ='),
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
