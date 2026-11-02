"""Trace controlled historical notes without publishing or guessing applicability."""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.feature_release_backfill import _classify_change
from app.services.feature_release_versions import version_sort_key
from app.services.knowledge_content import _file_sha256
from app.services.knowledge_documents import list_knowledge_documents
from app.services.knowledge_scope import resolve_query_scope


class ReleaseHistoryError(ValueError):
    pass


class ReleaseHistoryConflict(ReleaseHistoryError):
    pass


class ReleaseHistoryUnavailable(ReleaseHistoryError):
    pass


async def _ready(session: AsyncSession) -> bool:
    return (await session.execute(text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='knowledge_release_bindings'"))).first() is not None


def _fingerprint(document) -> str:
    fields = ('id', 'document_type', 'title', 'file_name', 'file_path', 'version', 'market', 'country', 'product_series', 'mime_type', 'sha256')
    value = {field: document[field] for field in fields}
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


async def _documents(session: AsyncSession) -> list[dict]:
    rows = (await session.execute(text('''SELECT d.*, e.status AS extraction_status,
        e.source_sha256 AS extraction_sha256 FROM knowledge_documents d
        LEFT JOIN knowledge_document_extractions e ON e.document_id=d.id
        WHERE d.document_type='release_note' ORDER BY d.id'''))).mappings()
    return [dict(row) for row in rows]


async def _quality(document) -> list[str]:
    reasons = []
    if document['source_status'] != 'active':
        reasons.append('资料已停用')
    if not re.fullmatch(r'\d+(?:\.\d+){1,3}', str(document['version'] or '')):
        reasons.append('缺少明确软件版本')
    if document['extraction_status'] != 'completed' or not document['sha256'] or document['extraction_sha256'] != document['sha256']:
        reasons.append('正文提取未完成或已过期')
    path = Path(document['file_path'])
    if not path.is_absolute() or not path.is_file():
        reasons.append('受控原件不可用')
    elif document['sha256']:
        try:
            if await asyncio.to_thread(_file_sha256, path) != document['sha256']:
                reasons.append('原件摘要已变化')
        except OSError:
            reasons.append('受控原件暂时无法读取')
    return reasons


async def list_release_documents(session, *, query=None, skip=0, limit=200) -> dict:
    items, total = await list_knowledge_documents(session, query=query, document_type='release_note', skip=skip, limit=limit)
    sources = {row['id']: row for row in await _documents(session)}
    for item in items:
        source = sources[item['id']]
        item.update(sha256=source['sha256'], source_status=source['source_status'], readiness_reasons=await _quality(source))
    return {'items': items, 'total': total, 'skip': skip, 'limit': limit}


async def list_release_bindings(session, *, product_model_id=None, include_inactive=False) -> dict:
    if not await _ready(session):
        return {'available': False, 'items': []}
    rows = (await session.execute(text('''SELECT b.*, d.title AS document_title,d.version AS release_version
        FROM knowledge_release_bindings b JOIN knowledge_documents d ON d.id=b.document_id
        WHERE (:model IS NULL OR b.product_model_id=:model) AND (:inactive OR b.is_active=1)
        ORDER BY b.id DESC'''), {'model': product_model_id, 'inactive': include_inactive})).mappings()
    return {'available': True, 'items': [dict(row) for row in rows]}


async def create_release_bindings(session: AsyncSession, payload: dict) -> dict:
    if not await _ready(session):
        raise ReleaseHistoryUnavailable('历史版本适用关系尚未初始化，请更新服务')
    values = {field: str(payload.get(field) or '').strip() for field in ('country', 'market', 'release_line', 'conditions', 'evidence_reference', 'confirmed_by')}
    if any(not values[field] for field in ('release_line', 'evidence_reference', 'confirmed_by')):
        raise ReleaseHistoryError('版本分支、适用依据和实际核对人不能为空')
    document_ids = sorted(set(payload['document_ids']))
    model_ids = sorted(set(payload['product_model_ids']))
    if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in document_ids + model_ids):
        raise ReleaseHistoryError('资料与完整机型ID必须为正整数')
    # Establish one write transaction before validation, so no partial bulk binding escapes.
    await session.rollback()
    await session.execute(text('BEGIN IMMEDIATE'))
    try:
        documents = {row['id']: row for row in await _documents(session)}
        created = []
        model_names = set((await session.execute(text('SELECT name FROM product_models'))).scalars())
        for document_id in document_ids:
            document = documents.get(document_id)
            if document is None:
                raise ReleaseHistoryError('只能关联已登记的Release Note')
            reasons = await _quality(document)
            if reasons:
                raise ReleaseHistoryError('；'.join(reasons))
            if document['country'] and document['country'] != values['country'].upper():
                raise ReleaseHistoryError('资料国家与确认范围冲突')
            if document['market'] not in (None, '', 'unspecified') and document['market'] != values['market']:
                raise ReleaseHistoryError('资料市场与确认范围冲突')
            for model_id in model_ids:
                scope = await resolve_query_scope(session, {**values, 'product_model_id': model_id, 'software_version': document['version']})
                assert scope is not None
                declared_models = {name for name in model_names if _explicit_model(document, {'model_name': name})}
                if declared_models and scope['model_name'] not in declared_models:
                    raise ReleaseHistoryError('资料明确记载的完整机型与所选机型冲突')
                params = {**values, 'country': scope['country'], 'model_id': model_id, 'document_id': document_id,
                          'fingerprint': _fingerprint(document), 'model_name': scope['model_name'], 'series_name': scope['series_name']}
                existing = (await session.execute(text('''SELECT * FROM knowledge_release_bindings
                    WHERE document_id=:document_id AND product_model_id=:model_id AND country=:country
                      AND market=:market AND release_line=:release_line AND is_active=1'''), params)).mappings().one_or_none()
                if existing:
                    if any(existing[field] != params[field] for field in ('conditions', 'evidence_reference', 'confirmed_by', 'model_name', 'series_name')) or existing['document_fingerprint'] != params['fingerprint']:
                        raise ReleaseHistoryConflict('已有不同的适用关系，请先停用旧记录再重新核对')
                    created.append(int(existing['id']))
                    continue
                result = await session.execute(text('''INSERT INTO knowledge_release_bindings
                    (document_id,product_model_id,country,market,release_line,conditions,evidence_reference,
                     confirmed_by,document_fingerprint,model_name,series_name)
                    VALUES (:document_id,:model_id,:country,:market,:release_line,:conditions,:evidence_reference,
                            :confirmed_by,:fingerprint,:model_name,:series_name) RETURNING id'''), params)
                created.append(int(result.scalar_one()))
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
    binding_list = await list_release_bindings(session, include_inactive=True)
    return {'available': True, 'items': [row for row in binding_list['items'] if row['id'] in created]}


async def deactivate_release_binding(session: AsyncSession, binding_id: int, expected_revision: int) -> dict:
    if not await _ready(session):
        raise ReleaseHistoryUnavailable('历史版本适用关系尚未初始化')
    result = await session.execute(text('''UPDATE knowledge_release_bindings SET is_active=0,
        revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE id=:id AND revision=:revision AND is_active=1 RETURNING id'''),
        {'id': binding_id, 'revision': expected_revision})
    if result.first() is None:
        await session.rollback()
        raise ReleaseHistoryConflict('适用关系已变化或已停用，请刷新后再操作')
    await session.commit()
    return {'id': binding_id, 'is_active': False, 'revision': expected_revision + 1}


def _normalize(value: str) -> str:
    return ''.join(character for character in unicodedata.normalize('NFKC', value).casefold() if character.isalnum())


def _topic(query: str, scope: dict) -> str:
    value = _normalize(query)
    model = _normalize(scope['model_name'])
    for phrase in sorted((model, re.sub(r'^vinno', 'v', model), '请问', '是否支持', '是否', '支持吗', '支持', '这个功能', '的功能', '功能', '吗'), key=len, reverse=True):
        if phrase:
            value = value.replace(phrase, '')
    if len(value) < 2:
        raise ReleaseHistoryError('请明确需要追溯的功能或子能力名称')
    return value


_RELEASE_HEADING = re.compile(r'(?:release\s*note|software\s*version|软件版本|版本)\s*[_:：vV\s-]*(\d+\.\d+(?:\.\d+){1,2})|^\s*[vV]?(\d+\.\d+(?:\.\d+){1,2})\s*(?:版本|release\s*note)', re.I)


_NEGATED_CHANGE = re.compile(
    r'(?:尚未|从未|未曾|并未|并没有|没有|无须|无需|不必|不需要|毋须|不得|不能|不可|不应|不用|不再|禁止|未|不)'
    r'\s*(?:(?:进行|予以|再|被|将|直接|实际|正式)\s*)*'
    r'(?:新增|添加|增加|取消|撤销|移除|删除|下架|上架)'
    r'|(?:no\s+need\s+to|not|never)\s+(?:be\s+)?(?:remov\w*|delet\w*|add\w*|cancel\w*|disabl\w*)', re.I)
_PROPOSED_CHANGE = re.compile(r'(?:计划|拟|建议|考虑|可能|预计|如果|尚需).*?(?:新增|添加|取消|移除|删除)')


def _events(document: dict, chunks: list[dict], topic: str, conditions='') -> list[dict]:
    headers = {m.group(1) or m.group(2) for chunk in chunks for line in chunk['content'].splitlines() if (m := _RELEASE_HEADING.search(line))}
    cumulative = len(headers) > 1
    current = None
    table_versions: dict[str, str | None] = {}
    events = []
    is_docx = ('wordprocessingml' in str(document.get('mime_type') or '')
               or str(document.get('file_name') or '').casefold().endswith('.docx'))
    for chunk in chunks:
        section = str(chunk.get('section_name') or '')
        # The existing DOCX extractor emits paragraphs first, followed by all
        # tables. A table must never inherit the last paragraph's version.
        table_key = section if is_docx and section.startswith('表格') else None
        local_version = table_versions.get(table_key) if table_key else current
        section_header = _RELEASE_HEADING.search(section)
        if section_header:
            local_version = section_header.group(1) or section_header.group(2)
        for line in chunk['content'].splitlines():
            header = _RELEASE_HEADING.search(line)
            if header:
                local_version = header.group(1) or header.group(2)
            if topic not in _normalize(line):
                continue
            clauses = [clause for clause in re.split(r'[。；;,，]', line) if topic in _normalize(clause)]
            relevant = '；'.join(clauses)
            change, _ = _classify_change(relevant, relevant, False)
            # Negating or proposing an action is not evidence that it happened.
            # Keep the original sentence and require review rather than inventing
            # a removal, addition or a contradictory first-support record.
            if _NEGATED_CHANGE.search(relevant) or _PROPOSED_CHANGE.search(relevant):
                change = 'unknown'
            elif re.search(r'取消|不再支持|停止支持|移除|删除|removed|disabled', relevant, re.I):
                change = 'unknown' if re.search(r'(?:取消|移除|删除).*?(?:限制|约束|条件)', relevant) else 'removed'
            elif re.search(r'不支持|暂不支持|尚不支持|not\s+support', relevant, re.I):
                change = 'restricted'
            elif re.search(r'仅|限制|limited|only', relevant, re.I):
                change = 'restricted'
            elif re.search(r'添加', relevant):
                change = 'added'
            version = local_version or (None if cumulative or table_key else document['version'])
            event = {'document_id': document['id'], 'document_title': document['title'],
                     'release_version': document['version'], 'event_version': version,
                     'event_version_basis': ('table_heading' if table_key else 'section_heading') if local_version else 'unresolved' if cumulative or table_key else 'document_version',
                     'source_ref': chunk['source_ref'], 'page_number': chunk.get('page_number'),
                     'excerpt': line.strip()[:1500], 'change_type': change,
                     'preview_url': f"/api/knowledge/documents/{document['id']}/preview", 'conditions': conditions}
            if event not in events:
                events.append(event)
        if table_key:
            table_versions[table_key] = local_version
        else:
            current = local_version
    return events


def _document_conditions(document: dict, chunks: list[dict]) -> list[dict]:
    """Keep hardware and upgrade declarations even when the queried term is elsewhere."""
    found = []
    for chunk in chunks:
        for line in chunk['content'].splitlines():
            platform = re.search(r'硬件|平台|升级|hardware|platform|upgrade|vlucid', line, re.I)
            limited = re.search(r'仅|只|不支持|不适用|必须|要求|不兼容|不能|无法|limited|only|not\s+support|vlucid|支持.*从.*升级', line, re.I)
            if platform and limited:
                item = {'document_id': document['id'], 'source_ref': chunk['source_ref'],
                        'page_number': chunk.get('page_number'), 'excerpt': line.strip()[:1500],
                        'preview_url': f"/api/knowledge/documents/{document['id']}/preview"}
                if item not in found:
                    found.append(item)
    return found


def _explicit_model(document: dict, scope: dict) -> bool:
    needle = re.escape(scope['model_name']).replace(r'\ ', r'\s*')
    names = [needle]
    simple = re.sub(r'^VINNO\s*', 'V', scope['model_name'], flags=re.I)
    if simple != scope['model_name']:
        names.append(re.escape(simple).replace(r'\ ', r'\s*'))
    return any(re.search(r'(?<![A-Za-z0-9])' + name + r'(?![A-Za-z0-9])', f"{document['product_series']} {document['title']}", re.I) for name in names)


async def trace_release_history(session: AsyncSession, query: str, supplied_scope: dict, *, release_line: str | None = None) -> dict:
    scope = await resolve_query_scope(session, supplied_scope)
    if scope is None:
        raise ReleaseHistoryError('请补齐国家、市场、完整机型和目标软件版本')
    topic = _topic(query, scope)
    available = await _ready(session)
    coverage: dict[str, Any] = {'document_count': 0, 'versions': [], 'excluded_documents': [], 'unresolved_documents': [], 'gaps': []}
    result: dict[str, Any] = {'available': available, 'assessment': 'unavailable', 'conclusion': '历史版本追溯尚未初始化',
              'scope': scope, 'query': query, 'coverage': coverage, 'chains': [], 'events': []}
    if not available:
        return result
    documents = {row['id']: row for row in await _documents(session)}
    bindings = (await session.execute(text('''SELECT * FROM knowledge_release_bindings WHERE is_active=1
        AND product_model_id=:model AND country=:country AND market=:market'''),
        {'model': scope['product_model_id'], 'country': scope['country'], 'market': scope['market']})).mappings().all()
    chunks_by_document: dict[int, list[dict]] = {}
    if documents:
        rows = (await session.execute(text('''SELECT document_id,source_ref,page_number,section_name,content
            FROM knowledge_document_chunks WHERE document_id IN :ids ORDER BY document_id,chunk_index''')
            .bindparams(bindparam('ids', expanding=True)), {'ids': list(documents)})).mappings()
        for row in rows:
            chunks_by_document.setdefault(row['document_id'], []).append(dict(row))
    selected = set()
    chains: dict[str, dict] = {}
    for binding in bindings:
        document = documents.get(binding['document_id'])
        reasons = []
        if document is None:
            reasons.append('原Release Note索引不存在')
        else:
            reasons.extend(await _quality(document))
            if binding['document_fingerprint'] != _fingerprint(document):
                reasons.append('适用关系对应的资料内容或元数据已变化')
            if version_sort_key(document['version']) > version_sort_key(scope['software_version']):
                reasons.append('晚于目标版本')
        if binding['model_name'] != scope['model_name'] or binding['series_name'] != scope['series_name']:
            reasons.append('完整机型身份已变化')
        if release_line and binding['release_line'] != release_line:
            reasons.append('其他版本分支')
        if reasons:
            coverage['excluded_documents'].append({'document_id': binding['document_id'], 'reasons': reasons})
            continue
        assert document is not None
        selected.add(document['id'])
        chain = chains.setdefault(binding['release_line'], {'release_line': binding['release_line'], 'documents': [], 'events': [], 'conditions': [], 'detected_conditions': []})
        chain['documents'].append({'document_id': document['id'], 'title': document['title'], 'version': document['version'], 'preview_url': f"/api/knowledge/documents/{document['id']}/preview"})
        if binding['conditions'] and binding['conditions'] not in chain['conditions']:
            chain['conditions'].append(binding['conditions'])
        detected = _document_conditions(document, chunks_by_document.get(document['id'], []))
        chain['detected_conditions'].extend(item for item in detected if item not in chain['detected_conditions'])
        event_conditions = '\n'.join([binding['conditions'], *(item['excerpt'] for item in detected)]).strip()
        events = _events(document, chunks_by_document.get(document['id'], []), topic, event_conditions)
        # Cumulative documents must not introduce a later section into an earlier target.
        chain['events'].extend(event for event in events if event['event_version'] is None or version_sort_key(event['event_version']) <= version_sort_key(scope['software_version']))
    # Related documents without a trusted applicability bridge remain visible as unresolved candidates.
    for document in documents.values():
        if document['id'] in selected or not _explicit_model(document, scope):
            continue
        if document['country'] and document['country'] != scope['country']:
            continue
        if document['market'] not in (None, '', 'unspecified', scope['market']):
            continue
        if version_sort_key(document['version']) > version_sort_key(scope['software_version']):
            continue
        quality_reasons = await _quality(document)
        reasons = list(quality_reasons)
        if not document['country']:
            reasons.append('国家范围未确认')
        if document['market'] in (None, '', 'unspecified'):
            reasons.append('市场范围未确认')
        reasons.append('缺少当前范围有效的人工适用关系')
        coverage['unresolved_documents'].append({'document_id': document['id'], 'title': document['title'], 'version': document['version'],
            'reasons': reasons, 'preview_url': f"/api/knowledge/documents/{document['id']}/preview",
            'detected_conditions': [] if quality_reasons else _document_conditions(document, chunks_by_document.get(document['id'], [])),
            'candidate_events': [] if quality_reasons else _events(document, chunks_by_document.get(document['id'], []), topic)})
    all_events: list[dict[str, Any]] = []
    for chain in chains.values():
        chain['documents'].sort(key=lambda row: version_sort_key(row['version']))
        chain['events'].sort(key=lambda row: (version_sort_key(row['event_version']), row['document_id'], row['source_ref']))
        all_events.extend({**event, 'release_line': chain['release_line']} for event in chain['events'])
    coverage['document_count'] = len(selected)
    coverage['versions'] = sorted({documents[id]['version'] for id in selected}, key=version_sort_key)
    if scope['software_version'] not in coverage['versions']:
        coverage['gaps'].append('未登记目标版本的明确适用Release Note；不能据历史记录直接保证当前版本能力')
    result.update(chains=list(chains.values()), events=all_events)
    if not chains:
        result.update(assessment='scope_unconfirmed' if coverage['unresolved_documents'] else 'no_applicable_documents',
                      conclusion='找到相关历史资料，但适用范围尚待核对。' if coverage['unresolved_documents'] else '没有当前完整机型与范围的有效历史资料；不能判断支持或不支持。')
    elif not all_events:
        result.update(assessment='no_record', conclusion='已登记适用历史资料中未检索到该子能力的明确记录；未检索到不等于不支持。')
    elif any({'added', 'removed'}.issubset({event['change_type'] for event in chain['events'] if event['event_version'] == version})
             for chain in chains.values() for version in {event['event_version'] for event in chain['events']}):
        result.update(assessment='conflicting_evidence', conclusion='同一版本分支与版本出现相反的新增/移除记录，需核对原文后才能判断。')
    elif len(chains) > 1 or any(chain['conditions'] or chain['detected_conditions'] for chain in chains.values()) or any(event['event_version'] is None or event['change_type'] in ('restricted', 'unknown') for event in all_events):
        result.update(assessment='conditional_evidence', conclusion='找到相关版本记录，但存在版本分支、硬件/升级限制或语义待核实；各分支分别展示，不直接继承为目标版本支持结论。')
    else:
        result.update(assessment='evidence_found', conclusion='找到该子能力的历史版本原文记录；以下为资料证据，尚未自动发布正式答案。')
    return result


async def history_for_question(session: AsyncSession, query: str, scope: dict) -> dict:
    """A broad ordinary question must not become a failed ask request."""
    try:
        return await trace_release_history(session, query, scope)
    except ReleaseHistoryError as error:
        return {'available': await _ready(session), 'assessment': 'needs_clarification',
                'conclusion': str(error), 'scope': scope, 'query': query,
                'coverage': {'document_count': 0, 'versions': [], 'excluded_documents': [], 'unresolved_documents': [], 'gaps': []},
                'chains': [], 'events': []}
