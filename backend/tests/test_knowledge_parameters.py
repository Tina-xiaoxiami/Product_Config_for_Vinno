"""Parameter answers keep controlled specification data separate from snapshots."""
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.models import ProductSeries, ProductModel, ConfigItem, ConfigVersion
from app.models import knowledge_parameters as parameter_models  # noqa: F401
from app.api.knowledge_parameters import router


@asynccontextmanager
async def client_for(tmp_path, *, tables=True, snapshot=None):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'parameters.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        if not tables:
            for table in ['knowledge_parameter_revisions', 'knowledge_parameter_specs', 'knowledge_parameter_topics']:
                await connection.execute(text(f'DROP TABLE {table}'))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    source = snapshot or {
        'models': [{'id': 1, 'name': 'VINNO 6'}, {'id': 2, 'name': 'VINNO 6EXP'}],
        'items': [
            {'id': 10, 'ipn': '1000101', 'zh_desc': '历史电池甲', 'values': {'1': {'selection_config': 'X', 'current_config': '研发甲'}, '2': {'selection_config': 'O'}}},
            {'id': 11, 'ipn': '1000102', 'zh_desc': '历史电池乙', 'values': {'1': {'selection_config': 'O'}, '2': {'selection_config': '#'}}},
        ],
    }
    async with factory() as db:
        db.add_all([ProductSeries(id=1, name='Before2023-China'), ProductSeries(id=2, name='Other-China'),
                    ProductModel(id=1, series_id=1, name='VINNO 6'), ProductModel(id=2, series_id=1, name='VINNO 6EXP'),
                    ProductModel(id=3, series_id=2, name='Other'),
                    ConfigItem(id=10, row_index=1, ipn='1000101', zh_desc='当前电池甲'),
                    ConfigItem(id=11, row_index=2, ipn='1000102', zh_desc='当前电池乙'),
                    ConfigVersion(id=1, series_id=1, version_number='1.14.80-正式版', snapshot_data=json.dumps(source, ensure_ascii=False))])
        await db.commit()
    app = FastAPI()
    app.include_router(router, prefix='/api/knowledge')
    async def database():
        async with factory() as db:
            yield db
    app.dependency_overrides[get_db] = database
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            yield client, factory
    finally:
        await engine.dispose()


TOPIC = {'name': '电池容量', 'question': '各型号电池容量是多少？', 'aliases': ['电池容量'],
         'fields': [{'key': 'capacity', 'label': '容量', 'unit': 'mAh', 'type': 'number'},
                    {'key': 'energy', 'label': '能量', 'unit': 'Wh', 'type': 'number'}]}


def spec(ipn='1000101', name='规格甲', **changes):
    return {'name': name, 'ipn': ipn, 'values': {'capacity': '5000', 'energy': '72'},
            'evidence_reference': '合成规格书第2页', 'confirmed_by': '测试核对人', 'is_active': True, **changes}


async def seed(client):
    created = await client.post('/api/knowledge/parameter-topics', json=TOPIC)
    assert created.status_code == 200, created.text
    topic = created.json()
    first = await client.post(f"/api/knowledge/parameter-topics/{topic['id']}/specs", json=spec())
    assert first.status_code == 200, first.text
    return topic, first.json()


@pytest.mark.asyncio
async def test_topic_and_spec_are_persisted_with_units_evidence_actor_and_revision(tmp_path):
    async with client_for(tmp_path) as (client, factory):
        assert (await client.get('/api/knowledge/parameter-topics')).json() == {'available': True, 'items': [], 'total': 0}
        topic, first = await seed(client)
        assert topic['fields'][0]['unit'] == 'mAh'
        assert first['revision'] == 1 and first['current_cn_name'] == '当前电池甲'
        changed = spec(values={'capacity': '5100', 'energy': '73.44'}, expected_revision=1)
        result = await client.put(f"/api/knowledge/parameter-topics/{topic['id']}/specs/{first['id']}", json=changed)
        assert result.status_code == 200 and result.json()['revision'] == 2
        stale = await client.put(f"/api/knowledge/parameter-topics/{topic['id']}/specs/{first['id']}", json=changed)
        assert stale.status_code == 409
        async with factory() as db:
            assert (await db.execute(text('SELECT count(*) FROM knowledge_parameter_revisions'))).scalar_one() == 2
        listing = (await client.get(f"/api/knowledge/parameter-topics/{topic['id']}/specs")).json()
        assert listing['total'] == 1 and listing['items'][0]['values']['capacity'] == '5100'


@pytest.mark.asyncio
async def test_preview_uses_snapshot_names_selection_and_all_matching_specs_without_mutation(tmp_path):
    async with client_for(tmp_path) as (client, factory):
        topic, first = await seed(client)
        assert (await client.post(f"/api/knowledge/parameter-topics/{topic['id']}/specs", json=spec('1000102', '规格乙'))).status_code == 200
        async with factory() as db:
            before = (await db.execute(text('SELECT snapshot_data FROM config_versions WHERE id=1'))).scalar_one()
        response = await client.post(f"/api/knowledge/parameter-topics/{topic['id']}/preview", json={'config_version_id': 1, 'model_ids': [1, 2]})
        assert response.status_code == 200, response.text
        data = response.json()
        assert data['snapshot']['version_number'] == '1.14.80-正式版'
        assert [m['selection_config'] for m in data['rows'][0]['matches']] == ['X', 'O']
        assert data['rows'][0]['matches'][0]['snapshot_cn_name'] == '历史电池甲'
        assert data['rows'][0]['matches'][0]['current_config_note'] == '研发甲'
        assert '5000 mAh' in data['rows'][0]['answer_text'] and '72 Wh' in data['answer_text']
        assert data['rows'][1]['status'] == 'needs_review'
        assert any(m['selection_config'] == '#' and not m['usable'] for m in data['rows'][1]['matches'])
        async with factory() as db:
            assert (await db.execute(text('SELECT snapshot_data FROM config_versions WHERE id=1'))).scalar_one() == before
            assert (await db.execute(text('SELECT count(*) FROM config_values'))).scalar_one() == 0
            assert (await db.execute(text('SELECT count(*) FROM knowledge_questions'))).scalar_one() == 0
            assert (await db.execute(text('SELECT count(*) FROM knowledge_parameter_revisions'))).scalar_one() == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [spec(values={'capacity': 'NaN', 'energy': '72'}), spec(values={'capacity': True, 'energy': '72'}), spec(values={'capacity': '50mAh', 'energy': '72'}), spec(evidence_reference=' '), spec(confirmed_by=''), spec(values={'capacity': '5000'}), spec(ipn='unknown')])
async def test_invalid_spec_does_not_create_rows(tmp_path, payload):
    async with client_for(tmp_path) as (client, factory):
        topic = (await client.post('/api/knowledge/parameter-topics', json=TOPIC)).json()
        result = await client.post(f"/api/knowledge/parameter-topics/{topic['id']}/specs", json=payload)
        assert result.status_code == 422
        async with factory() as db:
            assert (await db.execute(text('SELECT count(*) FROM knowledge_parameter_specs'))).scalar_one() == 0


@pytest.mark.asyncio
async def test_duplicate_active_ipn_rejected_and_inactive_spec_not_used(tmp_path):
    async with client_for(tmp_path) as (client, factory):
        topic, first = await seed(client)
        assert (await client.post(f"/api/knowledge/parameter-topics/{topic['id']}/specs", json=spec(name='同IPN另一规格'))).status_code == 409
        disabled = await client.put(f"/api/knowledge/parameter-topics/{topic['id']}/specs/{first['id']}", json=spec(is_active=False, expected_revision=1))
        assert disabled.status_code == 200
        preview = (await client.post(f"/api/knowledge/parameter-topics/{topic['id']}/preview", json={'config_version_id': 1, 'model_ids': [1]})).json()
        assert preview['rows'][0]['matches'] == [] and preview['rows'][0]['status'] == 'missing_spec'


@pytest.mark.asyncio
@pytest.mark.parametrize('model_ids', [[], [3], [999], [True]])
async def test_preview_requires_explicit_valid_snapshot_models(tmp_path, model_ids):
    async with client_for(tmp_path) as (client, _):
        topic, _ = await seed(client)
        result = await client.post(f"/api/knowledge/parameter-topics/{topic['id']}/preview", json={'config_version_id': 1, 'model_ids': model_ids})
        assert result.status_code == 422


@pytest.mark.asyncio
async def test_duplicate_snapshot_ipn_rejected(tmp_path):
    source = {'models': [{'id': 1, 'name': 'VINNO 6'}], 'items': [
        {'id': 1, 'ipn': '1000101', 'values': {'1': {'selection_config': 'X'}}},
        {'id': 2, 'ipn': '1000101', 'values': {'1': {'selection_config': 'O'}}}]}
    async with client_for(tmp_path, snapshot=source) as (client, _):
        topic, _ = await seed(client)
        result = await client.post(f"/api/knowledge/parameter-topics/{topic['id']}/preview", json={'config_version_id': 1, 'model_ids': [1]})
        assert result.status_code == 422 and '同一身份' in result.text


@pytest.mark.asyncio
async def test_recycled_model_id_cannot_reinterpret_snapshot(tmp_path):
    source = {'models': [{'id': 1, 'name': '不同旧机型'}], 'items': []}
    async with client_for(tmp_path, snapshot=source) as (client, _):
        topic, _ = await seed(client)
        result = await client.post(f"/api/knowledge/parameter-topics/{topic['id']}/preview", json={'config_version_id': 1, 'model_ids': [1]})
        assert result.status_code == 422 and '身份' in result.text


@pytest.mark.asyncio
async def test_legacy_database_is_readable_but_write_unavailable(tmp_path):
    async with client_for(tmp_path, tables=False) as (client, _):
        assert (await client.get('/api/knowledge/parameter-topics')).json() == {'available': False, 'items': [], 'total': 0}
        assert (await client.post('/api/knowledge/parameter-topics', json=TOPIC)).status_code == 503


@pytest.mark.asyncio
async def test_snapshot_options_match_preview_identities_and_reject_duplicate_raw_ids(tmp_path):
    async with client_for(tmp_path) as (client, factory):
        topic, _ = await seed(client)
        options = await client.get('/api/knowledge/parameter-snapshots/1')
        assert options.status_code == 200
        assert options.json()['models'] == [{'id': 1, 'name': 'VINNO 6'}, {'id': 2, 'name': 'VINNO 6EXP'}]
        assert options.json()['series_id'] == 1
        async with factory() as db:
            source = json.loads((await db.execute(text('SELECT snapshot_data FROM config_versions WHERE id=1'))).scalar_one())
            source['models'].append(dict(source['models'][0]))
            await db.execute(text('UPDATE config_versions SET snapshot_data=:snapshot WHERE id=1'), {'snapshot': json.dumps(source)})
            await db.commit()
        response = await client.get('/api/knowledge/parameter-snapshots/1')
        assert response.status_code == 422
        preview = await client.post(f"/api/knowledge/parameter-topics/{topic['id']}/preview", json={'config_version_id': 1, 'model_ids': [1]})
        assert preview.status_code == 422


@pytest.mark.asyncio
async def test_a_spec_can_be_disabled_after_its_current_ipn_becomes_ambiguous(tmp_path):
    async with client_for(tmp_path) as (client, factory):
        topic, first = await seed(client)
        async with factory() as db:
            db.add(ConfigItem(id=12, row_index=3, ipn='1000101', zh_desc='重复主数据'))
            await db.commit()
        response = await client.put(f"/api/knowledge/parameter-topics/{topic['id']}/specs/{first['id']}", json=spec(is_active=False, expected_revision=1))
        assert response.status_code == 200
        assert response.json()['is_active'] is False and response.json()['identity_issue']


@pytest.mark.asyncio
@pytest.mark.parametrize('selection', ['', 'N/A', '?'])
async def test_missing_or_unknown_selection_never_uses_rd_value_as_a_formal_answer(tmp_path, selection):
    source = {'models': [{'id': 1, 'name': 'VINNO 6'}], 'items': [
        {'id': 10, 'ipn': '1000101', 'values': {'1': {'selection_config': selection, 'current_config': 'X'}}}]}
    async with client_for(tmp_path, snapshot=source) as (client, _):
        topic, _ = await seed(client)
        result = (await client.post(f"/api/knowledge/parameter-topics/{topic['id']}/preview", json={'config_version_id': 1, 'model_ids': [1]})).json()
        assert result['rows'][0]['status'] == 'needs_review'
        assert result['rows'][0]['matches'][0]['current_config_note'] == 'X'
        assert not result['rows'][0]['matches'][0]['usable']
        assert '5000 mAh' not in result['answer_text']


@pytest.mark.asyncio
async def test_topic_validation_and_missing_resources_are_explicit(tmp_path):
    async with client_for(tmp_path) as (client, _):
        for patch in [{'name': ' '}, {'fields': [TOPIC['fields'][0], TOPIC['fields'][0]]}, {'fields': [{**TOPIC['fields'][0], 'unit': ''}]}]:
            assert (await client.post('/api/knowledge/parameter-topics', json={**TOPIC, **patch})).status_code == 422
        topic, first = await seed(client)
        assert (await client.post('/api/knowledge/parameter-topics', json=TOPIC)).status_code == 409
        assert (await client.get('/api/knowledge/parameter-topics/999/specs')).status_code == 404
        assert (await client.get('/api/knowledge/parameter-snapshots/999')).status_code == 404
        assert (await client.put(f"/api/knowledge/parameter-topics/{topic['id']}/specs/999", json=spec(expected_revision=1, is_active=False))).status_code == 404


@pytest.mark.asyncio
async def test_text_fields_preserve_explicit_values_without_unit_conversion(tmp_path):
    async with client_for(tmp_path) as (client, _):
        payload = {'name': '电池材料', 'question': '电池材料是什么？', 'fields': [{'key': 'material', 'label': '材料', 'unit': '', 'type': 'text'}]}
        topic = (await client.post('/api/knowledge/parameter-topics', json=payload)).json()
        response = await client.post(f"/api/knowledge/parameter-topics/{topic['id']}/specs", json=spec(values={'material': '合成材料名称'}))
        assert response.status_code == 200
        invalid = await client.post(f"/api/knowledge/parameter-topics/{topic['id']}/specs", json=spec('1000102', values={'material': 1}))
        assert invalid.status_code == 422
