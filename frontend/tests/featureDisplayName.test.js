import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
const source=readFileSync(new URL('../src/utils/featureNameStandard.js',import.meta.url),'utf8').replace(/^import .*$/gm,'').replace(/export /g,'')
test('each feature can show an independent custom or English name while canonical language selection stays intact',async()=>{
 const state=new Function('computed','ref','getFeatureNameStandardFlags',source+';return {loadFeatureNameStandardFlags,featureCurrentName}')(fn=>({get value(){return fn()}}),value=>({value}),async()=>({checks_by_feature:{1:{feature_cn_name:'穿刺增强',feature_en_name:'Needle Enhancement',feature_display_name:'Needle'},2:{feature_cn_name:'高灵敏度彩色多普勒',feature_en_name:'VFlow',feature_display_name:'高灵敏度血流'}}}))
 await state.loadFeatureNameStandardFlags()
 assert.equal(state.featureCurrentName(1,'旧名'),'Needle')
 assert.equal(state.featureCurrentName(2,'旧名'),'高灵敏度血流')
 assert.equal(state.featureCurrentName(1,'旧名','cn'),'穿刺增强')
 assert.equal(state.featureCurrentName(1,'旧名','en'),'Needle Enhancement')
})
