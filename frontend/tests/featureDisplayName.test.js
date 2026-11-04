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

test('standard update cannot discard an unsaved custom display label',async()=>{
 const component=readFileSync(new URL('../src/components/FeatureNameReviewDialog.vue',import.meta.url),'utf8')
 const block=component.slice(component.indexOf('async function confirm()'),component.indexOf('async function saveDisplay()'))
 let warnings=0
 const confirm=new Function('saving','displayDirty','ElMessage',block+';return confirm')({value:false},{value:true},{warning(){warnings++}})
 await confirm();assert.equal(warnings,1)
})

test('matrix table identity ignores display-label changes and retains active editors',()=>{
 const component=readFileSync(new URL('../src/components/ProbeConfigurationMatrix.vue',import.meta.url),'utf8')
 const code=component.slice(component.indexOf('const structureKey ='),component.indexOf('const colors ='))
 const segments={value:[{key:'feature:1',id:4,fixed:false,name:'血流',features:[{id:1,name:'旧名'}]}]}
 const key=new Function('computed','columnSegments',code+';return structureKey')(fn=>({get value(){return fn()}}),segments)
 const before=key.value;segments.value[0].features[0].name='VFlow'
 assert.equal(key.value,before)
 segments.value[0].features[0].id=2;assert.notEqual(key.value,before)
})

import { registerFeatureNameReview, openFeatureNameReview } from '../src/utils/featureNameReviewHost.js'
test('the app-hosted editor remains registered when a table header disappears',()=>{
 const calls=[]
 const stop=registerFeatureNameReview((...args)=>calls.push(args))
 openFeatureNameReview(1,true)
 assert.deepEqual(calls,[[1,true]])
 const other=[]
 const stopOther=registerFeatureNameReview((...args)=>other.push(args))
 stop();openFeatureNameReview(2,false)
 assert.deepEqual(other,[[2,false]])
 stopOther();openFeatureNameReview(3,true)
 assert.equal(other.length,1)
})
