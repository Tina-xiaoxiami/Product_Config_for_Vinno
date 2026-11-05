import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { runInNewContext } from 'node:vm'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { compile } from '@vue/compiler-ssr'

const sha = 'a'.repeat(64)
const citation = () => ({ document_id: 1, page: 2, version_id: sha, quote: '原文中的明确记录' })
const response = () => ({ ...citation(), chunk_id: null, title: '资料', source_ref: '第2页', text: '完整原文中的明确记录和限制。', verification: { source: 'hash_verified', extraction: 'hash_verified', quote: 'matched' }, preview_url: `/api/knowledge/documents/1/preview?version_id=${sha}#page=2` })
const wait = () => { let resolve, reject; const promise = new Promise((yes,no) => { resolve=yes;reject=no }); return { promise,resolve,reject } }

test('version-bound locator accepts PDF or chunk without inventing a page and excludes candidate ellipsis', async () => {
  const { citationRequest } = await import('../src/utils/knowledgeCitation.js')
  assert.deepEqual(citationRequest(citation()), { document_id: 1, params: { version_id: sha, page: 2, quote: '原文中的明确记录' } })
  assert.deepEqual(citationRequest({ document_id: 1, version_id: sha, chunk_id: 6, page_number: null, excerpt: '截断…' }), { document_id: 1, params: { version_id: sha, chunk_id: 6 } })
  assert.equal(citationRequest({ document_id: 1, page: 1 }), null)
  assert.equal(citationRequest({ ...citation(), version_id: '../secret' }), null)
})
test('close and rapid reopen discard stale evidence and abort old requests', async () => {
  const { createCitationController } = await import('../src/utils/knowledgeCitation.js')
  const state={}, calls=[]
  const controller=createCitationController({ state, request: (...args) => {const next=wait();calls.push({next,args});return next.promise} })
  const first=controller.open(citation());controller.close()
  assert.equal(calls[0].args[2].aborted,true)
  const second=controller.open(citation());calls[0].next.resolve(response());await first
  assert.equal(state.result,null)
  calls[1].next.resolve(response());assert.equal(await second,true);assert.equal(state.result.source_ref,'第2页')
  controller.dispose();assert.equal(state.result,null)
})
test('source changes clear earlier evidence and never fall back to an unversioned source', async () => {
  const { createCitationController } = await import('../src/utils/knowledgeCitation.js')
  let fail=false;const state={}
  const controller=createCitationController({state,request:async()=>{if(fail)throw {response:{status:409,data:{detail:'原件已变化'}}};return response()}})
  await controller.open(citation());fail=true;await controller.open(citation())
  assert.equal(state.result,null);assert.match(state.error,/重新查询/)
})
test('mismatched server identity, location and verification never become viewable evidence', async () => {
  const { createCitationController } = await import('../src/utils/knowledgeCitation.js')
  for (const change of [{version_id:'b'.repeat(64)},{document_id:3},{page:9},{verification:{}},{preview_url:'https://bad.invalid'}]) {
    const state={};const controller=createCitationController({state,request:async()=>({...response(),...change})})
    assert.equal(await controller.open(citation()),false);assert.equal(state.result,null);assert.ok(state.error)
  }
})
test('quote highlighting handles whitespace without interpreting source HTML', async () => {
  const { citationTextParts } = await import('../src/utils/knowledgeCitation.js')
  assert.deepEqual(citationTextParts('原文\n 引用 <script>尾部','原文 引用'),[{text:'原文\n 引用',highlight:true},{text:' <script>尾部',highlight:false}])
  assert.deepEqual(citationTextParts('完整正文',null),[{text:'完整正文',highlight:false}])
})
test('only actual visual audit marks a citation as model checked; never human approval',async()=>{
  const { citationVisualLabel } = await import('../src/utils/knowledgeCitation.js')
  assert.match(citationVisualLabel({verification_status:'model_visual_checked'}),/模型已看原页.*未人工确认/)
  assert.match(citationVisualLabel({}),/未看图/)
})

test('versioned preview links stay on the registered product document route',async()=>{
  const { evidenceCitationUrl }=await import('../src/utils/knowledgeEvidence.js')
  assert.equal(evidenceCitationUrl({...citation(),preview_url:response().preview_url}),response().preview_url)
  assert.equal(evidenceCitationUrl({...citation(),preview_url:`/api/knowledge/documents/2/preview?version_id=${sha}#page=2`}),null)
  assert.equal(evidenceCitationUrl({...citation(),preview_url:`/api/knowledge/documents/1/preview?version_id=${sha}&path=bad`}),null)
})

test('knowledge tab changes close both local and teleported child citation viewers', async () => {
  const { readFileSync } = await import('node:fs')
  const hub = readFileSync(new URL('../src/views/KnowledgeHub.vue', import.meta.url), 'utf8')
  const child = readFileSync(new URL('../src/components/KnowledgeEvidenceAnswer.vue', import.meta.url), 'utf8')
  assert.match(child, /defineExpose\(\{[^}]*closeCitation:\s*\(\)\s*=>\s*citationViewer\.value\?\.close\(\)/)
  const tabWatcher = hub.match(/watch\(activeTab,\s*\(\)\s*=>\s*\{([\s\S]*?)\},\s*\{\s*flush:\s*'sync'\s*\}\)/)
  assert.ok(tabWatcher, 'tab watcher must synchronously close teleported viewers')
  assert.match(tabWatcher[1], /citationViewer\.value\?\.close\(\)/)
  assert.match(tabWatcher[1], /evidenceAnswer\.value\?\.closeCitation\(\)/)
})

const officeCitation = () => ({ document_id: 1, version_id: sha, chunk_id: 6 })
const officeResponse = (format = 'docx', kind = 'paragraph') => {
  const location = format === 'xlsx'
    ? { format, kind: 'worksheet_row', sheet_name: '规格 表', sheet_index: 1, row_index: 5, range: 'A5:E5', formula_state: 'not_evaluated', cells: [
      { cell: 'A5', column_index: 1, text: '规格 <img src=x>', value_type: 'literal', number_format: 'General', merged_range: 'A5:B6' },
      { cell: 'C5', column_index: 3, text: '300 mAh', value_type: 'literal', number_format: '0.00' },
      { cell: 'E5', column_index: 5, text: '=SUM(1,1)', value_type: 'formula', number_format: 'General', formula_state: 'not_evaluated', formula_ref: 'E5:F5' },
    ] }
    : { format, kind, part: 'word/document.xml', body_index: kind === 'paragraph' ? 3 : 4,
      ...(kind === 'paragraph' ? { paragraph_index: 3 } : { table_index: 1, row_index: 2, cells: [
        { cell_index: 1, text: '2.5 mm', grid_span: 2, vertical_merge: 'restart', contains_nested_tables: true },
        { cell_index: 2, text: '', grid_span: 1, vertical_merge: 'continue', contains_nested_tables: false },
      ] }) }
  return { ...officeCitation(), title: '合成资料', source_ref: '原件结构位置', page: null, text: '规格 <img src=x> | 300 mAh | =SUM(1,1)', quote: null,
    preview_url: `/api/knowledge/documents/1/preview?version_id=${sha}`, model_answer_eligible: false,
    verification: { source: 'hash_verified', extraction: 'hash_verified', quote: 'not_requested', structure: 'matched', visual: 'not_checked', human: 'not_reviewed' },
    locator: { schema_version: 1, document_id: 1, source_sha256: sha, ...location } }
}
async function inspectOffice(result) {
  const { createCitationController } = await import('../src/utils/knowledgeCitation.js')
  const state = {}
  const controller = createCitationController({ state, request: async () => result })
  return { state, controller, accepted: await controller.open(officeCitation()) }
}

test('real Office paragraph/table and sparse worksheet locations stay readable without PDF pages', async () => {
  const afterTable = officeResponse(); Object.assign(afterTable.locator, { body_index: 5, paragraph_index: 4 })
  const secondSheet = officeResponse('xlsx'); Object.assign(secondSheet.locator, { sheet_name: '其他', sheet_index: 2 })
  const literalSheet = officeResponse('xlsx'); literalSheet.locator.cells = literalSheet.locator.cells.slice(0, 2); literalSheet.locator.range = 'A5:C5'
  for (const result of [officeResponse(), afterTable, officeResponse('docx', 'table_row'), officeResponse('xlsx'), secondSheet, literalSheet]) {
    const { accepted, state } = await inspectOffice(result)
    assert.equal(accepted, true)
    assert.equal(state.result.locator, result.locator)
    assert.equal(state.result.page, null)
    assert.equal(state.result.preview_url.includes('#page'), false)
  }
})

test('contradictory or unsupported Office metadata clears the previous evidence', async t => {
  const cases = [
    ['document', r => { r.locator.document_id = 2 }], ['hash', r => { r.locator.source_sha256 = 'b'.repeat(64) }],
    ['schema', r => { r.locator.schema_version = 2 }], ['format', r => { r.locator.format = 'xls' }],
    ['kind', r => { r.locator.kind = 'worksheet_row' }], ['foreign field', r => { r.locator.sheet_name = 'Sheet1' }],
    ['missing structure', r => { delete r.locator }], ['null structure', r => { r.locator = null }],
    ['fake PDF page', r => { r.page = 1; r.preview_url += '#page=1' }], ['model eligibility', r => { r.model_answer_eligible = true }],
    ['visual status', r => { r.verification.visual = 'model_checked' }], ['human status', r => { r.verification.human = 'confirmed' }],
    ['structure status', r => { r.verification.structure = 'unknown' }], ['DOCX part', r => { r.locator.part = 'word/header1.xml' }],
    ['DOCX index', r => { r.locator.paragraph_index = 0 }], ['DOCX body order', r => { r.locator.body_index = 2 }],
    ['table cell order', r => { r.locator.cells[1].cell_index = 1 }, 'table'],
    ['table span', r => { r.locator.cells[0].grid_span = 0 }, 'table'],
    ['table merge', r => { r.locator.cells[0].vertical_merge = 'guess' }, 'table'],
    ['table nested marker', r => { r.locator.cells[0].contains_nested_tables = 'yes' }, 'table'],
    ['table row', r => { r.locator.row_index = -1 }, 'table'], ['table index', r => { r.locator.table_index = 5 }, 'table'],
    ['empty cells', r => { r.locator.cells = [] }, 'xlsx'], ['sheet', r => { r.locator.sheet_name = '' }, 'xlsx'],
    ['sheet index', r => { r.locator.sheet_index = 0 }, 'xlsx'], ['range', r => { r.locator.range = 'B5:E5' }, 'xlsx'],
    ['wrong row', r => { r.locator.row_index = 6 }, 'xlsx'], ['row limit', r => { r.locator.row_index = 1048577 }, 'xlsx'],
    ['cell address', r => { r.locator.cells[0].cell = 'XFE5' }, 'xlsx'], ['column identity', r => { r.locator.cells[1].column_index = 2 }, 'xlsx'],
    ['cell order', r => { r.locator.cells.reverse() }, 'xlsx'], ['merge range', r => { r.locator.cells[0].merged_range = 'B5:C6' }, 'xlsx'],
    ['formula range', r => { r.locator.cells[2].formula_ref = 'F5:G5' }, 'xlsx'],
    ['formula state', r => { r.locator.cells[2].formula_state = 'calculated' }, 'xlsx'],
    ['formula source', r => { r.locator.cells[2].text = '2' }, 'xlsx'], ['literal formula flag', r => { r.locator.cells[0].formula_state = 'not_evaluated' }, 'xlsx'],
    ['row formula state', r => { r.locator.formula_state = 'calculated' }, 'xlsx'], ['cell type', r => { r.locator.cells[0].value_type = 'guessed' }, 'xlsx'],
    ['unknown cell field', r => { r.locator.cells[0].page = 1 }, 'xlsx'], ['number format', r => { r.locator.cells[0].number_format = null }, 'xlsx'],
  ]
  for (const [name, change, type] of cases) await t.test(name, async () => {
    const good = type === 'table' ? officeResponse('docx', 'table_row') : officeResponse(type === 'xlsx' ? 'xlsx' : 'docx')
    let next = good
    const { createCitationController } = await import('../src/utils/knowledgeCitation.js')
    const state = {}, controller = createCitationController({ state, request: async () => next })
    assert.equal(await controller.open(officeCitation()), true)
    next = structuredClone(good); change(next)
    assert.equal(await controller.open(officeCitation()), false)
    assert.equal(state.result, null)
    assert.ok(state.error)
  })
})

test('Office HTTP errors and late responses cannot leave an earlier structure visible', async () => {
  const { createCitationController } = await import('../src/utils/knowledgeCitation.js')
  for (const status of [409, 410, 422]) {
    let fail = false; const state = {}
    const controller = createCitationController({ state, request: async () => { if (fail) throw { response: { status, data: { detail: '格式或定位不支持' } } }; return officeResponse() } })
    await controller.open(officeCitation()); fail = true
    assert.equal(await controller.open(officeCitation()), false); assert.equal(state.result, null)
    assert.match(state.error, status === 422 ? /不支持/ : /重新查询/)
  }
  const state = {}, calls = []
  const controller = createCitationController({ state, request: (id, params, signal) => { const pending = wait(); calls.push({ pending, signal }); return pending.promise } })
  const first = controller.open(officeCitation()), second = controller.open(officeCitation())
  assert.equal(calls[0].signal.aborted, true)
  calls[1].pending.resolve(officeResponse('xlsx')); await second
  calls[0].pending.resolve(officeResponse()); await first
  assert.equal(state.result.locator.format, 'xlsx')
  controller.close(); assert.equal(state.result, null)
})

test('plain text fragments remain valid without being labelled Office structure', async () => {
  const result = officeResponse(); delete result.locator
  result.verification = { source: 'hash_verified', extraction: 'hash_verified', quote: 'not_requested' }
  const { accepted } = await inspectOffice(result)
  assert.equal(accepted, true)
})

test('single-cell array and merged references retain the existing backend contract', async () => {
  const result = officeResponse('xlsx')
  result.locator.cells[0].merged_range = 'A5'
  result.locator.cells[2].formula_ref = 'E5'
  assert.equal((await inspectOffice(result)).accepted, true)
})

test('ordinary unverified originals require an explicit same-document safe link and never replace a verifiable citation', async () => {
  const { canViewUnverifiedOriginal } = await import('../src/utils/knowledgeCitation.js')
  const old = { document_id: 1, preview_url: '/api/knowledge/documents/1/preview' }
  assert.equal(canViewUnverifiedOriginal(old), true)
  assert.equal(canViewUnverifiedOriginal({ ...old, preview_url: old.preview_url + '#page=2' }), true)
  for (const preview_url of [null, 3, { toString: 'invalid' }, 'https://bad.invalid', '/api/knowledge/documents/2/preview', old.preview_url + '?path=bad', old.preview_url + '#page=0']) assert.equal(canViewUnverifiedOriginal({ ...old, preview_url }), false)
  assert.equal(canViewUnverifiedOriginal({ ...old, ...officeCitation() }), false)
  assert.equal(canViewUnverifiedOriginal(null), false)
})

async function renderViewer(result, showOriginal = false) {
  const { citationStructure, citationTextParts } = await import('../src/utils/knowledgeCitation.js')
  const source = readFileSync(new URL('../src/components/KnowledgeCitationViewer.vue', import.meta.url), 'utf8')
  const template = source.slice(source.indexOf('<template>') + 10, source.indexOf('</template>\n<script'))
  const ssrRender = new Function('require', compile(template).code)(createRequire(import.meta.url))
  const app = createSSRApp({ setup: () => ({ state: { visible: true, result }, structure: citationStructure(result), showOriginal, controller: { close() {} }, citationTextParts }), ssrRender })
  app.component('el-dialog', { props: ['modelValue'], setup: (props, { slots }) => () => props.modelValue ? h('section', { role: 'dialog' }, slots.default?.()) : null })
  for (const name of ['el-tag', 'el-button', 'el-alert']) app.component(name, { setup: (_, { slots }) => () => h('span', slots.default?.()) })
  return renderToString(app)
}

test('existing viewer renders sparse coordinates, merge/formula semantics and explicit review boundaries as text', async () => {
  const xlsx = await renderViewer(officeResponse('xlsx'))
  for (const text of ['规格 表', 'A5:E5', 'A5', 'C5', 'E5', '300 mAh', '=SUM(1,1)', '未求值', 'A5:B6', 'E5:F5', '0.00', sha, '文件指纹', '结构已匹配', '未进行原页视觉核验', '未人工确认', '正式生产问答']) assert.ok(xlsx.includes(text), text)
  assert.ok(xlsx.includes('&lt;img src=x&gt;')); assert.equal(xlsx.includes('<img src=x>'), false)
  assert.equal(xlsx.includes('<iframe'), false); assert.equal(xlsx.includes('#page='), false)
  assert.match(await renderViewer(officeResponse()), /正文第3段/)
  const table = await renderViewer(officeResponse('docx', 'table_row'))
  for (const text of ['表格1', '第2行', '物理单元格1', '横跨2列', '纵向合并起始', '纵向合并延续', '嵌套表格', '（空）']) assert.ok(table.includes(text), text)
  const pdf = await renderViewer(response(), true)
  assert.match(pdf, /<iframe/); assert.match(pdf, /#page=2/); assert.equal(pdf.includes('结构已匹配'), false)
})

test('the actual knowledge citation entry reports missing identity instead of opening an unversioned original', async () => {
  const { citationRequest, createCitationController } = await import('../src/utils/knowledgeCitation.js')
  const source = readFileSync(new URL('../src/views/KnowledgeHub.vue', import.meta.url), 'utf8')
  const handler = source.slice(source.indexOf('const openCitation ='), source.indexOf('\nwatch(', source.indexOf('const openCitation =')))
  const state = {}, opens = []
  const controller = createCitationController({ state, request: async () => { throw new Error('missing identity must not request evidence') } })
  const entry = runInNewContext(`${handler}\nopenCitation`, { citationRequest, citationViewer: { value: controller }, window: { open: (...args) => opens.push(args) } })
  await entry({ document_id: 1, preview_url: '/api/knowledge/documents/1/preview' })
  assert.equal(opens.length, 0); assert.equal(state.visible, true); assert.equal(state.result, null); assert.match(state.error, /缺少版本或准确位置/)
})
