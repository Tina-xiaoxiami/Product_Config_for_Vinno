"""Resolve registered citations against the exact original and extraction version."""
from __future__ import annotations

import asyncio
import hashlib
from io import BytesIO
from pathlib import Path

from sqlalchemy import text

from app.services.knowledge_content import (
    MAX_SOURCE_BYTES, OFFICE_EXTRACTOR_VERSION, KnowledgeContentError,
    build_document_chunks, extract_office_blocks,
)


class CitationSourceError(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _snapshot(path: Path, expected: str) -> bytes:
    try:
        if not path.is_absolute():
            raise OSError('unregistered path')
        with path.open('rb') as stream:
            data = stream.read(MAX_SOURCE_BYTES + 1)
    except OSError as error:
        raise CitationSourceError(410, '原件不可用，请检查资料同步后重新查询') from error
    if len(data) > MAX_SOURCE_BYTES:
        raise CitationSourceError(422, '原件超过本次核验大小上限')
    if hashlib.sha256(data).hexdigest() != expected:
        raise CitationSourceError(409, '原件版本已变化，请重新提取并查询；未打开其他版本')
    return data


async def verified_original(db, document_id: int, version_id: str) -> tuple[dict, bytes]:
    row = (await db.execute(text('''SELECT id,title,file_name,file_path,mime_type,sha256
        FROM knowledge_documents WHERE id=:id AND source_status='active' '''), {'id': document_id})).mappings().one_or_none()
    if row is None:
        raise CitationSourceError(404, '资料不存在或已退役，请重新查询')
    if not row['sha256'] or row['sha256'] != version_id:
        raise CitationSourceError(409, '引用版本与当前登记不一致，请重新查询；未打开其他版本')
    document = dict(row)
    data = await asyncio.to_thread(_snapshot, Path(document['file_path']), version_id)
    return document, data


def _pdf_page_count(data: bytes) -> int:
    from pypdf import PdfReader
    try:
        return len(PdfReader(BytesIO(data)).pages)
    except Exception as error:
        raise CitationSourceError(422, 'PDF原页无法读取，未将提取文字视为原页核验通过') from error


def _normalized(value: str) -> str:
    return ' '.join(value.split())


def _office_location(document: dict, data: bytes, chunk: dict, version_id: str) -> dict:
    """Recover the locator from the verified original through the same extractor.

    Existing stored chunk indices/text/hashes must agree with this deterministic
    replay. No Office coordinates or paths supplied by callers are trusted.
    """
    try:
        blocks = extract_office_blocks(data, Path(document['file_name']).suffix, document['mime_type'])
        replayed = build_document_chunks(blocks)
    except KnowledgeContentError as error:
        raise CitationSourceError(422, str(error)) from error
    index = chunk['chunk_index']
    if type(index) is not int or index < 0 or index >= len(replayed):
        raise CitationSourceError(409, 'Office结构位置与提取索引不一致，请重新提取并查询')
    actual = replayed[index]
    if any(actual.get(key) != chunk[key] for key in ('content', 'content_hash', 'source_ref', 'section_name', 'page_number')):
        raise CitationSourceError(409, 'Office结构或正文与提取索引不一致，请重新提取并查询')
    locator = actual.get('locator')
    if not isinstance(locator, dict) or locator.get('source_sha256') != version_id:
        raise CitationSourceError(409, 'Office定位版本未核实，请重新提取并查询')
    return {**locator, 'document_id': document['id']}


async def citation_evidence(db, document_id: int, version_id: str, *, page: int | None = None,
                            chunk_id: int | None = None, quote: str | None = None) -> dict:
    if (page is None) == (chunk_id is None):
        raise CitationSourceError(422, '请明确一个页号或正文片段位置')
    document, data = await verified_original(db, document_id, version_id)
    suffix = Path(document['file_name']).suffix.casefold()
    if suffix == '.xls':
        raise CitationSourceError(422, '旧XLS结构定位尚未支持；未按XLSX处理')
    office = suffix in {'.docx', '.xlsx'}
    extraction = (await db.execute(text('''SELECT status,source_sha256,extractor_version FROM knowledge_document_extractions
        WHERE document_id=:id'''), {'id': document_id})).mappings().one_or_none()
    if not extraction or extraction['status'] != 'completed' or extraction['source_sha256'] != version_id:
        raise CitationSourceError(409, '正文提取与引用版本不一致，请重新提取并查询')
    if office and extraction['extractor_version'] != OFFICE_EXTRACTOR_VERSION:
        raise CitationSourceError(409, 'Office提取版本不支持结构核验，请重新提取并查询')
    pdf = document['file_name'].lower().endswith('.pdf')
    if page is not None and not pdf:
        raise CitationSourceError(422, '非PDF资料请按章节或工作表片段定位，不使用PDF页号')
    condition, location = ('page_number=:location', page) if page is not None else ('id=:location', chunk_id)
    chunks = (await db.execute(text(f'''SELECT id,chunk_index,page_number,section_name,source_ref,content,content_hash
        FROM knowledge_document_chunks WHERE document_id=:id AND {condition} ORDER BY chunk_index'''),
        {'id': document_id, 'location': location})).mappings().all()
    if not chunks:
        raise CitationSourceError(404, '引用位置不存在，请重新查询原文')
    if any(hashlib.sha256(row['content'].encode()).hexdigest() != row['content_hash'] for row in chunks):
        raise CitationSourceError(409, '正文片段已变化，请重新提取并查询')
    actual_page = chunks[0]['page_number'] if pdf else None
    if pdf and (type(actual_page) is not int or actual_page < 1 or actual_page > await asyncio.to_thread(_pdf_page_count, data)):
        raise CitationSourceError(404, '引用PDF页号超出原件范围')
    locator = await asyncio.to_thread(_office_location, document, data, dict(chunks[0]), version_id) if office else None
    content = '\n'.join(row['content'] for row in chunks)
    if quote is not None and (len(quote.strip()) < 6 or _normalized(quote) not in _normalized(content)):
        raise CitationSourceError(422, '引用短句不在该位置的原文中，未打开其他内容替代')
    url = f'/api/knowledge/documents/{document_id}/preview?version_id={version_id}'
    result = {'document_id': document_id, 'title': document['title'], 'version_id': version_id,
            'source_ref': f'PDF第{actual_page}页' if actual_page else chunks[0]['source_ref'],
            'page': actual_page, 'chunk_id': chunk_id, 'text': content, 'quote': quote,
            'verification': {'source': 'hash_verified', 'extraction': 'hash_verified', 'quote': 'matched' if quote else 'not_requested'},
            'preview_url': url + (f'#page={actual_page}' if actual_page else '')}

    if locator is not None:
        result['locator'] = locator
        result['model_answer_eligible'] = False
        result['verification'].update(structure='matched', visual='not_checked', human='not_reviewed')
    return result
