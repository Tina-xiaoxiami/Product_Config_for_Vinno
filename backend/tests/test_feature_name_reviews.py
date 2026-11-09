import sqlite3
import pytest
from app.database import Base
from test_knowledge_api import _create_knowledge_database
from test_feature_name_standards_api import _client_for,_upload,_standard_table_bytes

async def setup(tmp_path):
    path=tmp_path/'names.db';_create_knowledge_database(path)
    client,engine=await _client_for(path)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.tables['feature_name_reviews'].create)
    return path,client,engine


def standard_check(detail):
    return next(check for check in detail['checks'] if check['baseline']=='standard')

async def prepare(client):
    await client.post('/api/features/standards/import',files=_upload(_standard_table_bytes([('新的多普勒名称','Tissue Doppler Imaging','TDI')])))
    return (await client.get('/api/features/standards/reviews/1')).json()

@pytest.mark.asyncio
async def test_stale_source_prevents_standard_write_without_partial_updates(tmp_path):
    path,client,engine=await setup(tmp_path)
    async with client:
        before=await prepare(client)
        with sqlite3.connect(path) as db:db.execute("update features set primary_cn_name='另一个名称' where id=1")
        result=await client.post('/api/features/standards/reviews/1/apply-standard',json={'fingerprint':standard_check(before)['fingerprint']})
        assert result.status_code==409
        assert (await client.get('/api/features/standards/reviews/1')).json()['history']==[]
    await engine.dispose()

@pytest.mark.asyncio
async def test_configuration_description_changes_do_not_invalidate_standard_target(tmp_path):
    path,client,engine=await setup(tmp_path)
    async with client:
        before=await prepare(client)
        with sqlite3.connect(path) as db:db.execute("update config_items set zh_desc='任意配置表描述',en_desc='any old wording'")
        after=(await client.get('/api/features/standards/reviews/1')).json()
        assert standard_check(before)['fingerprint']==standard_check(after)['fingerprint']
        result=await client.post('/api/features/standards/reviews/1/apply-standard',json={'fingerprint':standard_check(before)['fingerprint']})
        assert result.status_code==200
    await engine.dispose()

@pytest.mark.asyncio
async def test_ambiguous_standards_cannot_be_applied(tmp_path):
    path,client,engine=await setup(tmp_path)
    async with client:
        await client.post('/api/features/standards/import',files=_upload(_standard_table_bytes([
            ('第一名称','Tissue Doppler Imaging','TDI'),('第二名称','Tissue Doppler Imaging','TDI')])))
        check=standard_check((await client.get('/api/features/standards/reviews/1')).json())
        assert not check['can_apply']
        result=await client.post('/api/features/standards/reviews/1/apply-standard',json={'fingerprint':check['fingerprint']})
        assert result.status_code==422
    await engine.dispose()

@pytest.mark.asyncio
async def test_conflicting_primary_links_block_name_update(tmp_path):
    path,client,engine=await setup(tmp_path)
    async with client:
        await prepare(client)
        with sqlite3.connect(path) as db:
            db.execute("insert into config_items (id,rd_name,ipn,zh_desc) values (999,'Other','OTHER-IPN','另一功能')")
            db.execute("insert into feature_config_item_links (feature_id,config_item_id,relation_type,source,review_status) values (1,999,'primary','test','approved')")
        detail=(await client.get('/api/features/standards/reviews/1')).json()
        assert all(not c['can_apply'] for c in detail['checks'])
        assert next(c for c in detail['checks'] if c['baseline']=='config')['severity']=='ambiguous'
        assert (await client.get('/api/features/standards/flags')).json()['summary']['config_differs']==1
        result=await client.post('/api/features/standards/reviews/1/apply-standard',json={'fingerprint':standard_check(detail)['fingerprint']})
        assert result.status_code==422
    await engine.dispose()

@pytest.mark.asyncio
async def test_primary_ipn_changes_reject_stale_standard_update(tmp_path):
    path,client,engine=await setup(tmp_path)
    async with client:
        before=await prepare(client)
        with sqlite3.connect(path) as db:db.execute("update features set ipn='OTHER' where id=1")
        result=await client.post('/api/features/standards/reviews/1/apply-standard',json={'fingerprint':standard_check(before)['fingerprint']})
        assert result.status_code==409
    await engine.dispose()

@pytest.mark.asyncio
async def test_alignment_history_is_not_a_dismissal_and_cannot_be_revoked_as_one(tmp_path):
    path,client,engine=await setup(tmp_path)
    async with client:
        before=await prepare(client)
        result=await client.post('/api/features/standards/reviews/1/apply-standard',json={'fingerprint':standard_check(before)['fingerprint'],'note':'采用标准名称'})
        assert result.status_code==200
        history=result.json()['history'][0]
        assert history['action']=='apply_standard' and history['note']=='采用标准名称'
        assert (await client.post(f"/api/features/standards/reviews/1/{history['id']}/revoke")).status_code==422
        repeated=await client.post('/api/features/standards/reviews/1/apply-standard',json={'fingerprint':standard_check(before)['fingerprint']})
        assert repeated.status_code==409
    await engine.dispose()

@pytest.mark.asyncio
async def test_two_features_matching_the_same_standard_never_auto_rename_either(tmp_path):
    path,client,engine=await setup(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute("insert into features (id,group_id,name,primary_cn_name,primary_en_name) values (999,1,'另一个功能','另一个功能','Tissue Doppler Imaging')")
    async with client:
        await prepare(client)
        detail=(await client.get('/api/features/standards/reviews/999')).json()
        check=standard_check(detail)
        assert not check['can_apply']
        result=await client.post('/api/features/standards/reviews/999/apply-standard',json={'fingerprint':check['fingerprint']})
        assert result.status_code==422
    await engine.dispose()

@pytest.mark.asyncio
async def test_missing_storage_and_unknown_feature_are_explicit_errors(tmp_path):
    path,client,engine=await setup(tmp_path)
    async with client:
        await prepare(client)
        assert (await client.get('/api/features/standards/reviews/999')).status_code==404
        assert (await client.post('/api/features/standards/reviews/999/apply-standard',json={'fingerprint':'0'*64})).status_code==404
        assert (await client.post('/api/features/standards/reviews/1/999/revoke')).status_code==409
        with sqlite3.connect(path) as db:db.execute('drop table feature_name_reviews')
        assert (await client.post('/api/features/standards/reviews/1/apply-standard',json={'fingerprint':'0'*64})).status_code==503
        assert (await client.post('/api/features/standards/reviews/1/999/revoke')).status_code==503
    await engine.dispose()
