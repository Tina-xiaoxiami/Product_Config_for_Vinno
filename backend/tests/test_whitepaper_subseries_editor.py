import json

import httpx
import pytest
from fastapi import FastAPI

from app.api import models
from app.database import get_db
from test_draft_safety import _draft_harness, _seed_catalog


async def editor(tmp_path, monkeypatch, document=None):
    ignored, sessions, engine = await _draft_harness(tmp_path)
    await ignored.aclose()
    await _seed_catalog(sessions)
    source = tmp_path / '子系列.json'
    source.write_text(json.dumps(document if document is not None else {
        '_说明': ['shared note'], 'extra_metadata': {'retain': True},
        'sub_series': [{'name': '主系列', 'series': 'V Series', 'models': ['V10', '原始未匹配']}],
    }, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setenv('WHITEPAPER_SUBSERIES_FILE', str(source))
    app = FastAPI()
    app.include_router(models.router, prefix='/api/models')

    async def db_override():
        async with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test'), source, engine


@pytest.mark.asyncio
async def test_editor_uses_complete_catalog_and_preserves_original_members(tmp_path, monkeypatch):
    client, source, engine = await editor(tmp_path, monkeypatch)
    original = source.read_bytes()
    async with client:
        response = await client.get('/api/models/subseries')
        assert response.status_code == 200, response.text
        body = response.json()
        assert source.read_bytes() == original
        assert {m['name'] for m in body['catalog']} == {'V10', 'V11', 'X1'}
        group = body['groups'][0]
        assert group['models'] == ['V10', '原始未匹配']
        assert {o['value'] for o in group['options']} == {'V10', 'V11', '原始未匹配'}
        assert any('未匹配' in o['label'] for o in group['options'])
        body['groups'][0]['models'].append('V11')
        body['groups'][0]['name'] = '已改名'
        saved = await client.put('/api/models/subseries', json=body)
        assert saved.status_code == 200, saved.text
        stored = json.loads(source.read_text())
        assert stored['sub_series'][0]['models'] == ['V10', '原始未匹配', 'V11']
        assert stored['_说明'] == ['shared note']
        assert stored['extra_metadata'] == {'retain': True}
        assert saved.json()['revision'] != body['revision']
    await engine.dispose()


@pytest.mark.asyncio
async def test_editor_rejects_stale_revision_without_overwriting_other_writer(tmp_path, monkeypatch):
    client, source, engine = await editor(tmp_path, monkeypatch)
    async with client:
        body = (await client.get('/api/models/subseries')).json()
        source.write_text(json.dumps({'sub_series': [], '_说明': 'concurrent writer'}))
        changed = source.read_bytes()
        response = await client.put('/api/models/subseries', json=body)
        assert response.status_code == 409, response.text
        assert source.read_bytes() == changed
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('groups', [
    [{'name': '错误', 'series': 'V Series', 'models': ['不存在的机型']}],
    [{'name': '跨系列', 'series': 'V Series', 'models': ['X1']}],
    [{'name': '空', 'series': 'V Series', 'models': []}],
    [{'name': '同名', 'models': ['V10']}, {'name': '同名', 'models': ['V11']}],
    [{'name': '错误系列', 'series': '不存在系列', 'models': ['V10']}],
])
async def test_editor_rejects_invalid_groups_without_partial_write(tmp_path, monkeypatch, groups):
    client, source, engine = await editor(tmp_path, monkeypatch)
    before = source.read_bytes()
    async with client:
        body = (await client.get('/api/models/subseries')).json()
        body['groups'] = groups
        response = await client.put('/api/models/subseries', json=body)
        assert response.status_code == 422, response.text
        assert source.read_bytes() == before
    await engine.dispose()


@pytest.mark.asyncio
async def test_editor_refuses_corrupt_source_and_allows_explicit_delete_all(tmp_path, monkeypatch):
    client, source, engine = await editor(tmp_path, monkeypatch)
    async with client:
        body = (await client.get('/api/models/subseries')).json()
        response = await client.put('/api/models/subseries', json={**body, 'groups': []})
        assert response.status_code == 200, response.text
        assert json.loads(source.read_text())['sub_series'] == []
        source.write_text('{broken')
        assert (await client.get('/api/models/subseries')).status_code == 503
        before = source.read_bytes()
        response = await client.put('/api/models/subseries', json=body)
        assert response.status_code == 503
        assert source.read_bytes() == before
    await engine.dispose()


@pytest.mark.asyncio
async def test_editor_preserves_whitepaper_spelling_and_new_config_only_members(tmp_path, monkeypatch):
    from app.models import ProductModel
    from app.services.whitepaper_subseries import get_subseries_editor, save_subseries_editor
    catalog = [ProductModel(id=1, series_id=6, name='ULTIMUS 9E Super 科研版(URM)'),
               ProductModel(id=2, series_id=6, name='ULTIMUS 9E_科研版(URM)'),
               ProductModel(id=3, series_id=6, name='ULTIMUS 9E Super 科研版(非URM)')]
    source = tmp_path/'shared.json'
    monkeypatch.setenv('WHITEPAPER_SUBSERIES_FILE', str(source))
    source.write_text(json.dumps({'sub_series':[{'name':'URM','series':'Tulip-China','models':['9E Super科研版（URM）']}]}))
    before = get_subseries_editor(catalog, {6:'Tulip-China'})
    options = before['groups'][0]['options']
    assert next(o for o in options if o['id']==1)['value']=='9E Super科研版（URM）'
    before['groups'][0]['models'].append('ULTIMUS 9E_科研版(URM)')
    after=save_subseries_editor(before['groups'],before['revision'],catalog,{6:'Tulip-China'})
    assert after['groups'][0]['models']==['9E Super科研版（URM）','ULTIMUS 9E_科研版(URM)']


@pytest.mark.asyncio
async def test_editor_failed_replace_retains_original_file_and_removes_temp(tmp_path, monkeypatch):
    from app.services import whitepaper_subseries
    client, source, engine=await editor(tmp_path,monkeypatch)
    async with client:
        body=(await client.get('/api/models/subseries')).json()
        original=source.read_bytes()
        def failed(*args):
            raise OSError('read only storage')
        monkeypatch.setattr(whitepaper_subseries.os,'replace',failed)
        response=await client.put('/api/models/subseries',json={**body,'groups':[]})
        assert response.status_code==503
        assert source.read_bytes()==original
        assert not list(tmp_path.glob('.subseries-*'))
    await engine.dispose()


def test_same_revision_concurrent_saves_allow_exactly_one_writer(tmp_path,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from app.models import ProductModel
    from app.services.whitepaper_subseries import get_subseries_editor, save_subseries_editor, SubseriesConflictError
    source=tmp_path/'new.json';monkeypatch.setenv('WHITEPAPER_SUBSERIES_FILE',str(source))
    catalog=[ProductModel(id=1,series_id=1,name='VINNO 5')]
    initial=get_subseries_editor(catalog,{1:'China'})
    def save(name):
        try:
            save_subseries_editor([{'name':name,'series':'China','models':['VINNO 5']}],initial['revision'],catalog,{1:'China'})
            return 'saved'
        except SubseriesConflictError:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(save,['one','two']))
    assert sorted(results)==['conflict','saved']
    assert len(json.loads(source.read_text())['sub_series'])==1


def test_unrestricted_subseries_supports_same_product_in_multiple_markets(tmp_path,monkeypatch):
    from app.models import ProductModel
    from app.services.whitepaper_subseries import get_subseries_editor, save_subseries_editor
    source=tmp_path/'multi.json';monkeypatch.setenv('WHITEPAPER_SUBSERIES_FILE',str(source))
    source.write_text(json.dumps({'sub_series':[{'name':'5 系','series':'','models':['VINNO 5']}]}))
    catalog=[ProductModel(id=1,series_id=1,name='VINNO 5'),ProductModel(id=2,series_id=2,name='VINNO 5')]
    current=get_subseries_editor(catalog,{1:'China',2:'Oversea'})
    assert len([o for o in current['groups'][0]['options'] if o['value']=='VINNO 5'])==1
    saved=save_subseries_editor(current['groups'],current['revision'],catalog,{1:'China',2:'Oversea'})
    assert saved['groups'][0]['models']==['VINNO 5']


def test_precise_members_survive_multiseries_roundtrip(tmp_path, monkeypatch):
    from app.models import ProductModel
    from app.services.whitepaper_subseries import get_subseries_editor, save_subseries_editor, read_subseries
    source = tmp_path / 'shared.json'
    monkeypatch.setenv('WHITEPAPER_SUBSERIES_FILE', str(source))
    catalog = [ProductModel(id=1, series_id=1, name='VINNO 5'), ProductModel(id=2, series_id=2, name='VINNO 5')]
    parents = {1: 'China', 2: 'Oversea'}
    before = get_subseries_editor(catalog, parents)
    saved = save_subseries_editor([{'name': 'One market', 'series_names': ['China', 'Oversea'], 'model_ids': [1], 'models': []}], before['revision'], catalog, parents)
    assert saved['groups'][0]['model_ids'] == [1]
    assert saved['groups'][0]['series_names'] == ['China', 'Oversea']
    assert read_subseries(catalog, parents)[0] == {1: ['One market'], 2: []}
    saved = save_subseries_editor(saved['groups'], saved['revision'], catalog, parents)
    assert saved['groups'][0]['model_ids'] == [1]
    assert saved['groups'][0]['missing_models'] == []
    assert json.loads(source.read_text())['sub_series'][0]['model_refs'] == [{'series': 'China', 'name': 'VINNO 5'}]
    with pytest.raises(ValueError, match='不属于'):
        save_subseries_editor([{'name': 'One market', 'series_names': ['Oversea'], 'model_ids': [1], 'models': []}], saved['revision'], catalog, parents)


def test_new_editor_preserves_legacy_unmatched_member(tmp_path, monkeypatch):
    from app.models import ProductModel
    from app.services.whitepaper_subseries import get_subseries_editor, save_subseries_editor
    source = tmp_path / 'shared.json'
    monkeypatch.setenv('WHITEPAPER_SUBSERIES_FILE', str(source))
    source.write_text(json.dumps({'sub_series': [{'name': 'G', 'series': 'China', 'models': ['old']}]}))
    catalog = [ProductModel(id=1, series_id=1, name='VINNO 5')]
    before = get_subseries_editor(catalog, {1: 'China'})
    saved = save_subseries_editor([{'name': 'G', 'series_names': ['China'], 'model_ids': [1], 'models': ['old']}], before['revision'], catalog, {1: 'China'})
    assert saved['groups'][0]['missing_models'] == ['old']
    assert saved['groups'][0]['model_ids'] == [1]


def test_precise_missing_same_name_keeps_market_on_rename(tmp_path, monkeypatch):
    from app.models import ProductModel
    from app.services.whitepaper_subseries import get_subseries_editor, save_subseries_editor
    source = tmp_path / 'shared.json'
    monkeypatch.setenv('WHITEPAPER_SUBSERIES_FILE', str(source))
    refs = [{'series': 'China', 'name': 'VINNO 5'}, {'series': 'Oversea', 'name': 'VINNO 5'}]
    source.write_text(json.dumps({'sub_series': [{'name': 'G', 'series': '', 'series_names': ['China', 'Oversea'], 'models': ['VINNO 5'], 'model_refs': refs}]}))
    catalog = [ProductModel(id=1, series_id=1, name='VINNO 5')]
    before = get_subseries_editor(catalog, {1: 'China', 2: 'Oversea'})
    before['groups'][0]['name'] = 'Renamed'
    saved = save_subseries_editor(before['groups'], before['revision'], catalog, {1: 'China', 2: 'Oversea'})
    assert saved['groups'][0]['unresolved_refs'] == [refs[1]]
    assert json.loads(source.read_text())['sub_series'][0]['model_refs'] == refs
