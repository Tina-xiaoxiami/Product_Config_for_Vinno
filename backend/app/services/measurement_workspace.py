"""Measurement library lifecycle. Documents own names, associations and frozen evidence.

The immutable import and append-only research stores are read only dependencies.
"""
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any

from app.schemas.measurement_workspace import EditInput, InitializeInput, PreviewInput, PublishInput, UndoInput

from app.models.measurement import MeasurementBatch, MeasurementEnrichmentCandidate, MeasurementEnrichmentReview
from app.models.measurement_workspace import MeasurementWorkspace, MeasurementWorkspaceVersion
from app.services.measurement_enrichment import storage_ready
from app.services.measurements import measurement_library

NAME_FIELDS = ('cn_name', 'description', 'en_name')
ASSIGNMENT_FIELDS = ('mode', 'categories', 'assignment_origin', 'classification_basis')
EVIDENCE_FIELDS = ('enrichment', 'enrichment_status', 'official_mode', 'official_categories')


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def signature(value: Any) -> str:
    return hashlib.sha256(encode(value).encode()).hexdigest()


def modes(value: str | list[str] | None) -> list[str]:
    return list(value) if isinstance(value, list) else [value] if value else []


def fields(row: dict[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
    return {name: deepcopy(row.get(name)) for name in names}


def project_source(row: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(row)
    enrichment = row.get('enrichment')
    # Every managed record has the same evidence shape, including raw measures.
    result['enrichment'] = deepcopy(enrichment)
    confirmed = enrichment.get('confirmed_payload') if enrichment and enrichment['status'] != 'stale_source' else None
    pending = enrichment.get('candidate', {}).get('payload') if enrichment and enrichment['status'] in {'pending', 'deferred', 'unresolved'} else None
    payload = confirmed or pending
    status_labels = {'pending': '待核对', 'confirmed': '已核对', 'rejected': '未采用', 'deferred': '暂缓核对', 'unresolved': '待补充', 'stale_source': '来源已变化'}
    if row['kind'] == 'measurement':
        status = '原表'
    elif confirmed:
        assert enrichment is not None
        status = '已核对（有新建议）' if enrichment.get('has_pending_update') else '已核对'
    else:
        status = status_labels.get(enrichment['status'], '待补充') if enrichment else '未补充'
    result.update(record_key=f"source:{row['id']}", source_entry_id=row['id'],
                  source_mode=deepcopy(row.get('mode', '')), source_categories=deepcopy(row.get('categories', [])),
                  mode=modes(payload['modes'] if payload else row.get('mode')),
                  categories=deepcopy(payload['categories'] if payload else row.get('categories', [])),
                  official_mode=modes(confirmed['modes'] if confirmed else row.get('mode')),
                  official_categories=deepcopy(confirmed['categories'] if confirmed else row.get('categories', [])),
                  assignment_origin='confirmed' if confirmed else 'suggestion' if pending else 'source',
                  classification_basis='已核对补充' if confirmed else '待核对建议' if pending else '原表',
                  enrichment_status=status)
    return result


def frozen_projection(row: dict[str, Any]) -> dict[str, Any]:
    """Derive automatic associations solely from this document's frozen evidence."""
    source = deepcopy(row)
    source['mode'] = deepcopy(row['source_mode'])
    source['categories'] = deepcopy(row['source_categories'])
    return project_source(source)


def evidence_payloads(row: dict[str, Any]) -> list[dict[str, Any]]:
    evidence = row.get('enrichment') or {}
    payloads = [(evidence.get('candidate') or {}).get('payload'), evidence.get('confirmed_payload')]
    payloads.extend(candidate.get('payload') for candidate in evidence.get('candidate_history', []))
    payloads.extend(review.get('confirmed_payload') for review in evidence.get('history', []))
    return [payload for payload in payloads if payload]


def register_codes(document: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    """Include hidden source, candidate and confirmation codes, preserving managed names."""
    applications = {item['code']: item for item in document['applications']}
    mode_dict = {item['code']: item for item in document['modes']}
    for row in rows:
        pairs = [(row.get('source_categories', []), modes(row.get('source_mode'))),
                 (row.get('categories', []), row.get('mode', [])),
                 (row.get('official_categories', []), row.get('official_mode', []))]
        for payload in evidence_payloads(row):
            pairs.append((payload.get('categories', []), payload.get('modes', [])))
        for categories, row_modes in pairs:
            for code in categories:
                applications.setdefault(code, {'code': code, 'name': code})
            for code in row_modes:
                mode_dict.setdefault(code, {'code': code, 'name': code})
    # Common is a reserved semantic code even in batches without a Common row.
    applications.setdefault('Common', {'code': 'Common', 'name': 'Common'})
    document['applications'] = sorted(applications.values(), key=lambda item: item['code'])
    document['modes'] = sorted(mode_dict.values(), key=lambda item: item['code'])


async def source_document(db: AsyncSession, batch_id: int) -> dict[str, Any]:
    try:
        library = await measurement_library(db, batch_id)
    except KeyError as error:
        raise HTTPException(404, '测量库来源批次不存在') from error
    history = defaultdict(list)
    candidate_history = defaultdict(list)
    if await storage_ready(db):
        candidates = (await db.scalars(select(MeasurementEnrichmentCandidate).where(
            MeasurementEnrichmentCandidate.batch_id == batch_id).order_by(MeasurementEnrichmentCandidate.revision, MeasurementEnrichmentCandidate.id))).all()
        for candidate in candidates:
            candidate_history[candidate.item_id].append({column.name: getattr(candidate, column.name).isoformat() if column.name == 'created_at' else deepcopy(getattr(candidate, column.name))
                                                         for column in MeasurementEnrichmentCandidate.__table__.columns})
        reviews = (await db.scalars(select(MeasurementEnrichmentReview).where(
            MeasurementEnrichmentReview.batch_id == batch_id).order_by(MeasurementEnrichmentReview.review_revision, MeasurementEnrichmentReview.id))).all()
        for review in reviews:
            history[review.item_id].append({column.name: getattr(review, column.name).isoformat() if column.name == 'created_at' else deepcopy(getattr(review, column.name))
                                           for column in MeasurementEnrichmentReview.__table__.columns})
    entries = [project_source(row) for row in library['entries']]
    for row in entries:
        if row.get('enrichment') is not None:
            row['enrichment']['history'] = history[row['item_id']]
            row['enrichment']['candidate_history'] = candidate_history[row['item_id']]
    document = {'schema_version': 1, 'batch': library['batch'], 'entries': entries, 'applications': [], 'modes': []}
    register_codes(document, entries)
    return document


def document_diff(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    """Logical changes, stable keys, and sufficient originals for lossless single undo."""
    result = []
    def add(key, entity, label, field, old, new, count=1):
        if old != new:
            result.append({'key': signature(key), 'change_type': 'create' if old is None else 'delete' if new is None else 'update',
                           'entity': entity, 'label': label, 'field': field, 'before': deepcopy(old), 'after': deepcopy(new), 'affected_count': count})
    old_rows = {row['record_key']: row for row in before['entries']}
    new_rows = {row['record_key']: row for row in after['entries']}
    names = defaultdict(list)
    for key in sorted(old_rows.keys() | new_rows.keys()):
        left, right = old_rows.get(key), new_rows.get(key)
        row = right if right is not None else left
        assert row is not None
        label = f"{row['kind']} · {row['item_id']}"
        if left is None or right is None:
            add(['record', key], 'item', label, 'record', left, right)
            continue
        if fields(left, NAME_FIELDS) != fields(right, NAME_FIELDS):
            names[(row['kind'], row['item_id'])].append(key)
        evidence_changed = fields(left, EVIDENCE_FIELDS) != fields(right, EVIDENCE_FIELDS)
        # Evidence and its automatic projection are one logical change. A manual
        # association remains independently editable/undoable during research sync.
        coupled = evidence_changed and right['assignment_origin'] != 'manual'
        evidence_fields = EVIDENCE_FIELDS + ASSIGNMENT_FIELDS if coupled else EVIDENCE_FIELDS
        if not coupled:
            add(['assignments', key], 'item', label, 'assignments', {'record_key': key, **fields(left, ASSIGNMENT_FIELDS)}, {'record_key': key, **fields(right, ASSIGNMENT_FIELDS)})
        add(['evidence', key], 'evidence', label, 'evidence', {'record_key': key, **fields(left, evidence_fields)}, {'record_key': key, **fields(right, evidence_fields)})
    for identity, keys in sorted(names.items()):
        add(['names', *identity], 'item', ' · '.join(identity), 'names',
            [{'record_key': key, **fields(old_rows[key], NAME_FIELDS)} for key in keys],
            [{'record_key': key, **fields(new_rows[key], NAME_FIELDS)} for key in keys], len(keys))
    for dimension in ('applications', 'modes'):
        old = {item['code']: item for item in before[dimension]}
        new = {item['code']: item for item in after[dimension]}
        for code in sorted(old.keys() | new.keys()):
            add(['dictionary', dimension, code], 'dictionary', f'{dimension} · {code}', dimension, old.get(code), new.get(code))
    return result


async def workspace(db: AsyncSession, workspace_id: int) -> MeasurementWorkspace:
    item = await db.get(MeasurementWorkspace, workspace_id)
    if item is None:
        raise HTTPException(404, '测量库工作区不存在')
    return item


async def view(db: AsyncSession, item: MeasurementWorkspace) -> dict[str, Any]:
    published = json.loads(item.published_data)
    document = json.loads(item.draft_data) if item.draft_data else published
    versions = (await db.scalars(select(MeasurementWorkspaceVersion).where(
        MeasurementWorkspaceVersion.workspace_id == item.id).order_by(MeasurementWorkspaceVersion.id.desc()))).all()
    return {'initialized': True, 'id': item.id, 'batch_id': item.batch_id, 'revision': item.revision,
            'has_draft': item.draft_data is not None, 'data': document, 'published_data': published,
            'versions': [version_data(row) for row in versions], 'changes': document_diff(published, document),
            'latest_version_id': versions[0].id if versions else None}


def version_data(row: MeasurementWorkspaceVersion, include_data: bool = False) -> dict[str, Any]:
    result = {'id': row.id, 'version_number': row.version_number, 'description': row.description,
              'created_at': row.created_at.isoformat(), 'initial': row.initial}
    if include_data:
        result['data'] = json.loads(row.snapshot_data)
    return result


def check_revision(item: MeasurementWorkspace, revision: int) -> None:
    if item.revision != revision:
        raise HTTPException(409, '草稿已被其他操作修改，请刷新后重新核对')


async def change(db: AsyncSession, item: MeasurementWorkspace, revision: int, **values: Any) -> None:
    changed = await db.execute(update(MeasurementWorkspace).where(
        MeasurementWorkspace.id == item.id, MeasurementWorkspace.revision == revision
    ).values(**values, revision=revision + 1).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        raise HTTPException(409, '草稿已被其他操作修改，请刷新后重新核对')
    await db.refresh(item)


def validate_document(document: dict[str, Any]) -> dict[str, Any]:
    """Undo/restore are also write paths: validate the complete library graph."""
    registered = {}
    for dimension in ('applications', 'modes'):
        values = document[dimension]
        codes = [entry['code'] for entry in values]
        if len(set(codes)) != len(codes) or any(not code or code != code.strip() for code in codes):
            raise HTTPException(422, '字典代码必须非空且唯一')
        if any(not entry['name'].strip() for entry in values):
            raise HTTPException(422, '字典名称不能为空')
        registered[dimension] = set(codes)
    if 'Common' not in registered['applications']:
        raise HTTPException(422, '通用分类 Common 为保留代码')
    keys = [row['record_key'] for row in document['entries']]
    if len(set(keys)) != len(keys):
        raise HTTPException(422, '测量库记录标识重复')
    for row in document['entries']:
        if row['assignment_origin'] != 'manual':
            expected = frozen_projection(row)
            automatic_fields = ASSIGNMENT_FIELDS + ('official_mode', 'official_categories', 'enrichment_status')
            if fields(row, automatic_fields) != fields(expected, automatic_fields):
                raise HTTPException(422, '自动分类与冻结证据不一致，请先同步或撤销相关证据变更')
        categories = set(row['categories']) | set(row['source_categories']) | set(row['official_categories'])
        row_modes = set(row['mode']) | set(modes(row['source_mode'])) | set(row['official_mode'])
        for payload in evidence_payloads(row):
            categories.update(payload.get('categories', []))
            row_modes.update(payload.get('modes', []))
        if not categories <= registered['applications'] or not row_modes <= registered['modes']:
            raise HTTPException(422, '记录或证据引用了缺失字典代码，请先还原对应字典变更')
    return document


async def save(db: AsyncSession, item: MeasurementWorkspace, revision: int, document: dict[str, Any]) -> dict[str, Any]:
    validate_document(document)
    draft = None if document == json.loads(item.published_data) else encode(document)
    await change(db, item, revision, draft_data=draft)
    await db.commit()
    return await view(db, item)


async def initialize(db: AsyncSession, data: InitializeInput) -> dict[str, Any]:
    # The legacy research writer takes this same SQLite write lock. Acquire it
    # before reading either projected state or audit rows to freeze one moment.
    await db.execute(text('BEGIN IMMEDIATE'))
    batch = await db.get(MeasurementBatch, data.batch_id)
    if batch is None:
        raise HTTPException(404, '测量库来源批次不存在')
    if batch.sha256 != data.expected_sha256:
        raise HTTPException(409, '来源批次内容已变化，请重新核对')
    existing = await db.scalar(select(MeasurementWorkspace).where(MeasurementWorkspace.batch_id == data.batch_id))
    if existing:
        return await view(db, existing)
    number = data.version_number if data.version_number is not None else batch.version
    if not number.strip() or number != number.strip():
        raise HTTPException(422, '版本号不能为空或含首尾空格')
    document = validate_document(await source_document(db, data.batch_id))
    item = MeasurementWorkspace(batch_id=data.batch_id, published_data=encode(document))
    db.add(item)
    try:
        await db.flush()
        db.add(MeasurementWorkspaceVersion(workspace_id=item.id, version_number=number, description=data.description,
                                           snapshot_data=encode(document), initial=True))
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        existing = await db.scalar(select(MeasurementWorkspace).where(MeasurementWorkspace.batch_id == data.batch_id))
        if existing:
            return await view(db, existing)
        raise HTTPException(409, '初始化版本冲突，请刷新重试') from error
    return await view(db, item)


def find_row(document: dict[str, Any], key: str) -> dict[str, Any]:
    row = next((row for row in document['entries'] if row['record_key'] == key), None)
    if row is None:
        raise HTTPException(404, '测量库记录不存在')
    return row


def validate_assignments(document: dict[str, Any], categories: list[str], row_modes: list[str]) -> None:
    if not set(categories) <= {item['code'] for item in document['applications']} or not set(row_modes) <= {item['code'] for item in document['modes']}:
        raise HTTPException(422, '请先登记新的分类或模式代码')


async def edit(db: AsyncSession, item: MeasurementWorkspace, data: EditInput) -> dict[str, Any]:
    check_revision(item, data.revision)
    document = json.loads(item.draft_data or item.published_data)
    operation = data.operation
    if operation == 'rename_item':
        selected = find_row(document, data.record_key)
        for row in document['entries']:
            if (row['kind'], row['item_id']) == (selected['kind'], selected['item_id']):
                row.update(cn_name=data.cn_name, description=data.description, en_name=data.description or row['item_id'])
    elif operation == 'assign_item':
        validate_assignments(document, data.categories, data.modes)
        row = find_row(document, data.record_key)
        if set(row['categories']) != set(data.categories) or set(row['mode']) != set(data.modes):
            baseline = next((entry for entry in json.loads(item.published_data)['entries'] if entry['record_key'] == row['record_key']), None)
            same_evidence = baseline is not None and fields(baseline, EVIDENCE_FIELDS) == fields(row, EVIDENCE_FIELDS)
            if baseline and same_evidence and set(baseline['categories']) == set(data.categories) and set(baseline['mode']) == set(data.modes):
                row.update(fields(baseline, ASSIGNMENT_FIELDS))
            else:
                row.update(categories=data.categories, mode=data.modes, assignment_origin='manual', classification_basis='人工维护')
    elif operation == 'upsert_dictionary':
        existing = next((entry for entry in document[data.dimension] if entry['code'] == data.code), None)
        if existing:
            existing['name'] = data.name
        else:
            document[data.dimension].append({'code': data.code, 'name': data.name})
            document[data.dimension].sort(key=lambda entry: entry['code'])
    elif operation == 'add_item':
        if data.item_id != data.item_id.strip():
            raise HTTPException(422, 'Id 不能为空或含首尾空格')
        validate_assignments(document, data.categories, data.modes)
        matches = [entry for entry in document['entries'] if (entry['kind'], entry['item_id']) == (data.kind, data.item_id)]
        if matches and not data.allow_existing_id:
            raise HTTPException(409, '同类型 Id 已存在；新增关联记录需明确确认')
        if matches and any((entry['cn_name'], entry['description']) != (data.cn_name, data.description) for entry in matches):
            raise HTTPException(422, '同类型 Id 名称必须统一，请先统一维护名称')
        document['entries'].append({'record_key': f'manual:{uuid4()}', 'source_entry_id': None, 'id': None,
            'batch_id': item.batch_id, 'kind': data.kind, 'item_id': data.item_id, 'cn_name': data.cn_name,
            'description': data.description, 'en_name': data.description or data.item_id, 'mode': data.modes,
            'categories': data.categories, 'group': data.group, 'unit': data.unit, 'enabled_raw': data.enabled_raw,
            'enabled': {'true': 'enabled', 'false': 'disabled'}.get(data.enabled_raw.casefold(), 'unknown'),
            'source_sheet': '', 'source_row': None, 'source_mode': '', 'source_categories': [],
            'official_mode': [], 'official_categories': [], 'enrichment': None, 'enrichment_status': '未补充',
            'assignment_origin': 'manual', 'classification_basis': '人工维护'})
    return await save(db, item, data.revision, document)


async def undo(db: AsyncSession, item: MeasurementWorkspace, data: UndoInput) -> dict[str, Any]:
    check_revision(item, data.revision)
    baseline = json.loads(item.published_data)
    document = json.loads(item.draft_data or item.published_data)
    delta = next((delta for delta in document_diff(baseline, document) if delta['key'] == data.change_key), None)
    if delta is None:
        raise HTTPException(409, '变更已不存在，请刷新草稿列表')
    before, after, field = delta['before'], delta['after'], delta['field']
    if delta['entity'] == 'dictionary':
        code = (before or after)['code']
        if before is None:
            references = ('categories', 'source_categories', 'official_categories') if field == 'applications' else ('mode', 'official_mode')
            payload_field = 'categories' if field == 'applications' else 'modes'
            assigned = any(code in row.get(name, []) for row in document['entries'] for name in references)
            evidenced = any(code in payload.get(payload_field, []) for row in document['entries'] for payload in evidence_payloads(row))
            if assigned or evidenced:
                raise HTTPException(409, '该字典代码仍被记录引用，请先撤销相关记录变更')
        document[field] = [entry for entry in document[field] if entry['code'] != code]
        if before is not None:
            document[field].append(before)
            document[field].sort(key=lambda entry: entry['code'])
    elif field == 'record':
        key = (before or after)['record_key']
        document['entries'] = [row for row in document['entries'] if row['record_key'] != key]
        if before is not None:
            # Restore the original order, making complete undo equal to baseline.
            document['entries'].append(before)
            order = {row['record_key']: index for index, row in enumerate(baseline['entries'])}
            document['entries'].sort(key=lambda row: order.get(row['record_key'], len(order)))
    elif field == 'names':
        for original in before:
            find_row(document, original['record_key']).update({key: value for key, value in original.items() if key != 'record_key'})
    elif field == 'assignments' and before['assignment_origin'] != 'manual':
        row = find_row(document, before['record_key'])
        # The published association may predate evidence retained in this draft.
        # Undoing a manual override returns to today's frozen automatic view.
        row.update(fields(frozen_projection(row), ASSIGNMENT_FIELDS))
    else:
        find_row(document, before['record_key']).update({key: value for key, value in before.items() if key != 'record_key'})
    return await save(db, item, data.revision, document)


async def preview(db: AsyncSession, item: MeasurementWorkspace, data: PreviewInput) -> dict[str, Any]:
    check_revision(item, data.revision)
    baseline = json.loads(item.published_data)
    document = json.loads(item.draft_data or item.published_data)
    validate_document(document)
    changes = document_diff(baseline, document)
    if not changes:
        raise HTTPException(400, '测量库没有变化，无需创建版本')
    exists = await db.scalar(select(MeasurementWorkspaceVersion.id).where(
        MeasurementWorkspaceVersion.workspace_id == item.id, MeasurementWorkspaceVersion.version_number == data.version_number))
    if exists:
        raise HTTPException(409, '版本号已存在，请使用新版本号')
    token = signature({'workspace_id': item.id, 'revision': item.revision, 'published_data': baseline,
                       'data': document, 'version_number': data.version_number, 'description': data.description})
    return {'signature': token, 'revision': item.revision, 'version_number': data.version_number,
            'description': data.description, 'changes': changes, 'change_count': len(changes)}


async def publish(db: AsyncSession, item: MeasurementWorkspace, data: PublishInput) -> dict[str, Any]:
    # Serialize writers before refreshing the snapshot/signature, as probe publication does.
    await db.execute(update(MeasurementWorkspace).where(MeasurementWorkspace.id == item.id).values(revision=MeasurementWorkspace.revision))
    await db.refresh(item)
    checked = await preview(db, item, data)
    if checked['signature'] != data.signature:
        raise HTTPException(409, '草稿或发布信息已变化，请重新核对发布预览')
    snapshot = item.draft_data
    await change(db, item, data.revision, published_data=snapshot, draft_data=None)
    db.add(MeasurementWorkspaceVersion(workspace_id=item.id, version_number=data.version_number,
                                       description=data.description, snapshot_data=snapshot, initial=False))
    try:
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(409, '版本号已存在，请重新核对发布预览') from error
    return await view(db, item)


async def version_for(db: AsyncSession, item: MeasurementWorkspace, version_id: int) -> MeasurementWorkspaceVersion:
    row = await db.get(MeasurementWorkspaceVersion, version_id)
    if row is None or row.workspace_id != item.id:
        raise HTTPException(404, '测量库历史版本不存在')
    return row


async def sync_evidence(db: AsyncSession, item: MeasurementWorkspace, revision: int) -> dict[str, Any]:
    await db.execute(text('BEGIN IMMEDIATE'))
    await db.refresh(item)
    check_revision(item, revision)
    document = json.loads(item.draft_data or item.published_data)
    current = await source_document(db, item.batch_id)
    source = {row['record_key']: row for row in current['entries']}
    for row in document['entries']:
        fresh = source.get(row['record_key'])
        if fresh is None:
            continue
        row.update(fields(fresh, EVIDENCE_FIELDS))
        if row['assignment_origin'] != 'manual':
            row.update(fields(fresh, ASSIGNMENT_FIELDS))
    register_codes(document, current['entries'])
    return await save(db, item, revision, document)
