import test from 'node:test'
import assert from 'node:assert/strict'
import { buildProbeMatrixRows } from '../src/utils/probeMatrix.js'
import { formatProbeSupport, parseProbeExcludes } from '../src/utils/probeSupport.js'

test('probe matrix uses one material row with feature cells instead of repeated probe/function rows', () => {
  const document = { rows: [
    {probe_model_id:1,variant_id:10,feature_id:1,defined_status:'supported'},
    {probe_model_id:1,variant_id:10,feature_id:2,defined_status:'conditional',defined_excludes:['心脏']},
    {probe_model_id:1,variant_id:11,feature_id:1,defined_status:'supported'},
  ] }
  const catalog = {probes:[{id:1,name:'P1',category_id:1}],variants:[{id:10,ipn:'A',internal_model:'P1a'},{id:11,ipn:'B',internal_model:'P1b'}],categories:[{id:1,name:'凸阵'}]}
  const rows = buildProbeMatrixRows(document, catalog)
  assert.equal(rows.length, 2)
  assert.equal(rows[0].cells[1].defined_status, 'supported')
  assert.equal(rows[0].cells[2].defined_status, 'conditional')
  assert.equal(rows[0].ipn, 'A')
  assert.equal(rows[1].ipn, 'B')
})
test('matrix and template share ALL, supported/excluded and tender formatting', () => {
  assert.equal(formatProbeSupport({status:'supported',apps:['腹部','心脏']}), 'ALL')
  assert.equal(formatProbeSupport({status:'unsupported'}), '—')
  assert.equal(formatProbeSupport({status:'pending'}), '待确认')
  assert.equal(formatProbeSupport({status:'conditional',apps:['腹部','心脏','血管'],excludes:['心脏'],mode:'excluded'}), '除: 心脏')
  assert.equal(formatProbeSupport({status:'conditional',apps:['腹部','心脏'],excludes:['心脏'],mode:'supported'}), '腹部')
  assert.equal(formatProbeSupport({status:'conditional',apps:['腹部'],tender:['特殊应用']}), '支:腹部 | 招:特殊应用')
  assert.deepEqual(parseProbeExcludes('{"excludes":["心脏"],"tender":["特殊应用"]}'), {excludes:['心脏'],tender:['特殊应用']})
})
