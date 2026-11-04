import test from 'node:test'
import assert from 'node:assert/strict'
import { loadPaneWidth, paneLayout, savePaneWidth } from '../src/utils/paneWidth.js'

test('pane width respects both sidebar bounds and usable content width', () => {
  assert.deepEqual(paneLayout(1600, 900), { stacked: false, min: 280, max: 640, width: 640 })
  assert.equal(paneLayout(1000, 600).width, 468)
  assert.equal(paneLayout(1000, 10).width, 280)
  assert.equal(paneLayout(1000, NaN).width, 440)
})

test('narrow windows stack panels without discarding the preferred width', () => {
  const preferred = 560
  assert.equal(paneLayout(810, preferred).stacked, true)
  assert.equal(paneLayout(900, preferred).width, 368)
  assert.equal(paneLayout(1600, preferred).width, 560)
})

test('storage accepts only valid widths and tolerates unavailable local storage', () => {
  for (const value of [null, '', 'garbage', '-1', 'Infinity', '999999', '0']) {
    assert.equal(loadPaneWidth({ getItem: () => value }, 'pane'), 440)
  }
  assert.equal(loadPaneWidth({ getItem: () => '512' }, 'pane'), 512)
  const blocked = { getItem() { throw new Error('blocked') }, setItem() { throw new Error('blocked') } }
  assert.equal(loadPaneWidth(blocked, 'pane'), 440)
  assert.doesNotThrow(() => savePaneWidth(blocked, 'pane', 512))
  const values = new Map()
  savePaneWidth({ setItem: (key, value) => values.set(key, value) }, 'pane', 512)
  assert.equal(loadPaneWidth({ getItem: key => values.get(key) }, 'pane'), 512)
})
