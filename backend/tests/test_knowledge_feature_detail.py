"""A feature view joins explicit identities and frozen scope without writes."""
import json

import pytest
from sqlalchemy import text

from test_knowledge_parameters import client_for
from app.models.probe import Feature, FeatureGroup
from app.models.knowledge import FeatureConfigItemLink

SCOPE = {'market': 'domestic', 'product_model_id': 1, 'software_version': '1.14.80'}

async def seed(factory):
    async with factory() as db:
        db.add(FeatureGroup(id=1, name='功能', sort_order=1))
        await db.flush()
        db.add(Feature(id=1, group_id=1, name='VATT', ipn='1000101', identity_status='confirmed'))
        await db.flush()
        db.add(FeatureConfigItemLink(feature_id=1, config_item_id=10, relation_type='primary', source='test', review_status='approved'))
        db.add(FeatureConfigItemLink(feature_id=1, config_item_id=11, relation_type='version_variant', source='test', review_status='approved'))
        await db.commit()

async def detail(db, **changes):
    from app.services.knowledge_feature_detail import feature_detail
    return await feature_detail(db, 1, scope=changes.get('scope', SCOPE), configuration_version_id=changes.get('version', 1))

@pytest.mark.asyncio
async def test_detail_uses_frozen_selection_and_keeps_related_ipns_separate(tmp_path):
    async with client_for(tmp_path) as (_, factory):
        await seed(factory)
        async with factory() as db:
            before = (await db.execute(text('SELECT snapshot_data FROM config_versions'))).scalar_one()
            result = await detail(db)
            assert result['feature']['id'] == 1
            assert result['configuration']['snapshot']['version_number'] == '1.14.80-正式版'
            rows = result['configuration']['items']
            assert rows[0]['selection_config'] == 'X'
            assert rows[0]['snapshot_name'] == '历史电池甲'
            assert rows[0]['current_config_note'] == '研发甲'
            assert rows[1]['relation_type'] == 'version_variant'
            assert result['scope']['software_version'] == '1.14.80'
            assert (await db.execute(text('SELECT snapshot_data FROM config_versions'))).scalar_one() == before
            assert (await db.execute(text('SELECT count(*) FROM config_values'))).scalar_one() == 0

@pytest.mark.asyncio
@pytest.mark.parametrize('scope', [None, {'market': 'domestic'}])
async def test_partial_scope_shows_identity_without_claiming_applicability(tmp_path, scope):
    async with client_for(tmp_path) as (_, factory):
        await seed(factory)
        async with factory() as db:
            result = await detail(db, scope=scope)
            assert result['status'] == 'needs_scope'
            assert result['configuration'] is None and result['citations'] == []

@pytest.mark.asyncio
async def test_snapshot_is_explicit_and_never_inferred_from_software_version(tmp_path):
    async with client_for(tmp_path) as (_, factory):
        await seed(factory)
        async with factory() as db:
            result = await detail(db, version=None)
            assert result['configuration'] is None
            assert '请选择已发布配置快照' in result['issues']

@pytest.mark.asyncio
@pytest.mark.parametrize('scope', [{**SCOPE, 'market': 'overseas'}, {**SCOPE, 'product_model_id': 3}])
async def test_wrong_market_or_series_rejected(tmp_path, scope):
    from app.services.knowledge_scope import KnowledgeScopeError
    from app.services.knowledge_parameters import ParameterError
    async with client_for(tmp_path) as (_, factory):
        await seed(factory)
        async with factory() as db:
            with pytest.raises((KnowledgeScopeError, ParameterError)):
                await detail(db, scope=scope)

@pytest.mark.asyncio
async def test_missing_ipn_does_not_fall_back_to_name_or_live_configuration(tmp_path):
    async with client_for(tmp_path) as (_, factory):
        await seed(factory)
        async with factory() as db:
            raw = json.loads((await db.execute(text('SELECT snapshot_data FROM config_versions'))).scalar_one())
            raw['items'][0]['ipn'] = '9999999'
            await db.execute(text('UPDATE config_versions SET snapshot_data=:s'), {'s': json.dumps(raw)})
            await db.commit()
            result = await detail(db)
            assert result['configuration']['items'][0]['selection_config'] is None
            assert result['configuration']['items'][0]['status'] == 'missing'

@pytest.mark.asyncio
async def test_unknown_feature_and_invalid_snapshot(tmp_path):
    from app.services.knowledge_feature_detail import feature_detail
    from app.services.knowledge_parameters import ParameterError
    async with client_for(tmp_path) as (_, factory):
        await seed(factory)
        async with factory() as db:
            assert await feature_detail(db, 999, scope=SCOPE, configuration_version_id=1) is None
            with pytest.raises(ParameterError):
                await detail(db, version=999)

@pytest.mark.asyncio
async def test_sources_reuse_same_scope_and_require_version_identity(tmp_path, monkeypatch):
    from app.services import knowledge_feature_detail as service
    calls = []
    async def candidates(db, query, *, scope, limit):
        calls.append(('source', query, scope))
        return [{'document_id': 1, 'chunk_id': 2, 'version_id': 'a'*64, 'source_ref': '第2页'},
                {'document_id': 3, 'chunk_id': 4, 'version_id': None}]
    async def history(db, query, scope):
        calls.append(('history', query, scope))
        return {'assessment': 'no_record', 'events': [], 'conclusion': '没有记录'}
    monkeypatch.setattr(service, 'find_candidate_evidence', candidates)
    monkeypatch.setattr(service, 'trace_release_history', history)
    async with client_for(tmp_path) as (_, factory):
        await seed(factory)
        async with factory() as db:
            result = await detail(db)
            assert len(result['citations']) == 1
            assert result['citations'][0]['source_ref'] == '第2页'
            assert calls[0][2] == calls[1][2] == result['scope']
            assert result['history']['assessment'] == 'no_record'

@pytest.mark.asyncio
async def test_public_detail_route_validates_scope_and_returns_missing_feature(tmp_path):
    import httpx
    from fastapi import FastAPI
    from app.api.knowledge import router
    from app.database import get_db
    async with client_for(tmp_path) as (_, factory):
        await seed(factory)
        app = FastAPI()
        app.include_router(router, prefix='/api/knowledge')
        async def database():
            async with factory() as db:
                yield db
        app.dependency_overrides[get_db] = database
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            response = await client.post('/api/knowledge/features/1/detail', json={'scope': SCOPE, 'configuration_version_id': 1})
            assert response.status_code == 200, response.text
            assert response.json()['configuration']['items'][0]['selection_config'] == 'X'
            assert (await client.post('/api/knowledge/features/999/detail', json={})).status_code == 404
            assert (await client.post('/api/knowledge/features/1/detail', json={'configuration_version_id': -1})).status_code == 422
            assert (await client.post('/api/knowledge/features/1/detail', json={'scope': {**SCOPE, 'market': 'overseas'}, 'configuration_version_id': 1})).status_code == 422

@pytest.mark.asyncio
async def test_detail_rejects_fuzzy_unrelated_sources_and_uses_approved_search_name(tmp_path, monkeypatch):
    from app.services import knowledge_feature_detail as service
    seen = []
    async def candidates(db, query, **kwargs):
        seen.append(query)
        return [{'chunk_id': 1, 'version_id': 'a'*64, 'excerpt': 'VATT 超声衰减成像'},
                {'chunk_id': 2, 'version_id': 'a'*64, 'excerpt': 'VAid Breast 乳腺'},
                {'chunk_id': 3, 'version_id': 'a'*64, 'excerpt': 'NVATT2 unrelated'}]
    monkeypatch.setattr(service, 'find_candidate_evidence', candidates)
    async with client_for(tmp_path) as (_, factory):
        await seed(factory)
        async with factory() as db:
            await db.execute(text("UPDATE features SET name='超声衰减成像', primary_en_name='VATT' WHERE id=1"))
            result = await detail(db)
            assert [row['chunk_id'] for row in result['citations']] == [1]
            assert seen == ['VATT']
