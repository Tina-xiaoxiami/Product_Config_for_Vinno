import test from 'node:test'
import assert from 'node:assert/strict'
import { cloneSubseriesGroups, subseriesGroupOptions, subseriesPayload, subseriesSnapshot } from '../src/utils/subseriesEditor.js'

test('editing preserves existing short names and unmatched members without mutating source',()=>{
 const raw=[{name:'URM',series:'Tulip-China',models:['9E科研版（URM）','旧机型'],options:[{id:40,value:'9E科研版（URM）',label:'ULTIMUS 9E科研版(URM)',series:'Tulip-China'}]}]
 const groups=cloneSubseriesGroups(raw)
 const options=subseriesGroupOptions(groups[0],[{id:40,name:'ULTIMUS 9E科研版(URM)',series:'Tulip-China'},{id:41,name:'ULTIMUS 9L',series:'Tulip-China'},{id:42,name:'ULTIMUS 9L',series:'Tulip-Oversea'}])
 assert.deepEqual(options.map(o=>o.value),['9E科研版（URM）','ULTIMUS 9L','旧机型'])
 groups[0].models.push('ULTIMUS 9L');assert.equal(raw[0].models.length,2)
 assert.deepEqual(subseriesPayload('revision',groups),{revision:'revision',groups:[{name:'URM',series:'Tulip-China',models:['9E科研版（URM）','旧机型','ULTIMUS 9L']}]})
})
test('new group can include configuration-only models and parent changes keep selections for explicit validation',()=>{
 const g={name:'新子系列',series:'China',models:['海外型号']}
 const options=subseriesGroupOptions(g,[{id:1,name:'只有配置的机型',series:'China'},{id:2,name:'海外型号',series:'Oversea'}])
 assert.deepEqual(options.map(o=>o.value),['只有配置的机型','海外型号'])
 assert.deepEqual(g.models,['海外型号'])
 assert.notEqual(subseriesSnapshot([g]),subseriesSnapshot([{...g,name:'改名'}]))
})
