import assert from 'node:assert/strict'
import test from 'node:test'
import { catalogCoverageLabel, catalogCoverageType } from '../src/utils/featureCatalog.js'

test('coverage names configuration completeness without claiming human confirmation', () => {
  assert.equal(catalogCoverageLabel(null), '配置覆盖待加载')
  assert.equal(catalogCoverageType(null), 'info')
  assert.equal(catalogCoverageLabel({ configured_items: 172, covered_items: 40 }), '配置覆盖 40/172')
  assert.equal(catalogCoverageType({ configured_items: 172, covered_items: 40, unlinked_count: 132 }), 'warning')
  assert.equal(catalogCoverageLabel({ configured_items: 172, covered_items: 172 }), '配置覆盖 172/172')
  assert.equal(catalogCoverageType({ configured_items: 172, covered_items: 172, unlinked_count: 0 }), 'success')
  assert.equal(catalogCoverageType({ configured_items: 0, covered_items: 0 }), 'info')
})
