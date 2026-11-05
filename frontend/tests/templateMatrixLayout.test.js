import test from 'node:test'
import assert from 'node:assert/strict'
import { buildTemplateMatrixColumns, templateMatrixSections, normalizeColumnLayout, saveColumnLayout, loadColumnLayout } from '../src/utils/tableColumnLayout.js'

const features = [{ id: 1, name: '很长的功能中文名称', group_id: 10 }, { id: 2, name: '同名', group_id: 20 }, { id: 3, name: '同名', group_id: 10 }]
const groups = [{ id: 10, name: '基础功能' }, { id: 20, name: '血流' }]
test('template columns retain independent widths and stable feature identity after rename, reorder and refresh', () => {
  const defaults = buildTemplateMatrixColumns(features)
  const saved = normalizeColumnLayout(defaults, [{ key: 'feature:3', width: 935, fixed: true }, { key: 'feature:2', width: 30, visible: false }])
  const data = new Map(), storage = { getItem: key => data.get(key), setItem: (key, value) => data.set(key, value) }
  saveColumnLayout(storage, 'template-matrix-columns-v1', saved)
  const restored = loadColumnLayout(storage, 'template-matrix-columns-v1', buildTemplateMatrixColumns(features.map(f => ({ ...f, name: f.id === 3 ? '改名' : f.name }))))
  assert.equal(restored[0].key, 'feature:3'); assert.equal(restored[0].width, 935); assert.equal(restored[0].label, '改名'); assert.equal(restored[0].fixed, true)
  assert.equal(restored.find(c => c.key === 'feature:1').width, 110)
  assert.equal(restored.find(c => c.key === 'feature:2').visible, false)
})
test('matrix keeps filtered preferences and honors arbitrary order, fixed groups and application toggles', () => {
  const defaults = buildTemplateMatrixColumns(features)
  const columns = normalizeColumnLayout(defaults, [{ key: 'feature:3', fixed: true }, { key: 'category' }, { key: 'feature:2' }, { key: 'regular' }, { key: 'feature:1' }])
  const sections = templateMatrixSections(columns, features, groups, { showRegular: false, showPOC: false })
  assert.deepEqual(sections.map(section => section.key), ['group:10:fixed:feature:3', 'category', 'group:20:normal:feature:2', 'group:10:normal:feature:1'])
  assert.equal(sections[0].columns[0].feature.id, 3)
  assert.equal(sections[0].fixed, true)
  const filtered = templateMatrixSections(columns, [features[0]], groups, { showRegular: true, showPOC: true })
  assert.deepEqual(filtered.flatMap(s => s.columns || []).map(c => c.key), ['feature:1'])
  assert.equal(columns.find(c => c.key === 'feature:3').visible, true)
})
test('new columns receive defaults and removed features cannot steal widths', () => {
  const saved = buildTemplateMatrixColumns(features)
  const updated = normalizeColumnLayout(buildTemplateMatrixColumns([{ id: 4, name: '新增', group_id: 99 }]), saved)
  assert.deepEqual(updated.map(c => c.key), ['category', 'regular', 'poc', 'feature:4'])
  assert.equal(templateMatrixSections(updated, [{id:4,group_id:99}], [], {})[3].label, '未分类')
})
