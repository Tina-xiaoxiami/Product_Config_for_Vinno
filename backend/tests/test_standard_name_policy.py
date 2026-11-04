import json
import sqlite3
import pytest
from test_feature_name_reviews import setup
from test_feature_name_standards_api import _upload, _standard_table_bytes

@pytest.mark.asyncio
async def test_config_description_is_not_a_name_baseline(tmp_path):
    path, client, engine = await setup(tmp_path)
    async with client:
        await client.post('/api/features/standards/import', files=_upload(_standard_table_bytes([('组织多普勒成像', 'Tissue Doppler Imaging', 'TDI')])))
        with sqlite3.connect(path) as db:
            db.execute("update config_items set zh_desc='历史配置描述', en_desc='Old configuration name'")
        flags = (await client.get('/api/features/standards/flags')).json()
        assert '1' not in flags['by_feature']
        detail = (await client.get('/api/features/standards/reviews/1')).json()
        link = next(check for check in detail['checks'] if check['baseline'] == 'config')
        assert link['label'] == '配置项链接' and link['severity'] == 'ok'
        assert not link['confirmable']
    await engine.dispose()

@pytest.mark.asyncio
async def test_apply_standard_changes_names_and_keeps_ipn_links_config_and_old_names(tmp_path):
    path, client, engine = await setup(tmp_path)
    with sqlite3.connect(path) as db:
        before_links = db.execute('select * from feature_config_item_links').fetchall()
        before_config = db.execute('select * from config_items').fetchall()
    async with client:
        await client.post('/api/features/standards/import', files=_upload(_standard_table_bytes([('新的多普勒名称', 'Tissue Doppler Imaging', 'TDI')])))
        detail = (await client.get('/api/features/standards/reviews/1')).json()
        check = next(c for c in detail['checks'] if c['baseline'] == 'standard')
        response = await client.post('/api/features/standards/reviews/1/apply-standard', json={'fingerprint':check['fingerprint']})
        assert response.status_code == 200, response.text
        assert '1' not in (await client.get('/api/features/standards/flags')).json()['by_feature']
        with sqlite3.connect(path) as db:
            assert db.execute('select name,primary_cn_name,primary_en_name from features where id=1').fetchone() == ('新的多普勒名称','新的多普勒名称','Tissue Doppler Imaging')
            assert db.execute('select * from feature_config_item_links').fetchall() == before_links
            assert db.execute('select * from config_items').fetchall() == before_config
            assert db.execute("select 1 from feature_names where feature_id=1 and language='cn' and name='组织多普勒成像' and name_type='alias'").fetchone()
        history = response.json()['history']
        assert history[0]['action'] == 'apply_standard'
        assert not history[0]['effective']
    await engine.dispose()

@pytest.mark.asyncio
async def test_standard_differences_cannot_be_dismissed_by_historical_confirmation(tmp_path):
    path, client, engine = await setup(tmp_path)
    async with client:
        await client.post('/api/features/standards/import', files=_upload(_standard_table_bytes([('新的多普勒名称','Tissue Doppler Imaging','TDI')])))
        check = next(c for c in (await client.get('/api/features/standards/reviews/1')).json()['checks'] if c['baseline']=='standard')
        with sqlite3.connect(path) as db:
            db.execute("insert into feature_name_reviews (feature_id,baseline,fingerprint,snapshot_data,note,confirmed_by,confirmed_at) values (1,'standard',?,'{}','','local_user','2026-11-04')",(check['fingerprint'],))
        assert '1' in (await client.get('/api/features/standards/flags')).json()['by_feature']
        rejected=await client.post('/api/features/standards/reviews/1',json={'checks':{'standard':check['fingerprint']}})
        assert rejected.status_code==422
    await engine.dispose()
