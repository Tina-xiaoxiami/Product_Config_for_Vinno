"""Managed releases preserve source facts, exact associations and research audit history."""
from copy import deepcopy

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import measurement_workspace, measurements
from app.database import Base, get_db
from app.models.measurement import MeasurementBatch, MeasurementEntry
from app.models.measurement_workspace import MeasurementWorkspaceVersion
from test_measurement_enrichment import payload as research_payload

BASE = '/api/measurement-workspace'


@pytest_asyncio.fixture
async def api(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'workspace.db'}")
    async with engine.begin() as connection:
        for name in ('measurement_batches', 'measurement_entries', 'measurement_enrichment_candidates',
                     'measurement_enrichment_reviews', 'measurement_workspaces', 'measurement_workspace_versions'):
            await connection.run_sync(Base.metadata.tables[name].create)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        db.add(MeasurementBatch(id=1, version='1.51.90', sha256='a' * 64, source_file='source.xlsx', summary={}, warnings=[]))
        await db.flush()
        db.add_all([
            MeasurementEntry(id=1, batch_id=1, kind='measurement', item_id='A/B.', cn_name='距离甲', description='Distance A', mode='Tissue', categories=['Common'], source_sheet='Measures', source_row=2),
            MeasurementEntry(id=2, batch_id=1, kind='measurement', item_id='A/B.', cn_name='距离乙', description='', mode='Doppler', categories=['CARD'], source_sheet='Measures', source_row=3),
            MeasurementEntry(id=3, batch_id=1, kind='calculation', item_id='C.(1)', cn_name='计算', description='', mode='', categories=[], source_sheet='Calculations', source_row=2),
            MeasurementEntry(id=4, batch_id=1, kind='calculation', item_id='A/B.', cn_name='另一类型', description='', mode='', categories=[], source_sheet='Calculations', source_row=3),
        ])
        await db.commit()
    app = FastAPI()
    app.include_router(measurements.router, prefix='/api/measurements')
    app.include_router(measurement_workspace.router, prefix=BASE)
    async def override():
        async with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        yield client, sessions
    await engine.dispose()


async def initialize(client):
    response = await client.post(BASE + '/initialize', json={'batch_id': 1, 'expected_sha256': 'a' * 64})
    assert response.status_code == 200, response.text
    return response.json()


async def edit(client, workspace, operation, **values):
    response = await client.post(f"{BASE}/{workspace['id']}/edit", json={
        'revision': workspace['revision'], 'operation': operation, **values})
    assert response.status_code == 200, response.text
    return response.json()


async def act(client, workspace, action, **values):
    response = await client.post(f"{BASE}/{workspace['id']}/{action}", json={'revision': workspace['revision'], **values})
    assert response.status_code == 200, response.text
    return response.json()


async def publish(client, workspace, number='next', description='release'):
    metadata = {'version_number': number, 'description': description}
    preview = await act(client, workspace, 'preview', **metadata)
    return await act(client, workspace, 'publish', **metadata, signature=preview['signature'])


async def import_evidence(client, **updates):
    payload = research_payload()
    payload.update(updates)
    response = await client.post('/api/measurements/enrichment/import', json={
        'batch_id': 1, 'expected_sha256': 'a' * 64, 'expected_version': '1.51.90', 'schema_version': 1,
        'candidates': [{'item_id': 'C.(1)', 'payload': payload}]})
    assert response.status_code == 200, response.text
    return response.json()['candidates'][0]['id']


async def confirm(client, candidate_id, action='confirm'):
    detail = (await client.get(f'/api/measurements/enrichment/{candidate_id}')).json()['enrichment']
    response = await client.post(f'/api/measurements/enrichment/{candidate_id}/review', json={
        'action': action, 'expected_candidate_fingerprint': detail['candidate']['fingerprint'],
        'expected_source_fingerprint': detail['source_fingerprint'], 'expected_review_revision': detail['review_revision'],
        'confirmed_by': 'Reviewer', 'note': 'Independently checked'})
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_initialization_freezes_pending_source_rows_and_is_idempotent(api):
    client, sessions = api
    raw = (await client.get('/api/measurements')).json()['entries']
    assert (await client.get(BASE, params={'batch_id': 1})).json() == {'initialized': False}
    assert (await client.post(BASE + '/initialize', json={'batch_id': 1, 'expected_sha256': 'b' * 64})).status_code == 409
    await import_evidence(client)
    workspace = await initialize(client)
    assert workspace['has_draft'] is False
    assert workspace['changes'] == []
    assert len(workspace['versions']) == 1 and workspace['versions'][0]['initial'] is True
    assert (await initialize(client)) == workspace
    assert len(workspace['data']['entries']) == 4
    rows = workspace['data']['entries']
    assert rows[0]['mode'] == ['Tissue'] and rows[1]['mode'] == ['Doppler']
    assert rows[2]['mode'] == ['Tissue'] and rows[2]['assignment_origin'] == 'suggestion'
    assert rows[2]['enrichment_status'] == '待核对' and rows[2]['official_mode'] == []
    assert rows[2]['enrichment']['status'] == 'pending'
    assert rows[2]['enrichment']['history'] == []
    assert rows[0]['source_entry_id'] == 1 and rows[0]['record_key'] == 'source:1'
    after = (await client.get('/api/measurements')).json()['entries']
    for before, current in zip(raw, after):
        assert {k: v for k, v in before.items() if k != 'enrichment'} == {k: v for k, v in current.items() if k != 'enrichment'}
    async with sessions() as db:
        assert len((await db.scalars(select(MeasurementWorkspaceVersion))).all()) == 1


@pytest.mark.asyncio
async def test_group_names_preserve_type_and_individual_originals_on_undo(api):
    client, _ = api
    workspace = await initialize(client)
    baseline = deepcopy(workspace['data'])
    workspace = await edit(client, workspace, 'rename_item', record_key='source:1', cn_name='统一距离', description='')
    assert [row['cn_name'] for row in workspace['data']['entries']] == ['统一距离', '统一距离', '计算', '另一类型']
    assert all(row['en_name'] == 'A/B.' for row in workspace['data']['entries'][:2])
    assert len(workspace['changes']) == 1 and workspace['changes'][0]['affected_count'] == 2
    workspace = await act(client, workspace, 'undo', change_key=workspace['changes'][0]['key'])
    assert workspace['data'] == baseline and workspace['has_draft'] is False
    assert (await client.get('/api/measurements')).json()['entries'][0]['cn_name'] == '距离甲'


@pytest.mark.asyncio
async def test_dictionary_only_release_frozen_names_compare_and_restore(api):
    client, _ = api
    workspace = await initialize(client)
    initial = workspace['latest_version_id']
    workspace = await edit(client, workspace, 'upsert_dictionary', dimension='applications', code='Common', name='通用')
    assert workspace['changes'][0]['entity'] == 'dictionary'
    preview = await act(client, workspace, 'preview', version_number='V2', description='Display name')
    assert preview['change_count'] == 1
    workspace = await act(client, workspace, 'publish', version_number='V2', description='Display name', signature=preview['signature'])
    latest = workspace['latest_version_id']
    assert workspace['has_draft'] is False
    old = (await client.get(f"{BASE}/{workspace['id']}/versions/{initial}")).json()
    assert next(row for row in old['data']['applications'] if row['code'] == 'Common')['name'] == 'Common'
    compared = (await client.get(f"{BASE}/{workspace['id']}/compare", params={'from_version_id': initial, 'to_version_id': latest})).json()
    assert compared['change_count'] == 1 and compared['changes'][0]['after']['name'] == '通用'
    workspace = await act(client, workspace, f'restore/{initial}')
    assert workspace['has_draft'] and workspace['published_data']['applications'] != workspace['data']['applications']
    workspace = await act(client, workspace, 'discard')
    assert workspace['has_draft'] is False and workspace['latest_version_id'] == latest


@pytest.mark.asyncio
async def test_new_codes_items_relationships_and_reference_protected_undo(api):
    client, _ = api
    workspace = await initialize(client)
    workspace = await edit(client, workspace, 'upsert_dictionary', dimension='modes', code='Novel', name='新模式')
    dictionary_key = workspace['changes'][0]['key']
    workspace = await edit(client, workspace, 'add_item', kind='measurement', item_id='New', cn_name='新项目', description='', categories=['Common'], modes=['Novel'])
    added = workspace['data']['entries'][-1]
    assert added['record_key'].startswith('manual:') and added['en_name'] == 'New'
    assert added['source_entry_id'] is None
    rejected = await client.post(f"{BASE}/{workspace['id']}/undo", json={'revision': workspace['revision'], 'change_key': dictionary_key})
    assert rejected.status_code == 409
    # A duplicate ID is explicit, and inherits the already uniform managed names.
    response = await client.post(f"{BASE}/{workspace['id']}/edit", json={'revision': workspace['revision'], 'operation': 'add_item', 'kind': 'measurement', 'item_id': 'New', 'cn_name': '新项目', 'description': '', 'categories': [], 'modes': []})
    assert response.status_code == 409
    workspace = await edit(client, workspace, 'add_item', kind='measurement', item_id='New', cn_name='新项目', description='', categories=['CARD'], modes=['Tissue'], allow_existing_id=True)
    assert len(workspace['data']['entries']) == 6
    assert workspace['data']['entries'][-1]['categories'] == ['CARD']
    # Undoing one new relationship never removes other rows of the same identity.
    item_key = next(change['key'] for change in workspace['changes'] if change['field'] == 'record' and change['after']['record_key'] == added['record_key'])
    workspace = await act(client, workspace, 'undo', change_key=item_key)
    assert len(workspace['data']['entries']) == 5
    workspace = await act(client, workspace, 'undo', change_key=dictionary_key)
    assert all(row['code'] != 'Novel' for row in workspace['data']['modes'])
    assert len((await client.get('/api/measurements')).json()['entries']) == 4


@pytest.mark.asyncio
async def test_assignment_return_baseline_noop_and_strict_source_write_rejection(api):
    client, _ = api
    workspace = await initialize(client)
    baseline = deepcopy(workspace['data'])
    workspace = await edit(client, workspace, 'assign_item', record_key='source:1', categories=['CARD'], modes=['Doppler'])
    assert workspace['data']['entries'][0]['assignment_origin'] == 'manual'
    workspace = await edit(client, workspace, 'assign_item', record_key='source:1', categories=['Common'], modes=['Tissue'])
    assert workspace['data'] == baseline and workspace['has_draft'] is False
    response = await client.post(f"{BASE}/{workspace['id']}/preview", json={'revision': workspace['revision'], 'version_number': 'V2'})
    assert response.status_code == 400
    for extra in ({'enrichment_status': '已核对'}, {'batch_id': 2}, {'source_row': 99}):
        response = await client.post(f"{BASE}/{workspace['id']}/edit", json={'revision': workspace['revision'], 'operation': 'rename_item', 'record_key': 'source:1', 'cn_name': 'x', 'description': '', **extra})
        assert response.status_code == 422
    response = await client.post(f"{BASE}/{workspace['id']}/edit", json={'revision': workspace['revision'], 'operation': 'assign_item', 'record_key': 'source:1', 'categories': ['UNKNOWN'], 'modes': []})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_stale_revision_and_signature_metadata_conflicts_never_publish(api):
    client, sessions = api
    initial = await initialize(client)
    workspace = await edit(client, initial, 'rename_item', record_key='source:3', cn_name='新名称', description='')
    response = await client.post(f"{BASE}/{workspace['id']}/discard", json={'revision': initial['revision']})
    assert response.status_code == 409
    preview = await act(client, workspace, 'preview', version_number='V2', description='first')
    response = await client.post(f"{BASE}/{workspace['id']}/publish", json={'revision': workspace['revision'], 'version_number': 'V2', 'description': 'different', 'signature': preview['signature']})
    assert response.status_code == 409
    workspace = await edit(client, workspace, 'rename_item', record_key='source:3', cn_name='更新名称', description='')
    response = await client.post(f"{BASE}/{workspace['id']}/publish", json={'revision': preview['revision'], 'version_number': 'V2', 'description': 'first', 'signature': preview['signature']})
    assert response.status_code == 409
    async with sessions() as db:
        assert len((await db.scalars(select(MeasurementWorkspaceVersion))).all()) == 1
    workspace = await publish(client, workspace, 'V2')
    workspace = await edit(client, workspace, 'rename_item', record_key='source:3', cn_name='第三名称', description='')
    assert (await client.post(f"{BASE}/{workspace['id']}/preview", json={'revision': workspace['revision'], 'version_number': 'V2'})).status_code == 409
    assert (await client.post(f"{BASE}/{workspace['id']}/publish", json={'revision': workspace['revision'], 'version_number': 'V3'})).status_code == 422


@pytest.mark.asyncio
async def test_restore_deletes_new_rows_and_delete_undo_restores_published_document(api):
    client, _ = api
    workspace = await initialize(client)
    initial = workspace['latest_version_id']
    workspace = await edit(client, workspace, 'add_item', kind='calculation', item_id='new.C', cn_name='新增', description='New', categories=[], modes=['Tissue'])
    workspace = await publish(client, workspace)
    baseline = deepcopy(workspace['data'])
    workspace = await act(client, workspace, f'restore/{initial}')
    deletion = next(change for change in workspace['changes'] if change['change_type'] == 'delete')
    assert deletion['before']['item_id'] == 'new.C' and deletion['after'] is None
    workspace = await act(client, workspace, 'undo', change_key=deletion['key'])
    assert workspace['data'] == baseline and workspace['has_draft'] is False


@pytest.mark.asyncio
async def test_evidence_sync_preserves_manual_names_dicts_associations_and_frozen_audit(api):
    client, _ = api
    cid = await import_evidence(client)
    workspace = await initialize(client)
    initial_id = workspace['latest_version_id']
    initial_document = deepcopy(workspace['data'])
    workspace = await edit(client, workspace, 'rename_item', record_key='source:3', cn_name='人工名称', description='Managed')
    workspace = await edit(client, workspace, 'assign_item', record_key='source:3', categories=['Common'], modes=['Doppler'])
    workspace = await edit(client, workspace, 'upsert_dictionary', dimension='applications', code='CARD', name='心脏')
    await confirm(client, cid)
    workspace = await act(client, workspace, 'sync-evidence')
    row = workspace['data']['entries'][2]
    assert row['cn_name'] == '人工名称' and row['description'] == 'Managed'
    assert row['mode'] == ['Doppler'] and row['categories'] == ['Common'] and row['assignment_origin'] == 'manual'
    assert row['official_mode'] == ['Tissue'] and row['official_categories'] == ['CARD']
    assert row['enrichment_status'] == '已核对' and row['enrichment']['status'] == 'confirmed'
    audit = row['enrichment']['history'][0]
    assert audit['confirmed_by'] == 'Reviewer' and audit['note'] == 'Independently checked' and audit['created_at']
    assert next(item['name'] for item in workspace['data']['applications'] if item['code'] == 'CARD') == '心脏'
    assert any(change['entity'] == 'evidence' for change in workspace['changes'])
    frozen = (await client.get(f"{BASE}/{workspace['id']}/versions/{initial_id}")).json()['data']
    assert frozen == initial_document
    workspace = await publish(client, workspace, 'Reviewed')
    reviewed_id = workspace['latest_version_id']
    await confirm(client, cid, 'revoke')
    workspace = await act(client, workspace, 'sync-evidence')
    assert workspace['data']['entries'][2]['enrichment']['status'] == 'pending'
    assert workspace['data']['entries'][2]['assignment_origin'] == 'manual'
    frozen = (await client.get(f"{BASE}/{workspace['id']}/versions/{reviewed_id}")).json()['data']
    assert frozen['entries'][2]['enrichment']['status'] == 'confirmed'
    assert len(frozen['entries'][2]['enrichment']['history']) == 1


@pytest.mark.asyncio
async def test_evidence_only_release_and_hidden_source_dictionary_union(api):
    client, _ = api
    cid = await import_evidence(client)
    await confirm(client, cid)
    # New pending evidence remains hidden under active confirmation, but codes are archived.
    await import_evidence(client, categories=['OB'], modes=['VShear'], formula_reference='Updated evidence')
    workspace = await initialize(client)
    row = workspace['data']['entries'][2]
    assert row['mode'] == ['Tissue'] and row['assignment_origin'] == 'confirmed'
    assert {'OB', 'CARD', 'Common'} <= {item['code'] for item in workspace['data']['applications']}
    assert 'VShear' in {item['code'] for item in workspace['data']['modes']}
    await import_evidence(client, categories=['OB'], modes=['VShear'], formula_reference='Evidence revision only')
    workspace = await act(client, workspace, 'sync-evidence')
    assert workspace['changes'] and all(change['entity'] == 'evidence' for change in workspace['changes'])
    preview = await act(client, workspace, 'preview', version_number='Evidence-only')
    assert preview['change_count'] >= 1
    workspace = await act(client, workspace, 'publish', version_number='Evidence-only', signature=preview['signature'])
    assert workspace['has_draft'] is False


@pytest.mark.asyncio
async def test_concurrent_publication_consumes_preview_once(api):
    import asyncio

    client, sessions = api
    workspace = await initialize(client)
    workspace = await edit(client, workspace, 'rename_item', record_key='source:3', cn_name='竞态发布', description='')
    preview = await act(client, workspace, 'preview', version_number='Race')
    request = {'revision': workspace['revision'], 'version_number': 'Race', 'signature': preview['signature']}
    responses = await asyncio.gather(*[client.post(f"{BASE}/{workspace['id']}/publish", json=request) for _ in range(2)])
    assert sorted(response.status_code for response in responses) == [200, 409]
    async with sessions() as db:
        versions = (await db.scalars(select(MeasurementWorkspaceVersion))).all()
        assert len(versions) == 2
        assert [version.version_number for version in versions].count('Race') == 1


@pytest.mark.asyncio
async def test_nonmanual_evidence_sync_projects_confirmed_assignments_as_draft(api):
    client, _ = api
    cid = await import_evidence(client)
    workspace = await initialize(client)
    baseline = deepcopy(workspace['published_data'])
    await confirm(client, cid)
    workspace = await act(client, workspace, 'sync-evidence')
    assert workspace['data']['entries'][2]['assignment_origin'] == 'confirmed'
    assert workspace['data']['entries'][2]['enrichment_status'] == '已核对'
    assert workspace['published_data'] == baseline
    assert workspace['has_draft']
    workspace = await act(client, workspace, 'discard')
    assert workspace['data'] == baseline
    # Discarding the managed draft does not rewrite the independently saved review.
    current = (await client.get(f'/api/measurements/enrichment/{cid}')).json()
    assert current['enrichment']['status'] == 'confirmed'


@pytest.mark.asyncio
async def test_old_candidate_evidence_is_frozen_and_hidden_new_codes_cannot_be_undone(api):
    client, _ = api
    cid = await import_evidence(client)
    await confirm(client, cid)
    workspace = await initialize(client)
    await import_evidence(client, categories=['OB'], modes=['VShear'], formula_reference='Hidden new revision')
    workspace = await act(client, workspace, 'sync-evidence')
    row = workspace['data']['entries'][2]
    assert row['mode'] == ['Tissue']
    assert len(row['enrichment']['candidate_history']) == 2
    assert row['enrichment']['candidate_history'][0]['payload']['formula_reference'] == 'Public reference only'
    dictionary_change = next(change for change in workspace['changes'] if change['entity'] == 'dictionary' and change['after']['code'] == 'VShear')
    response = await client.post(f"{BASE}/{workspace['id']}/undo", json={'revision': workspace['revision'], 'change_key': dictionary_change['key']})
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_restore_delete_undo_requires_dictionary_dependency_first(api):
    client, _ = api
    workspace = await initialize(client)
    initial_id = workspace['latest_version_id']
    workspace = await edit(client, workspace, 'upsert_dictionary', dimension='modes', code='Novel', name='新模式')
    workspace = await edit(client, workspace, 'add_item', kind='measurement', item_id='Novel-row', cn_name='项目', description='', categories=[], modes=['Novel'])
    workspace = await publish(client, workspace, 'Novel-release')
    published = deepcopy(workspace['published_data'])
    workspace = await act(client, workspace, f'restore/{initial_id}')
    row_change = next(change for change in workspace['changes'] if change['field'] == 'record')
    dictionary_change = next(change for change in workspace['changes'] if change['entity'] == 'dictionary')
    response = await client.post(f"{BASE}/{workspace['id']}/undo", json={'revision': workspace['revision'], 'change_key': row_change['key']})
    assert response.status_code == 422
    unchanged = (await client.get(f"{BASE}/{workspace['id']}")).json()
    assert unchanged == workspace
    workspace = await act(client, workspace, 'undo', change_key=dictionary_change['key'])
    workspace = await act(client, workspace, 'undo', change_key=row_change['key'])
    assert workspace['has_draft'] is False and workspace['data'] == published


@pytest.mark.asyncio
async def test_evidence_undo_atomically_restores_automatic_projection_and_preserves_manual(api):
    client, _ = api
    cid = await import_evidence(client)
    workspace = await initialize(client)
    baseline = deepcopy(workspace['data'])
    await confirm(client, cid)
    workspace = await act(client, workspace, 'sync-evidence')
    evidence = next(change for change in workspace['changes'] if change['entity'] == 'evidence')
    assert evidence['after']['assignment_origin'] == 'confirmed'
    assert not any(change['field'] == 'assignments' for change in workspace['changes'])
    workspace = await act(client, workspace, 'undo', change_key=evidence['key'])
    assert workspace['data'] == baseline and workspace['has_draft'] is False
    workspace = await edit(client, workspace, 'assign_item', record_key='source:3', categories=['Common'], modes=['Doppler'])
    workspace = await act(client, workspace, 'sync-evidence')
    evidence = next(change for change in workspace['changes'] if change['entity'] == 'evidence')
    workspace = await act(client, workspace, 'undo', change_key=evidence['key'])
    row = workspace['data']['entries'][2]
    assert row['assignment_origin'] == 'manual' and row['mode'] == ['Doppler']
    assert row['enrichment']['status'] == 'pending' and row['enrichment_status'] == '待核对'


@pytest.mark.asyncio
async def test_reassign_published_values_after_research_change_remains_manual(api):
    client, _ = api
    await import_evidence(client)
    workspace = await initialize(client)
    cid = await import_evidence(client, modes=['Doppler'], formula_reference='Changed association')
    await confirm(client, cid)
    workspace = await act(client, workspace, 'sync-evidence')
    assert workspace['data']['entries'][2]['mode'] == ['Doppler']
    workspace = await edit(client, workspace, 'assign_item', record_key='source:3', categories=['CARD'], modes=['Tissue'])
    row = workspace['data']['entries'][2]
    assert row['assignment_origin'] == 'manual'
    workspace = await act(client, workspace, 'sync-evidence')
    assert workspace['data']['entries'][2]['assignment_origin'] == 'manual'
    assert workspace['data']['entries'][2]['mode'] == ['Tissue']


@pytest.mark.asyncio
@pytest.mark.parametrize('action', ['initialize', 'sync-evidence'])
async def test_evidence_snapshot_serializes_projection_and_audit_reads(api, monkeypatch, action):
    import asyncio
    from app.services import measurement_workspace as service

    client, _ = api
    cid = await import_evidence(client)
    await confirm(client, cid)
    workspace = await initialize(client) if action == 'sync-evidence' else None
    read_projection, release_read = asyncio.Event(), asyncio.Event()
    original = service.measurement_library

    async def pause_after_projection(*args, **kwargs):
        result = await original(*args, **kwargs)
        read_projection.set()
        await release_read.wait()
        return result

    monkeypatch.setattr(service, 'measurement_library', pause_after_projection)
    snapshot_task = asyncio.create_task(initialize(client) if workspace is None else act(client, workspace, 'sync-evidence'))
    await asyncio.wait_for(read_projection.wait(), timeout=2)
    review_task = asyncio.create_task(confirm(client, cid, 'revoke'))
    try:
        # The independent append-only research writer cannot interleave between
        # projection and audit reads while the snapshot owns BEGIN IMMEDIATE.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(review_task), timeout=0.1)
    finally:
        release_read.set()
    snapshot = await asyncio.wait_for(snapshot_task, timeout=2)
    await asyncio.wait_for(review_task, timeout=2)
    row = snapshot['data']['entries'][2]
    assert row['enrichment']['status'] == 'confirmed'
    assert row['enrichment_status'] == '已核对'
    assert [review['action'] for review in row['enrichment']['history']] == ['confirm']
    current = (await client.get(f'/api/measurements/enrichment/{cid}')).json()
    assert current['enrichment']['status'] == 'pending'


@pytest.mark.asyncio
async def test_assignment_undo_derives_nonmanual_state_from_current_frozen_evidence(api):
    client, _ = api
    await import_evidence(client)
    workspace = await initialize(client)
    cid = await import_evidence(client, modes=['Doppler'], formula_reference='Confirmed Doppler revision')
    await confirm(client, cid)
    workspace = await act(client, workspace, 'sync-evidence')
    workspace = await edit(client, workspace, 'assign_item', record_key='source:3', categories=['Common'], modes=['Tissue'])
    assignment = next(change for change in workspace['changes'] if change['field'] == 'assignments')
    workspace = await act(client, workspace, 'undo', change_key=assignment['key'])
    row = workspace['data']['entries'][2]
    assert row['mode'] == row['official_mode'] == ['Doppler']
    assert row['categories'] == row['official_categories'] == ['CARD']
    assert row['assignment_origin'] == 'confirmed'
    assert row['classification_basis'] == '已核对补充'
    assert row['enrichment']['status'] == 'confirmed'
    assert not any(change['field'] == 'assignments' for change in workspace['changes'])
    workspace = await publish(client, workspace, 'Consistent-evidence')
    assert workspace['published_data']['entries'][2]['assignment_origin'] == 'confirmed'


@pytest.mark.asyncio
async def test_preview_rejects_inconsistent_automatic_projection(api):
    from app.models.measurement_workspace import MeasurementWorkspace
    from app.services import measurement_workspace as service

    client, sessions = api
    cid = await import_evidence(client)
    workspace = await initialize(client)
    await confirm(client, cid)
    workspace = await act(client, workspace, 'sync-evidence')
    # Defense in depth for any future write path, beyond current closed operations.
    inconsistent = deepcopy(workspace['data'])
    inconsistent['entries'][2]['assignment_origin'] = 'suggestion'
    inconsistent['entries'][2]['classification_basis'] = '待核对建议'
    async with sessions() as db:
        item = await db.get(MeasurementWorkspace, workspace['id'])
        item.draft_data = service.encode(inconsistent)
        await db.commit()
    response = await client.post(f"{BASE}/{workspace['id']}/preview", json={'revision': workspace['revision'], 'version_number': 'Invalid'})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_dictionary_order_is_versioned_validated_and_undoable(api):
    client, _ = api
    workspace = await initialize(client)
    initial = workspace['latest_version_id']
    for dimension in ('applications', 'modes'):
        original = [entry['code'] for entry in workspace['data'][dimension]]
        response = await client.post(f"{BASE}/{workspace['id']}/edit", json={
            'revision': workspace['revision'], 'operation': 'reorder_dictionary',
            'dimension': dimension, 'codes': original[:-1]})
        assert response.status_code == 422
        workspace = await edit(client, workspace, 'reorder_dictionary', dimension=dimension, codes=original[::-1])
        assert [entry['code'] for entry in workspace['data'][dimension]] == original[::-1]
    assert len(workspace['changes']) == 2
    workspace = await publish(client, workspace)
    old = (await client.get(f"{BASE}/{workspace['id']}/versions/{initial}")).json()
    assert old['data']['modes'] != workspace['data']['modes']
    current = [entry['code'] for entry in workspace['data']['modes']]
    workspace = await edit(client, workspace, 'reorder_dictionary', dimension='modes', codes=current[::-1])
    workspace = await act(client, workspace, 'undo', change_key=workspace['changes'][0]['key'])
    assert [entry['code'] for entry in workspace['data']['modes']] == current
    assert not workspace['has_draft']


@pytest.mark.asyncio
async def test_batch_drafts_and_release_bilingual_matching_are_isolated(api):
    """Measurement workspaces are batch-scoped; Release resolves its own feature names."""
    import sqlite3
    from tracker.database import Database

    client, sessions = api
    async with sessions() as db:
        db.add(MeasurementBatch(id=2, version='2.0', sha256='b' * 64, source_file='other.xlsx', summary={}, warnings=[]))
        db.add(MeasurementEntry(id=5, batch_id=2, kind='measurement', item_id='A/B.', cn_name='另一批次', description='Other', mode='Tissue', categories=['CARD'], source_sheet='Measures', source_row=2))
        await db.commit()
    first = await initialize(client)
    response = await client.post(BASE + '/initialize', json={'batch_id': 2, 'expected_sha256': 'b' * 64})
    assert response.status_code == 200, response.text
    second = response.json()
    connection = sqlite3.connect(':memory:')
    connection.row_factory = sqlite3.Row
    connection.executescript('''
        CREATE TABLE releases (id INTEGER, project_id INTEGER);
        CREATE TABLE features (id INTEGER, project_id INTEGER, cn_name TEXT, en_name TEXT, category TEXT);
        CREATE TABLE terms (id INTEGER, cn_name TEXT, en_name TEXT, category TEXT, needs_review INTEGER, entry_type TEXT);
        INSERT INTO releases VALUES (1, 10);
        INSERT INTO features VALUES (2, 10, '距离', 'Distance', '测量');
    ''')
    candidate = {'release_id': 1, 'title_cn': '新增距离测量', 'title_en': 'New Distance measurement'}
    tracker = Database(':memory:')
    expected = tracker._resolve_verified_feature_match(connection, candidate)
    assert expected['id'] == 2 and expected['source'] == 'feature'
    first = await edit(client, first, 'rename_item', record_key='source:1', cn_name='第一批草稿', description='First draft')
    second = await edit(client, second, 'rename_item', record_key='source:5', cn_name='第二批草稿', description='Second draft')
    for dimension in ('applications', 'modes'):
        codes = [entry['code'] for entry in first['data'][dimension]]
        first = await edit(client, first, 'reorder_dictionary', dimension=dimension, codes=codes[::-1])
    for batch, expected_workspace in ((2, second), (1, first), (2, second)):
        loaded = (await client.get(BASE, params={'batch_id': batch})).json()
        assert loaded['id'] == expected_workspace['id']
        assert loaded['data'] == expected_workspace['data']
        assert loaded['has_draft'] is True
        assert tracker._resolve_verified_feature_match(connection, candidate) == expected
    assert first['data']['entries'][0]['cn_name'] == '第一批草稿'
    assert second['data']['entries'][0]['cn_name'] == '第二批草稿'
    connection.close()
