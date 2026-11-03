"""Adding a configuration identity to templates is staged, atomic and versioned."""
import json

import pytest
from sqlalchemy import select, func, text

from app.models.config import ConfigItem
from app.models.knowledge import FeatureConfigItemLink
from app.models.probe import Feature, FeatureGroup, ProbeCategory, TemplateDraft, TemplateFeature, TemplateVersion
from test_draft_safety import _draft_harness


async def harness(tmp_path):
    from app.api.template_features import router
    client, sessions, engine = await _draft_harness(tmp_path)
    client._transport.app.include_router(router, prefix='/api/template-features')
    async with sessions() as db:
        db.add_all([FeatureGroup(id=1,name='原分类'),FeatureGroup(id=2,name='新增分类'),
                    ProbeCategory(id=1,name='凸阵'),ProbeCategory(id=2,name='线阵'),
                    ConfigItem(id=12,category='Optional Features',row_index=1,ipn='6000',zh_desc='当前配置中文',en_desc='Current English')])
        await db.flush()
        db.add_all([Feature(id=1,group_id=1,name='原功能',probe_matrix_enabled=True),
                    Feature(id=2,group_id=1,name='旧名称',primary_cn_name='旧中文',primary_en_name='English',ipn='6000',probe_matrix_enabled=False),
                    Feature(id=3,group_id=1,name='其他候选',probe_matrix_enabled=False)])
        await db.flush()
        db.add_all([FeatureConfigItemLink(feature_id=2,config_item_id=12,relation_type='primary',source='test',review_status='approved'),
                    TemplateFeature(category_id=1,feature_id=1,default_support='supported')])
        await db.commit()
    return client,sessions,engine


async def stage(client, **changes):
    return await client.post('/api/template-features/catalog-draft',json={'feature_id':2,'group_id':2,'category_ids':[1],**changes})


@pytest.mark.asyncio
async def test_catalog_reads_current_configuration_names_without_enrolling_every_identity(tmp_path):
    client,sessions,engine=await harness(tmp_path)
    async with client:
        response=await client.get('/api/template-features/catalog')
        assert response.status_code==200,response.text
        result=response.json()
        assert result['total']==3 and len(result['items'])==3
        assert [row['id'] for row in result['matrix_items']]==[1]
        candidate=next(row for row in result['items'] if row['id']==2)
        assert candidate['name']=='当前配置中文' and not candidate['pending']
        assert len(result['groups'])==2
    await engine.dispose()


@pytest.mark.asyncio
async def test_stage_keeps_live_membership_group_and_cells_untouched_and_pending_cells_editable(tmp_path):
    client,sessions,engine=await harness(tmp_path)
    async with client:
        response=await stage(client,category_ids=[1,1,2])
        assert response.status_code==200,response.text
        async with sessions() as db:
            feature=await db.get(Feature,2)
            assert not feature.probe_matrix_enabled and feature.group_id==1
            assert await db.scalar(select(func.count()).select_from(TemplateFeature).where(TemplateFeature.feature_id==2))==0
        report=(await client.get('/api/template-features/catalog')).json()
        row=next(row for row in report['matrix_items'] if row['id']==2)
        assert row['pending'] and row['group_id']==2 and row['original_group_id']==1
        drafts=(await client.get('/api/template-features/drafts')).json()
        assert drafts['total']==2 and len(drafts['catalog_additions'])==1
        assert drafts['catalog_additions'][0]['category_ids']==[1,2]
        edited=await client.post('/api/template-features/save-draft',json={'category_id':1,'feature_id':2,'new_support':'conditional','excludes':'["心脏"]'})
        assert edited.status_code==200,edited.text
        drafts=(await client.get('/api/template-features/drafts')).json()
        assert next(row for row in drafts['drafts'] if row['category_id']==1)['new_excludes']=='["心脏"]'
    await engine.dispose()


@pytest.mark.asyncio
async def test_discard_removes_catalog_and_cell_drafts_without_modifying_features(tmp_path):
    client,sessions,engine=await harness(tmp_path)
    async with client:
        assert (await stage(client)).status_code==200
        assert (await client.post('/api/template-features/discard')).status_code==200
        drafts=(await client.get('/api/template-features/drafts')).json()
        assert drafts['total']==0 and not drafts['catalog_additions']
        catalog=(await client.get('/api/template-features/catalog')).json()
        assert [row['id'] for row in catalog['matrix_items']]==[1]
    async with sessions() as db:
        feature=await db.get(Feature,2)
        assert feature.group_id==1 and not feature.probe_matrix_enabled
        assert await db.scalar(select(func.count()).select_from(Feature))==3
    await engine.dispose()


@pytest.mark.asyncio
async def test_submit_commits_membership_group_cells_and_v2_snapshot_together(tmp_path):
    client,sessions,engine=await harness(tmp_path)
    async with client:
        assert (await stage(client)).status_code==200
        submitted=await client.post('/api/template-features/submit',json={'version_number':'v2-added'})
        assert submitted.status_code==200,submitted.text
        assert (await client.get('/api/template-features/drafts')).json()['total']==0
    async with sessions() as db:
        feature=await db.get(Feature,2)
        assert feature.probe_matrix_enabled and feature.group_id==2
        rows=(await db.scalars(select(TemplateFeature).where(TemplateFeature.feature_id==2))).all()
        assert [(row.category_id,row.default_support) for row in rows]==[(1,'supported')]
        version=await db.scalar(select(TemplateVersion))
        snapshot=json.loads(version.snapshot_data)
        assert snapshot['schema_version']==2
        assert snapshot['features']==[{'feature_id':1,'group_id':1},{'feature_id':2,'group_id':2}]
        assert len(snapshot['templates'])==2
        assert await db.scalar(text('SELECT COUNT(*) FROM template_catalog_drafts'))==0
    await engine.dispose()


@pytest.mark.asyncio
async def test_v2_rollback_restores_matrix_membership_without_deleting_feature_identity(tmp_path):
    client,sessions,engine=await harness(tmp_path)
    async with client:
        await client.post('/api/template-features/save-draft',json={'category_id':1,'feature_id':1,'new_support':'conditional'})
        assert (await client.post('/api/template-features/submit',json={'version_number':'before'})).status_code==200
        before=(await client.get('/api/template-features/versions')).json()[0]['id']
        await stage(client)
        assert (await client.post('/api/template-features/submit',json={'version_number':'after'})).status_code==200
        after=(await client.get('/api/template-features/versions')).json()[0]['id']
        response=await client.post(f'/api/template-features/rollback/{before}')
        assert response.status_code==200,response.text
        assert [row['id'] for row in (await client.get('/api/template-features/catalog')).json()['matrix_items']]==[1]
        assert (await client.post(f'/api/template-features/rollback/{after}')).status_code==200
    async with sessions() as db:
        feature=await db.get(Feature,2)
        assert feature.probe_matrix_enabled and feature.group_id==2 and feature.ipn=='6000'
        assert await db.scalar(select(func.count()).select_from(Feature))==3
    await engine.dispose()


@pytest.mark.asyncio
async def test_legacy_rollback_keeps_membership_and_refuses_pending_work(tmp_path):
    client,sessions,engine=await harness(tmp_path)
    async with sessions() as db:
        version=TemplateVersion(version_number='legacy',snapshot_data=json.dumps([{'category_id':1,'feature_id':1,'default_support':'supported','default_excludes':None}]))
        db.add(version);await db.commit();identifier=version.id
    async with client:
        await stage(client)
        blocked=await client.post(f'/api/template-features/rollback/{identifier}')
        assert blocked.status_code==409
        await client.post('/api/template-features/submit',json={'version_number':'added'})
        response=await client.post(f'/api/template-features/rollback/{identifier}')
        assert response.status_code==200,response.text
        assert response.json()['membership_restored'] is False and '成员' in response.json()['message']
    async with sessions() as db:
        assert (await db.get(Feature,2)).probe_matrix_enabled
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('changes,status',[({'feature_id':999},422),({'group_id':999},422),({'category_ids':[999]},422),({'category_ids':[]},422),({'feature_id':1},409)])
async def test_stage_invalid_references_and_enrolled_member_are_atomic(tmp_path,changes,status):
    client,sessions,engine=await harness(tmp_path)
    async with client:
        response=await stage(client,**changes)
        assert response.status_code==status,response.text
        assert (await client.get('/api/template-features/drafts')).json()['total']==0
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['duplicate','committed_hidden_cell','hidden_draft'])
async def test_stage_cannot_overwrite_existing_hidden_cells_or_another_catalog_draft(tmp_path,kind):
    client,sessions,engine=await harness(tmp_path)
    if kind!='duplicate':
        async with sessions() as db:
            db.add(TemplateFeature(category_id=1,feature_id=2,default_support='unsupported') if kind=='committed_hidden_cell'
                   else TemplateDraft(category_id=1,feature_id=2,new_support='supported'))
            await db.commit()
    async with client:
        if kind=='duplicate':
            assert (await stage(client)).status_code==200
        response=await stage(client)
        assert response.status_code==409,response.text
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('changed',['group','membership'])
async def test_submit_rejects_concurrent_identity_changes_without_partial_application(tmp_path,changed):
    client,sessions,engine=await harness(tmp_path)
    async with client:
        assert (await stage(client)).status_code==200
        async with sessions() as db:
            feature=await db.get(Feature,2)
            if changed=='group': feature.group_id=2
            else:feature.probe_matrix_enabled=True
            await db.commit()
        response=await client.post('/api/template-features/submit')
        assert response.status_code==409,response.text
        assert (await client.get('/api/template-features/drafts')).json()['total']==1
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(TemplateFeature).where(TemplateFeature.feature_id==2))==0
        assert await db.scalar(select(func.count()).select_from(TemplateVersion))==0
    await engine.dispose()


@pytest.mark.asyncio
async def test_snapshot_failure_rolls_back_membership_cells_and_retains_drafts(tmp_path):
    client,sessions,engine=await harness(tmp_path)
    async with sessions() as db:
        await db.execute(text("CREATE TRIGGER reject_version BEFORE INSERT ON template_versions BEGIN SELECT RAISE(ABORT,'version rejected'); END"))
        await db.commit()
    async with client:
        await stage(client)
        response=await client.post('/api/template-features/submit')
        assert response.status_code==409,response.text
        assert (await client.get('/api/template-features/drafts')).json()['total']==1
    async with sessions() as db:
        feature=await db.get(Feature,2)
        assert not feature.probe_matrix_enabled and feature.group_id==1
        assert await db.scalar(select(func.count()).select_from(TemplateFeature).where(TemplateFeature.feature_id==2))==0
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('bad',[
    {'schema_version':2,'templates':[],'features':[{'feature_id':1,'group_id':999}]},
    {'schema_version':2,'templates':[],'features':[{'feature_id':999,'group_id':1}]},
    {'schema_version':2,'templates':[],'features':[{'feature_id':1,'group_id':1},{'feature_id':1,'group_id':2}]},
    {'schema_version':2,'templates':[{'category_id':999,'feature_id':1,'default_support':'supported'}],'features':[]},
    {'schema_version':2,'templates':[{'category_id':1,'feature_id':1,'default_support':'invalid'}],'features':[]},
])
async def test_invalid_membership_snapshot_fails_closed_before_any_delete(tmp_path,bad):
    client,sessions,engine=await harness(tmp_path)
    async with sessions() as db:
        version=TemplateVersion(version_number='bad',snapshot_data=json.dumps(bad));db.add(version);await db.commit();identifier=version.id
    async with client:
        response=await client.post(f'/api/template-features/rollback/{identifier}')
        assert response.status_code==422,response.text
    async with sessions() as db:
        assert (await db.get(Feature,1)).probe_matrix_enabled
        assert await db.scalar(select(func.count()).select_from(TemplateFeature))==1
    await engine.dispose()
