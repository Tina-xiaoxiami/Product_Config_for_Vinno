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

@pytest.mark.asyncio
async def test_confirmed_differences_hide_markers_without_changing_names_and_can_be_revoked(tmp_path):
    path,client,engine=await setup(tmp_path)
    async with client:
        await client.post('/api/features/standards/import',files=_upload(_standard_table_bytes([('新的多普勒名称','Tissue Doppler Imaging','TDI')])))
        before=(await client.get('/api/features/standards/reviews/1')).json()
        checks=[c for c in before['checks'] if c['confirmable']]
        assert checks
        saved=await client.post('/api/features/standards/reviews/1',json={'checks':{c['baseline']:c['fingerprint'] for c in checks},'note':'核对后保留当前写法'})
        assert saved.status_code==200,saved.text
        assert '1' not in (await client.get('/api/features/standards/flags')).json()['by_feature']
        history=saved.json()['history'];assert len(history)==len(checks)
        revoked=await client.post(f"/api/features/standards/reviews/1/{history[0]['id']}/revoke")
        assert revoked.status_code==200
        assert '1' in (await client.get('/api/features/standards/flags')).json()['by_feature']
    with sqlite3.connect(path) as db:
        assert db.execute('select primary_cn_name from features where id=1').fetchone()[0]=='组织多普勒成像'
    await engine.dispose()

@pytest.mark.asyncio
async def test_stale_confirmation_rejected_and_new_source_changes_reopen_marker(tmp_path):
    path,client,engine=await setup(tmp_path)
    async with client:
        await client.post('/api/features/standards/import',files=_upload(_standard_table_bytes([('新的多普勒名称','Tissue Doppler Imaging','TDI')])))
        before=(await client.get('/api/features/standards/reviews/1')).json()
        payload={'checks':{c['baseline']:c['fingerprint'] for c in before['checks'] if c['confirmable']}}
        with sqlite3.connect(path) as db:db.execute("update features set primary_cn_name='新的系统名称' where id=1")
        stale=await client.post('/api/features/standards/reviews/1',json=payload)
        assert stale.status_code==409
        assert (await client.get('/api/features/standards/reviews/1')).json()['history']==[]
        fresh=(await client.get('/api/features/standards/reviews/1')).json()
        saved=await client.post('/api/features/standards/reviews/1',json={'checks':{c['baseline']:c['fingerprint'] for c in fresh['checks'] if c['confirmable']}})
        assert saved.status_code==200
        with sqlite3.connect(path) as db:db.execute("update features set primary_cn_name='再次修改' where id=1")
        assert '1' in (await client.get('/api/features/standards/flags')).json()['by_feature']
    await engine.dispose()
