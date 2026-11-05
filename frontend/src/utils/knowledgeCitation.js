const positive = value => Number.isSafeInteger(value) && value > 0
const hash = value => typeof value === 'string' && /^[a-f0-9]{64}$/i.test(value)
export function citationRequest(citation) {
  if (!positive(citation?.document_id) || !hash(citation.version_id)) return null
  const params = { version_id: citation.version_id }
  if (positive(citation.chunk_id)) params.chunk_id = citation.chunk_id
  else if (positive(citation.page)) params.page = citation.page
  else return null
  if (typeof citation.quote === 'string' && citation.quote.length >= 6 && citation.quote.length <= 400) params.quote = citation.quote
  return { document_id: citation.document_id, params }
}
export const citationVisualLabel = citation => citation?.verification_status === 'model_visual_checked' ? '模型已看原页 · 未人工确认' : '未看图或未完成图像核验 · 未人工确认'
export function citationTextParts(text, quote) {
  if (!quote) return [{ text, highlight: false }]
  const tokens = quote.trim().split(/\s+/).map(part => part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  const match = new RegExp(tokens.join('\\s+')).exec(text)
  if (!match) return [{ text, highlight: false }]
  const parts=[]
  if (match.index) parts.push({text:text.slice(0,match.index),highlight:false})
  parts.push({text:match[0],highlight:true})
  if (match.index+match[0].length < text.length) parts.push({text:text.slice(match.index+match[0].length),highlight:false})
  return parts
}

function fields(value, required, optional = []) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    && required.every(key => Object.hasOwn(value, key))
    && Object.keys(value).every(key => required.includes(key) || optional.includes(key))
}
function address(value) {
  const match = typeof value === 'string' && /^([A-Z]{1,3})([1-9]\d{0,6})$/.exec(value)
  if (!match) return null
  const column = [...match[1]].reduce((total, letter) => total * 26 + letter.charCodeAt(0) - 64, 0)
  const row = Number(match[2])
  return column <= 16384 && row <= 1048576 ? { column, row } : null
}
function range(value) {
  const parts = typeof value === 'string' ? value.split(':') : []
  if (parts.length !== 2) return null
  const start = address(parts[0]), end = address(parts[1])
  return start && end && start.column <= end.column && start.row <= end.row ? { start, end } : null
}
function worksheetCells(location) {
  let previousColumn = 0
  for (const cell of location.cells) {
    if (!fields(cell, ['cell', 'column_index', 'text', 'value_type', 'number_format'], ['merged_range', 'formula_state', 'formula_ref'])) return false
    const position = address(cell.cell)
    if (!position || position.row !== location.row_index || position.column !== cell.column_index || position.column <= previousColumn
      || typeof cell.text !== 'string' || !cell.text.length || typeof cell.number_format !== 'string') return false
    previousColumn = position.column
    if (Object.hasOwn(cell, 'merged_range')) {
      const merged = range(cell.merged_range)
      if (!merged || merged.start.row !== position.row || merged.start.column !== position.column) return false
    }
    if (cell.value_type === 'formula') {
      if (!cell.text.startsWith('=') || cell.formula_state !== 'not_evaluated') return false
      if (Object.hasOwn(cell, 'formula_ref')) {
        const formula = range(cell.formula_ref)
        if (!formula || position.row < formula.start.row || position.row > formula.end.row
          || position.column < formula.start.column || position.column > formula.end.column) return false
      }
    } else if (cell.value_type !== 'literal' || Object.hasOwn(cell, 'formula_state') || Object.hasOwn(cell, 'formula_ref')) return false
  }
  return location.range === `${location.cells[0].cell}:${location.cells.at(-1).cell}`
}
function officeLocation(result) {
  const location = result.locator
  const identity = ['schema_version', 'format', 'kind', 'document_id', 'source_sha256']
  if (!location || location.schema_version !== 1 || location.document_id !== result.document_id || location.source_sha256 !== result.version_id
    || result.page !== null || result.model_answer_eligible !== false || result.verification.structure !== 'matched'
    || result.verification.visual !== 'not_checked' || result.verification.human !== 'not_reviewed') return false
  if (location.format === 'docx') {
    if (location.part !== 'word/document.xml' || !positive(location.body_index)) return false
    const base = [...identity, 'part', 'body_index']
    if (location.kind === 'paragraph') return fields(location, [...base, 'paragraph_index'])
      && positive(location.paragraph_index) && location.paragraph_index <= location.body_index
    return location.kind === 'table_row' && fields(location, [...base, 'table_index', 'row_index', 'cells'])
      && positive(location.table_index) && location.table_index <= location.body_index && positive(location.row_index)
      && Array.isArray(location.cells) && location.cells.length > 0 && location.cells.every((cell, index) =>
        fields(cell, ['cell_index', 'text', 'grid_span', 'vertical_merge', 'contains_nested_tables'])
        && cell.cell_index === index + 1 && typeof cell.text === 'string' && positive(cell.grid_span)
        && [null, 'restart', 'continue'].includes(cell.vertical_merge) && typeof cell.contains_nested_tables === 'boolean')
  }
  return location.format === 'xlsx' && location.kind === 'worksheet_row'
    && fields(location, [...identity, 'sheet_name', 'sheet_index', 'row_index', 'range', 'cells', 'formula_state'])
    && typeof location.sheet_name === 'string' && location.sheet_name.length > 0 && positive(location.sheet_index)
    && positive(location.row_index) && location.row_index <= 1048576 && location.formula_state === 'not_evaluated'
    && Array.isArray(location.cells) && location.cells.length > 0 && worksheetCells(location)
}

// Display only after createCitationController has validated the server response.
export function citationStructure(result) {
  const location = result?.locator
  if (!location) return null
  if (location.format === 'docx') return {
    format: 'DOCX',
    label: location.kind === 'paragraph' ? `正文第${location.paragraph_index}段` : `表格${location.table_index} · 第${location.row_index}行`,
    detail: `${location.part} · 正文节点${location.body_index}`,
    cells: (location.cells || []).map(cell => ({ position: `物理单元格${cell.cell_index}`, text: cell.text || '（空）',
      note: [cell.grid_span > 1 ? `横跨${cell.grid_span}列` : '', cell.vertical_merge === 'restart' ? '纵向合并起始' : cell.vertical_merge === 'continue' ? '纵向合并延续' : '',
        cell.contains_nested_tables ? '含未提取的嵌套表格' : ''].filter(Boolean).join(' · ') })),
  }
  return {
    format: 'XLSX', label: `工作表「${location.sheet_name}」 · ${location.range}`,
    detail: `工作表序号${location.sheet_index} · 第${location.row_index}行`,
    cells: location.cells.map(cell => ({ position: cell.cell, text: cell.text,
      note: [cell.merged_range ? `合并范围 ${cell.merged_range}` : '', `存储格式：${cell.number_format}`,
        cell.value_type === 'formula' ? '公式源码 · 未求值' : '', cell.formula_ref ? `数组范围 ${cell.formula_ref}` : ''].filter(Boolean).join(' · ') })),
  }
}

function validate(result, locator) {
  const {document_id,params}=locator
  const fragment = result?.page ? `#page=${result.page}` : ''
  if (result?.document_id !== document_id || result.version_id !== params.version_id || typeof result.text !== 'string'
    || (params.page && result.page !== params.page) || (params.chunk_id && result.chunk_id !== params.chunk_id)
    || result.verification?.source !== 'hash_verified' || result.verification?.extraction !== 'hash_verified'
    || (params.quote && (result.verification.quote !== 'matched' || result.quote !== params.quote))
    || result.preview_url !== `/api/knowledge/documents/${document_id}/preview?version_id=${params.version_id}${fragment}`) throw new Error('引用定位或核验结果不一致，请重新查询。')
  if ((Object.hasOwn(result, 'locator') || Object.hasOwn(result.verification, 'structure')) && !officeLocation(result)) throw new Error('Office结构定位或核验结果不一致，请重新查询。')
  return result
}
export function createCitationController({state,request}) {
  Object.assign(state,{visible:false,loading:false,error:'',result:null})
  let sequence=0,active=null,disposed=false
  const close=()=>{sequence++;active?.abort();active=null;Object.assign(state,{visible:false,loading:false,error:'',result:null})}
  return {close,dispose(){disposed=true;close()},async open(citation){
    if(disposed)return false
    close();const locator=citationRequest(citation)
    Object.assign(state,{visible:true,loading:true})
    if(!locator){Object.assign(state,{loading:false,error:'此引用缺少版本或准确位置，请重新查询。'});return false}
    const current=sequence;active=new AbortController()
    try {
      const result=await request(locator.document_id,locator.params,active.signal)
      if(disposed||current!==sequence)return false
      state.result=validate(result,locator);return true
    } catch(error) {
      if(!disposed&&current===sequence){state.result=null;state.error=[409,410].includes(error?.response?.status)?'资料版本或提取已变化，请关闭后重新查询。':error?.response?.data?.detail||error?.message||'无法核验引用，请重新查询。'}
      return false
    } finally {if(!disposed&&current===sequence){state.loading=false;active=null}}
  }}
}
