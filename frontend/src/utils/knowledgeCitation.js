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
function validate(result, locator) {
  const {document_id,params}=locator
  const fragment = result?.page ? `#page=${result.page}` : ''
  if (result?.document_id !== document_id || result.version_id !== params.version_id || typeof result.text !== 'string'
    || (params.page && result.page !== params.page) || (params.chunk_id && result.chunk_id !== params.chunk_id)
    || result.verification?.source !== 'hash_verified' || result.verification?.extraction !== 'hash_verified'
    || (params.quote && (result.verification.quote !== 'matched' || result.quote !== params.quote))
    || result.preview_url !== `/api/knowledge/documents/${document_id}/preview?version_id=${params.version_id}${fragment}`) throw new Error('引用定位或核验结果不一致，请重新查询。')
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
