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
