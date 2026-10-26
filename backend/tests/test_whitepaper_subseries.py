import json
import pytest
from app.api import models
from test_draft_safety import _draft_harness, _seed_catalog

@pytest.mark.asyncio
async def test_model_list_reuses_live_whitepaper_subseries_without_writing(tmp_path, monkeypatch):
    client, sessions, engine = await _draft_harness(tmp_path)
    await _seed_catalog(sessions)
    source = tmp_path / '子系列.json'
    monkeypatch.setenv('WHITEPAPER_SUBSERIES_FILE', str(source))
    source.write_text(json.dumps({'sub_series': [{'name': '科研', 'series': 'V Series', 'models': ['V10']}, {'name':'海外', 'series':'Other Series', 'models':['V10']}]}))
    async with sessions() as db:
        response = await models.get_models(series_id=1, skip=0, limit=100, db=db)
        assert response.model_dump()['items'][0]['sub_series'] == ['科研']
        source.write_text(json.dumps({'sub_series':[{'name':'新子系列', 'series':'V Series','models':['V10']}]}))
        response = await models.get_models(series_id=1, skip=0, limit=100, db=db)
        assert response.model_dump()['items'][0]['sub_series'] == ['新子系列']
    await client.aclose()
    await engine.dispose()

@pytest.mark.asyncio
async def test_subseries_reader_reports_bad_source_and_preserves_models(tmp_path,monkeypatch):
    client,sessions,engine=await _draft_harness(tmp_path)
    await _seed_catalog(sessions)
    source=tmp_path/'子系列.json';source.write_text('{bad')
    monkeypatch.setenv('WHITEPAPER_SUBSERIES_FILE',str(source))
    async with sessions() as db:
        response=await models.get_models(series_id=1,skip=0,limit=100,db=db)
        assert len(response.items)==2
        assert response.model_dump()['sub_series_problems']
        assert all(item.model_dump()['sub_series']==[] for item in response.items)
    await client.aclose();await engine.dispose()
