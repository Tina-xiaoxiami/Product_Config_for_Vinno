"""Named combinations store references and resolve current shared members."""
import json

import pytest

from test_whitepaper_subseries_editor import editor


def definition():
    return {'note': 'keep', 'sub_series': [
        {'name': 'V组', 'series': 'V Series', 'models': ['V10', '未匹配']},
        {'name': '跨系列', 'series': '', 'models': ['V10', 'X1']},
    ], 'sub_series_combinations': [{'name': '常用', 'sub_series': ['V组', '跨系列']}]}


@pytest.mark.asyncio
async def test_combination_resolves_overlap_cross_series_and_source_changes(tmp_path, monkeypatch):
    client, source, engine = await editor(tmp_path, monkeypatch, definition())
    async with client:
        body = (await client.get('/api/models/subseries')).json()
        by_name = {m['name']: m['id'] for m in body['catalog']}
        assert body['groups'][0]['model_ids'] == [by_name['V10']]
        assert body['groups'][0]['missing_models'] == ['未匹配']
        combo = body['combinations'][0]
        assert combo['model_ids'] == [by_name['V10'], by_name['X1']]
        assert combo['missing_models'] == ['V组：未匹配']
        body['combinations'].append({'name': '单组', 'sub_series': ['跨系列', '跨系列']})
        response = await client.put('/api/models/subseries', json=body)
        assert response.status_code == 200, response.text
        stored = json.loads(source.read_text())
        assert stored['note'] == 'keep'
        assert stored['sub_series_combinations'][-1] == {'name': '单组', 'sub_series': ['跨系列']}
        stored['sub_series'][0]['models'] = ['V11']
        source.write_text(json.dumps(stored))
        latest = (await client.get('/api/models/subseries')).json()['combinations'][0]
        assert latest['model_ids'] == [by_name['V11'], by_name['V10'], by_name['X1']]
        assert latest['missing_models'] == []
    await engine.dispose()


@pytest.mark.asyncio
async def test_rename_and_combination_update_are_atomic_and_stale_revision_conflicts(tmp_path, monkeypatch):
    client, source, engine = await editor(tmp_path, monkeypatch, definition())
    async with client:
        body = (await client.get('/api/models/subseries')).json()
        body['groups'][0]['name'] = '新名字'
        body['combinations'] = [{'name': '常用', 'sub_series': ['新名字', '跨系列']}]
        response = await client.put('/api/models/subseries', json=body)
        assert response.status_code == 200, response.text
        assert json.loads(source.read_text())['sub_series_combinations'] == body['combinations']
        assert response.json()['combinations'][0]['sub_series'] == ['新名字', '跨系列']
        before = source.read_bytes()
        assert (await client.put('/api/models/subseries', json=body)).status_code == 409
        assert source.read_bytes() == before
    await engine.dispose()


@pytest.mark.asyncio
async def test_explicit_clear_combinations_allows_group_deletion(tmp_path, monkeypatch):
    client, source, engine = await editor(tmp_path, monkeypatch, definition())
    async with client:
        body = (await client.get('/api/models/subseries')).json()
        response = await client.put('/api/models/subseries', json={
            'revision': body['revision'], 'groups': [], 'combinations': []})
        assert response.status_code == 200, response.text
        assert response.json()['combinations'] == []
        assert json.loads(source.read_text())['sub_series_combinations'] == []
    await engine.dispose()


def test_resolution_respects_parent_and_reports_ambiguous_members(tmp_path, monkeypatch):
    from app.models import ProductModel
    from app.services.whitepaper_subseries import get_subseries_editor
    source = tmp_path / 'strict.json'
    monkeypatch.setenv('WHITEPAPER_SUBSERIES_FILE', str(source))
    source.write_text(json.dumps({'sub_series': [
        {'name': 'China', 'series': 'China', 'models': ['VINNO 5', 'VINNO 6']},
        {'name': 'Oversea', 'series': 'Oversea', 'models': ['VINNO 5']},
    ], 'sub_series_combinations': [{'name': 'Both', 'sub_series': ['China', 'Oversea']}]}))
    catalog = [ProductModel(id=1, series_id=1, name='VINNO 5'),
               ProductModel(id=2, series_id=2, name='VINNO 5'),
               ProductModel(id=3, series_id=1, name='VINNO 6'),
               ProductModel(id=4, series_id=1, name='VINNO 6')]
    body = get_subseries_editor(catalog, {1: 'China', 2: 'Oversea'})
    assert body['groups'][0]['model_ids'] == [1]
    assert body['groups'][0]['missing_models'] == ['VINNO 6']
    assert body['groups'][1]['model_ids'] == [2]
    assert body['combinations'][0]['model_ids'] == [1, 2]
    assert body['combinations'][0]['missing_models'] == ['China：VINNO 6']


@pytest.mark.asyncio
@pytest.mark.parametrize('combinations', [None, {}, [{'name': '', 'sub_series': ['V组']}],
    [{'name': '空', 'sub_series': []}], [{'name': '错', 'sub_series': ['不存在']}],
    [{'name': '错', 'sub_series': ['常用']}], [{'name': '错', 'sub_series': [1]}],
    [{'name': '错', 'sub_series': 'V组'}],
    [{'name': '重复', 'sub_series': ['V组']}, {'name': ' 重复 ', 'sub_series': ['跨系列']}],
])
async def test_invalid_combination_rejected_without_write(tmp_path, monkeypatch, combinations):
    client, source, engine = await editor(tmp_path, monkeypatch, definition())
    async with client:
        body = (await client.get('/api/models/subseries')).json()
        before = source.read_bytes()
        response = await client.put('/api/models/subseries', json={**body, 'combinations': combinations})
        assert response.status_code == 422, response.text
        assert source.read_bytes() == before
    await engine.dispose()


@pytest.mark.asyncio
async def test_old_client_preserves_combinations_and_rejects_dangling_deletion(tmp_path, monkeypatch):
    client, source, engine = await editor(tmp_path, monkeypatch, definition())
    async with client:
        body = (await client.get('/api/models/subseries')).json()
        old = {'groups': body['groups'], 'revision': body['revision']}
        saved = await client.put('/api/models/subseries', json=old)
        assert saved.status_code == 200, saved.text
        assert json.loads(source.read_text())['sub_series_combinations'] == definition()['sub_series_combinations']
        before = source.read_bytes()
        response = await client.put('/api/models/subseries', json={
            'revision': saved.json()['revision'], 'groups': old['groups'][1:]})
        assert response.status_code == 422, response.text
        assert source.read_bytes() == before
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('broken', [None, {}, [{'name': 'broken', 'sub_series': ['不存在']}],
    [{'name': 'a', 'sub_series': ['V组']}, {'name': 'a', 'sub_series': ['V组']}],
])
async def test_corrupt_source_combinations_fail_closed(tmp_path, monkeypatch, broken):
    doc = definition()
    doc['sub_series_combinations'] = broken
    client, source, engine = await editor(tmp_path, monkeypatch, doc)
    before = source.read_bytes()
    async with client:
        response = await client.get('/api/models/subseries')
        assert response.status_code == 503, response.text
        assert '组合' in response.json()['detail']
        response = await client.put('/api/models/subseries', json={'groups': [], 'combinations': [], 'revision': ''})
        assert response.status_code == 503, response.text
        assert source.read_bytes() == before
    await engine.dispose()
