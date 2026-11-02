import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { sourceApplicabilityDisplay, confirmationQuestion } from '../src/utils/knowledgeSourceApplicability.js'

test('source-declared models and limits are displayed as extracted facts without inventing country', () => {
  const source = {document_id:91,title:'V3/5/6 Release Note',version:'1.14.65',source_applicability:{provenance:'source_extract',status:'extracted',models:[{name:'VINNO 6',scope:'series'}],version:{value:'1.14.65'},country:{value:null,status:'not_stated'},market:{value:null,status:'not_stated'},field_evidence:[{field:'upgrades',label:'V6升级路径',value:'VLucid+，1.14.61 → 1.14.65',source_ref:'第3页',excerpt:'本版本同样适用于V6系列的VLucid+平台，即支持从1.14.61升级。'}]}}
  const display = sourceApplicabilityDisplay(source)
  assert.equal(display.version,'1.14.65')
  assert.match(display.models,/VINNO 6/)
  assert.match(display.country,/原文未声明/)
  assert.match(display.market,/原文未声明/)
  assert.equal(display.fields[0].excerpt,source.source_applicability.field_evidence[0].excerpt)
  assert.equal(display.status,'原文直接提取')
})

test('concrete confirmation questions remain separate from extracted document facts', () => {
  assert.equal(confirmationQuestion({question:'这台V6是V10116还是V10921？',reason:'配置主数据没有整机码'}),'这台V6是V10116还是V10921？')
  const source = readFileSync(new URL('../src/components/KnowledgeHistoryTrace.vue',import.meta.url),'utf8')
  assert.match(source,/source_documents/)
  assert.match(source,/confirmation_items/)
  assert.match(source,/本次没有需要你重复确认的资料事实/)
  assert.match(source,/原文未声明/)
})
