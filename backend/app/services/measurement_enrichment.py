"""Source-bound, immutable research candidates and serialized human review."""
from collections import defaultdict
from collections.abc import Sequence
from typing import Any, cast
import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.measurement import (
    MeasurementBatch, MeasurementEntry,
    MeasurementEnrichmentCandidate as Candidate, MeasurementEnrichmentReview as Review,
)
from app.schemas.measurement_enrichment import EnrichmentImport, EnrichmentPayload, EnrichmentReview


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


async def storage_ready(db: AsyncSession) -> bool:
    connection = await db.connection()
    return await connection.run_sync(lambda c: all(inspect(c).has_table(name) for name in (
        Candidate.__tablename__, Review.__tablename__)))


async def require_storage(db: AsyncSession) -> None:
    if not await storage_ready(db):
        raise HTTPException(503, '计算补全审核表尚未初始化，请更新服务后重试')


def raw_data(row: MeasurementEntry) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in MeasurementEntry.__table__.columns}


def source_fingerprint(batch: MeasurementBatch, rows: Sequence[MeasurementEntry]) -> str:
    return digest({'batch_id': batch.id, 'sha256': batch.sha256, 'version': batch.version,
                   'rows': [raw_data(row) for row in rows]})


def candidate_data(row: Candidate) -> dict[str, Any]:
    return {'id': row.id, 'revision': row.revision, 'fingerprint': row.fingerprint, 'source_fingerprint': row.source_fingerprint, 'payload': row.payload}


def active_confirmation(reviews: Sequence[Review], source: str) -> Review | None:
    for review in reviews:
        if review.source_fingerprint != source:
            continue
        if review.action == 'revoke':
            return None
        if review.action == 'confirm':
            return review
    return None


def state_for(batch: MeasurementBatch, rows: Sequence[MeasurementEntry], candidates: Sequence[Candidate], reviews: Sequence[Review]) -> dict[str, Any] | None:
    if not candidates:
        return None
    candidate = candidates[0]
    source = source_fingerprint(batch, rows)
    source_stale = cast(str, candidate.source_fingerprint) != source
    active = None if source_stale else active_confirmation(reviews, source)
    latest = reviews[0] if reviews else None
    current = latest if latest and latest.candidate_id == candidate.id and latest.source_fingerprint == source else None
    status = {'confirm': 'confirmed', 'reject': 'rejected', 'defer': 'deferred', 'revoke': 'pending'}.get(cast(str, current.action)) if current else None
    if not status:
        status = 'unresolved' if candidate.payload['research_status'] == 'unresolved' else 'pending'
    if source_stale:
        status = 'stale_source'
    return {'candidate': candidate_data(candidate), 'source_fingerprint': source, 'source_stale': source_stale,
            'review_revision': latest.review_revision if latest else 0, 'status': status,
            'confirmed_payload': active.confirmed_payload if active else None,
            'has_pending_update': bool(active and active.candidate_id != candidate.id and not current)}


async def batch_records(db: AsyncSession, batch_id: int) -> tuple[dict[str, list[Candidate]], dict[str, list[Review]]]:
    candidates = (await db.scalars(select(Candidate).where(Candidate.batch_id == batch_id).order_by(Candidate.revision.desc(), Candidate.id.desc()))).all()
    reviews = (await db.scalars(select(Review).where(Review.batch_id == batch_id).order_by(Review.review_revision.desc(), Review.id.desc()))).all()
    by_candidates: dict[str, list[Candidate]] = defaultdict(list)
    by_reviews: dict[str, list[Review]] = defaultdict(list)
    for row in candidates:
        by_candidates[cast(str, row.item_id)].append(row)
    for row in reviews:
        by_reviews[cast(str, row.item_id)].append(row)
    return by_candidates, by_reviews


async def decorate_library(db: AsyncSession, batch: MeasurementBatch | None, rows: Sequence[MeasurementEntry], entries: list[dict[str, Any]]) -> bool:
    """Three bulk queries independent of row count; source dictionaries stay unchanged."""
    available = await storage_ready(db)
    if available and batch:
        candidates, reviews = await batch_records(db, cast(int, batch.id))
        source_rows: dict[str, list[MeasurementEntry]] = defaultdict(list)
        for row in rows:
            if row.kind == 'calculation':
                source_rows[cast(str, row.item_id)].append(row)
        for entry in entries:
            if entry['kind'] == 'calculation':
                entry['enrichment'] = state_for(batch, source_rows[entry['item_id']], candidates[entry['item_id']], reviews[entry['item_id']])
    else:
        for entry in entries:
            if entry['kind'] == 'calculation':
                entry['enrichment'] = None
    return available


def validate_dependencies(payload: dict[str, Any], identities: set[tuple[str, str]]) -> None:
    for term in payload['input_terms']:
        for dependency in term['possible_dependencies']:
            if (dependency['kind'], dependency['item_id']) not in identities:
                raise HTTPException(422, f"依赖 Id 在当前批次不存在：{dependency['item_id']}")


async def import_candidates(db: AsyncSession, manifest: EnrichmentImport) -> dict[str, Any]:
    await require_storage(db)
    await db.execute(text('BEGIN IMMEDIATE'))
    try:
        batch = await db.get(MeasurementBatch, manifest.batch_id)
        if not batch:
            raise HTTPException(404, '测量库版本不存在')
        if batch.sha256 != manifest.expected_sha256 or batch.version != manifest.expected_version:
            raise HTTPException(409, '来源批次内容或版本已变化，请重新生成候选清单')
        rows = (await db.scalars(select(MeasurementEntry).where(MeasurementEntry.batch_id == batch.id).order_by(MeasurementEntry.id))).all()
        identities = {(cast(str, row.kind), cast(str, row.item_id)) for row in rows}
        grouped: dict[str, list[MeasurementEntry]] = defaultdict(list)
        for row in rows:
            if row.kind == 'calculation':
                grouped[cast(str, row.item_id)].append(row)
        if len({item.item_id for item in manifest.candidates}) != len(manifest.candidates):
            raise HTTPException(422, '候选清单存在重复 Id')
        prepared: list[tuple[str, dict[str, Any], str, str]] = []
        for item in manifest.candidates:
            if item.item_id not in grouped:
                raise HTTPException(422, f'当前批次不存在计算 Id：{item.item_id}')
            payload = item.payload.model_dump(exclude_none=True)
            validate_dependencies(payload, identities)
            source = source_fingerprint(batch, grouped[item.item_id])
            fingerprint = digest({'source_fingerprint': source, 'schema_version': 1, 'payload': payload})
            prepared.append((item.item_id, payload, source, fingerprint))
        candidates, _ = await batch_records(db, cast(int, batch.id))
        result, created = [], 0
        for item_id, payload, source, fingerprint in prepared:
            existing = next((c for c in candidates[item_id] if c.fingerprint == fingerprint), None)
            if existing is None:
                existing = Candidate(batch_id=batch.id, item_id=item_id, payload=payload, source_fingerprint=source,
                                     fingerprint=fingerprint, revision=max((c.revision for c in candidates[item_id]), default=0)+1)
                db.add(existing)
                await db.flush()
                created += 1
            result.append({'item_id': item_id, 'id': existing.id, 'revision': existing.revision, 'fingerprint': existing.fingerprint})
        await db.commit()
        return {'batch_id': batch.id, 'created': created, 'reused': len(result)-created, 'candidates': result}
    except Exception:
        await db.rollback()
        raise


async def detail(db: AsyncSession, candidate_id: int) -> dict[str, Any]:
    await require_storage(db)
    requested = await db.get(Candidate, candidate_id)
    if not requested:
        raise HTTPException(404, '候选不存在')
    batch = await db.get(MeasurementBatch, requested.batch_id)
    if batch is None:
        raise HTTPException(404, '来源批次不存在')
    rows = (await db.scalars(select(MeasurementEntry).where(MeasurementEntry.batch_id == batch.id,
            MeasurementEntry.kind == 'calculation', MeasurementEntry.item_id == requested.item_id).order_by(MeasurementEntry.id))).all()
    candidates, reviews = await batch_records(db, cast(int, batch.id))
    history = [{key: getattr(r, key) for key in ('id', 'candidate_id', 'review_revision', 'action', 'confirmed_by', 'note',
               'confirmed_payload', 'source_fingerprint', 'candidate_fingerprint')} | {'created_at': r.created_at.isoformat()} for r in reviews[cast(str, requested.item_id)]]
    return {'batch_id': batch.id, 'item_id': requested.item_id, 'raw_rows': [raw_data(row) for row in rows],
            'enrichment_available': True, 'enrichment': state_for(batch, rows, candidates[cast(str, requested.item_id)], reviews[cast(str, requested.item_id)]), 'history': history}


def numeric_dependencies(payload: dict[str, Any]) -> list[str]:
    """Only numeric inputs and alternatives contribute calculation graph edges."""
    return [dependency['item_id'] for term in payload['input_terms']
            if term.get('relation_kind', 'input') in {'input', 'alternative'}
            for dependency in term['possible_dependencies'] if dependency['kind'] == 'calculation']


def validate_graph(graph: dict[str, list[str]]) -> None:
    # Iterative DFS avoids recursion limits for large imported calculation sets.
    complete: set[str] = set()
    for root in graph:
        if root in complete:
            continue
        path: set[str] = set()
        stack: list[tuple[str, bool]] = [(root, False)]
        while stack:
            node, leaving = stack.pop()
            if leaving:
                path.remove(node)
                complete.add(node)
                continue
            if node in path:
                raise HTTPException(422, '确认后的计算依赖存在循环，请修订依赖')
            if node in complete:
                continue
            path.add(node)
            stack.append((node, True))
            stack.extend((child, False) for child in graph.get(node, []))


async def review_candidate(db: AsyncSession, candidate_id: int, request: EnrichmentReview) -> dict[str, Any]:
    await require_storage(db)
    if not request.confirmed_by.strip() or (request.action != 'confirm' and not request.note.strip()):
        raise HTTPException(422, '请填写实际审核人；拒绝、暂缓和撤销还须填写原因')
    if request.action != 'confirm' and request.confirmed_payload is not None:
        raise HTTPException(422, '只有确认操作可以提交修订后的内容')
    await db.execute(text('BEGIN IMMEDIATE'))
    try:
        data = await detail(db, candidate_id)
        state = data['enrichment']
        candidate = state['candidate']
        if candidate['id'] != candidate_id or candidate['fingerprint'] != request.expected_candidate_fingerprint or state['source_fingerprint'] != request.expected_source_fingerprint:
            raise HTTPException(409, '来源或候选已更新，请刷新后审核')
        stored_candidate = await db.get(Candidate, candidate_id)
        if stored_candidate is None:
            raise HTTPException(404, '候选不存在')
        if stored_candidate.source_fingerprint != state['source_fingerprint']:
            raise HTTPException(409, '原始数据已变化，请重新生成候选')
        fingerprint = digest({'candidate_id': candidate_id, **request.model_dump(exclude_none=True)})
        candidates, reviews = await batch_records(db, data['batch_id'])
        latest = reviews[data['item_id']][0] if reviews[data['item_id']] else None
        if state['review_revision'] != request.expected_review_revision:
            if latest and latest.request_fingerprint == fingerprint:
                await db.rollback()
                return await detail(db, candidate_id)
            raise HTTPException(409, '已有新的审核结论，请刷新后重试')
        confirmed = None
        if request.action == 'confirm':
            confirmed = (request.confirmed_payload or EnrichmentPayload.model_validate(candidate['payload'])).model_dump(exclude_none=True)
            if confirmed['research_status'] != 'proposed' or not confirmed['categories'] or not confirmed['sources']:
                raise HTTPException(422, '确认须提供明确分类、公开依据和已修订的 proposed 内容')
            rows = (await db.scalars(select(MeasurementEntry).where(MeasurementEntry.batch_id == data['batch_id']).order_by(MeasurementEntry.id))).all()
            validate_dependencies(confirmed, {(cast(str, r.kind), cast(str, r.item_id)) for r in rows})
            source_rows: dict[str, list[MeasurementEntry]] = defaultdict(list)
            for row in rows:
                if row.kind == 'calculation':
                    source_rows[cast(str, row.item_id)].append(row)
            batch = await db.get(MeasurementBatch, data['batch_id'])
            if batch is None:
                raise HTTPException(404, '来源批次不存在')
            graph: dict[str, list[str]] = {}
            for item_id, item_reviews in reviews.items():
                active = active_confirmation(item_reviews, source_fingerprint(batch, source_rows[item_id]))
                if active:
                    graph[item_id] = numeric_dependencies(cast(dict[str, Any], active.confirmed_payload))
            graph[data['item_id']] = numeric_dependencies(confirmed)
            validate_graph(graph)
        db.add(Review(batch_id=data['batch_id'], item_id=data['item_id'], candidate_id=candidate_id,
                      review_revision=state['review_revision']+1, candidate_fingerprint=candidate['fingerprint'],
                      source_fingerprint=state['source_fingerprint'], request_fingerprint=fingerprint,
                      action=request.action, confirmed_by=request.confirmed_by.strip(), note=request.note.strip(), confirmed_payload=confirmed))
        await db.commit()
        return await detail(db, candidate_id)
    except Exception:
        await db.rollback()
        raise
