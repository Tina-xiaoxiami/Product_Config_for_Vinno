"""Candidate evidence must remain separate from immutable source facts."""
import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.measurements import router
from app.database import Base, get_db
from app.models.measurement import MeasurementBatch, MeasurementEntry


@pytest_asyncio.fixture
async def api(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'enrichment.db'}")
    async with engine.begin() as conn:
        for name in ('measurement_batches', 'measurement_entries', 'measurement_enrichment_candidates', 'measurement_enrichment_reviews'):
            await conn.run_sync(Base.metadata.tables[name].create)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        db.add(MeasurementBatch(id=1, version='1.51.90', sha256='a'*64, source_file='source.xlsx', summary={}, warnings=[]))
        await db.flush()
        for kind, item in [('measurement', 'A/B.'), ('calculation', 'C.(1)'), ('calculation', 'D')]:
            db.add(MeasurementEntry(batch_id=1, kind=kind, item_id=item, source_sheet='source', source_row=2))
        await db.commit()
    app = FastAPI()
    app.include_router(router, prefix='/api/measurements')
    async def override():
        async with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        yield client, engine
    await engine.dispose()


def payload():
    return dict(categories=['CARD'], modes=['Tissue'], input_terms=[dict(term='Distance', possible_dependencies=[dict(kind='measurement', item_id='A/B.')], uncertainty='Review mapping')], formula_reference='Public reference only', sources=[dict(url='https://example.org/reference', title='Reference', locator='section 1', supports=['formula_reference'])], uncertainties=['Manufacturer implementation unknown'], research_status='proposed', mapping_basis='Exact source ID reviewed')


def manifest(items=None):
    return dict(batch_id=1, expected_sha256='a'*64, expected_version='1.51.90', schema_version=1, candidates=items or [dict(item_id='C.(1)', payload=payload())])


async def import_one(client):
    response = await client.post('/api/measurements/enrichment/import', json=manifest())
    assert response.status_code == 200, response.text
    return response.json()['candidates'][0]['id']


def review(detail, action='confirm', **extra):
    state = detail['enrichment']
    return dict(action=action, expected_candidate_fingerprint=state['candidate']['fingerprint'], expected_source_fingerprint=state['source_fingerprint'], expected_review_revision=state['review_revision'], confirmed_by='Reviewer', note='Checked public source', **extra)


@pytest.mark.asyncio
async def test_import_atomic_guard_idempotence_and_preservation(api):
    client, _ = api
    before = (await client.get('/api/measurements')).json()['entries']
    bad = manifest([dict(item_id='C.(1)', payload=payload()), dict(item_id='missing', payload=payload())])
    assert (await client.post('/api/measurements/enrichment/import', json=bad)).status_code == 422
    assert all(row.get('enrichment') is None for row in (await client.get('/api/measurements')).json()['entries'])
    bad = manifest(); bad['expected_version'] = 'wrong'
    assert (await client.post('/api/measurements/enrichment/import', json=bad)).status_code == 409
    bad = manifest(); bad['expected_sha256'] = 'b'*64
    assert (await client.post('/api/measurements/enrichment/import', json=bad)).status_code == 409
    cid = await import_one(client)
    repeat = await client.post('/api/measurements/enrichment/import', json=manifest())
    assert repeat.json()['created'] == 0
    assert repeat.json()['candidates'][0]['id'] == cid
    after = (await client.get('/api/measurements')).json()
    assert after['enrichment_available'] is True
    for old, new in zip(before, after['entries']):
        assert {k:v for k,v in old.items() if k != 'enrichment'} == {k:v for k,v in new.items() if k != 'enrichment'}
    assert after['entries'][1]['mode'] == '' and after['entries'][1]['categories'] == []


@pytest.mark.asyncio
async def test_review_stale_retry_and_pending_retains_confirmation(api):
    client, _ = api
    cid = await import_one(client)
    url = f'/api/measurements/enrichment/{cid}'
    detail = (await client.get(url)).json()
    request = review(detail)
    confirmed = await client.post(url+'/review', json=request)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()['enrichment']['status'] == 'confirmed'
    assert (await client.post(url+'/review', json=request)).json()['enrichment']['review_revision'] == 1
    conflict = dict(request, note='Different decision')
    assert (await client.post(url+'/review', json=conflict)).status_code == 409
    changed = payload(); changed['formula_reference'] = 'New evidence'
    result = await client.post('/api/measurements/enrichment/import', json=manifest([dict(item_id='C.(1)', payload=changed)]))
    new_id = result.json()['candidates'][0]['id']
    updated = (await client.get(f'/api/measurements/enrichment/{new_id}')).json()
    assert updated['enrichment']['confirmed_payload'] == payload()
    assert updated['enrichment']['has_pending_update'] is True
    assert (await client.post(url+'/review', json=request)).status_code == 409
    request = review(updated, 'revoke')
    result = await client.post(f'/api/measurements/enrichment/{new_id}/review', json=request)
    assert result.json()['enrichment']['confirmed_payload'] is None
    assert len(result.json()['history']) == 2


@pytest.mark.asyncio
async def test_dependencies_exact_ids_cycles_and_unresolved_confirmation(api):
    client, _ = api
    bad = payload(); bad['input_terms'][0]['possible_dependencies'][0]['item_id'] = 'A/B'
    assert (await client.post('/api/measurements/enrichment/import', json=manifest([dict(item_id='C.(1)', payload=bad)]))).status_code == 422
    p = payload(); p['input_terms'][0]['possible_dependencies'] = [dict(kind='calculation', item_id='D')]
    q = payload(); q['input_terms'][0]['possible_dependencies'] = [dict(kind='calculation', item_id='C.(1)')]
    result = await client.post('/api/measurements/enrichment/import', json=manifest([dict(item_id='C.(1)', payload=p), dict(item_id='D', payload=q)]))
    ids = [x['id'] for x in result.json()['candidates']]
    for i, cid in enumerate(ids):
        url = f'/api/measurements/enrichment/{cid}'
        detail = (await client.get(url)).json()
        response = await client.post(url+'/review', json=review(detail))
        assert response.status_code == (200 if i == 0 else 422), response.text
    p['research_status'] = 'unresolved'
    result = await client.post('/api/measurements/enrichment/import', json=manifest([dict(item_id='D', payload=p)]))
    cid = result.json()['candidates'][0]['id']; url = f'/api/measurements/enrichment/{cid}'
    detail = (await client.get(url)).json()
    assert (await client.post(url+'/review', json=review(detail))).status_code == 422
    assert (await client.post(url+'/review', json=review(detail, confirmed_payload=payload()))).status_code == 200


@pytest.mark.asyncio
async def test_missing_storage_raw_read_and_mutation_unavailable(api):
    client, engine = api
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.tables['measurement_enrichment_reviews'].drop)
    result = await client.get('/api/measurements')
    assert result.status_code == 200
    assert result.json()['enrichment_available'] is False
    assert len(result.json()['entries']) == 3
    assert (await client.post('/api/measurements/enrichment/import', json=manifest())).status_code == 503


@pytest.mark.asyncio
async def test_review_serializes_conflicts_and_safe_retries(api):
    import asyncio
    client, _ = api
    cid = await import_one(client)
    url = f'/api/measurements/enrichment/{cid}'
    initial = (await client.get(url)).json()
    first, second = await asyncio.gather(
        client.post(url+'/review', json=review(initial)),
        client.post(url+'/review', json=review(initial, 'defer')),
    )
    assert sorted([first.status_code, second.status_code]) == [200, 409]
    assert len((await client.get(url)).json()['history']) == 1


@pytest.mark.asyncio
async def test_actor_notes_confirm_requirements_and_schema(api):
    client, _ = api
    cid = await import_one(client)
    url = f'/api/measurements/enrichment/{cid}'
    initial = (await client.get(url)).json()
    for action in ('reject', 'defer', 'revoke'):
        request = review(initial, action); request['note'] = ' '
        assert (await client.post(url+'/review', json=request)).status_code == 422
    request = review(initial); request['confirmed_by'] = ' '
    assert (await client.post(url+'/review', json=request)).status_code == 422
    for field in ('categories', 'sources'):
        corrected = payload(); corrected[field] = []
        assert (await client.post(url+'/review', json=review(initial, confirmed_payload=corrected))).status_code == 422
    corrected = payload(); corrected['modes'] = []
    response = await client.post(url+'/review', json=review(initial, confirmed_payload=corrected))
    assert response.status_code == 200
    confirmed = response.json()
    assert confirmed['enrichment']['confirmed_payload']['modes'] == []
    assert (await client.post(url+'/review', json=review(confirmed, 'reject', confirmed_payload=corrected))).status_code == 422
    deferred = await client.post(url+'/review', json=review(confirmed, 'defer'))
    assert deferred.json()['enrichment']['status'] == 'deferred'
    rejected = await client.post(url+'/review', json=review(deferred.json(), 'reject'))
    assert rejected.json()['enrichment']['status'] == 'rejected'
    for change in ({'modes':['2D']}, {'categories':['INVALID']}, {'extra':'forbidden'}):
        invalid = payload(); invalid.update(change)
        assert (await client.post('/api/measurements/enrichment/import', json=manifest([dict(item_id='D', payload=invalid)]))).status_code == 422
    invalid = payload(); invalid['sources'][0]['url'] = 'file:///private/document.pdf'
    assert (await client.post('/api/measurements/enrichment/import', json=manifest([dict(item_id='D', payload=invalid)]))).status_code == 422
    duplicate = manifest([dict(item_id='D', payload=payload()), dict(item_id='D', payload=payload())])
    assert (await client.post('/api/measurements/enrichment/import', json=duplicate)).status_code == 422
    assert (await client.get('/api/measurements/enrichment/9999')).status_code == 404
    missing = manifest(); missing['batch_id'] = 9999
    assert (await client.post('/api/measurements/enrichment/import', json=missing)).status_code == 404


@pytest.mark.asyncio
async def test_cross_batch_isolation_and_changed_source_guard(api):
    from sqlalchemy import insert, update
    client, engine = api
    cid = await import_one(client)
    url = f'/api/measurements/enrichment/{cid}'
    initial = (await client.get(url)).json()
    async with engine.begin() as conn:
        await conn.execute(insert(MeasurementBatch).values(id=2, version='1.51.91', sha256='b'*64, source_file='next.xlsx', summary={}, warnings=[]))
        await conn.execute(insert(MeasurementEntry).values(batch_id=2, kind='calculation', item_id='C.(1)', source_sheet='source', source_row=2))
    batch2 = (await client.get('/api/measurements', params={'batch_id':2})).json()
    assert batch2['entries'][0]['enrichment'] is None
    async with engine.begin() as conn:
        await conn.execute(update(MeasurementEntry).where(MeasurementEntry.batch_id == 1, MeasurementEntry.kind == 'calculation').values(unit='changed externally'))
    assert (await client.post(url+'/review', json=review(initial))).status_code == 409
    changed = (await client.get(url)).json()
    assert (await client.post(url+'/review', json=review(changed))).status_code == 409
