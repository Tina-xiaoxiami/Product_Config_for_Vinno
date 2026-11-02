import test from 'node:test'
import assert from 'node:assert/strict'
import { buildProbeMatrixRows, newProbeMaterialRows, matrixColumnSegments, probeMaterialExists } from '../src/utils/probeMatrix.js'
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

test('unmatched historical exclusions stay visible rather than implying support', () => {
  assert.equal(formatProbeSupport({ status: 'supported', apps: [], excludes: ['早'] }), '待核对排除: 早')
  assert.equal(formatProbeSupport({ status: 'conditional', apps: ['早孕', '中孕', '晚孕', '胎心'],
    excludes: ['早', '中', '晚孕', '胎心'], mode: 'supported' }), '待核对排除: 早, 中')
  assert.equal(formatProbeSupport({ status: 'conditional', apps: ['早孕', '中孕', '晚孕', '胎心'],
    excludes: ['早\\中\\晚孕'], mode: 'supported' }), '胎心')
})

test('identical material duplicates share one visible row while conflicting values stay marked', () => {
  const document = {rows:[{probe_model_id:1,variant_id:1,feature_id:2,current_status:'supported'},{probe_model_id:1,variant_id:2,feature_id:2,current_status:'unsupported'}]}
  const rows = buildProbeMatrixRows(document,{probes:[{id:1,name:'P'}],variants:[{id:1,ipn:'A',internal_model:'P'},{id:2,ipn:'A',internal_model:'P'}]})
  assert.equal(rows.length,1)
  assert.deepEqual(rows[0].cells[2].keys,['1:1:2','1:2:2'])
  assert.equal(rows[0].cells[2].current_status,'mixed')
})

test('new material fills every template feature and leaves current values pending', () => {
  const catalog = {probes:[{id:1,category_id:2}],variants:[{id:3,probe_model_id:1}],features:[{id:4},{id:5}],templates:[{category_id:2,feature_id:4,default_support:'supported',default_excludes:'["心脏"]'}]}
  const rows = newProbeMaterialRows('1:3', catalog)
  assert.equal(rows.length,2)
  assert.equal(rows[0].defined_status,'conditional')
  assert.deepEqual(rows[0].defined_excludes,['心脏'])
  assert.equal(rows[0].current_status,'pending')
  assert.equal(rows[1].defined_status,'unsupported')
  assert.throws(()=>newProbeMaterialRows('1:99',catalog))
})
test('matrix groups preserve reordered columns and fixed at parent level', () => {
  const layout = [{key:'feature:1',visible:true,fixed:true},{key:'probe_name',visible:true,fixed:true},{key:'feature:2',visible:true,fixed:false},{key:'feature:3',visible:true,fixed:false},{key:'feature:4',visible:true,fixed:true}]
  const segments=matrixColumnSegments(layout,[{id:1,group_id:1},{id:2,group_id:2},{id:3,group_id:1},{id:4,group_id:1}],[{id:1,name:'A'},{id:2,name:'B'}])
  assert.deepEqual(segments.map(s=>s.key),layout.map(c=>c.key))
  assert.deepEqual(segments.filter(s=>s.features).map(s=>s.fixed),[true,false,false,true])
})

test('configuration source material with no confirmed category keeps definitions pending', () => {
  const rows=newProbeMaterialRows('-12:-12',{probes:[{id:-12,category_id:null}],variants:[{id:-12,probe_model_id:-12}],features:[{id:1}],templates:[]})
  assert.equal(rows[0].defined_status,'pending')
  assert.equal(rows[0].current_status,'pending')
})

test('manual add recognizes a source material after its master is registered', () => {
  const catalog={variants:[{id:20,ipn:'A'}],config_materials:[{config_item_id:12,probe_model_id:2,variant_id:20,ipn:'A'}]}
  assert.equal(probeMaterialExists([{probe_model_id:-12,variant_id:-12}],{probe_model_id:2,variant_id:20},catalog),true)
  assert.equal(probeMaterialExists([{probe_model_id:3,variant_id:30}],{probe_model_id:2,variant_id:20},catalog),false)
})
