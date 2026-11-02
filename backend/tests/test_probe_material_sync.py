"""Main machine configuration, not legacy function coverage, defines the probe union."""
import json
import pytest
from sqlalchemy import select,func
from app.models import ConfigItem,ConfigValue
from app.models.probe import ProbeModel,ProbeModelVariant,ProductProbeConfig,TemplateFeature
from app.models.probe_workspace import ProbeWorkspace,ProbeWorkspaceRelease
from test_probe_workspace import harness,create


async def add_config_materials(sessions):
    async with sessions() as db:
        db.add_all([
            ProbeModel(id=2,category_id=1,model_number='P2'),
            ProbeModelVariant(id=2,probe_model_id=2,internal_model='P2a',ipn='P-2'),
            ProbeModelVariant(id=3,probe_model_id=2,internal_model='P2a',ipn='P-2'),
            ConfigItem(id=202,category='Probes',row_index=5,rd_name='P2a',en_desc='P2',ipn='P-2'),
            ConfigItem(id=203,category='Probes',row_index=6,rd_name='Unknown【启用】',ipn='P-3'),
            ConfigItem(id=204,category='Probes',row_index=7,rd_name='Selection only',ipn='P-4'),
            ConfigItem(id=205,category='Probes',row_index=8,rd_name='Final only',en_desc='P2',ipn='P-5'),
            ConfigValue(item_id=202,model_id=10,current_config='O',final_config='N/A'),
            ConfigValue(item_id=202,model_id=11,current_config='N/A',final_config='N/A'),
            ConfigValue(item_id=203,model_id=20,current_config='Δ',final_config='N/A'),
            ConfigValue(item_id=204,model_id=10,current_config='N/A',final_config='N/A',selection_config='O'),
            ConfigValue(item_id=205,model_id=10,current_config='N/A',final_config='X'),
            TemplateFeature(category_id=1,feature_id=1,default_support='supported'),
        ])
        await db.commit()


@pytest.mark.asyncio
async def test_initial_total_includes_configured_materials_without_legacy_function_records(tmp_path,monkeypatch):
    client,sessions,engine,_=await harness(tmp_path,monkeypatch)
    await add_config_materials(sessions)
    async with client:
        total=await create(client)
        cat=(await client.get('/api/probes/workspaces/catalog')).json()
        variants={v['id']:v for v in cat['variants']}
        by_ipn={variants[r['variant_id']]['ipn']:r for r in total['data']['rows']}
        assert set(by_ipn)=={'P-1','P-2','P-3','P-5'}
        assert len(total['data']['rows'])==4 # duplicate catalog variants do not inflate the union
        assert by_ipn['P-2']['defined_status']=='supported'
        assert by_ipn['P-3']['defined_status']=='pending' # unknown category must not invent a template
        assert by_ipn['P-2']['current_status']=='pending' # probe availability is not feature verification
        result=(await client.get(f"/api/probes/workspaces/{total['id']}/results")).json()['results']
        assert next(r for r in result if r['model_id']==11 and r['ipn']=='P-2')['current_status']=='not_applicable'
        unknown=next(r for r in result if r['model_id']==20 and r['ipn']=='P-3')
        assert unknown['source']['probe']['current_config']=='Δ'
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ProbeModel))==2
        assert await db.scalar(select(func.count()).select_from(ProbeModelVariant))==3
        assert await db.scalar(select(func.count()).select_from(ProductProbeConfig))==1
        assert await db.scalar(select(func.count()).select_from(ProbeWorkspaceRelease))==0
    await engine.dispose()


@pytest.mark.asyncio
async def test_existing_draft_sync_is_explicit_additive_and_revision_checked(tmp_path,monkeypatch):
    client,sessions,engine,_=await harness(tmp_path,monkeypatch)
    async with client:
        initial=await create(client)
        await add_config_materials(sessions)
        path=f"/api/probes/workspaces/{initial['id']}"
        viewed=(await client.get(path)).json()
        assert viewed['data']==initial['data']
        assert viewed['material_sync']['missing_count']==3
        synced=await client.put(path+'/draft',json={'revision':viewed['revision'],'data':viewed['data'],'sync_materials':True})
        assert synced.status_code==200,synced.text
        saved=synced.json()
        assert saved['data']['overrides']==initial['data']['overrides']
        prior=initial['data']['rows'][0]
        kept=next(r for r in saved['data']['rows'] if r['variant_id']==prior['variant_id'])
        assert kept['current_status']==prior['current_status']
        assert saved['published_data'] is None
        assert (await client.get(path)).json()['material_sync']['missing_count']==0
        repeat=await client.put(path+'/draft',json={'revision':saved['revision'],'data':saved['data'],'sync_materials':True})
        assert len(repeat.json()['data']['rows'])==4
        stale=await client.put(path+'/draft',json={'revision':viewed['revision'],'data':viewed['data'],'sync_materials':True})
        assert stale.status_code==409
    await engine.dispose()
