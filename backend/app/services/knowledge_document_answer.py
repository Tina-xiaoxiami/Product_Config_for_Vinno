"""Read-only product evidence drafts over the shared guideline runtime."""
from __future__ import annotations

import asyncio
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re

from sqlalchemy import bindparam, text

from app.integrations.guideline_evidence import SharedEvidenceUnavailable, run_shared_evidence
from app.services.knowledge_content import _file_sha256
from app.services.knowledge_parameters import topics_for_question
from app.services.knowledge_release_history import trace_release_history
from app.services.knowledge_scope import KnowledgeScopeError, resolve_query_scope, document_model_identity_unique

MAX_PAGES = 500
MAX_TEXT_BYTES = 3 * 1024 * 1024


def _base(status: str, message: str = '', *, gaps=None, coverage=None) -> dict:
    return {'status': status, 'message': message, 'claims': [], 'gaps': gaps or [],
            'coverage': coverage or {}, 'metrics': {'model_calls': 0}}


def _fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


async def _pages(db, question: str, scope: dict) -> tuple[list[dict], list[str], str]:
    if not await document_model_identity_unique(db, scope):
        return [], ['同市场存在同名型号，资料尚不能唯一关联当前完整型号'], _fingerprint({'scope': scope, 'ambiguous': True})
    trace = await trace_release_history(db, question, scope)
    release_ids = {item['document_id'] for item in trace.get('source_documents', [])}
    release_ids.update(item['document_id'] for chain in trace.get('chains', []) for item in chain.get('documents', []))
    docs = (await db.execute(text('''SELECT d.*,e.source_sha256,e.status AS extraction_status
        FROM knowledge_documents d LEFT JOIN knowledge_document_extractions e ON e.document_id=d.id
        WHERE d.source_status='active' ORDER BY d.id'''))).mappings().all()
    eligible, gaps = [], []
    for row in docs:
        document = dict(row)
        same_scope = (document['market'] == scope['market'] and document['product_series'] == scope['model_name']
                      and document['version'] == scope['software_version']
                      and (not scope['country'] or document['country'] == scope['country']))
        if document['id'] not in release_ids and not (document['document_type'] != 'release_note' and same_scope):
            continue
        ident = document['id']
        if not document['file_name'].lower().endswith('.pdf'):
            gaps.append(f'资料{ident}不是有真实PDF页号的资料，未送入资料回答')
            continue
        if document['extraction_status'] != 'completed' or not document['sha256'] or document['sha256'] != document['source_sha256']:
            gaps.append(f'资料{ident}提取未完成或摘要已变化')
            continue
        try:
            path = Path(document['file_path'])
            if not path.is_absolute() or await asyncio.to_thread(_file_sha256, path) != document['sha256']:
                raise ValueError('source changed')
        except (OSError, ValueError):
            gaps.append(f'资料{ident}原件不可用或摘要已变化')
            continue
        eligible.append(document)
    if not eligible:
        return [], gaps, _fingerprint({'scope': scope, 'pages': []})
    chunks = (await db.execute(text('''SELECT document_id,page_number,chunk_index,content FROM knowledge_document_chunks
        WHERE document_id IN :ids ORDER BY document_id,chunk_index''').bindparams(bindparam('ids', expanding=True)),
        {'ids': [doc['id'] for doc in eligible]})).mappings().all()
    grouped = defaultdict(list)
    for chunk in chunks:
        if isinstance(chunk['page_number'], int) and chunk['page_number'] > 0:
            grouped[(chunk['document_id'], chunk['page_number'])].append(chunk['content'])
        else:
            gaps.append(f"资料{chunk['document_id']}存在缺少真实PDF页号的内容，未送入资料回答")
    pages: list[dict] = []
    size = 0
    for doc in eligible:
        for (ident, page), parts in grouped.items():
            if ident != doc['id']:
                continue
            content = '\n'.join(parts)
            if len(content.strip()) < 6:
                gaps.append(f'资料{ident}第{page}页没有足够可引用正文，未送入资料回答')
                continue
            if len(content) > 32000 or len(pages) >= MAX_PAGES or size + len(content.encode()) > MAX_TEXT_BYTES:
                gaps.append(f'资料{ident}第{page}页超过本次完整页预算，未截断后取证')
                continue
            size += len(content.encode())
            pages.append({'id': f'kb-{ident}', 'page': page, 'text': content, 'version_id': doc['sha256'],
                          'title': doc['title'], 'file_name': doc['file_name'], 'year': None,
                          'source_url': f'/api/knowledge/documents/{ident}/preview'})
    fingerprint = _fingerprint({'scope': scope, 'pages': pages, 'documents': eligible})
    return pages, list(dict.fromkeys(gaps)), fingerprint


def _claims(result: dict, pages: list[dict]) -> list[dict]:
    lookup = {(page['id'], page['page']): page for page in pages}
    claims = result.get('claims', [])
    if not isinstance(claims, list) or len(claims) > 32:
        raise ValueError('invalid claims')
    checked = []
    for claim in claims:
        if not isinstance(claim, dict) or not isinstance(claim.get('text'), str) or not 1 <= len(claim['text']) <= 2000:
            raise ValueError('invalid claim')
        citations = claim.get('citations')
        if not isinstance(citations, list) or not 1 <= len(citations) <= 6:
            raise ValueError('missing citation')
        bound = []
        for citation in citations:
            source = lookup.get((citation.get('document_id'), citation.get('pdf_page')))
            quote = citation.get('original_excerpt')
            if (not source or type(citation.get('pdf_page')) is not int or citation.get('version_id') != source['version_id']
                    or not isinstance(quote, str) or not 6 <= len(quote) <= 400
                    or ' '.join(quote.split()) not in ' '.join(source['text'].split())):
                raise ValueError('unregistered citation')
            bound.append({'document_id': int(source['id'].removeprefix('kb-')), 'title': source['title'],
                          'page': source['page'], 'quote': quote, 'version_id': source['version_id'],
                          'preview_url': source['source_url'] + f"#page={source['page']}"})
        checked.append({'text': claim['text'], 'kind': claim.get('kind'), 'support_status': claim.get('support_status'),
                        'citations': bound})
    return checked


async def document_answer(db, question: str, supplied_scope: dict) -> dict:
    scope = await resolve_query_scope(db, supplied_scope)
    if scope is None:
        raise KnowledgeScopeError('请明确市场、完整机型及软件版本')
    if re.search(r'标配|选配|招标|注册|选型|电池|容量|频率范围', question) or await topics_for_question(db, question):
        return {**_base('deterministic_required', '此问题请使用正式配置、注册或参数型答案入口，资料草稿不替代确定性查询'), 'scope': scope}
    pages, gaps, fingerprint = await _pages(db, question, scope)
    coverage = {'document_count': len({page['id'] for page in pages}), 'page_count': len(pages)}
    if not pages:
        return {**_base('no_evidence', '当前范围缺少可完整定位的资料页', gaps=gaps, coverage=coverage), 'scope': scope}
    try:
        result = await asyncio.to_thread(run_shared_evidence, {'question': question, 'scope': scope, 'pages': pages})
    except SharedEvidenceUnavailable as error:
        return {**_base('unavailable', str(error), gaps=gaps, coverage=coverage), 'scope': scope}
    # This endpoint owns a read-only session. End its read transaction to recheck
    # current applicability, text and files after a potentially long model call.
    await db.rollback()
    current_scope = await resolve_query_scope(db, supplied_scope)
    if current_scope != scope:
        return {**_base('unavailable', '机型范围已变化，请重新查询'), 'scope': scope}
    _, _, current = await _pages(db, question, scope)
    if current != fingerprint:
        return {**_base('unavailable', '原文、提取或适用范围已变化，请重新查询'), 'scope': scope}
    try:
        claims = _claims(result, pages)
        status = result['status']
        if status not in {'draft', 'partial', 'no_evidence', 'validation_failed', 'unavailable'}:
            raise ValueError('invalid status')
        if status in {'draft', 'partial'} and not claims:
            status = 'validation_failed'
    except (ValueError, TypeError, KeyError, AttributeError):
        return {**_base('validation_failed', '回答或引用核验未通过，未发布任何答案', gaps=gaps, coverage=coverage), 'scope': scope}
    return {'status': status, 'claims': claims if status in {'draft', 'partial'} else [], 'scope': scope,
            'message': '资料草稿，尚未人工确认或发布', 'gaps': gaps + result.get('gaps', []),
            'coverage': {**result.get('coverage', {}), **coverage}, 'metrics': result.get('metrics', {}),
            'runtime_identity': result.get('runtime_identity', {})}
