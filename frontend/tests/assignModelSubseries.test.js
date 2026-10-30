import test from 'node:test'
import assert from 'node:assert/strict'
import { assignModelSubseriesPayload } from '../src/utils/assignModelSubseries.js'
const data = {revision:'fresh',catalog:[{id:1,name:'VINNO 5',series:'China'},{id:2,name:'VINNO 5',series:'Oversea'}],groups:[{name:'国内',series:'China',models:['VINNO 5'],model_ids:[1],missing_models:[]}]}
test('assign uses exact market identity, deduplicates and preserves source', () => {
 const payload=assignModelSubseriesPayload(data,1,'国内')
 assert.deepEqual(payload.groups[0].model_ids,[1]);assert.equal(payload.revision,'fresh')
 assert.equal(payload.combinations,undefined)
 assert.deepEqual(data.groups[0].models,['VINNO 5'])
 assert.throws(()=>assignModelSubseriesPayload(data,2,'国内'),/所属系列/)
})
test('create trims new name and limits parent to the selected model market', () => {
 const payload=assignModelSubseriesPayload(data,2,' 新系列 ')
 assert.deepEqual(payload.groups[1],{name:'新系列',series_names:['Oversea'],model_ids:[2],models:[]})
 assert.throws(()=>assignModelSubseriesPayload(data,3,'新'),/型号已变化/)
 assert.throws(()=>assignModelSubseriesPayload(data,2,'  '),/名称/)
})
