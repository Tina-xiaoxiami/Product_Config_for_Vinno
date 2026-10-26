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

def test_strict_matching_qualifiers_ambiguity_overlap_and_invalid_rows(tmp_path,monkeypatch):
    from types import SimpleNamespace as M
    from app.services.whitepaper_subseries import read_subseries
    source=tmp_path/'sub.json';monkeypatch.setenv('WHITEPAPER_SUBSERIES_FILE',str(source))
    catalog=[M(id=1,series_id=6,name='ULTIMUS 9E Super 科研版(URM)'),M(id=2,series_id=6,name='ULTIMUS 9E Super 科研版(非URM)'),M(id=3,series_id=5,name='ULTIMUS 9E Super 科研版(URM)'),M(id=4,series_id=6,name='ULTIMUS 7P 全身应用版'),M(id=5,series_id=6,name='ULTIMUS 7P全身应用版')]
    source.write_text(json.dumps({'sub_series':[{'name':'URM','series':'Tulip-China','models':['9E Super科研版（URM）']},{'name':'第二组','series':'Tulip-China','models':['9E Super科研版（URM）']},{'name':'歧义','series':'Tulip-China','models':['7P全身应用版']},42]}))
    result,problems=read_subseries(catalog,{6:'Tulip-China',5:'Tulip-Oversea'})
    assert result=={1:['URM','第二组'],2:[],3:[],4:[],5:[]}
    assert len(problems)==2

def test_workspace_path_and_absent_or_invalid_definition(tmp_path,monkeypatch):
    from types import SimpleNamespace as M
    from app.services.whitepaper_subseries import read_subseries
    monkeypatch.delenv('WHITEPAPER_SUBSERIES_FILE',raising=False)
    monkeypatch.setenv('WP_VAULT',str(tmp_path))
    catalog=[M(id=1,series_id=1,name='VINNO 5')]
    assert read_subseries(catalog,{1:'China'})[1]
    source=tmp_path/'白皮书工作区'/'子系列.json';source.parent.mkdir()
    source.write_text('42');assert read_subseries(catalog,{1:'China'})[1]
    source.write_text(json.dumps([{'name':'5 系','models':['V5']},{'name':'5 系','models':['V5']}]))
    memberships,problems=read_subseries(catalog,{1:'China'})
    assert memberships=={1:['5 系']}
    assert len(problems)==1
